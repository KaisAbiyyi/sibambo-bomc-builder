"""BMB-024: durable, hash-chained agent sessions with checkpoints, resume and deterministic replay.

A session is one append-only JSON-lines file (`<root>/sessions/<id>.jsonl`, no timestamps) recording
what an agent read (digest + token cost) and wrote (the full request and the resulting revision and
journal hash). A checkpoint snapshots every module's (revision, journal hash). `resume` compares that
snapshot with the live journal and reports only what changed, so a returning agent re-reads the delta
instead of the scene. `replay_into` re-executes the recorded writes into another store and proves the
result byte-identical through the journal hashes. Sessions are advisory bookkeeping, not authentication.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from agentctx.budget import canonical, digest
from agentctx.retrieval import MAX_TOKENS, MIN_TOKENS, ContextProvider
from core.storage.journal import JournalStore

SESSION_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
GENESIS = "0" * 64
MAX_ENTRIES = 10_000
MAX_LINE_BYTES = 128 * 1024
MAX_REQUEST_BYTES = 96 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
DEFAULT_TOKEN_CAP = 50_000
MAX_TOKEN_CAP = 1_000_000
MAX_REPORTED = 50


class SessionError(ValueError):
    """Rejected request, corrupt session file or broken session; the journal is never touched by this."""


class SessionBudgetExceeded(SessionError):
    """The session's cumulative context budget does not allow another response."""


class ReplayDivergence(SessionError):
    """Replaying a recorded write produced a different revision or journal hash."""


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise SessionError(message)


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _reject_constant(name):
    raise ValueError(f"non-finite number {name}")


def _entry_hash(entry: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "hash"}).encode()).hexdigest()


