"""SE-02: volatile, single-writer project actor with revisions and fenced write ownership.

One in-memory ``ProjectActor`` per (tenant, project, epoch). Every mutating call runs under
one mutex; a write is validated in this exact order and swapped in *once*:

    epoch open -> pause boundary -> grant (write) -> owner heartbeat -> lease fence
    -> request shape/hash -> idempotent replay -> expected project revision
    -> tombstones + per-module CAS in a staged ledger copy -> SE-01 atomic validation
    -> candidate projection -> consistency check -> ONE reference swap.

Anything that raises before the swap leaves every byte of committed state (typed IR,
ledger revisions, idempotency cache, tombstones) unchanged. There is no disk I/O, no
journal, no unbounded queue (``max_pending`` admission), no last-write-wins and no lookup
outside the exact (tenant, project, epoch). Auth transport, WebSocket and Editor wiring
belong to SE-03/SE-05; this module only enforces the in-process contract they will call.
"""
from __future__ import annotations

import json
import math
import threading
import time
from contextlib import contextmanager
from types import MappingProxyType

from core.project import state as S
from core.project.operations import (
    MAX_REQUEST_BYTES, OperationError, _schema_check, apply_transaction, canonical_json, parse_transaction,
    project_view, sha256_hex)
from core.project.state import ActorError, ActorState, Grant, Lease

MAX_EPOCH = 0xFFFFFFFF


