"""Local add-on transport. One primary Editor, bounded FIFO, no geometry state."""
import asyncio
import concurrent.futures
import hashlib
import json
import time
import uuid
from fnmatch import fnmatchcase
import anyio

from starlette.websockets import WebSocket, WebSocketDisconnect
from service import errors
from service.recorder import SLOT, SESSION

READ_TIMEOUT, WRITE_TIMEOUT = 30, 120
MAX_REQUEST, MAX_RESULT = 256 * 1024, 4 * 1024 * 1024
READ_TOOLS = frozenset(('describe_scene', 'describe_element', 'query_region', 'measure', 'check_model'))
RELAY_TOOLS = READ_TOOLS | {'get_floor_plan', 'edit_model', 'model_ops', 'undo'}


def failure(code, message):
    return {'ok': False, 'error': errors.error_body(code, message)}


def offline():
    return failure('EDITOR_OFFLINE', 'Open the Editor, open or create a model in authoring mode and press Hubungkan agent')


class AgentRelay:
    def __init__(self, loop, recorder):
        self.loop, self.recorder = loop, recorder
        self.primary, self.worker = None, None
        self.pending, self.queue = {}, asyncio.Queue(maxsize=8)
        self.ignored, self.closed = 0, False
        self.scope, self.authorized = None, lambda: True

    async def attach(self, socket, authorized=None):
        if self.closed:
            raise ValueError('relay stopped')
        previous = self.primary
        if previous is not None:
            await self.detach(previous)
        self.primary = socket
        self.authorized = authorized or (lambda: True)
        if previous is not None:
            try:
                await asyncio.wait_for(previous.send_json({'type': 'superseded'}), 5)
                await previous.close(code=1000, reason='superseded')
            except (OSError, RuntimeError, asyncio.TimeoutError):
                pass

    async def detach(self, socket):
        if self.primary is not socket:
            return
        self.primary = None
        for future in self.pending.values():
            if not future.done():
                future.set_result(offline())

    def receive(self, socket, message):
        valid = (socket is self.primary and self.authorized() and isinstance(message, dict) and message.get('type') == 'agent_result'
                 and isinstance(message.get('id'), str) and type(message.get('ok')) is bool)
        if valid:
            key = 'result' if message['ok'] else 'error'
            valid = set(message) == {'type', 'id', 'ok', key}
            if key == 'error':
                body = message.get('error')
                valid = valid and isinstance(body, dict) and all(k in body for k in ('code', 'message', 'retryable', 'nextAction'))
            future = self.pending.get(message['id'])
            if valid and future is not None and not future.done():
                future.set_result({'ok': message['ok'], key: message[key]})
                return
        self.ignored += 1

    def call_sync(self, slot, session, tool, args):
        if self.loop is None or not self.loop.is_running() or self.closed:
            reply = offline()
            self._record(slot, session, tool, args, reply, 0)
            return reply
        future = asyncio.run_coroutine_threadsafe(self.call(slot, session, tool, args), self.loop)
        try:
            return future.result(timeout=135)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return failure('EDITOR_TIMEOUT', 'The Editor may still finish; call describe_scene before retrying')

    async def call(self, slot, session, tool, args):
        started, reply = time.monotonic(), None
        try:
            if (not isinstance(slot, str) or not SLOT.fullmatch(slot) or not isinstance(session, str) or not SESSION.fullmatch(session)
                    or not isinstance(tool, str) or tool not in RELAY_TOOLS or not isinstance(args, dict)):
                reply = failure('INVALID_REQUEST', 'Invalid add-on call identity, tool or arguments')
            else:
                try:
                    size = len(json.dumps(args, allow_nan=False).encode('utf-8'))
                except (ValueError, TypeError, RecursionError):
                    size = MAX_REQUEST + 1
                if size > MAX_REQUEST:
                    reply = failure('BUDGET_EXCEEDED', 'Add-on request exceeds 256 KiB')
                elif self.closed or self.primary is None or not self.authorized():
                    reply = offline()
                elif self.queue.full():
                    reply = failure('BUSY', 'Editor call queue is full')
                else:
                    if self.worker is None:
                        self.worker = asyncio.create_task(self._work())
                    done = asyncio.get_running_loop().create_future()
                    self.queue.put_nowait((self.primary, slot, session, tool, args, done))
                    reply = await done
            return reply
        except asyncio.CancelledError:
            reply = failure('EDITOR_TIMEOUT', 'The Editor may still finish; call describe_scene before retrying')
            raise
        finally:
            if reply is not None:
                self._record(slot, session, tool, args, reply, (time.monotonic() - started) * 1000)

    def _record(self, slot, session, tool, args, reply, ms):
        payload = reply['result'] if reply['ok'] else reply['error']
        revision = payload.get('revision') if isinstance(payload, dict) else None
        self.recorder.append(slot, session, tool, args, reply['ok'], payload, ms, revision)

    async def _work(self):
        while True:
            socket, slot, session, tool, args, done = await self.queue.get()
            rid = uuid.uuid4().hex
            try:
                if done.cancelled():
                    continue
                if socket is not self.primary or not self.authorized():
                    reply = offline()
                else:
                    response = asyncio.get_running_loop().create_future()
                    self.pending[rid] = response
                    async def roundtrip():
                        await socket.send_json({'type': 'agent_call', 'id': rid, 'slot': slot,
                                                'session': session, 'tool': tool, 'args': args})
                        return await response
                    try:
                        reply = await asyncio.wait_for(roundtrip(), READ_TIMEOUT if tool in READ_TOOLS else WRITE_TIMEOUT)
                    except asyncio.TimeoutError:
                        reply = failure('EDITOR_TIMEOUT', 'The Editor may still finish; call describe_scene before retrying')
                    except (OSError, RuntimeError, WebSocketDisconnect):
                        await self.detach(socket)
                        reply = offline()
                if not done.done():
                    done.set_result(reply)
            except asyncio.CancelledError:
                if not done.done():
                    done.set_result(offline())
                raise
            finally:
                self.pending.pop(rid, None)
                self.queue.task_done()

    async def stop(self):
        self.closed = True
        if self.primary is not None:
            socket = self.primary
            await self.detach(socket)
            try:
                await socket.close(code=1001)
            except (OSError, RuntimeError):
                pass
        if self.worker is not None:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        while not self.queue.empty():
            *_, done = self.queue.get_nowait()
            if not done.done():
                done.set_result(offline())
            self.queue.task_done()


