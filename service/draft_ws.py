"""SE-05 application WebSocket and bounded volatile revision delivery.

This is independent of MCP transport. Canonical actor/compiler state stays authoritative.
All mutable channel/queue/presence data is guarded by one hub RLock; no disk or logging.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from starlette.websockets import WebSocket, WebSocketDisconnect
from core.project.operations import canonical_json, sha256_hex
from core.project.state import ActorError

HEARTBEAT = 5
PRESENCE_TTL = 15
ACK_DEADLINE = 2
IDLE_TTL = 1800
MAX_QUEUE_EVENTS = 64
MAX_QUEUE_BYTES = 4 * 1024 * 1024
MAX_REPLAY_EVENTS = 128
MAX_REPLAY_BYTES = 8 * 1024 * 1024
# Nominal 30s cap, conservatively shortened for coarse Windows/JS wall-clock ticks.
# Keep the BFF/browser's strict <=30,000ms validation; never extend a ticket for skew.
TICKET_LIFETIME = 29.95


def compact(value):
    return canonical_json(value).decode('utf-8')


def records(actor, state=None):
    """One immutable actor-state reference, never a multi-revision read."""
    state = state or actor._state
    view = state.view()
    projections = {m['moduleId']: m for m in view['projection']['modules']}
    changed, manifest = [], []
    for mid, module in sorted(state.project.modules.items()):
        ir = compact(module)
        projection = compact(projections[mid]) if mid in projections else compact({
            'moduleId': mid, 'revision': module['revision'], 'positions': [], 'faces': [],
            'materials': [], 'worldTransform': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]})
        digest = sha256_hex(ir.encode('utf-8'))
        changed.append(dict(moduleId=mid, moduleRevision=module['revision'], canonicalIrJson=ir,
                            contentSha256=digest, projectionJson=projection,
                            projectionSha256=sha256_hex(projection.encode('utf-8'))))
        manifest.append([mid, module['revision'], digest])
    for mid in state.tombstones:
        manifest.append([mid, state.ledger.snapshot(mid)[0], None])
    manifest.sort(key=lambda row: row[0])
    return state.project.project_revision, changed, manifest, sha256_hex(canonical_json(manifest))


@dataclass(eq=False)
class Peer:
    channel: object
    seen: float
    queue: deque = field(default_factory=deque)
    queued_bytes: int = 0
    visible: bool = True
    closed: bool = False
    needs_resync: bool = False

    def enqueue(self, message):
        raw = compact(message)
        size = len(raw.encode('utf-8'))
        if self.needs_resync:
            return
        if len(self.queue) >= MAX_QUEUE_EVENTS or self.queued_bytes + size > MAX_QUEUE_BYTES:
            self.queue.clear()
            self.queued_bytes = 0
            self.needs_resync = True
            raw = compact({'type': 'resync_required', 'reason': 'SLOW_CONSUMER'})
            size = len(raw)
        self.queue.append(raw)
        self.queued_bytes += size

    def drain(self):
        if not self.queue:
            return None
        raw = self.queue.popleft()
        self.queued_bytes -= len(raw.encode('utf-8'))
        return raw


class Channel:
    def __init__(self, actor, now):
        self.actor = actor
        self.epoch = str(uuid.uuid4())  # random per ACTOR INSTANCE, not the legacy integer epoch
        self.peers = []
        self.primary = None
        self.acked = -1
        self.ack_hash = None
        self.pending_since = None
        self.events = deque()
        self.event_bytes = 0
        self.authority = 0
        self.detached_at = now
        self.requests = {}  # bounded metadata only; original text belongs to RequestStore
        self.request_operations = {}
        self.wire_requests = {}  # bound to the actor's 1024 retained outcome entries
        self._snapshot_state = None
        self._snapshot = None

    def snapshot(self):
        state = self.actor._state
        if state is not self._snapshot_state:
            revision, modules, manifest, digest = records(self.actor, state)
            self._snapshot = dict(type='snapshot', schemaVersion=1, projectId=self.actor.project, epoch=self.epoch,
                                  revision=revision, modules=modules, manifest=manifest, draftSha256=digest)
            self._snapshot_state = state
        return self._snapshot


class DraftHub:
    def __init__(self, host, *, clock=None):
        self.host = host
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self.channels = {}
        self.tickets = {}  # SHA256(ticket) -> (expiry, channel, authority); never the raw ticket
        self.pending = {}
        self.identities = {}  # signed credential subject labels, never display-name authorization

    def channel(self, actor):
        key = (actor.tenant, actor.project)
        with self.lock:
            channel = self.channels.get(key)
            if channel is None or channel.actor is not actor:
                if channel:
                    for peer in channel.peers:
                        peer.closed = True
                channel = Channel(actor, self.clock())
                self.channels[key] = channel
                if channel.actor._state.project.project_revision == 0 and actor.epoch > 1:
                    self.host.requests.clear(*key)
            return channel

    def _current(self, channel):
        try:
            return not channel.actor._closed and self.host.actor(channel.actor.tenant, channel.actor.project) is channel.actor
        except Exception:
            return False

    def issue_ticket(self, actor):
        from service.tools import ToolFailure
        with self.lock:
            now = self.clock()
            self.tickets = {k: v for k, v in self.tickets.items() if v[0] > now and self._current(v[1])}
            if len(self.tickets) >= 1024:
                raise ToolFailure('BUSY', 'too many outstanding draft tickets')
            channel = self.channel(actor)
            ticket = secrets.token_urlsafe(48)
            self.tickets[hashlib.sha256(ticket.encode()).hexdigest()] = (now + TICKET_LIFETIME, channel, channel.authority)
            return dict(ticket=ticket, ttlSeconds=30,
                        ticketExpiresAt=datetime.fromtimestamp(time.time() + TICKET_LIFETIME, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))

    def attach(self, hello):
        with self.lock:
            ticket = hello.get('ticket')
            if not isinstance(ticket, str) or not 32 <= len(ticket) <= 512:
                raise ValueError('invalid attachment')
            binding = self.tickets.pop(hashlib.sha256(ticket.encode()).hexdigest(), None)
            if not binding:
                raise ValueError('invalid attachment')
            expires, channel, authority = binding
            if expires <= self.clock() or authority != channel.authority or not self._current(channel) or hello.get('projectId') != channel.actor.project:
                raise ValueError('invalid attachment')
            if hello.get('epoch') not in (None, channel.epoch):
                # Explicit restart recovery belongs to SE-08; never silently replace retained old-epoch state.
                raise ValueError('EPOCH_CHANGED')
            for field in ('lastAppliedRevision', 'lastRenderedRevision'):
                if type(hello.get(field)) is not int or not 0 <= hello[field] <= 2**53 - 1:
                    raise ValueError('invalid revision')
            peer = Peer(channel, self.clock())
            channel.peers.append(peer)
            previous = channel.primary
            channel.primary = peer  # last attachment wins; followers never gate or ACK
            if previous:
                previous.enqueue(dict(type='viewer_role', role='follower'))
            channel.acked = -1
            channel.pending_since = self.clock()
            channel.detached_at = None
            peer.enqueue(dict(type='viewer_role', role='primary'))
            # A new primary must validate the complete snapshot before acknowledging; it cannot inherit ACK.
            self.resync(peer)
            channel.actor.owner_heartbeat(channel.actor.owner)
            return peer

    def resync(self, peer):
        with self.lock:
            snapshot = peer.channel.snapshot()
            if len(compact(snapshot).encode('utf-8')) > MAX_QUEUE_BYTES:
                raise ValueError('snapshot exceeds bounded channel budget')
            peer.queue.clear()
            peer.queued_bytes = 0
            peer.needs_resync = False
            peer.enqueue(dict(type='viewer_role', role='primary' if peer is peer.channel.primary else 'follower'))
            peer.enqueue(snapshot)

    def detach(self, peer):
        with self.lock:
            peer.closed = True
            channel = peer.channel
            if peer in channel.peers:
                channel.peers.remove(peer)
            if channel.primary is peer:
                channel.primary = None  # no implicit promotion of a stale follower
            if not channel.peers:
                channel.detached_at = self.clock()

    def viewer(self, actor, status):
        with self.lock:
            channel = self.channel(actor)
            peer = channel.primary
            if not peer or peer.closed or not peer.visible or self.clock() - peer.seen >= PRESENCE_TTL:
                return 'none'
            revision = actor._state.project.project_revision
            if channel.acked != revision or peer.needs_resync:
                return 'timeout' if channel.pending_since is not None and self.clock() - channel.pending_since >= ACK_DEADLINE else 'pending'
            return 'ok'

    def acknowledge(self, peer, revision, digest):
        with self.lock:
            channel = peer.channel
            snapshot = channel.snapshot()
            if peer is not channel.primary or not peer.visible or peer.closed or peer.needs_resync:
                return False
            if type(revision) is not int or revision != snapshot['revision'] or digest != snapshot['draftSha256']:
                raise ValueError('invalid ACK')
            channel.acked, channel.ack_hash = revision, digest
            channel.pending_since = None
            request_id = channel.request_operations.pop(revision, None)
            if request_id in channel.requests and channel.requests[request_id].get('status') != 'withdrawn':
                channel.requests[request_id]['status'] = 'addressed'
                from service.owner_mcp import OwnerMcp
                OwnerMcp(None, self.host, None).request_status(channel.actor)
            return True

    def publish(self, actor, outcome, request_id=None):
        with self.lock:
            if outcome.get('replayed'):
                return  # retrying an accepted operation never creates another event
            channel = self.channel(actor)
            snapshot = channel.snapshot()
            revision, modules, manifest, digest = (snapshot[key] for key in ('revision', 'modules', 'manifest', 'draftSha256'))
            changed = set(outcome['changedModules'])
            event = dict(type='event', schemaVersion=1, projectId=actor.project, epoch=channel.epoch,
                         revision=revision, previousRevision=revision - 1, operationId=outcome['transactionId'],
                         changed=[m for m in modules if m['moduleId'] in changed], removed=outcome['removedModules'],
                         manifest=manifest, draftSha256=digest)
            raw_bytes = len(compact(event).encode('utf-8'))
            channel.events.append((event, raw_bytes))
            channel.event_bytes += raw_bytes
            while len(channel.events) > MAX_REPLAY_EVENTS or channel.event_bytes > MAX_REPLAY_BYTES:
                channel.event_bytes -= channel.events.popleft()[1]
            channel.pending_since = self.clock()
            if isinstance(request_id, str) and request_id in channel.requests:
                channel.request_operations[revision] = request_id
            for peer in channel.peers:
                peer.enqueue(event)

    def heartbeat(self, peer, visible):
        with self.lock:
            if not self._current(peer.channel):
                raise ValueError('EPOCH_CHANGED')
            peer.seen, peer.visible = self.clock(), visible is True
            if peer is peer.channel.primary and peer.visible:
                peer.channel.actor.owner_heartbeat(peer.channel.actor.owner)
            channel = peer.channel
            return dict(type='presence', projectId=channel.actor.project, epoch=channel.epoch,
                        role='primary' if channel.primary is peer else 'follower',
                        phase='awaiting_viewer' if self.viewer(channel.actor, {}) != 'ok' else 'live',
                        idleTtlSeconds=IDLE_TTL, revision=channel.actor._state.project.project_revision)

    def invalidate(self, actor):
        with self.lock:
            self.channel(actor).authority += 1

    def disconnect_owner(self, principal):
        with self.lock:
            for channel in self.channels.values():
                if channel.actor.tenant == principal.tenant and channel.actor.owner == principal.id:
                    channel.authority += 1
                    channel.actor.pause(principal.id)
                    for peer in channel.peers:
                        peer.closed = True

    def sweep(self):
        with self.lock:
            now = self.clock()
            for key, channel in list(self.channels.items()):
                for peer in list(channel.peers):
                    if now - peer.seen >= PRESENCE_TTL:
                        self.detach(peer)
                if channel.detached_at is not None and now - channel.detached_at >= IDLE_TTL:
                    channel.actor.close(channel.actor.owner)
                    self.host.requests.clear(*key)
                    self.channels.pop(key, None)
                    self.host.registry._actors.pop((*key, channel.actor.epoch), None)
                    if self.host._epochs.get(key) == channel.actor.epoch:
                        self.host._epochs.pop(key, None)
                        self.host._write_gates.pop(key, None)
            self.tickets = {k: v for k, v in self.tickets.items() if v[0] > now and self._current(v[1])}
            self.pending = {k: v for k, v in self.pending.items() if v['deadline'] > now}
            active_grants = {gid for channel in self.channels.values() for gid in channel.actor._grants}
            self.identities = {gid: sub for gid, sub in self.identities.items() if gid in active_grants}

    def request_pairing(self, principal, actor):
        from service.tools import ToolFailure
        with self.lock:
            self.sweep()
            key = (actor.tenant, actor.project, principal.id)
            item = self.pending.get(key)
            if not item:
                if len(self.pending) >= 1000:
                    raise ToolFailure('BUSY', 'pairing queue is full')
                item = dict(id=secrets.token_urlsafe(18), clientId=principal.client, agentSubject=principal.subject,
                            displayName=principal.client, scopes=['read', 'write'],
                            pairingCode=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8)),
                            expiresAt=datetime.fromtimestamp(time.time() + 300, timezone.utc).isoformat().replace('+00:00', 'Z'),
                            deadline=self.clock() + 300, attempts=0, principal=principal)
                self.pending[key] = item
            return {k: v for k, v in item.items() if k not in ('deadline', 'attempts', 'principal')}


class DraftSocket:
    def __init__(self, app, hub, origins, hosts):
        self.app, self.hub, self.origins, self.hosts = app, hub, set(origins), hosts

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            task = None
            async def sweep_forever():
                while True:
                    await asyncio.sleep(5)
                    await asyncio.to_thread(self.hub.sweep)
            async def lifespan_send(message):
                nonlocal task
                if message['type'] == 'lifespan.startup.complete':
                    task = asyncio.create_task(sweep_forever())
                await send(message)
            try:
                return await self.app(scope, receive, lifespan_send)
            finally:
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        if scope['type'] != 'websocket' or scope['path'] != '/draft':
            if scope['type'] == 'http':
                self.hub.sweep()
            return await self.app(scope, receive, send)
        from fnmatch import fnmatchcase
        headers = {k.lower(): v.decode('latin1') for k, v in scope['headers']}
        if (headers.get(b'origin') not in self.origins or scope.get('query_string') or
                not any(fnmatchcase(headers.get(b'host', ''), host) for host in self.hosts)):
            return await send({'type': 'websocket.close', 'code': 1008})
        socket = WebSocket(scope, receive, send)
        peer = None
        await socket.accept()
        try:
            raw = await asyncio.wait_for(socket.receive_text(), timeout=5)
            if len(raw.encode('utf-8')) > 4096:
                raise ValueError('invalid attachment')
            hello = json.loads(raw)
            if not isinstance(hello, dict) or hello.get('type') != 'HELLO':
                raise ValueError('invalid attachment')
            peer = self.hub.attach(hello)
            # Drop the token-bearing first message before entering the long-lived loop.
            del hello, raw

            async def sender():
                while not peer.closed:
                    with self.hub.lock:
                        raw = peer.drain()
                    if raw is not None:
                        await asyncio.wait_for(socket.send_text(raw), timeout=5)
                    else:
                        await asyncio.sleep(.025)
                await socket.close(code=1001)

            async def receiver():
                while not peer.closed:
                    raw = await asyncio.wait_for(socket.receive_text(), timeout=PRESENCE_TTL)
                    if len(raw.encode('utf-8')) > 4096:
                        raise ValueError('message too large')
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError('invalid message')
                    kind = message.get('type')
                    if kind == 'heartbeat':
                        reply = self.hub.heartbeat(peer, message.get('visible'))
                        with self.hub.lock:
                            peer.enqueue(reply)
                    elif kind == 'ACK':
                        if self.hub.acknowledge(peer, message.get('revision'), message.get('draftSha256')):
                            with self.hub.lock:
                                peer.enqueue(self.hub.heartbeat(peer, peer.visible))
                    elif kind == 'RESYNC':
                        self.hub.resync(peer)
                    else:
                        raise ValueError('unsupported message')

            tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (ValueError, KeyError, TypeError, ActorError, WebSocketDisconnect, asyncio.TimeoutError) as error:
            try:
                await socket.close(code=1008, reason='EPOCH_CHANGED' if str(error) == 'EPOCH_CHANGED' else 'Attachment or channel rejected')
            except (RuntimeError, OSError):
                pass
        finally:
            if peer:
                self.hub.detach(peer)
