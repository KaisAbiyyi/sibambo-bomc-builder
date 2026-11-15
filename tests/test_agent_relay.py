"""WP2 relay tests use scripted Editor sockets, never an LLM."""
import asyncio
import unittest
from unittest.mock import patch

from service.agent_relay import AgentRelay


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.closed = False

    async def send_json(self, message):
        await self.messages.put(message)

    async def close(self, **kwargs):
        self.closed = True


class Capture:
    def __init__(self):
        self.rows = []

    def append(self, *args):
        self.rows.append(args)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.recorder = Capture()
        self.relay = AgentRelay(asyncio.get_running_loop(), self.recorder)
        self.socket = Socket()
        await self.relay.attach(self.socket)

    async def asyncTearDown(self):
        await self.relay.stop()

    async def reply(self, socket, result=None):
        call = await asyncio.wait_for(socket.messages.get(), 1)
        self.relay.receive(socket, {'type': 'agent_result', 'id': call['id'], 'ok': True,
                                    'result': result or {'revision': 4}})
        return call

    async def test_latest_primary_fences_old_results_and_disconnects_in_flight(self):
        task = asyncio.create_task(self.relay.call('codex', 'a' * 32, 'describe_scene', {}))
        call = await self.socket.messages.get()
        second = Socket()
        await self.relay.attach(second)
        self.assertTrue(self.socket.closed)
        self.assertEqual((await self.socket.messages.get())['type'], 'superseded')
        self.relay.receive(self.socket, {'type': 'agent_result', 'id': call['id'], 'ok': True, 'result': {}})
        self.assertEqual((await task)['error']['code'], 'EDITOR_OFFLINE')
        await self.relay.detach(self.socket)
        next_call = asyncio.create_task(self.relay.call('codex', 'a' * 32, 'measure', {}))
        await self.reply(second)
        self.assertTrue((await next_call)['ok'])

    async def test_fifo_eight_waiting_overflow_busy_and_all_outcomes_recorded(self):
        tasks = [asyncio.create_task(self.relay.call('codex', 'a' * 32, 'measure', {'n': 0}))]
        first = await self.socket.messages.get()
        for n in range(1, 9):
            tasks.append(asyncio.create_task(self.relay.call('codex', 'a' * 32, 'measure', {'n': n})))
        await asyncio.sleep(0)
        busy = await self.relay.call('codex', 'a' * 32, 'measure', {'n': 9})
        self.assertEqual(busy['error']['code'], 'BUSY')
        self.assertTrue(self.socket.messages.empty())
        self.relay.receive(self.socket, {'type': 'agent_result', 'id': first['id'], 'ok': True, 'result': {}})
        for n in range(1, 9):
            message = await self.reply(self.socket)
            self.assertEqual(message['args']['n'], n)
        self.assertTrue(all(r['ok'] for r in await asyncio.gather(*tasks)))
        self.assertEqual(len(self.recorder.rows), 10)

    async def test_timeout_and_late_reply_do_not_complete_the_next_request(self):
        with patch('service.agent_relay.READ_TIMEOUT', .01):
            result = await self.relay.call('codex', 'a' * 32, 'measure', {})
        self.assertEqual(result['error']['code'], 'EDITOR_TIMEOUT')
        old = await self.socket.messages.get()
        task = asyncio.create_task(self.relay.call('codex', 'a' * 32, 'measure', {}))
        current = await self.socket.messages.get()
        self.relay.receive(self.socket, {'type': 'agent_result', 'id': old['id'], 'ok': True, 'result': {}})
        self.assertFalse(task.done())
        self.relay.receive(self.socket, {'type': 'agent_result', 'id': current['id'], 'ok': True, 'result': {}})
        self.assertTrue((await task)['ok'])

    async def test_disconnect_mid_call_and_offline_calls_fail_without_hanging(self):
        task = asyncio.create_task(self.relay.call('codex', 'a' * 32, 'measure', {}))
        await self.socket.messages.get()
        await self.relay.detach(self.socket)
        self.assertEqual((await task)['error']['code'], 'EDITOR_OFFLINE')
        self.assertEqual((await self.relay.call('codex', 'a' * 32, 'measure', {}))['error']['code'], 'EDITOR_OFFLINE')

    async def test_invalid_result_is_ignored_and_request_budget_rejects_before_send(self):
        task = asyncio.create_task(self.relay.call('codex', 'a' * 32, 'measure', {}))
        call = await self.socket.messages.get()
        for bad in ([], {'type': 'agent_result', 'id': call['id'], 'ok': 'yes', 'result': {}},
                    {'type': 'agent_result', 'id': call['id'], 'ok': True, 'error': {}}):
            self.relay.receive(self.socket, bad)
        self.assertFalse(task.done())
        self.relay.receive(self.socket, {'type': 'agent_result', 'id': call['id'], 'ok': False,
                                       'error': {'code': 'NO_EDITABLE_DOCUMENT', 'message': 'Open a model',
                                                 'retryable': False, 'nextAction': 'Open a model'}})
        self.assertEqual((await task)['error']['code'], 'NO_EDITABLE_DOCUMENT')
        result = await self.relay.call('codex', 'a' * 32, 'measure', {'x': 'x' * (256 * 1024)})
        self.assertEqual(result['error']['code'], 'BUDGET_EXCEEDED')
        self.assertTrue(self.socket.messages.empty())
