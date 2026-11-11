"""SE-02: committed actor state, grants/leases and the staged module-revision ledger.

Pure and in-memory. Nothing in this module (or ``actor.py``) touches the filesystem, a
network socket, a journal or any credential: unsaved designs are volatile by contract
(``JournalStore`` is deliberately never imported). The SE-01 immutable ``ProjectState`` is
the canonical typed-IR map; ``ModuleStore`` (BMB-008) is used, in a *staged deep copy*, as
the per-module revision/idempotency ledger. One committed ``ActorState`` is swapped in as
a single reference, so readers and a crash can only ever observe the old or the new state.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from types import MappingProxyType

from core.identity.store import IdentityError, ModuleStore, StaleRevisionError
from core.project.operations import (
    EMPTY_STATE, ProjectState, canonical_ir_json, canonical_json, project_view, sha256_hex)

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
SCOPES = frozenset({"read", "write"})
MAX_OUTCOMES = 1024                 # bounded idempotency/outcome cache (FIFO), like SE-01
IR_BLOCK = "ir"                     # the single ledger block recording a module's canonical IR digest

# Stable error vocabulary (the wire layer in SE-03 maps these 1:1; no free-text parsing).
REVISION_CONFLICT = "REVISION_CONFLICT"
DEPENDENCY_STALE = "DEPENDENCY_STALE"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
FENCE_STALE = "FENCE_STALE"
LEASE_HELD = "LEASE_HELD"
LEASE_EXPIRED = "LEASE_EXPIRED"
GRANT_DENIED = "GRANT_DENIED"
OWNER_ABSENT = "OWNER_ABSENT"
PAUSED = "PAUSED"
QUEUE_FULL = "QUEUE_FULL"
TOMBSTONED = "TOMBSTONED"
INVALID_REQUEST = "INVALID_REQUEST"
INVALID_OPERATION = "INVALID_OPERATION"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
EPOCH_CLOSED = "EPOCH_CLOSED"
NOT_FOUND = "NOT_FOUND"
TENANT_MISMATCH = "TENANT_MISMATCH"
INTERNAL_ERROR = "INTERNAL_ERROR"


class ActorError(Exception):
    """A rejected actor call. The committed state is never partially changed."""

    def __init__(self, code: str, message: str, **detail):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


def token(value: object, label: str) -> str:
    if not (isinstance(value, str) and TOKEN.match(value)):
        raise ActorError(INVALID_REQUEST, f"{label} must match {TOKEN.pattern}")
    return value


@dataclass(frozen=True)
class Grant:
    """What the owner approved for one exact principal in one exact tenant/project.

    ``subject`` is the credential principal identity (decided by SE-03). ``client`` is a
    display label only: it is never used for authorisation.
    """
    tenant: str
    project: str
    subject: str
    client: str
    scopes: frozenset

    def __post_init__(self):
        token(self.tenant, "grant tenant")
        token(self.project, "grant project")
        token(self.subject, "grant subject")
        if not (isinstance(self.client, str) and 1 <= len(self.client) <= 128):
            raise ActorError(INVALID_REQUEST, "grant client label must be 1..128 characters")
        scopes = frozenset(self.scopes)
        if not scopes or not scopes <= SCOPES:
            raise ActorError(INVALID_REQUEST, "grant scopes must be a non-empty subset of read/write")
        object.__setattr__(self, "scopes", scopes)


@dataclass(frozen=True)
class Lease:
    """Fenced single-writer lease. Only ``holder`` and ``fence`` are trusted by the actor."""
    holder: str
    fence: int
    expires_at: float


# --- staged ledger ---------------------------------------------------------------------

def derived_key(idempotency_key: str, module_id: str) -> str:
    """Per-module ledger idempotency key derived from the transaction key (<=128, KEY_PATTERN)."""
    return sha256_hex(f"{idempotency_key}|{module_id}".encode("utf-8"))[:48]


def ir_record(module: dict) -> dict:
    data = canonical_json(module)
    return {"sha256": sha256_hex(data), "bytes": len(data)}


def stage_ledger(state: "ActorState", txn: dict, on_first_target=None) -> tuple[ModuleStore, frozenset]:
    """Apply every target to a *deep copy* of the ledger and return it with the new tombstones.

    CAS failures raise ``REVISION_CONFLICT``; tombstoned ids can never be reused in this
    epoch; dependency minimum revisions are verified after all targets are staged so a
    dependency created in the same atomic transaction is honoured. The committed ledger is
    never touched.
    """
    staged = copy.deepcopy(state.ledger)
    tombstones = set(state.tombstones)
    key = txn["idempotencyKey"]
    live = state.project.module_revisions()
    replaced: list[dict] = []
    first = True
    for change in txn["changes"]:
        mid, expected = change["moduleId"], change["expectedModuleRevision"]
        if mid in state.tombstones:
            raise ActorError(TOMBSTONED, f"{mid} was removed in this epoch and its id cannot be reused",
                             moduleId=mid)
        dk = derived_key(key, mid)
        try:
            if change["op"] == "replace_module":
                module = change["module"]
                if mid in live:
                    if type(expected) is not int:
                        raise ActorError(REVISION_CONFLICT, f"{mid} already exists; expected revision is required",
                                         moduleId=mid, currentModuleRevision=live[mid])
                    staged.apply(mid, expected, dk,
                                 [{"op": "replace", "id": IR_BLOCK, "data": ir_record(module)}])
                else:
                    if expected is not None:
                        raise ActorError(REVISION_CONFLICT, f"{mid} does not exist at revision {expected}",
                                         moduleId=mid)
                    if module.get("revision") != 1:
                        raise ActorError(INVALID_OPERATION, f"{mid}: a new module must start at revision 1",
                                         moduleId=mid)
                    staged.create_module(mid)
                    staged.apply(mid, 0, dk, [{"op": "add", "id": IR_BLOCK, "data": ir_record(module)}])
                replaced.append(module)
            else:
                if mid not in live:
                    raise ActorError(INVALID_OPERATION, f"{mid}: cannot remove a module that does not exist",
                                     moduleId=mid)
                staged.apply(mid, expected, dk, [{"op": "remove", "id": IR_BLOCK}])
                tombstones.add(mid)
        except StaleRevisionError as exc:
            raise ActorError(REVISION_CONFLICT, str(exc), moduleId=mid,
                             expectedModuleRevision=exc.expected, currentModuleRevision=exc.actual) from exc
        except IdentityError as exc:
            code = BUDGET_EXCEEDED if "budget" in str(exc) else INVALID_OPERATION
            raise ActorError(code, str(exc), moduleId=mid) from exc
        if first and on_first_target is not None:
            on_first_target()
        first = False
    for module in replaced:
        for dep in module.get("dependencies", []):
            need, dep_id = dep["minRevision"], dep["moduleId"]
            if dep_id in tombstones or dep_id not in staged.modules() or staged.revision(dep_id) < need:
                have = None if dep_id in tombstones or dep_id not in staged.modules() else staged.revision(dep_id)
                raise ActorError(DEPENDENCY_STALE,
                                 f"{module['moduleId']}: dependency {dep_id} is at revision {have}, need >= {need}",
                                 moduleId=module["moduleId"], dependency=dep_id, required=need, actual=have)
    return staged, frozenset(tombstones)


def verify_consistent(project: ProjectState, ledger: ModuleStore, tombstones: frozenset, touched: set) -> None:
    """Fail closed (before the swap) if the typed-IR map and the revision ledger disagree."""
    revisions = project.module_revisions()
    ledger_ids = set(ledger.modules())
    if ledger_ids != set(revisions) | set(tombstones):
        raise ActorError(INTERNAL_ERROR, "ledger and project module sets diverged")
    for mid in touched:
        if mid in revisions:
            rev, blocks = ledger.snapshot(mid)
            module = project.module(mid)
            if rev != revisions[mid] or blocks.get(IR_BLOCK) != ir_record(module):
                raise ActorError(INTERNAL_ERROR, f"{mid}: ledger revision/digest diverged from typed IR")
        elif ledger.snapshot(mid)[1]:
            raise ActorError(INTERNAL_ERROR, f"{mid}: tombstoned module still has ledger blocks")


# --- committed state ---------------------------------------------------------------------

class ActorState:
    """One committed actor state; replaced as a whole, never mutated.

    ``ledger`` is a ``ModuleStore`` that is only ever *deep-copied and re-staged*; the
    instance held here is never written to after commit. ``outcomes`` maps idempotency key
    to ``(subject, request sha256, canonical outcome bytes)`` and is committed atomically
    with the swap.
    """
    __slots__ = ("project", "tombstones", "ledger", "outcomes", "order", "view_bytes")

    def __init__(self, project, tombstones, ledger, outcomes, order, view_bytes):
        for name, value in (("project", project), ("tombstones", frozenset(tombstones)), ("ledger", ledger),
                            ("outcomes", MappingProxyType(dict(outcomes))), ("order", tuple(order)),
                            ("view_bytes", view_bytes)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("ActorState is immutable; the actor swaps whole states")

    def __delattr__(self, name):
        raise AttributeError("ActorState is immutable; the actor swaps whole states")

    @classmethod
    def initial(cls) -> "ActorState":
        return cls(EMPTY_STATE, frozenset(), ModuleStore(), {}, (), canonical_json(project_view(EMPTY_STATE)))

    def succeed(self, project: ProjectState, tombstones: frozenset, ledger: ModuleStore,
                key: str, record: tuple, view: dict) -> "ActorState":
        outcomes = dict(self.outcomes)
        order = list(self.order)
        outcomes[key] = record
        order.append(key)
        while len(order) > MAX_OUTCOMES:
            outcomes.pop(order.pop(0), None)
        return ActorState(project, tombstones, ledger, outcomes, order, canonical_json(view))

    def view(self) -> dict:
        return json.loads(self.view_bytes)

    def digest(self) -> str:
        """sha256 over the canonical IR, project revision, tombstones, the whole ledger
        (revisions, blocks, per-module idempotency keys) and the outcome cache."""
        ledger = []
        for mid in self.ledger.modules():
            rev, blocks = self.ledger.snapshot(mid)
            ledger.append([mid, rev, blocks, sorted(self.ledger._keys[mid].items())])  # read-only peek
        return sha256_hex(canonical_json({
            "ir": sha256_hex(canonical_ir_json(self.project)),
            "projectRevision": self.project.project_revision,
            "tombstones": sorted(self.tombstones),
            "ledger": ledger,
            "outcomes": [[k, self.outcomes[k][0], self.outcomes[k][1]] for k in self.order],
            "view": sha256_hex(self.view_bytes),
        }))
