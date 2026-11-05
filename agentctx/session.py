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
import stat
from pathlib import Path

from agentctx.budget import canonical, digest
from agentctx.retrieval import MAX_TOKENS, MIN_TOKENS, ContextProvider
from core.identity.store import IdentityError
from core.storage.journal import JournalStore
from core.storage import DurabilityUncertainError

SESSION_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
GENESIS = "0" * 64
MAX_ENTRIES = 10_000
MAX_LINE_BYTES = 128 * 1024
MAX_REQUEST_BYTES = 96 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
DEFAULT_TOKEN_CAP = 50_000
MAX_TOKEN_CAP = 1_000_000
MAX_REPORTED = 50
OUTCOME_RESERVE_BYTES = 2048   # room kept free for the entry that resolves an open intent


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


def _check_private(path: Path, *, directory: bool) -> None:
    """POSIX: refuse symlinks and foreign owners, tighten group/other access to 0o700 / 0o600. Windows ACLs are not validated."""
    if os.name != "posix":
        return
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise SessionError(f"cannot inspect {path.name}: {exc}") from exc
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    _need(kind(info.st_mode), f"{path.name} must be a plain {'directory' if directory else 'file'} (no symlinks)")
    _need(info.st_uid == os.geteuid(), f"{path.name} is owned by another user")
    if info.st_mode & 0o077:
        os.chmod(path, 0o700 if directory else 0o600)
        _need(not os.lstat(path).st_mode & 0o077, f"cannot restrict {path.name} to its owner")