class SessionStore:
    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root) / "sessions"

    def path(self, session_id: str) -> Path:
        _need(isinstance(session_id, str) and SESSION_ID.match(session_id) is not None, f"invalid session id {session_id!r}")
        return self.root / f"{session_id}.jsonl"

    def sessions(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.jsonl")) if self.root.is_dir() else []

    def create(self, session_id: str, *, brief_hash: str | None = None, token_cap: int = DEFAULT_TOKEN_CAP) -> "Session":
        path = self.path(session_id)
        _need(brief_hash is None or (isinstance(brief_hash, str) and re.fullmatch(r"[0-9a-f]{64}", brief_hash)),
              "brief_hash must be a lowercase sha256 hex digest")
        _need(type(token_cap) is int and MIN_TOKENS <= token_cap <= MAX_TOKEN_CAP, "token_cap out of range")
        self.root.mkdir(parents=True, exist_ok=True)
        session = Session(path)
        session._append({"type": "session", "id": session_id, "briefHash": brief_hash, "tokenCap": token_cap}, create=True)
        session.token_cap, session.brief_hash = token_cap, brief_hash
        return session

    def open(self, session_id: str) -> "Session":
        path = self.path(session_id)
        _need(path.is_file(), f"unknown session {session_id!r}")
        session = Session(path)
        session._load()
        return session


class Session:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._tail, self._size, self._seq = GENESIS, 0, -1
        self.id = path.stem
        self.token_cap = DEFAULT_TOKEN_CAP
        self.brief_hash = None
        self.tokens_used = 0
        self._steps: list[dict] = []
        self._checkpoints: list[dict] = []
        self._broken = False

    # --- file ------------------------------------------------------------------
    def _load(self) -> None:
        if self.path.stat().st_size > MAX_FILE_BYTES:
            raise SessionError("session file exceeds the size budget")
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):  # torn tail: that entry never completed
            data = data[:data.rfind(b"\n") + 1]
            os.truncate(self.path, len(data))
        lines = data.split(b"\n")[:-1]
        _need(0 < len(lines) <= MAX_ENTRIES, "empty or oversized session")
        prev = GENESIS
        for n, line in enumerate(lines):
            try:
                _need(len(line) <= MAX_LINE_BYTES, "line too large")
                entry = json.loads(line.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
                _need(isinstance(entry, dict) and entry.get("seq") == n and entry.get("prev") == prev
                      and entry.get("hash") == _entry_hash(entry), "chain, sequence or hash mismatch")
                self._apply_loaded(entry, n)
            except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
                raise SessionError(f"{self.path.name}: corrupt at line {n + 1}: {exc}") from exc
            prev = entry["hash"]
        self._tail, self._size, self._seq = prev, len(data), len(lines) - 1

    def _apply_loaded(self, entry: dict, n: int) -> None:
        kind = entry["type"]
        if n == 0:
            _need(kind == "session" and entry["id"] == self.path.stem, "bad session header")
            self.token_cap, self.brief_hash = entry["tokenCap"], entry["briefHash"]
        elif kind == "step":
            _need(entry["effect"] in ("read", "write"), "bad step effect")
            self._steps.append(entry)
            self.tokens_used += entry["tokens"] if entry["effect"] == "read" else 0
        elif kind == "checkpoint":
            _need(isinstance(entry["modules"], dict), "bad checkpoint")
            self._checkpoints.append(entry)
        else:
            raise ValueError(f"unknown entry type {kind!r}")

    def _append(self, fields: dict, create: bool = False) -> dict:
        _need(not self._broken, "session is broken after a failed write; reopen it")
        _need(self._seq + 1 <= MAX_ENTRIES, "session entry budget exceeded")
        entry = {"v": 1, "seq": self._seq + 1, "prev": self._tail, **fields}
        entry["hash"] = _entry_hash(entry)
        line = (canonical(entry) + "\n").encode()
        _need(len(line) <= MAX_LINE_BYTES and self._size + len(line) <= MAX_FILE_BYTES, "session size budget exceeded")
        if not create and self.path.stat().st_size != self._size:
            self._broken = True
            raise SessionError("session file changed on disk; reopen it")
        flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0) | (os.O_CREAT | os.O_EXCL if create else 0)
        try:
            fd = os.open(self.path, flags, 0o644)
            try:
                view = memoryview(line)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
        except FileExistsError as exc:
            raise SessionError(f"session {self.path.stem!r} already exists") from exc
        except OSError as exc:
            self._broken = True  # outcome unknown: the entry may or may not be on disk
            raise SessionError(f"session write failed ({exc}); reopen it") from exc
        self._tail, self._size, self._seq = entry["hash"], self._size + len(line), entry["seq"]
        return entry

    # --- reads ----------------------------------------------------------------------
    def remaining_tokens(self) -> int:
        return self.token_cap - self.tokens_used

    def _read(self, provider_call, tool: str, request: dict, max_tokens: int | None) -> dict:
        remaining = self.remaining_tokens()
        if remaining < MIN_TOKENS:
            raise SessionBudgetExceeded(f"session budget exhausted ({self.tokens_used}/{self.token_cap} tokens)")
        ask = min(max_tokens if max_tokens is not None else remaining, remaining, MAX_TOKENS)
        response = provider_call(max_tokens=ask)
        tokens = response["budget"]["usedTokens"]
        entry = self._append({"type": "step", "effect": "read", "tool": tool, "request": dict(request, max_tokens=ask),
                              "result": {"digest": digest(response, 16), "tokens": tokens}, "tokens": tokens})
        self._steps.append(entry)
        self.tokens_used += tokens
        return response

    def manifest(self, provider: ContextProvider, *, cursor=None, page_size=25, max_tokens=None) -> dict:
        return self._read(lambda max_tokens: provider.manifest(cursor=cursor, page_size=page_size, max_tokens=max_tokens),
                          "manifest", {"cursor": cursor, "page_size": page_size}, max_tokens)

    def module(self, provider: ContextProvider, module_id: str, *, depth=1, blocks=None, max_tokens=None) -> dict:
        return self._read(lambda max_tokens: provider.module(module_id, depth=depth, blocks=blocks, max_tokens=max_tokens),
                          "module", {"module": module_id, "depth": depth, "blocks": blocks}, max_tokens)

    # --- recorded writes --------------------------------------------------------------
    def _write(self, tool: str, request: dict, call, store: JournalStore, module_id: str) -> object:
        _need(len(canonical(request).encode()) <= MAX_REQUEST_BYTES, "request too large to record")
        result = call()  # exceptions propagate unlogged: nothing was committed
        if getattr(result, "replayed", False):
            return result  # an idempotent retry changed nothing, so there is nothing to replay
        entry = self._append({"type": "step", "effect": "write", "tool": tool, "request": request, "tokens": 0,
                              "result": {"revision": result if isinstance(result, int) else result.revision,
                                         "replayed": getattr(result, "replayed", False),
                                         "tail": store.tail_hash(module_id)}})
        self._steps.append(entry)
        return result

    def create_module(self, store: JournalStore, module_id: str) -> int:
        return self._write("create_module", {"module": module_id}, lambda: store.create_module(module_id), store, module_id)

    def apply(self, store: JournalStore, module_id: str, expected_revision: int, key: str, ops: list,
              min_revisions: dict | None = None):
        request = {"module": module_id, "expectedRevision": expected_revision, "key": key, "ops": ops,
                   "minRevisions": min_revisions}
        return self._write("apply", request, lambda: store.apply(module_id, expected_revision, key, ops, min_revisions),
                           store, module_id)

    def rollback(self, store: JournalStore, module_id: str, expected_revision: int, key: str, to_revision: int):
        request = {"module": module_id, "expectedRevision": expected_revision, "key": key, "toRevision": to_revision}
        return self._write("rollback", request, lambda: store.rollback(module_id, expected_revision, key, to_revision),
                           store, module_id)

    def steps(self) -> list[dict]:
        return [dict(s) for s in self._steps]

    # --- checkpoint / resume ------------------------------------------------------------
    def checkpoint(self, provider: ContextProvider, label: str | None = None) -> dict:
        _need(label is None or (isinstance(label, str) and SESSION_ID.match(label)), "label must be a short slug")
        state = provider.state()
        entry = self._append({"type": "checkpoint", "label": label, "projectDigest": provider.project_digest(),
                              "modules": {m: list(v) for m, v in sorted(state.items())}, "tokensUsed": self.tokens_used,
                              "stepsSoFar": len(self._steps)})
        self._checkpoints.append(entry)
        return {"seq": entry["seq"], "label": label, "projectDigest": entry["projectDigest"], "modules": len(state)}

    def last_checkpoint(self) -> dict | None:
        return None if not self._checkpoints else dict(self._checkpoints[-1])

    def resume(self, provider: ContextProvider) -> dict:
        """Compare the last checkpoint with the live journal and report only what changed."""
        cp = self.last_checkpoint()
        _need(cp is not None, "session has no checkpoint")
        current = provider.state()
        if provider.project_digest() == cp["projectDigest"]:
            return {"status": "current", "checkpointSeq": cp["seq"], "projectDigest": cp["projectDigest"],
                    "changed": [], "tokensUsed": self.tokens_used, "tokensRemaining": self.remaining_tokens()}
        saved = {m: tuple(v) for m, v in cp["modules"].items()}
        report = {"unchanged": 0, "advanced": [], "diverged": [], "missing": [], "new": []}
        for m, (rev, tail) in sorted(saved.items()):
            if m not in current:
                report["missing"].append(m)
            elif current[m] == (rev, tail):
                report["unchanged"] += 1
            elif current[m][0] > rev and provider.revision_hashes(m)[rev] == tail:
                report["advanced"].append({"id": m, "from": rev, "to": current[m][0]})
            else:
                report["diverged"].append(m)
        report["new"] = sorted(set(current) - set(saved))
        changed = sorted([a["id"] for a in report["advanced"]] + report["diverged"] + report["missing"] + report["new"])
        omitted = {k: max(0, len(report[k]) - MAX_REPORTED) for k in ("advanced", "diverged", "missing", "new")}
        for k in omitted:
            report[k] = report[k][:MAX_REPORTED]
        return {"status": "diverged" if report["diverged"] or report["missing"] else "advanced",
                "checkpointSeq": cp["seq"], "projectDigest": provider.project_digest(), **report,
                "changed": changed[:MAX_REPORTED], "changedOmitted": max(0, len(changed) - MAX_REPORTED),
                "omitted": omitted, "tokensUsed": self.tokens_used, "tokensRemaining": self.remaining_tokens()}

    # --- replay ----------------------------------------------------------------------------
    def replay_into(self, target: JournalStore) -> dict:
        """Re-run the recorded writes, in order, against `target`; every result must match the recording."""
        count = 0
        for s in self._steps:
            if s["effect"] != "write":
                continue
            r, rec = s["request"], s["result"]
            replayed = False
            if s["tool"] == "create_module" and r["module"] in target.modules():
                # already present (replay into the original or a partial copy): it must be the same module
                if ContextProvider(target).revision_hashes(r["module"])[0] != rec["tail"]:
                    raise ReplayDivergence(f"step {s['seq']}: existing module {r['module']} has a different origin")
                revision, replayed = 0, True
            elif s["tool"] == "create_module":
                revision = target.create_module(r["module"])
            else:
                got = (target.apply(r["module"], r["expectedRevision"], r["key"], r["ops"], r["minRevisions"])
                       if s["tool"] == "apply" else
                       target.rollback(r["module"], r["expectedRevision"], r["key"], r["toRevision"]))
                revision, replayed = got.revision, got.replayed
            if revision != rec["revision"]:
                raise ReplayDivergence(f"step {s['seq']}: revision {revision}, recorded {rec['revision']}")
            if not replayed and target.tail_hash(r["module"]) != rec["tail"]:
                raise ReplayDivergence(f"step {s['seq']}: journal hash differs from the recording")
            count += 1
        return {"replayedWrites": count, "modules": len(target.modules())}

