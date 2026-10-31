"""BMB-008: stable IDs, revision-checked writes and idempotent replay.

Each module has a monotonically increasing revision and a set of blocks keyed
by stable slug ids (never array positions). A write names the revision it
read; if the module has moved on the whole batch is rejected. A repeated
idempotency key replays the stored result instead of applying again. Every
batch is applied to a copy and committed last, so any rejection leaves the
store untouched. Pure Python, no persistence (journal is BMB-010).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

MODULE_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+\Z")
BLOCK_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_MODULES = 1024
MAX_BLOCKS_PER_MODULE = 4096
MAX_OPS_PER_BATCH = 256
MAX_BLOCK_BYTES = 65_536
MAX_KEYS_PER_MODULE = 4096
OPS = ("add", "replace", "remove")


class IdentityError(ValueError):
    """Rejected input or edit; the store is never partially mutated."""


class StaleRevisionError(IdentityError):
    def __init__(self, module_id: str, expected: int, actual: int):
        super().__init__(f"stale write to {module_id}: expected revision {expected}, current {actual}")
        self.expected, self.actual = expected, actual


class StaleDependencyError(IdentityError):
    def __init__(self, module_id: str, required: int, actual: int | None):
        super().__init__(f"dependency {module_id} at revision {actual}, need >= {required}")
        self.required, self.actual = required, actual


class IdempotencyConflictError(IdentityError):
    """The idempotency key was already used for a different request."""


@dataclass(frozen=True)
class ApplyResult:
    module_id: str
    revision: int
    replayed: bool


def _need(test: bool, reason: str) -> None:
    if not test:
        raise IdentityError(reason)


def _slug(pattern: re.Pattern, value: object, label: str) -> str:
    _need(isinstance(value, str) and pattern.match(value) is not None,
          f"{label}: invalid id {value!r}")
    return value


def _payload(value: object, label: str) -> dict:
    """JSON round-trip copy: detaches caller data and rejects non-JSON values."""
    _need(isinstance(value, dict), f"{label}: block data must be an object")
    try:
        text = json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise IdentityError(f"{label}: block data is not plain JSON") from exc
    _need(len(text.encode()) <= MAX_BLOCK_BYTES, f"{label}: block exceeds size budget")
    return json.loads(text)


def _fingerprint(module_id: str, expected: int, ops: list, mins: dict) -> str:
    text = json.dumps([module_id, expected, ops, sorted(mins.items())],
                      sort_keys=True, allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


class ModuleStore:
    def __init__(self) -> None:
        self._rev: dict[str, int] = {}
        self._blocks: dict[str, dict[str, dict]] = {}
        # moduleId -> {key: (fingerprint, resulting revision)}
        self._keys: dict[str, dict[str, tuple[str, int]]] = {}

    # queries
    def modules(self) -> list[str]:
        return sorted(self._rev)

    def revision(self, module_id: str) -> int:
        _need(module_id in self._rev, f"unknown module {module_id!r}")
        return self._rev[module_id]

    def snapshot(self, module_id: str) -> tuple[int, dict[str, dict]]:
        """Revision and a deep copy of the blocks, ordered by id."""
        rev = self.revision(module_id)
        return rev, {k: json.loads(json.dumps(v)) for k, v in sorted(self._blocks[module_id].items())}

    # edits
    def create_module(self, module_id: str) -> int:
        _slug(MODULE_ID_PATTERN, module_id, "module")
        _need(module_id not in self._rev, f"duplicate module {module_id!r}")
        _need(len(self._rev) < MAX_MODULES, "module budget exceeded")
        self._rev[module_id] = 0
        self._blocks[module_id] = {}
        self._keys[module_id] = {}
        return 0

    def apply(self, module_id: str, expected_revision: int, idempotency_key: str,
              ops: list[dict], min_revisions: dict[str, int] | None = None) -> ApplyResult:
        """Apply a batch of {op: add|replace|remove, id, data?} atomically.

        Order of checks: key syntax, idempotent replay, revision, dependency
        minimums, then the ops themselves. Only a fully valid batch bumps the
        revision (by exactly one) and records the key.
        """
        _need(module_id in self._rev, f"unknown module {module_id!r}")
        _need(type(expected_revision) is int and expected_revision >= 0, "expected_revision must be a non-negative int")
        _slug(KEY_PATTERN, idempotency_key, "idempotency key")
        _need(isinstance(ops, list) and 0 < len(ops) <= MAX_OPS_PER_BATCH, "ops must be 1..256 entries")
        _need(min_revisions is None or isinstance(min_revisions, dict), "min_revisions must be an object or None")
        mins = {} if min_revisions is None else dict(min_revisions)
        for dep, need in mins.items():
            _slug(MODULE_ID_PATTERN, dep, "dependency")
            _need(type(need) is int and need >= 0, f"dependency {dep}: minimum revision must be a non-negative int")
        checked = self._check_ops(ops)
        fp = _fingerprint(module_id, expected_revision, checked, mins)

        seen = self._keys[module_id].get(idempotency_key)
        if seen is not None:
            if seen[0] != fp:
                raise IdempotencyConflictError(f"idempotency key {idempotency_key!r} reused for a different request")
            return ApplyResult(module_id, seen[1], True)

        if expected_revision != self._rev[module_id]:
            raise StaleRevisionError(module_id, expected_revision, self._rev[module_id])
        for dep, need in sorted(mins.items()):
            if dep not in self._rev or self._rev[dep] < need:
                raise StaleDependencyError(dep, need, self._rev.get(dep))
        _need(len(self._keys[module_id]) < MAX_KEYS_PER_MODULE, "idempotency key budget exceeded")

        staged = dict(self._blocks[module_id])
        for item in checked:
            block, op = item["id"], item["op"]
            if op == "add":
                _need(block not in staged, f"duplicate block {block!r}")
                _need(len(staged) < MAX_BLOCKS_PER_MODULE, "block budget exceeded")
                staged[block] = item["data"]
            elif op == "replace":
                _need(block in staged, f"unknown block {block!r}")
                staged[block] = item["data"]
            else:
                _need(block in staged, f"unknown block {block!r}")
                del staged[block]

        new_rev = self._rev[module_id] + 1
        self._blocks[module_id] = staged
        self._rev[module_id] = new_rev
        self._keys[module_id][idempotency_key] = (fp, new_rev)
        return ApplyResult(module_id, new_rev, False)

    @staticmethod
    def _check_ops(ops: list) -> list[dict]:
        out = []
        for n, raw in enumerate(ops):
            label = f"op {n}"
            _need(isinstance(raw, dict) and raw.get("op") in OPS, f"{label}: op must be one of {OPS}")
            _need(set(raw) <= {"op", "id", "data"}, f"{label}: unknown field")
            item = {"op": raw["op"], "id": _slug(BLOCK_ID_PATTERN, raw.get("id"), label)}
            if raw["op"] == "remove":
                _need("data" not in raw, f"{label}: remove takes no data")
            else:
                item["data"] = _payload(raw.get("data"), label)
            out.append(item)
        _need(len({i["id"] for i in out}) == len(out), "batch touches the same block id twice")
        return out