def _private_dir(path: Path) -> None:
    """Create the sessions directory owner-only, or validate and tighten an existing one."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(path, 0o700)
    _check_private(path, directory=True)


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
        _private_dir(self.root)
        session = Session(path)
        session._append({"type": "session", "id": session_id, "briefHash": brief_hash, "tokenCap": token_cap}, create=True)
        session.token_cap, session.brief_hash = token_cap, brief_hash
        return session

    def open(self, session_id: str) -> "Session":
        path = self.path(session_id)
        _need(path.is_file() or path.is_symlink(), f"unknown session {session_id!r}")
        _check_private(self.root, directory=True)
        _check_private(path, directory=False)
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
        self._pending: dict[int, dict] = {}   # write intents recorded before the journal call, not yet resolved
        self._uncertain_intents: set[int] = set()  # intents whose journal write reported unknown durability
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
            _need(entry["effect"] == "read", "bad step effect")
            self._steps.append(entry)
            self.tokens_used += entry["tokens"]
        elif kind == "intent":
            _need(entry["tool"] in ("create_module", "apply", "rollback") and isinstance(entry["request"], dict), "bad intent")
            self._pending[entry["seq"]] = entry
        elif kind == "uncertain":
            _need(entry["intent"] in self._pending, "uncertain marker without an open intent")
            self._uncertain_intents.add(entry["intent"])
        elif kind == "outcome":
            intent = self._pending.pop(entry["intent"], None)
            self._uncertain_intents.discard(entry["intent"])
            _need(intent is not None, "outcome without an open intent")
            _need(entry["status"] in ("applied", "noop", "rejected", "abandoned", "conflict"), "bad outcome status")
            if entry["status"] == "applied":
                self._steps.append(self._write_step(intent, entry))
        elif kind == "checkpoint":
            _need(isinstance(entry["modules"], dict), "bad checkpoint")
            self._checkpoints.append(entry)
        else:
            raise ValueError(f"unknown entry type {kind!r}")

    @staticmethod
    def _write_step(intent: dict, outcome: dict) -> dict:
        return {"v": 1, "seq": intent["seq"], "prev": intent["prev"], "type": "step", "effect": "write",
                "tool": intent["tool"], "request": intent["request"], "tokens": 0, "result": outcome["result"]}

    def _append(self, fields: dict, create: bool = False, reserve_entries: int = 0, reserve_bytes: int = 0) -> dict:
        _need(not self._broken, "session is broken after a failed write; reopen it")
        if self._pending and fields["type"] != "outcome":  # always keep room for the entry that resolves the open intent
            reserve_entries, reserve_bytes = max(reserve_entries, 1), max(reserve_bytes, OUTCOME_RESERVE_BYTES)
        _need(self._seq + 2 + reserve_entries <= MAX_ENTRIES, "session entry budget exceeded")  # entries after = seq + 2, as _load() counts them
        entry = {"v": 1, "seq": self._seq + 1, "prev": self._tail, **fields}
        entry["hash"] = _entry_hash(entry)
        line = (canonical(entry) + "\n").encode()
        _need(len(line) <= MAX_LINE_BYTES and self._size + len(line) + reserve_bytes <= MAX_FILE_BYTES,
              "session size budget exceeded")
        if not create and self.path.stat().st_size != self._size:
            self._broken = True
            raise SessionError("session file changed on disk; reopen it")
        flags = (os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                 | (os.O_CREAT | os.O_EXCL if create else 0))
        try:
            fd = os.open(self.path, flags, 0o600)  # owner-only: the file holds full write requests, block data included
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
        """Write-ahead: record the intent, run the journal call, then record the outcome.

        The intent is durable before the journal can change, and the room for its outcome is reserved up
        front, so a session that is full or broken refuses the write *before* the journal is touched. If the
        outcome cannot be recorded afterwards (I/O failure) the intent stays open: reopen the session and call
        `reconcile(store)`; writes are refused until then.
        """
        _need(not self._pending, f"{len(self._pending)} write intent(s) are unresolved; call reconcile(store)")
        _need(len(canonical(request).encode()) <= MAX_REQUEST_BYTES, "request too large to record")
        fields = {"type": "intent", "tool": tool, "request": request}
        if tool == "create_module":  # what the journal looked like before: lets reconcile rule out a pre-existing module
            provider = ContextProvider(store)  # a stale store handle may not know a module another writer created
            fields["before"] = {"moduleExists": module_id in store.modules() or provider.journal_exists(module_id),
                                "projectDigest": provider.project_digest()}
        intent = self._append(fields, reserve_entries=2, reserve_bytes=2 * OUTCOME_RESERVE_BYTES)
        self._pending[intent["seq"]] = intent
        try:
            result = call()
        except IdentityError:           # rejected: validation and stale-write errors guarantee nothing was committed
            self._resolve(intent, "rejected", {})
            raise
        except DurabilityUncertainError:  # the line may be visible but is not known to be durable: say so in the log
            try:
                self._append({"type": "uncertain", "intent": intent["seq"]})
                self._uncertain_intents.add(intent["seq"])
            except SessionError:
                pass                    # the session is broken now; the open intent is still there for reconcile
            raise
        # any other failure (storage) leaves the outcome unknown: the intent stays open for reconcile
        if getattr(result, "replayed", False):
            self._resolve(intent, "noop", {})   # an idempotent retry changed nothing, so there is nothing to replay
            return result
        revision = result if isinstance(result, int) else result.revision
        self._resolve(intent, "applied", {"revision": revision, "replayed": False, "tail": store.tail_hash(module_id),
                                          "durable": True})
        return result

    def _resolve(self, intent: dict, status: str, result: dict) -> None:
        try:
            outcome = self._append({"type": "outcome", "intent": intent["seq"], "status": status, "result": result})
        except SessionError as exc:
            raise SessionError(f"the journal call finished but its outcome could not be recorded ({exc}); "
                               "reopen the session and call reconcile(store)") from exc
        self._pending.pop(intent["seq"], None)
        if status == "applied":
            self._steps.append(self._write_step(intent, outcome))

    def pending(self) -> list[dict]:
        """Write intents whose outcome was never recorded (crash, I/O error): resolve them with `reconcile(store)`."""
        return [{"intent": s, "tool": e["tool"], "module": e["request"].get("module"),
                 "durabilityUncertain": s in self._uncertain_intents} for s, e in sorted(self._pending.items())]

    def reconcile(self, store: JournalStore, *, adopt=(), discard=(), accept_unconfirmed=()) -> dict:
        """Decide, from the journal itself, what happened to every open intent; never certify what it cannot prove.

        applied    — the journal holds exactly this request (same key, revision, operations); it becomes a step.
        abandoned  — nothing in the journal (or, for a create, the module already existed): never replayed.
        conflict   — a different request under the same key: reported, never replayed.
        stays open — recorded in `open` with a reason, and writes stay refused, when it cannot be proven:
          * `UNVERIFIED_CREATE`: the module exists but a create leaves no identity in the journal (every creation of
            a module id writes the same genesis entry), so this intent cannot be told apart from a foreign create.
            The host decides: `adopt=[module ids]` records it as applied and flagged `adopted`, `discard=[...]`
            records it as abandoned.
          * `DURABILITY_UNCERTAIN`: the journal quarantined the module after an fsync failure. `store.recover` is
            attempted first; only after it succeeds is the write recorded (as durable). A visible line is never
            taken for a durable commit.
          * `DURABILITY_UNCONFIRMED`: the session logged an uncertain write and the store was reopened (so it no
            longer knows). Recorded only with `accept_unconfirmed=[module ids]`, and then flagged `durable: false`.
        """
        adopt, discard, accept = set(adopt), set(discard), set(accept_unconfirmed)
        resolved, open_ = [], []
        provider = ContextProvider(store)
        for seq, intent in sorted(self._pending.items()):
            decision = self._inspect(intent, store, provider, adopt, discard, accept)
            if decision[0] == "open":
                open_.append({"intent": seq, "module": intent["request"]["module"], "reason": decision[1]})
                continue
            self._resolve(intent, *decision)
            resolved.append({"intent": seq, "status": decision[0]})
        return {"resolved": resolved, "open": open_, "pending": len(self._pending)}

    def _inspect(self, intent: dict, store: JournalStore, provider: ContextProvider, adopt: set, discard: set,
                 accept: set) -> tuple:
        r, module, seq = intent["request"], intent["request"]["module"], intent["seq"]
        recovered = False
        if module in store.uncertain_modules():
            try:
                store.recover(module)
            except DurabilityUncertainError as exc:
                return ("open", f"DURABILITY_UNCERTAIN: recovery failed ({exc})")
            recovered = True
        if intent["tool"] == "create_module":
            if intent["before"]["moduleExists"]:
                return "abandoned", {"reason": "the module existed before the intent, so the create could not have succeeded"}
            if module in discard or module not in store.modules():
                return "abandoned", {}
            if module in adopt:
                durable = True
                if seq in self._uncertain_intents and not recovered:
                    if module not in accept:
                        return ("open", "DURABILITY_UNCONFIRMED: the create was logged as durability-uncertain, "
                                        "but the journal was reopened; pass accept_unconfirmed=[...] to adopt "
                                        "without claiming durability")
                    durable = False
                return "applied", {"revision": 0, "replayed": False, "tail": provider.revision_hashes(module)[0],
                                   "durable": durable, "adopted": True}
            return ("open", "UNVERIFIED_CREATE: the module exists but the journal cannot show that this intent created it; "
                            "pass adopt=[...] or discard=[...]")
        if module not in store.modules():
            return "abandoned", {}
        found = next((e for e in provider.revision_entries(module)[1:] if e["key"] == r["key"]), None)
        if found is None:
            return "abandoned", {}
        if intent["tool"] == "apply":
            same = (found["type"] == "commit" and found["rev"] - 1 == r["expectedRevision"]
                    and found["ops"] == type(store)._check_ops(r["ops"])
                    and found["mins"] == dict(sorted((r["minRevisions"] or {}).items())))
        else:
            same = (found["type"] == "rollback" and found["rev"] - 1 == r["expectedRevision"]
                    and found["rollbackTo"] == r["toRevision"])
        if not same:
            return "conflict", {}
        result = {"revision": found["rev"], "replayed": False, "tail": found["hash"], "durable": True}
        if seq in self._uncertain_intents and not recovered:
            if module not in accept:
                return ("open", "DURABILITY_UNCONFIRMED: the write was logged as durability-uncertain and the journal has "
                                "been reopened; establish durability independently or pass accept_unconfirmed=[...]")
            result["durable"] = False
        return "applied", result

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
    def replay_into(self, target: JournalStore, *, require_final_state: bool = False) -> dict:
        """Re-run the recorded writes, in order, against `target` and verify the HISTORY they produced.

        Contract. For every recorded write the target must end up with the recorded revision AND the recorded
        journal hash at that revision: a freshly applied write is compared with the target's newest hash, a write
        the target already had (idempotent replay) is compared with the target's journal entry at that revision.
        So a successful replay proves the target contains exactly the recorded history for every module it touched.

        It does NOT, by default, prove the target's *final* state equals the recording: later revisions made after
        the session are legitimate. The report always says so (`finalStateMatches`, `extraRevisions`); pass
        `require_final_state=True` to turn any extra revision into a `ReplayDivergence`.
        """
        count, last = 0, {}
        provider = ContextProvider(target)
        for s in self._steps:
            if s["effect"] != "write":
                continue
            r, rec = s["request"], s["result"]
            replayed = False
            if s["tool"] == "create_module" and r["module"] in target.modules():
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
            # newly applied: the newest hash; already present: the hash recorded at that revision, never skipped
            actual = (provider.revision_hashes(r["module"])[revision] if replayed else target.tail_hash(r["module"]))
            if actual != rec["tail"]:
                raise ReplayDivergence(f"step {s['seq']}: journal hash at revision {revision} differs from the recording")
            last[r["module"]] = (revision, rec["tail"])
            count += 1
        extra = {m: target.revision(m) - rev for m, (rev, _) in sorted(last.items()) if target.revision(m) != rev}
        if require_final_state and extra:
            raise ReplayDivergence(f"target has revisions beyond the recording: {extra}")
        return {"replayedWrites": count, "modules": len(last), "historyVerified": True,
                "finalStateMatches": not extra, "extraRevisions": extra,
                "nonDurableSteps": sum(1 for s in self._steps if s["effect"] == "write" and not s["result"].get("durable", True))}
