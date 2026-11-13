"""SE-05: real owner HTTP and application WebSocket, synthetic identities only."""
import asyncio
import copy
import json
import ssl
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime
from wsproto import WSConnection, ConnectionType
from wsproto.events import Request, TextMessage, AcceptConnection, CloseConnection, RejectConnection
from tests.remote_support import Env, TENANT, ISSUER
from service.tools import Tools, ToolFailure
from service.auth import Principal
from tests.test_remote_mcp import txn, create
from examples import bmb026_house as house


class Socket:
    async def connect(self, env, *, origin='https://editor.sibambo.test', target='/draft'):
        self.protocol = WSConnection(ConnectionType.CLIENT)
        self.reader, self.writer = await asyncio.open_connection('127.0.0.1', env.port,
            ssl=ssl.create_default_context(cafile=env.verify), server_hostname='127.0.0.1')
        headers = [(b'origin', origin.encode())] if origin else []
        self.writer.write(self.protocol.send(Request(host=f'127.0.0.1:{env.port}', target=target, extra_headers=headers)))
        await self.writer.drain()
        self.pending = []
        event = await self.event()
        if not isinstance(event, AcceptConnection):
            await self.close()
            raise ValueError('upgrade denied')
        return self

    async def event(self):
        while not self.pending:
            data = await asyncio.wait_for(self.reader.read(65536), 8)
            if not data:
                raise ValueError('socket closed')
            self.protocol.receive_data(data)
            self.pending.extend(self.protocol.events())
        return self.pending.pop(0)

    async def send(self, message):
        self.writer.write(self.protocol.send(TextMessage(data=json.dumps(message))))
        await self.writer.drain()

    async def message(self, kind=None):
        text = ''
        while True:
            event = await self.event()
            if isinstance(event, CloseConnection):
                raise ValueError('socket closed')
            if isinstance(event, TextMessage):
                text += event.data
                if event.message_finished:
                    value, text = json.loads(text), ''
                    if kind is None or value['type'] == kind:
                        return value

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class OwnerCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = Env().start()
        self.token = await self.env.setup_project('draft-test')

    async def asyncTearDown(self):
        for socket in getattr(self, 'sockets', []):
            await socket.close()
        self.env.stop()

    async def ticket(self):
        async with self.env.http(self.token) as http:
            return (await http.post(self.env.base + '/v1/projects/draft-test/owner/mcp/ticket', json={})).json()

    async def attach(self, ticket=None, epoch=None):
        socket = await Socket().connect(self.env)
        self.sockets = [*getattr(self, 'sockets', []), socket]
        ticket = ticket or await self.ticket()
        await socket.send(dict(type='HELLO', ticket=ticket['ticket'], projectId='draft-test', epoch=epoch,
                               lastAppliedRevision=0, lastRenderedRevision=0))
        return socket, await socket.message('snapshot')

    async def ack(self, socket, snapshot):
        await socket.send(dict(type='ACK', revision=snapshot['revision'], draftSha256=snapshot['draftSha256']))
        # A following round-trip fences the asynchronous ACK before testing a new tool call.
        await socket.send(dict(type='heartbeat', visible=True))
        await socket.message('presence')

    def call(self, name, **args):
        principal = Principal(self.env.pid('agent-1'), TENANT, ISSUER, 'agent-1', 'Test Client')
        return Tools(self.env.host).call(principal, 'draft-test', name, args)

    async def test_actual_editor_owner_paths_and_thirty_second_ticket(self):
        async with self.env.http(self.token) as http:
            url = self.env.base + '/v1/projects/draft-test/owner/mcp'
            status = await http.get(url)
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()['contract'], 'se04-owner-mcp-v1')
            self.assertEqual(status.json()['projectId'], 'draft-test')
            ticket = await http.post(url + '/ticket', json={})
            self.assertEqual(ticket.status_code, 200, ticket.text)
            self.assertEqual(ticket.json()['ttlSeconds'], 30)
            self.assertIn('ticketExpiresAt', ticket.json())
            self.assertRegex(ticket.json()['ticketExpiresAt'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')

    async def test_ticket_never_exceeds_strict_cap_on_a_coarse_receiver_clock(self):
        actor = self.env.host.actor(TENANT, 'draft-test')
        hub = self.env.host.drafts
        hub.clock = lambda: 10.0
        # Windows receiver Date.now can lag the issuer's fine wall clock by one ~16ms tick.
        with patch('service.draft_ws.time.time', return_value=1000.015):
            ticket = hub.issue_ticket(actor)
        expires = datetime.fromisoformat(ticket['ticketExpiresAt'].replace('Z', '+00:00')).timestamp()
        self.assertLessEqual(expires - 1000.0, 30.0)
        self.assertGreater(expires - 1000.0, 29.0)
        self.assertLessEqual(next(iter(hub.tickets.values()))[0] - 10.0, 30.0)

    async def test_no_viewer_is_not_substituted_by_owner_rest_heartbeat(self):
        with self.assertRaises(ToolFailure) as error:
            self.call('acquire_writer')
        self.assertEqual(error.exception.code, 'NO_ACTIVE_VIEWER')

    async def test_real_socket_ack_gates_real_remote_mcp_and_retry_is_idempotent(self):
        socket, snapshot = await self.attach()
        uuid.UUID(snapshot['epoch'])
        with self.assertRaises(ToolFailure) as error:
            self.call('acquire_writer')
        self.assertEqual(error.exception.code, 'RENDER_PENDING')
        await self.ack(socket, snapshot)
        token = self.env.mint('agent-1')
        async with self.env.client(token, 'draft-test') as client:
            lease = await client.call_tool('acquire_writer', {})
            lease = lease.structured_content
            fence = lease['fence']
            transaction = txn(0, [create(house._room('living', False))], 'socket-operation-1')
            result = await client.call_tool('apply_operation', {'fence': fence, 'transaction': transaction})
            self.assertFalse(result.is_error)
            event = await socket.message('event')
            self.assertEqual((event['revision'], event['previousRevision']), (1, 0))
            self.assertEqual(event['operationId'], 'socket-operation-1')
            self.assertEqual(len(event['changed']), 1)
            with self.assertRaises(ToolFailure) as error:
                self.call('apply_operation', fence=fence, transaction=txn(1, [], 'blocked-next'))
            self.assertEqual(error.exception.code, 'RENDER_PENDING')
            await self.ack(socket, event)
            replay = self.call('apply_operation', fence=fence, transaction=transaction)
            self.assertTrue(replay['replayed'])
            self.assertTrue(replay['rendered'])
            self.assertEqual(len(self.env.host.drafts.channel(self.env.host.actor(TENANT, 'draft-test')).events), 1)

    async def test_latest_primary_follower_ack_cannot_open_write_gate(self):
        one, snapshot = await self.attach()
        await self.ack(one, snapshot)
        two, second = await self.attach()
        await self.ack(one, second)
        with self.assertRaises(ToolFailure) as error:
            self.call('acquire_writer')
        self.assertEqual(error.exception.code, 'RENDER_PENDING')
        await self.ack(two, second)
        self.assertIn('fence', self.call('acquire_writer'))

    async def test_ticket_reuse_wrong_origin_and_query_are_rejected(self):
        ticket = await self.ticket()
        await self.attach(ticket)
        with self.assertRaises(ValueError):
            await self.attach(ticket)
        for origin, target in [('https://evil.test', '/draft'), (None, '/draft'),
                               ('https://editor.sibambo.test', '/draft?ticket=forbidden')]:
            with self.assertRaises(ValueError):
                await Socket().connect(self.env, origin=origin, target=target)

    async def test_pause_revokes_unused_ticket_and_new_epoch_rejects_old_attachment(self):
        ticket = await self.ticket()
        async with self.env.http(self.token) as http:
            await http.post(self.env.base + '/v1/projects/draft-test/owner/mcp/pause', json={'paused': True})
        with self.assertRaises(ValueError):
            await self.attach(ticket)
        socket, snapshot = await self.attach()
        await self.env.owner_post(self.token, 'draft-test', 'open', {'newEpoch': True})
        with self.assertRaises(ValueError):
            await self.attach(epoch=snapshot['epoch'])

    async def test_slow_consumer_queue_bounded_and_idle_ttl_purges_actor(self):
        socket, snapshot = await self.attach()
        hub = self.env.host.drafts
        channel = hub.channel(self.env.host.actor(TENANT, 'draft-test'))
        peer = channel.primary
        with hub.lock:
            for i in range(80):
                peer.enqueue({'type': 'test', 'index': i})
            self.assertTrue(peer.needs_resync)
            self.assertLessEqual(len(peer.queue), 64)
            self.assertLessEqual(peer.queued_bytes, 4 * 1024 * 1024)
            hub.detach(peer)
            hub.clock = lambda: channel.detached_at + 1801
            hub.sweep()
        with self.assertRaises(ToolFailure):
            self.env.host.actor(TENANT, 'draft-test')

    async def test_expired_ticket_wrong_project_and_ack_timeout_fail_closed(self):
        hub = self.env.host.drafts
        actor = self.env.host.actor(TENANT, 'draft-test')
        clock = [10.0]; hub.clock = lambda: clock[0]
        ticket = hub.issue_ticket(actor)
        hello = dict(type='HELLO', ticket=ticket['ticket'], projectId='draft-test', epoch=None,
                     lastAppliedRevision=0, lastRenderedRevision=0)
        clock[0] += 31
        with self.assertRaises(ValueError):
            hub.attach(hello)
        fresh = hub.issue_ticket(actor); hello['ticket'] = fresh['ticket']; hello['projectId'] = 'wrong-project'
        with self.assertRaises(ValueError):
            hub.attach(hello)
        hello.update(ticket=hub.issue_ticket(actor)['ticket'], projectId='draft-test')
        peer = hub.attach(hello)
        clock[0] += 3
        with self.assertRaises(ToolFailure) as error:
            self.call('acquire_writer')
        self.assertEqual(error.exception.code, 'RENDER_ACK_TIMEOUT')
        hub.detach(peer)

    async def test_numeric_wire_uuid_mapping_and_tombstone_manifest(self):
        socket, snapshot = await self.attach(); await self.ack(socket, snapshot)
        fence = self.call('acquire_writer')['fence']
        module = house._room('living', False)
        opid = str(uuid.uuid4())
        operation = dict(schemaVersion=1, projectId='draft-test', epoch=snapshot['epoch'], operationId=opid,
                         expectedProjectRevision=0, leaseFence=fence, expectedModuleRevisions={module['moduleId']: None},
                         action=dict(kind='transaction', changes=[dict(kind='replace_module', module=module)]))
        self.call('apply_operation', fence=fence, transaction=operation)
        event = await socket.message('event'); self.assertEqual(event['operationId'], opid); await self.ack(socket, event)
        self.assertTrue(self.call('apply_operation', fence=fence, transaction=operation)['replayed'])
        operation.update(operationId=str(uuid.uuid4()), expectedProjectRevision=1, expectedModuleRevisions={module['moduleId']: 1},
                         action=dict(kind='transaction', changes=[dict(kind='remove_module', moduleId=module['moduleId'])]))
        self.call('apply_operation', fence=fence, transaction=operation)
        removed = await socket.message('event')
        self.assertEqual(removed['manifest'], [[module['moduleId'], 2, None]])

    async def test_real_pairing_exact_identity_attempt_cap_and_cross_owner_denial(self):
        url = self.env.base + '/v1/projects/draft-test/owner/mcp'
        principal = self.env.app.app.verifier.principal_of(self.env.mint('new-agent', client='real-client'))
        pairing = self.env.host.drafts.request_pairing(principal, self.env.host.actor(TENANT, 'draft-test'))
        body = dict(projectId='draft-test', action='approve', grantId=pairing['id'], agentSubject='new-agent',
                    clientId='real-client', scopes=['read', 'write'], confirmationCode='WRONG222')
        async with self.env.http(self.token) as http:
            for _ in range(5):
                self.assertEqual((await http.post(url + '/grants', json=body)).status_code, 403)
            body['confirmationCode'] = pairing['pairingCode']
            self.assertEqual((await http.post(url + '/grants', json=body)).status_code, 403)
        async with self.env.http(self.env.mint('other-owner')) as http:
            for endpoint in ('', '/ticket', '/requests'):
                reply = await http.get(url) if not endpoint else await http.post(url + endpoint, json={})
                self.assertEqual(reply.status_code, 403)

    async def test_same_subject_different_signed_client_cannot_reuse_grant(self):
        principal = Principal(self.env.pid('agent-1'), TENANT, ISSUER, 'agent-1', 'unapproved-client')
        with self.assertRaises(ToolFailure) as error:
            Tools(self.env.host).call(principal, 'draft-test', 'read_project')
        self.assertEqual(error.exception.code, 'FORBIDDEN')

    async def test_same_human_subject_in_agent_oauth_client_is_not_the_owner_bff(self):
        async with self.env.http(self.env.mint('owner-1', client='agent-oauth-client')) as http:
            reply = await http.get(self.env.base + '/v1/projects/draft-test/owner/mcp')
            self.assertEqual(reply.status_code, 403)

    async def test_withdrawn_request_is_not_offered_to_agent_and_typed_context_is_retained(self):
        url = self.env.base + '/v1/projects/draft-test/owner/mcp/requests'
        body = dict(action='create', body='Revise width', moduleIds=['house/room'], kind='typed-parameters', parameters={'width': 3.5})
        async with self.env.http(self.token) as http:
            first = (await http.post(url, json=body)).json()['requests'][-1]['id']
            await http.post(url, json=dict(action='withdraw', requestId=first))
            second = (await http.post(url, json=body)).json()['requests'][-1]['id']
        items = self.call('read_owner_requests')['requests']
        self.assertEqual([str(x['id']) for x in items], [second])
        self.assertEqual(items[0]['parameters'], {'width': 3.5})
        self.assertEqual(items[0]['moduleIds'], ['house/room'])
        self.assertEqual(self.env.host.actor(TENANT, 'draft-test')._state.project.project_revision, 0)

    async def test_legacy_owner_pause_invalidates_new_unused_ticket(self):
        ticket = await self.ticket()
        await self.env.owner_post(self.token, 'draft-test', 'pause', {})
        with self.assertRaises(ValueError):
            await self.attach(ticket)

    async def test_logout_fences_writer_tickets_and_presence_but_retains_draft(self):
        socket, snapshot = await self.attach(); await self.ack(socket, snapshot)
        fence = self.call('acquire_writer')['fence']
        self.call('apply_operation', fence=fence, transaction=txn(0, [create(house._room('living', False))], 'logout-1'))
        ticket = await self.ticket()
        async with self.env.http(self.token) as http:
            self.assertEqual((await http.post(self.env.base + '/owner/v1/logout')).status_code, 200)
        with self.assertRaises(ValueError):
            await self.attach(ticket)
        actor = self.env.host.actor(TENANT, 'draft-test')
        self.assertEqual(actor._state.project.project_revision, 1)
        self.assertTrue(actor.status(actor.owner)['paused'])
        with self.assertRaises(ToolFailure) as error:
            self.call('acquire_writer')
        self.assertEqual(error.exception.code, 'PAUSED_BY_OWNER')

    async def test_wire_dependency_cas_and_complete_idempotency_are_preserved(self):
        socket, snapshot = await self.attach(); await self.ack(socket, snapshot)
        fence = self.call('acquire_writer')['fence']
        module, dependency = house._room('living', False), house._room('bedroom-a', False)
        module['dependencies'] = [dict(moduleId=dependency['moduleId'], minRevision=1)]
        self.call('apply_operation', fence=fence, transaction=txn(0, [create(module), create(dependency)], 'deps-1'))
        await self.ack(socket, await socket.message('event'))
        module['revision'] = 2
        operation = dict(schemaVersion=1, projectId='draft-test', epoch=snapshot['epoch'], operationId=str(uuid.uuid4()),
                         expectedProjectRevision=1, leaseFence=fence, expectedModuleRevisions={module['moduleId']: 1},
                         action=dict(kind='transaction', changes=[dict(kind='replace_module', module=module)]))
        with self.assertRaises(ToolFailure) as missing:
            self.call('apply_operation', fence=fence, transaction=operation)
        self.assertEqual(missing.exception.code, 'REVISION_CONFLICT')
        operation['expectedModuleRevisions'][dependency['moduleId']] = 1
        self.call('apply_operation', fence=fence, transaction=operation)
        await self.ack(socket, await socket.message('event'))
        self.assertTrue(self.call('apply_operation', fence=fence, transaction=operation)['replayed'])
        changed = copy.deepcopy(operation); changed['expectedModuleRevisions'][dependency['moduleId']] = 2
        with self.assertRaises(ToolFailure) as conflict:
            self.call('apply_operation', fence=fence, transaction=changed)
        self.assertEqual(conflict.exception.code, 'IDEMPOTENCY_CONFLICT')

    async def test_lost_accepted_http_receipt_retries_without_a_second_event_or_write(self):
        host = self.env.host
        self.env.stop(); self.env = Env(host=host)
        product = self.env.app
        lost = []
        async def lose_one_receipt(scope, receive, send):
            suppress = False
            async def intercepted(message):
                nonlocal suppress
                if message['type'] == 'http.response.start' and not lost and scope['path'] == '/mcp' and host.actor(TENANT, 'draft-test')._state.project.project_revision == 1:
                    lost.append(True); suppress = True
                    await send({'type': 'http.response.start', 'status': 503, 'headers': []})
                    await send({'type': 'http.response.body', 'body': b'receipt interrupted by synthetic test'})
                elif not suppress:
                    await send(message)
            await product(scope, receive, intercepted)
        self.env.server.config.app = lose_one_receipt
        self.env.start(); self.token = self.env.mint('owner-1')
        socket, snapshot = await self.attach(); await self.ack(socket, snapshot)
        async with self.env.client(self.env.mint('agent-1'), 'draft-test') as client:
            fence = (await client.call_tool('acquire_writer', {})).structured_content['fence']
            transaction = txn(0, [create(house._room('living', False))], 'lost-accepted-receipt')
            with self.assertRaises(Exception):
                await client.call_tool('apply_operation', dict(fence=fence, transaction=transaction))
            event = await socket.message('event')
            self.assertEqual(event['revision'], 1)
            await self.ack(socket, event)
            replay = await client.call_tool('apply_operation', dict(fence=fence, transaction=transaction))
            self.assertTrue(replay.structured_content['replayed'])
            self.assertTrue(replay.structured_content['rendered'])
        self.assertEqual(len(lost), 1)
        self.assertEqual(len(host.drafts.channel(host.actor(TENANT, 'draft-test')).events), 1)

    async def test_real_agent_pairing_approval_read_and_revocation_round_trip(self):
        agent_token = self.env.mint('owner-1', client='agent-client-approved')
        async with self.env.http(agent_token) as http:
            denied = await http.post(self.env.audience + '?project=draft-test', json={})
        self.assertEqual(denied.status_code, 403)
        pairing = denied.json()['pairing']
        url = self.env.base + '/v1/projects/draft-test/owner/mcp'
        async with self.env.http(self.token) as http:
            status = (await http.get(url)).json()
            self.assertNotIn('pairingCode', status['pending'][0])
            body = dict(action='approve', grantId=pairing['id'], clientId=pairing['clientId'],
                        agentSubject=pairing['agentSubject'], scopes=pairing['scopes'], confirmationCode=pairing['pairingCode'])
            approved = await http.post(url + '/grants', json=body)
            self.assertEqual(approved.status_code, 200)
            grant = next(g for g in approved.json()['grants'] if g['clientId'] == 'agent-client-approved')
        async with self.env.client(agent_token, 'draft-test') as client:
            self.assertFalse((await client.call_tool('read_project', {})).is_error)
        async with self.env.http(agent_token) as http:
            self.assertEqual((await http.get(url)).status_code, 403)
        async with self.env.http(self.token) as http:
            revoke = dict(action='revoke', grantId=grant['id'], agentSubject=grant['agentSubject'], clientId=grant['clientId'], scopes=grant['scopes'])
            self.assertEqual((await http.post(url + '/grants', json=revoke)).status_code, 200)
        async with self.env.http(agent_token) as http:
            self.assertEqual((await http.post(self.env.audience + '?project=draft-test', json={})).status_code, 403)


if __name__ == '__main__':
    unittest.main()