class ProjectActor:
    def __init__(self, tenant: str, project: str, epoch: int, owner: str, *, clock=None,
                 heartbeat_ttl: float = 30.0, lease_ttl: float = 60.0, max_pending: int = 16,
                 _fault_hook=None):
        self.tenant = S.token(tenant, "tenant")
        self.project = S.token(project, "project")
        self.owner = S.token(owner, "owner subject")
        if not (type(epoch) is int and 1 <= epoch <= MAX_EPOCH):
            raise ActorError(S.INVALID_REQUEST, "epoch must be an integer in 1..4294967295")
        for label, ttl in (("heartbeat_ttl", heartbeat_ttl), ("lease_ttl", lease_ttl)):
            if not (isinstance(ttl, (int, float)) and math.isfinite(ttl) and ttl > 0):
                raise ActorError(S.INVALID_REQUEST, f"{label} must be a positive finite number")
        if not (type(max_pending) is int and 1 <= max_pending <= 1024):
            raise ActorError(S.INVALID_REQUEST, "max_pending must be an integer in 1..1024")
        self.epoch = epoch
        self._clock = clock or time.monotonic
        self._hb_ttl, self._lease_ttl, self._max_pending = float(heartbeat_ttl), float(lease_ttl), max_pending
        self._fault = _fault_hook            # test seam only: called with a named point, may raise
        self._mutex = threading.Lock()       # the single writer mutex
        self._admit = threading.Lock()       # guards _pending only
        self._pending = 0
        self._state = ActorState.initial()
        self._grants = MappingProxyType({})  # replaced copy-on-write under the mutex
        self._fence = 0
        self._lease: Lease | None = None
        self._paused = False
        self._pause_requested = False        # set *before* waiting for the mutex: owner pause priority
        self._closed = False
        self._owner_seen: float | None = None

    # ------------------------------------------------------------------ plumbing
    @contextmanager
    def _exclusive(self, priority: bool = False):
        """Bounded admission, then the writer mutex. Owner pause/revoke/close skip admission only."""
        if not priority:
            with self._admit:
                if self._pending >= self._max_pending:
                    raise ActorError(S.QUEUE_FULL, f"more than {self._max_pending} calls are pending",
                                     maxPending=self._max_pending)
                self._pending += 1
        try:
            with self._mutex:
                yield
        finally:
            if not priority:
                with self._admit:
                    self._pending -= 1

    def _point(self, name: str) -> None:
        if self._fault is not None:
            self._fault(name)

    def _open(self) -> None:
        if self._closed:
            raise ActorError(S.EPOCH_CLOSED, "this epoch is closed; open the new epoch")

    def _owner_only(self, subject: str) -> None:
        if subject != self.owner:
            raise ActorError(S.GRANT_DENIED, "only the project owner may do this")

    def _authorize(self, subject: object, scope: str) -> str:
        if subject == self.owner:
            return "owner"
        grant = self._grants.get(subject) if isinstance(subject, str) else None
        if grant is None or scope not in grant.scopes:
            raise ActorError(S.GRANT_DENIED, f"no active {scope} grant for this principal")
        return "agent"

    def _owner_alive(self, now: float) -> bool:
        return self._owner_seen is not None and now - self._owner_seen <= self._hb_ttl

    def _need_owner(self, now: float) -> None:
        if not self._owner_alive(now):
            raise ActorError(S.OWNER_ABSENT, "owner heartbeat expired; writes are rejected until it returns")

    def _live_lease(self, now: float) -> Lease | None:
        lease = self._lease
        return lease if lease is not None and now <= lease.expires_at else None

    def _writer_name(self, now: float) -> str | None:
        lease = self._live_lease(now)
        return lease.holder if lease else None

    def _bump_fence(self) -> None:
        self._fence += 1
        self._lease = None

    # ------------------------------------------------------------------ owner controls
    def owner_heartbeat(self, subject: str) -> None:
        self._owner_only(subject)
        self._owner_seen = self._clock()

    def grant(self, subject: str, grant: Grant) -> None:
        self._owner_only(subject)
        if not isinstance(grant, Grant):
            raise ActorError(S.INVALID_REQUEST, "a Grant is required")
        if (grant.tenant, grant.project) != (self.tenant, self.project):
            raise ActorError(S.TENANT_MISMATCH, "grant is for a different tenant/project")
        if grant.subject == self.owner:
            raise ActorError(S.INVALID_REQUEST, "the owner is not granted; it already has every scope")
        with self._exclusive():
            self._open()
            self._owner_seen = self._clock()
            grants = dict(self._grants)
            grants[grant.subject] = grant
            self._grants = MappingProxyType(grants)
            if "write" not in grant.scopes and self._lease is not None and self._lease.holder == grant.subject:
                self._bump_fence()                     # a downgrade fences the old writer out immediately

    def revoke(self, subject: str, target: str) -> bool:
        self._owner_only(subject)
        with self._exclusive(priority=True):
            self._open()
            self._owner_seen = self._clock()
            grants = dict(self._grants)
            existed = grants.pop(target, None) is not None
            self._grants = MappingProxyType(grants)
            if self._lease is not None and self._lease.holder == target:
                self._bump_fence()                     # fenced out immediately
            return existed

    def pause(self, subject: str) -> None:
        """Owner pause: takes effect at the next operation boundary and bumps the fence."""
        self._owner_only(subject)
        self._pause_requested = True                   # queued writers see this once they get the mutex
        with self._exclusive(priority=True):
            self._open()
            self._owner_seen = self._clock()
            self._paused = True
            self._bump_fence()

    def resume(self, subject: str) -> None:
        """Resume does not restore any lease: every writer must acquire a fresh fence."""
        self._owner_only(subject)
        with self._exclusive(priority=True):
            self._open()
            self._owner_seen = self._clock()
            self._paused = False
            self._pause_requested = False

    def owner_acquire(self, subject: str) -> Lease:
        """The owner takes the writer lease (preempting an agent: the fence moves)."""
        self._owner_only(subject)
        with self._exclusive():
            self._open()
            if self._paused or self._pause_requested:
                raise ActorError(S.PAUSED, "project is paused; resume before acquiring ownership")
            now = self._clock()
            self._owner_seen = now
            live = self._live_lease(now)
            if live is not None and live.holder == self.owner:
                fence = live.fence
            else:
                self._fence += 1
                fence = self._fence
            self._lease = Lease(self.owner, fence, now + self._lease_ttl)
            return self._lease

    def close(self, subject: str) -> None:
        """Retire this epoch (the registry does this when it opens the next one)."""
        self._owner_only(subject)
        with self._exclusive(priority=True):
            self._closed = True
            self._bump_fence()

    # ------------------------------------------------------------------ writer lease
    def acquire_lease(self, subject: str) -> Lease:
        """Agent writer lease: exactly one live holder; the rest get a named LEASE_HELD."""
        with self._exclusive():
            self._open()
            if self._paused or self._pause_requested:
                raise ActorError(S.PAUSED, "project is paused by the owner")
            role = self._authorize(subject, "write")
            if role == "owner":
                raise ActorError(S.INVALID_REQUEST, "the owner acquires with owner_acquire")
            now = self._clock()
            self._need_owner(now)
            live = self._live_lease(now)
            if live is not None:
                if live.holder != subject:
                    raise ActorError(S.LEASE_HELD, f"writer lease is held by {live.holder}",
                                     writer=live.holder, fence=self._fence)
                fence = live.fence
            else:
                self._fence += 1
                fence = self._fence
            self._lease = Lease(subject, fence, now + self._lease_ttl)
            return self._lease

    def release_lease(self, subject: str, lease: Lease) -> bool:
        with self._exclusive():
            self._open()
            cur = self._lease
            if cur is not None and cur.holder == subject and isinstance(lease, Lease) and lease.fence == cur.fence:
                self._lease = None
                return True
            return False

    # ------------------------------------------------------------------ reads (concurrent, no mutex)
    def view(self, subject: str) -> dict:
        """draft-view-v1 of the last committed state. Never blocks on, or observes, a write in flight."""
        self._open()
        self._authorize(subject, "read")
        return self._state.view()

    def status(self, subject: str) -> dict:
        self._open()
        self._authorize(subject, "read")
        state, now = self._state, self._clock()
        return {"tenant": self.tenant, "project": self.project, "epoch": self.epoch,
                "projectRevision": state.project.project_revision,
                "moduleRevisions": state.project.module_revisions(),
                "removedModules": sorted(state.tombstones),
                "writer": self._writer_name(now), "fence": self._fence,
                "paused": self._paused or self._pause_requested, "ownerAlive": self._owner_alive(now)}

    def state_digest(self) -> str:
        return self._state.digest()

    # ------------------------------------------------------------------ the write path
    def submit_bytes(self, subject: str, lease: Lease, payload: bytes) -> dict:
        try:
            txn = parse_transaction(payload)
        except OperationError as exc:
            raise ActorError(S.INVALID_REQUEST, str(exc)) from exc
        return self.submit(subject, lease, txn)

    def submit(self, subject: str, lease: Lease, txn: object) -> dict:
        with self._exclusive():
            self._open()
            if self._pause_requested or self._paused:     # owner pause wins at this boundary
                raise ActorError(S.PAUSED, "project is paused by the owner")
            now = self._clock()
            if self._authorize(subject, "write") == "owner":
                self._owner_seen = now                     # an owner write is itself a heartbeat
            self._need_owner(now)
            self._check_lease(subject, lease, now)
            try:
                return self._commit(subject, txn, now)
            except ActorError:
                raise
            except Exception as exc:                       # fail closed: nothing was swapped yet
                raise ActorError(S.INTERNAL_ERROR, f"unexpected {type(exc).__name__}; state unchanged") from exc

    def _check_lease(self, subject: str, lease: object, now: float) -> None:
        cur = self._lease
        ok = (isinstance(lease, Lease) and cur is not None and lease.fence == self._fence
              and lease.holder == subject and cur.holder == subject)
        if not ok:
            raise ActorError(S.FENCE_STALE, "your writer lease is no longer current", fence=self._fence,
                             writer=self._writer_name(now))
        if now > cur.expires_at:
            raise ActorError(S.LEASE_EXPIRED, "writer lease expired; acquire it again", fence=self._fence)

    def _commit(self, subject: str, txn: object, now: float) -> dict:
        try:
            raw = canonical_json(txn)
            if len(raw) > MAX_REQUEST_BYTES:
                raise OperationError("request exceeds 256 KiB")
            txn = json.loads(raw)                          # private, detached copy of the request
            _schema_check(txn)
        except OperationError as exc:
            raise ActorError(S.INVALID_REQUEST, str(exc)) from exc
        request_hash = sha256_hex(raw)
        state = self._state
        key = txn["idempotencyKey"]

        seen = state.outcomes.get(key)
        if seen is not None:                               # replay wins over the stale-revision check
            if seen[0] != subject or seen[1] != request_hash:
                raise ActorError(S.IDEMPOTENCY_CONFLICT, "idempotency key was already used for a different request")
            outcome = json.loads(seen[2])
            outcome["replayed"] = True
            return outcome

        current = state.project.project_revision
        if txn["baseProjectRevision"] != current:
            raise ActorError(S.REVISION_CONFLICT,
                             f"stale baseProjectRevision {txn['baseProjectRevision']}, project is at {current}",
                             currentProjectRevision=current, writer=self._writer_name(now))

        ledger, tombstones = S.stage_ledger(state, txn, lambda: self._point("after-first-target"))
        try:
            result = apply_transaction(state.project, txn)  # SE-01: whole-project atomic validation
        except OperationError as exc:
            raise ActorError(S.INVALID_OPERATION, str(exc)) from exc
        if result.replayed:
            raise ActorError(S.INTERNAL_ERROR, "project-level replay diverged from the actor outcome cache")
        project = result.state
        view = project_view(project)                       # candidate is projected before it can be swapped
        S.verify_consistent(project, ledger, tombstones, set(result.changed_modules) | set(result.removed_modules))
        self._point("after-validate")

        outcome = {"status": "COMMITTED", "tenant": self.tenant, "project": self.project, "epoch": self.epoch,
                   "transactionId": txn["transactionId"], "idempotencyKey": key, "requestSha256": request_hash,
                   "subject": subject, "fence": self._fence, "projectRevision": project.project_revision,
                   "moduleRevisions": project.module_revisions(),
                   "changedModules": list(result.changed_modules), "removedModules": list(result.removed_modules),
                   "canonicalIrSha256": view["canonicalIrSha256"], "projectionSha256": view["projectionSha256"]}
        blob = canonical_json(outcome)
        new_state = state.succeed(project, tombstones, ledger, key, (subject, request_hash, blob), view)
        self._point("before-swap")
        self._state = new_state                            # the single swap: state, ledger, outcome, tombstones
        self._lease = Lease(subject, self._fence, now + self._lease_ttl)
        out = json.loads(blob)
        out["replayed"] = False
        return out


