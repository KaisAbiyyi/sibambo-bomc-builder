"""Official MCP stdio client -> TCP discovery -> ASGI scripted Editor (no LLM)."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from service.bridge import bridge_call_addon
from service.local_demo import LocalDemo

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'read_guide', 'describe_scene', 'describe_element', 'query_region', 'measure',
         'check_model', 'get_floor_plan', 'edit_model', 'model_ops', 'undo'}


def make_demo():
    return LocalDemo(project='addon-test', port=8765, owner_secret='s' * 40,
                     editor_origins=('http://localhost:5175',), clients=('codex',), no_record=True)


def hello(demo):
    actor = demo.host.actor('local', demo.project)
    return {'type': 'HELLO', **demo.host.drafts.issue_ticket(actor), 'projectId': demo.project,
            'epoch': None, 'lastAppliedRevision': 0, 'lastRenderedRevision': 0}


class AddonProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_client_exact_inventory_roundtrip_and_offline_guide(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo = make_demo()
            demo.start_bridges()
            try:
                demo.write_client_files(Path(tmp))
                params = StdioServerParameters(command=sys.executable, args=['-m', 'service.stdio_bridge'], cwd=str(ROOT),
                    env={**os.environ, 'PYTHONPATH': str(ROOT), 'SIBAMBO_LOCAL_RUN_ROOT': tmp, 'SIBAMBO_CLIENT_SLOT': 'codex'})
                with TestClient(demo.app, base_url='http://127.0.0.1:8765') as http:
                    async with Client(params) as client:
                        tools = (await client.list_tools()).tools
                        self.assertEqual({t.name for t in tools}, NAMES)
                        self.assertTrue(all(len(t.description) <= 2048 for t in tools))
                        guide = await client.call_tool('read_guide', {})
                        self.assertFalse(guide.is_error)
                        offline = await client.call_tool('describe_scene', {})
                        self.assertEqual(offline.structured_content['error']['code'], 'EDITOR_OFFLINE')
                        with http.websocket_connect('ws://127.0.0.1:8765/agent', headers={'origin': 'http://localhost:5175'}) as ws:
                            ws.send_json(hello(demo))
                            for _ in range(100):
                                if demo.relay.primary is not None:
                                    break
                                await asyncio.sleep(.01)
                            self.assertIsNotNone(demo.relay.primary)
                            pending = asyncio.create_task(client.call_tool('describe_scene', {'limit': 7}))
                            call = await asyncio.to_thread(ws.receive_json)
                            self.assertEqual(call['tool'], 'describe_scene')
                            self.assertEqual(call['slot'], 'codex')
                            self.assertEqual(call['args']['limit'], 7)
                            ws.send_json({'type': 'agent_result', 'id': call['id'], 'ok': True,
                                          'result': {'revision': 12, 'text': 'Owner selection: none'}})
                            result = await pending
                            self.assertEqual(result.structured_content['revision'], 12)
                            # Add-on result payload may be text as well as a dict; preserve it.
                            pending = asyncio.create_task(client.call_tool('get_floor_plan', {'moduleId': 'house/ground'}))
                            call = await asyncio.to_thread(ws.receive_json)
                            ws.send_json({'type': 'agent_result', 'id': call['id'], 'ok': True, 'result': 'Floor plan pending'})
                            result = await pending
                            self.assertIn('Floor plan pending', result.content[0].text)
                        (Path(tmp) / 'private/bridge-codex.json').unlink()
                        offline = await client.call_tool('describe_scene', {})
                        self.assertEqual(offline.structured_content['error']['code'], 'SERVICE_OFFLINE')
                        self.assertFalse((await client.call_tool('read_guide', {'topic': 'errors'})).is_error)
                        missing = await client.call_tool('read_guide', {'topic': '../../auth'})
                        self.assertEqual(missing.structured_content['error']['code'], 'NOT_FOUND')
            finally:
                demo.stop()

    async def test_bad_discovery_never_connects_outside_loopback_or_reads_oversized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private/bridge-codex.json'
            path.parent.mkdir()
            for body in ({'addr': 'example.com:1234', 'secret': 'a' * 64, 'project': 'x', 'epoch': 'x', 'slot': 'codex'},
                         {'addr': '127.0.0.1:1'}, [], 'x' * 4097):
                path.write_text(json.dumps(body))
                reply = bridge_call_addon('measure', {}, tmp, 'codex', 'a' * 32)
                self.assertEqual(reply['error']['code'], 'SERVICE_OFFLINE')
            reply = bridge_call_addon('measure', {}, tmp, '../../escape', 'a' * 32)
            self.assertEqual(reply['error']['code'], 'SERVICE_OFFLINE')


class AgentHandshakeTests(unittest.TestCase):
    def test_origin_host_query_ticket_replay_and_legacy_primary_is_untouched(self):
        demo = make_demo()
        try:
            with TestClient(demo.app, base_url='http://127.0.0.1:8765') as client:
                for path, headers in [('/agent', {'origin': 'http://evil.test'}),
                                      ('/agent?ticket=secret', {'origin': 'http://localhost:5175'}),
                                      ('/agent', {'origin': 'http://localhost:5175', 'host': 'evil.test'})]:
                    with self.assertRaises(WebSocketDisconnect):
                        with client.websocket_connect(path, headers=headers):
                            pass
                ticket = hello(demo)
                with client.websocket_connect('ws://127.0.0.1:8765/agent', headers={'origin': 'http://localhost:5175'}) as ws:
                    ws.send_json(ticket)
                    import time
                    for _ in range(100):
                        if demo.relay.primary is not None:
                            break
                        time.sleep(.01)
                    self.assertIsNotNone(demo.relay.primary)
                    # A deterministic round trip establishes that HELLO was consumed.
                    pending = asyncio.run_coroutine_threadsafe(demo.relay.call('codex', 'a' * 32, 'measure', {}), demo.relay.loop)
                    call = ws.receive_json()
                    ws.send_json({'type': 'agent_result', 'id': call['id'], 'ok': True, 'result': {}})
                    self.assertTrue(pending.result(2)['ok'])
                    channel = demo.host.drafts.channel(demo.host.actor('local', demo.project))
                    self.assertIsNone(channel.primary)
                    with client.websocket_connect('ws://127.0.0.1:8765/agent', headers={'origin': 'http://localhost:5175'}) as replay:
                        replay.send_json(ticket)
                        with self.assertRaises(WebSocketDisconnect):
                            replay.receive_json()
        finally:
            demo.stop()
