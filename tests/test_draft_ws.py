"""SE-05: real owner HTTP and application WebSocket, synthetic identities only."""
import asyncio
import json
import ssl
import unittest
import uuid
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


if __name__ == '__main__':
    unittest.main()
