"""BMB-010: durable per-module journal with reopen and deterministic rollback.

`JournalStore` is a `ModuleStore` (BMB-008) whose committed revisions are also
appended to one small append-only file per module. A line is a hash-chained
JSON entry; a revision is committed once its newline-terminated line is written
and fsynced. State is rebuilt by replaying the journal, so each module reloads
independently of the others. Rollback never rewrites history: it commits a new
revision whose ops restore the blocks of an earlier one. Entries carry no
timestamps, so identical operations give byte-identical files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from core.identity.store import (
    KEY_PATTERN, MODULE_ID_PATTERN, ApplyResult, IdempotencyConflictError, IdentityError,
    ModuleStore, StaleRevisionError, _fingerprint)

GENESIS = "0" * 64
JOURNAL = "journal.jsonl"
MAX_ENTRIES = 10_000          # revisions per module (plus the create entry)
MAX_LINE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_ITEMS = 256               # dependency minimums per entry, as in ModuleStore ops per batch
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = {
    "create": {"v", "type", "moduleId", "rev", "prev", "hash"},
    "commit": {"v", "type", "moduleId", "rev", "prev", "hash", "key", "fp", "mins", "ops"},
    "rollback": {"v", "type", "moduleId", "rev", "prev", "hash", "key", "fp", "mins", "ops", "rollbackTo"},
}


class StorageError(Exception):
    """Journal I/O failure; the in-memory state is reloaded from disk."""


class DurabilityUncertainError(StorageError):
    """The record was written completely but fsync failed, so it may be lost.

    The module is quarantined: its in-memory state matches the visible file,
    but writes (and reads-as-dependency) are refused until `recover()` re-writes
    the journal through a freshly fsynced file. Never retry fsync on the same
    file and call it durable: after a failed fsync the OS may drop the dirty
    pages and report a later fsync as successful.
    """


class CorruptJournalError(StorageError):
    """A journal fails integrity checks; it is never partially trusted."""


class ConcurrentWriteError(StorageError):
    """The journal changed on disk since this store last read or wrote it."""


def _dirname(module_id: str) -> str:
    return module_id.replace("/", "__")  # ids contain no underscore, so this is reversible


def _module_id(dirname: str) -> str:
    module_id = dirname.replace("__", "/")
    if MODULE_ID_PATTERN.match(module_id) is None or _dirname(module_id) != dirname:
        raise CorruptJournalError(f"unexpected directory {dirname!r} under modules/")
    return module_id


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(entry: dict) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in entry.items() if k != "hash"}).encode()).hexdigest()


def _reject_constant(name: str):
    raise ValueError(f"non-finite number {name}")


class JournalStore(ModuleStore):
    def __init__(self, root: str | os.PathLike) -> None:
        super().__init__()
        self._root = Path(root)
        self._tail: dict[str, tuple[str, int]] = {}      # module -> (last entry hash, file size)
        self._history: dict[str, list[list[dict]]] = {}  # module -> ops of revision 1..n
        self._uncertain: set[str] = set()                # modules whose newest record may not be durable

    # --- open / reload -----------------------------------------------------
    @classmethod
    def open(cls, root: str | os.PathLike, modules: list[str] | None = None) -> "JournalStore":
        """Load every module under `root`, or only `modules` (others are not read)."""
        store = cls(root)
        base = store._root / "modules"
        base.mkdir(parents=True, exist_ok=True)
        found = {_module_id(p.name): p.name for p in sorted(base.iterdir()) if p.is_dir()}
        wanted = sorted(found) if modules is None else list(modules)
        for module_id in wanted:
            if not isinstance(module_id, str) or module_id not in found:
                raise StorageError(f"no journal for module {module_id!r}")
        for module_id in sorted(set(wanted)):
            store._load(module_id)
        return store

    def _path(self, module_id: str) -> Path:
        return self._root / "modules" / _dirname(module_id) / JOURNAL

    def _forget(self, module_id: str) -> None:
        for table in (self._rev, self._blocks, self._keys, self._tail, self._history):
            table.pop(module_id, None)
        self._uncertain.discard(module_id)

    def _reload(self, module_id: str) -> None:
        self._forget(module_id)
        if self._path(module_id).exists():
            self._load(module_id)

    def _load(self, module_id: str) -> None:
        path = self._path(module_id)
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise CorruptJournalError(f"{module_id}: journal exceeds size budget")
            data = path.read_bytes()
            if data and not data.endswith(b"\n"):  # torn tail: the commit never completed
                data = data[:data.rfind(b"\n") + 1]
                os.truncate(path, len(data))
            if not data:  # create never completed
                path.unlink()
                path.parent.rmdir()
                return
            self._replay(module_id, data)
        except CorruptJournalError:
            self._forget(module_id)
            raise
        except OSError as exc:
            self._forget(module_id)
            raise StorageError(f"{module_id}: cannot read journal: {exc}") from exc

    def _replay(self, module_id: str, data: bytes) -> None:
        lines = data.split(b"\n")[:-1]
        if len(lines) > MAX_ENTRIES + 1:
            raise CorruptJournalError(f"{module_id}: too many entries")
        prev = GENESIS
        try:
            for n, line in enumerate(lines):
                if len(line) > MAX_LINE_BYTES:
                    raise ValueError("line exceeds size budget")
                entry = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
                kind = entry.get("type") if isinstance(entry, dict) else None
                if kind not in FIELDS or set(entry) != FIELDS[kind]:
                    raise ValueError("unknown entry shape")
                if (entry["v"] != 1 or entry["moduleId"] != module_id or entry["rev"] != n
                        or (n == 0) != (kind == "create") or entry["prev"] != prev
                        or entry["hash"] != _digest(entry)):
                    raise ValueError("chain, revision or hash mismatch")
                if n == 0:
                    ModuleStore.create_module(self, module_id)
                else:
                    self._replay_commit(module_id, n, kind, entry)
                if n == 0:
                    self._history[module_id] = []
                prev = entry["hash"]
        except (ValueError, KeyError, TypeError, AttributeError, IdentityError, RecursionError) as exc:
            self._forget(module_id)
            raise CorruptJournalError(f"{module_id}: corrupt journal at line {n + 1}: {exc}") from exc
        self._tail[module_id] = (prev, len(data))

    def _replay_commit(self, module_id: str, n: int, kind: str, entry: dict) -> None:
        """Apply one commit/rollback entry and verify its recorded request metadata."""
        mins = entry["mins"]
        if not (isinstance(mins, dict) and len(mins) <= MAX_ITEMS
                and all(isinstance(k, str) and MODULE_ID_PATTERN.match(k) and type(v) is int and v >= 0
                        for k, v in mins.items())):
            raise ValueError("bad dependency minimums")
        if kind == "rollback":
            target = entry["rollbackTo"]
            if type(target) is not int or not 0 <= target < n - 1:
                raise ValueError("bad rollbackTo")
            if mins:
                raise ValueError("rollback records no dependency minimums")
            expected_fp = _fingerprint(module_id, n - 1, [{"op": "rollback", "to": target}], {})
            restored = self._blocks_at(module_id, target)
        checked = self._check_ops(entry["ops"])
        if kind == "commit":
            expected_fp = _fingerprint(module_id, n - 1, checked, mins)
        if entry["fp"] != expected_fp:
            raise ValueError("recorded fingerprint does not match the recorded request")
        result = ModuleStore.apply(self, module_id, n - 1, entry["key"], entry["ops"])
        if result.replayed or result.revision != n:
            raise ValueError("duplicate idempotency key")
        if kind == "rollback" and self._blocks[module_id] != restored:
            raise ValueError(f"rollback ops do not restore revision {target}")
        self._keys[module_id][entry["key"]] = (expected_fp, n)
        self._history[module_id].append(checked)

    # --- appending ---------------------------------------------------------
    def _append(self, module_id: str, fields: dict, create: bool = False) -> None:
        path = self._path(module_id)
        prev, size = self._tail.get(module_id, (GENESIS, 0))
        entry = {"v": 1, "moduleId": module_id, "prev": prev, **fields}
        entry["hash"] = _digest(entry)
        line = (_canonical(entry) + "\n").encode()
        if len(line) > MAX_LINE_BYTES or fields["rev"] > MAX_ENTRIES or size + len(line) > MAX_FILE_BYTES:
            raise StorageError(f"{module_id}: journal size budget exceeded")  # a file open() would reject is never written
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif path.stat().st_size != size:
            raise ConcurrentWriteError(f"{module_id}: journal changed on disk; reopen the store")
        flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0) | (os.O_CREAT | os.O_EXCL if create else 0)
        fd = os.open(path, flags, 0o644)
        unsynced = None
        try:
            self._write_all(fd, line)
            try:
                os.fsync(fd)
            except OSError as exc:  # the line is fully written; whether it is durable is unknown
                unsynced = exc
        finally:
            os.close(fd)
        self._tail[module_id] = (entry["hash"], size + len(line))  # the file now ends with this line
        if create:
            self._sync_dir(path.parent)
        if unsynced is not None:
            raise DurabilityUncertainError(
                f"{module_id}: record written but fsync failed ({unsynced}); durability unknown, "
                "module quarantined until recover()") from unsynced

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]

    @staticmethod
    def _sync_dir(directory: Path) -> None:
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:  # not supported on every platform
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _persist(self, module_id: str, fields: dict, ops: list[dict]) -> None:
        try:
            self._append(module_id, fields)
        except DurabilityUncertainError:
            self._uncertain.add(module_id)      # memory matches the visible file; durability is unknown
            self._history[module_id].append(ops)
            raise
        except Exception as exc:
            self._reload(module_id)  # disk is the truth; drop the uncommitted in-memory change
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"{module_id}: commit failed: {exc}") from exc
        self._history[module_id].append(ops)

    # --- public edits ------------------------------------------------------
    def create_module(self, module_id: str) -> int:
        super().create_module(module_id)
        try:
            self._append(module_id, {"type": "create", "rev": 0}, create=True)
        except DurabilityUncertainError:
            self._uncertain.add(module_id)
            self._history[module_id] = []
            raise
        except Exception as exc:
            self._forget(module_id)
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"{module_id}: cannot create journal: {exc}") from exc
        self._history[module_id] = []
        return 0

    def apply(self, module_id: str, expected_revision: int, idempotency_key: str,
              ops: list[dict], min_revisions: dict[str, int] | None = None) -> ApplyResult:
        self._refuse_uncertain(module_id, min_revisions)
        result = super().apply(module_id, expected_revision, idempotency_key, ops, min_revisions)
        if result.replayed:
            return result
        checked = self._check_ops(ops)
        self._persist(module_id, {
            "type": "commit", "rev": result.revision, "key": idempotency_key,
            "fp": self._keys[module_id][idempotency_key][0],
            "mins": dict(sorted((min_revisions or {}).items())), "ops": checked}, checked)
        return result

    def rollback(self, module_id: str, expected_revision: int, idempotency_key: str,
                 to_revision: int) -> ApplyResult:
        """Commit a new revision restoring the blocks as of `to_revision`.

        History is kept: revision numbers only grow. A repeated key with the
        same request replays; the same key for a different request is rejected.
        """
        if module_id not in self._rev:
            raise IdentityError(f"unknown module {module_id!r}")
        self._refuse_uncertain(module_id, None)
        if type(expected_revision) is not int or expected_revision < 0:
            raise IdentityError("expected_revision must be a non-negative int")
        if type(to_revision) is not int or to_revision < 0:
            raise IdentityError("to_revision must be a non-negative int")
        if not isinstance(idempotency_key, str) or KEY_PATTERN.match(idempotency_key) is None:
            raise IdentityError(f"idempotency key: invalid id {idempotency_key!r}")
        fp = _fingerprint(module_id, expected_revision, [{"op": "rollback", "to": to_revision}], {})
        seen = self._keys[module_id].get(idempotency_key)
        if seen is not None:
            if seen[0] != fp:
                raise IdempotencyConflictError(f"idempotency key {idempotency_key!r} reused for a different request")
            return ApplyResult(module_id, seen[1], True)
        if expected_revision != self._rev[module_id]:
            raise StaleRevisionError(module_id, expected_revision, self._rev[module_id])
        if to_revision >= expected_revision:
            raise IdentityError(f"cannot roll back to revision {to_revision} from {expected_revision}")
        target = self._blocks_at(module_id, to_revision)
        current = self._blocks[module_id]
        ops = [{"op": "remove", "id": b} for b in sorted(current.keys() - target.keys())]
        ops += [{"op": "replace" if b in current else "add", "id": b, "data": target[b]}
                for b in sorted(target) if current.get(b) != target[b]]
        if not ops:
            raise IdentityError(f"state at revision {to_revision} equals the current state; nothing to roll back")
        result = ModuleStore.apply(self, module_id, expected_revision, idempotency_key, ops)
        self._keys[module_id][idempotency_key] = (fp, result.revision)
        checked = self._check_ops(ops)
        self._persist(module_id, {"type": "rollback", "rev": result.revision, "key": idempotency_key,
                                  "fp": fp, "mins": {}, "ops": checked, "rollbackTo": to_revision}, checked)
        return result

    def _blocks_at(self, module_id: str, revision: int) -> dict[str, dict]:
        blocks: dict[str, dict] = {}
        for ops in self._history[module_id][:revision]:
            for op in ops:
                if op["op"] == "remove":
                    del blocks[op["id"]]
                else:
                    blocks[op["id"]] = op["data"]
        return blocks

    # --- uncertain durability ----------------------------------------------
    def uncertain_modules(self) -> list[str]:
        """Modules quarantined after a write whose fsync failed, sorted."""
        return sorted(self._uncertain)

    def _refuse_uncertain(self, module_id: str, min_revisions: object) -> None:
        deps = set(min_revisions) if isinstance(min_revisions, dict) else set()
        blocked = sorted(({module_id} | deps) & self._uncertain)
        if blocked:  # even an idempotent replay must not report success for a record that may be lost
            raise DurabilityUncertainError(f"{blocked[0]}: durability of the newest record is unknown; call recover()")

    def recover(self, module_id: str) -> None:
        """Make a quarantined module durable by re-writing its journal through a new, fsynced file.

        The visible content is copied to `journal.jsonl.recover`, fsynced, atomically renamed
        over the journal, and the module is reloaded and checked. If any step fails the
        module stays quarantined and the original file is left in place.
        """
        if module_id not in self._rev:
            raise IdentityError(f"unknown module {module_id!r}")
        if module_id not in self._uncertain:
            return
        path = self._path(module_id)
        tmp = path.with_name(JOURNAL + ".recover")
        revision, size = self._rev[module_id], self._tail[module_id][1]
        try:
            data = path.read_bytes()
            if len(data) != size:
                raise ConcurrentWriteError(f"{module_id}: journal changed on disk; reopen the store")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o644)
            try:
                self._write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise DurabilityUncertainError(f"{module_id}: recovery failed ({exc}); module stays quarantined") from exc
        self._sync_dir(path.parent)
        self._reload(module_id)  # also lifts the quarantine
        if self._rev.get(module_id) != revision:
            raise StorageError(f"{module_id}: recovered journal is at revision {self._rev.get(module_id)}, expected {revision}")

    def tail_hash(self, module_id: str) -> str:
        """Hash of the newest committed entry: identifies the exact journal state."""
        self.revision(module_id)
        return self._tail[module_id][0]