class AgentSocket:
    """Reuses the single-use ticket store, without registering a legacy draft viewer."""
    def __init__(self, app, relay, hub, origins, hosts):
        self.app, self.relay, self.hub = app, relay, hub
        self.origins, self.hosts = set(origins), hosts

    def _consume(self, hello):
        if not isinstance(hello, dict) or hello.get('type') != 'HELLO':
            raise ValueError('invalid attachment')
        ticket = hello.get('ticket')
        if not isinstance(ticket, str) or not 32 <= len(ticket) <= 512:
            raise ValueError('invalid attachment')
        # Same checks as DraftHub.attach; do not change the draft primary or its ACK.
        with self.hub.lock:
            binding = self.hub.tickets.pop(hashlib.sha256(ticket.encode()).hexdigest(), None)
            if not binding:
                raise ValueError('invalid attachment')
            expires, channel, authority = binding
            if (expires <= self.hub.clock() or authority != channel.authority or not self.hub._current(channel)
                    or (self.relay.scope is not None and self.relay.scope != (channel.actor.tenant, channel.actor.project))
                    or hello.get('projectId') != channel.actor.project or hello.get('epoch') not in (None, channel.epoch)):
                raise ValueError('invalid attachment')
            for field in ('lastAppliedRevision', 'lastRenderedRevision'):
                if type(hello.get(field)) is not int or not 0 <= hello[field] <= 2**53 - 1:
                    raise ValueError('invalid revision')
            return channel, authority

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            self.relay.loop = asyncio.get_running_loop()
            try:
                return await self.app(scope, receive, send)
            finally:
                await self.relay.stop()
        if scope['type'] != 'websocket' or scope['path'] != '/agent':
            return await self.app(scope, receive, send)
        headers = {k.lower(): v.decode('latin1') for k, v in scope['headers']}
        if (headers.get(b'origin') not in self.origins or scope.get('query_string')
                or not any(fnmatchcase(headers.get(b'host', ''), host) for host in self.hosts)):
            return await send({'type': 'websocket.close', 'code': 1008})
        socket = WebSocket(scope, receive, send)
        await socket.accept()
        tasks = []
        try:
            raw = await asyncio.wait_for(socket.receive_text(), 5)
            if len(raw.encode('utf-8')) > 4096:
                raise ValueError('invalid attachment')
            channel, authority = self._consume(json.loads(raw))
            del raw
            def authorized():
                with self.hub.lock:
                    return self.hub._current(channel) and channel.authority == authority
            await self.relay.attach(socket, authorized)

            async def receiver():
                while True:
                    raw = await socket.receive_text()
                    if len(raw.encode('utf-8')) > MAX_RESULT:
                        raise ValueError('message too large')
                    try:
                        message = json.loads(raw)
                    except (ValueError, RecursionError):
                        self.relay.ignored += 1
                        continue
                    self.relay.receive(socket, message)

            async def heartbeat():
                while True:
                    await asyncio.sleep(20)
                    with self.hub.lock:
                        valid = self.hub._current(channel) and channel.authority == authority
                    if not valid:
                        raise ValueError('attachment revoked')
                    await socket.send_json({'type': 'ping'})
            tasks = [asyncio.create_task(receiver()), asyncio.create_task(heartbeat())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            # ASGI may cancel a disconnected WebSocket before its receive task observes
            # websocket.disconnect. Retire the peer just as for an ordinary disconnect.
            pass
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, WebSocketDisconnect, asyncio.TimeoutError):
            try:
                await socket.close(code=1008, reason='Attachment or channel rejected')
            except (RuntimeError, OSError):
                pass
        finally:
            # Starlette's ASGI cancellation scope can already be cancelled here.
            # Shield bounded teardown so another cancellation cannot strand the
            # primary or escape while its receiver/heartbeat tasks are retiring.
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self.relay.detach(socket)