class ActorRegistry:
    """Exact-triple lookup only. No listing, no prefix/tenant search, one answer for every miss."""

    def __init__(self, **actor_defaults):
        self._defaults = actor_defaults
        self._lock = threading.Lock()
        self._actors: dict[tuple, ProjectActor] = {}
        self._epochs: dict[tuple, int] = {}

    def open_epoch(self, tenant: str, project: str, owner: str) -> ProjectActor:
        """Start the next epoch (1, 2, ...) with an empty actor and retire the previous one.

        Restoring a saved design into the new epoch is SE-08's explicit owner action, not this call.
        """
        key = (S.token(tenant, "tenant"), S.token(project, "project"))
        with self._lock:
            previous = self._actors.get((*key, self._epochs.get(key, 0)))
            epoch = self._epochs.get(key, 0) + 1
            actor = ProjectActor(*key, epoch, owner, **self._defaults)
            if previous is not None:
                previous.close(previous.owner)
            self._epochs[key] = epoch
            self._actors[(*key, epoch)] = actor
            return actor

    def get(self, tenant: str, project: str, epoch: int) -> ProjectActor:
        actor = self._actors.get((tenant, project, epoch)) if isinstance(tenant, str) and isinstance(project, str) else None
        if actor is None:
            raise ActorError(S.NOT_FOUND, "no such project actor")
        return actor
