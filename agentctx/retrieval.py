"""BMB-024: scoped, budgeted context retrieval over the journal (and an optional typed assembly).

An agent asks for a manifest page or for ONE module with its neighbours; it never receives the whole
scene. Every response is deterministic, carries a revision/hash for each module it mentions, and is
cut to a hard token budget with explicit `omitted` counts and a continuation cursor, never silently.
"""
from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path

from agentctx.budget import ESTIMATOR, canonical, digest, estimate_tokens
from core.assembly import Assembly
from core.graph import dag
from core.identity.store import MODULE_ID_PATTERN
from core.storage.journal import JOURNAL, JournalStore, _dirname
from core.validator import validate_assembly
from core.textsafe import show

DEFAULT_TOKENS = 1500
MAX_TOKENS = 8000
MIN_TOKENS = 200
DEFAULT_PAGE = 25
MAX_PAGE = 50
MAX_NEIGHBORS = 32
MAX_DEPTH = 2
MAX_DIAGNOSTICS = 20
BLOCK_PREVIEW_BYTES = 2048
MAX_REQUESTED_BLOCKS = 16


class ContextError(ValueError):
    """Rejected context request; `code` is stable for programmatic clients."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _need(ok: bool, code: str, message: str) -> None:
    if not ok:
        raise ContextError(code, message)


def _budget(value: object) -> int:
    _need(type(value) is int and MIN_TOKENS <= value <= MAX_TOKENS, "BAD_BUDGET",
          f"max_tokens must be an integer in {MIN_TOKENS}..{MAX_TOKENS}")
    return value


def _module_id(value: object, label: str = "module id") -> str:
    _need(isinstance(value, str) and MODULE_ID_PATTERN.match(value) is not None, "BAD_ID", f"{label}: invalid {show(value)}")
    return value


class ContextProvider:
    """Read-only view of a `JournalStore` plus, optionally, a BMB-011 `Assembly` of the same modules."""

    def __init__(self, store: JournalStore, assembly: Assembly | None = None) -> None:
        _need(isinstance(store, JournalStore), "BAD_STORE", "a JournalStore is required")
        self.store, self.assembly = store, assembly
        self._diagnostics = None

    # --- project state --------------------------------------------------------
    def state(self) -> dict[str, tuple[int, str]]:
        """{module id: (revision, hash of the newest journal entry)} for every loaded module."""
        return {m: (self.store.revision(m), self.store.tail_hash(m)) for m in self.store.modules()}

    def project_digest(self) -> str:
        return digest([[m, r, h] for m, (r, h) in sorted(self.state().items())])

    def journal_exists(self, module_id: str) -> bool:
        """Is there a journal file for the module on disk, whether or not this store handle has loaded it?"""
        _module_id(module_id)
        return (Path(self.store._root) / "modules" / _dirname(module_id) / JOURNAL).exists()

    def revision_entries(self, module_id: str) -> list[dict]:
        """Journal entry (parsed) for revision 0..n of one module, read from its already verified journal file."""
        _module_id(module_id)
        _need(module_id in self.store.modules(), "UNKNOWN_MODULE", f"unknown module {show(module_id)}")
        path = Path(self.store._root) / "modules" / _dirname(module_id) / JOURNAL
        return [json.loads(line) for line in path.read_bytes().split(b"\n")[:-1]]

    def revision_hashes(self, module_id: str) -> list[str]:
        """Entry hash for revision 0..n of one module."""
        return [e["hash"] for e in self.revision_entries(module_id)]

    def _block_count(self, module_id: str) -> int:
        return len(self.store._blocks[module_id])  # no deep copy: a manifest must stay cheap for big projects

    # --- manifest -------------------------------------------------------------
    def manifest(self, cursor: str | None = None, page_size: int = DEFAULT_PAGE,
                 max_tokens: int = DEFAULT_TOKENS) -> dict:
        """A page of the module list: id, revision, block count, short hash. Never block contents."""
        limit = _budget(max_tokens)
        _need(type(page_size) is int and 1 <= page_size <= MAX_PAGE, "BAD_PAGE", f"page_size must be 1..{MAX_PAGE}")
        if cursor is not None:
            _module_id(cursor, "cursor")
        ids = self.store.modules()
        start = 0 if cursor is None else next((i for i, m in enumerate(ids) if m > cursor), len(ids))
        state = self.state()
        totals = {"modules": len(ids), "blocks": sum(self._block_count(m) for m in ids)}
        out = {"kind": "manifest", "projectDigest": self.project_digest(), "totals": totals, "modules": [],
               "page": {"cursor": cursor, "next": None, "omitted": 0},
               "budget": {"maxTokens": limit, "usedTokens": 0, "estimator": ESTIMATOR}}
        _need(estimate_tokens(out) <= limit, "BUDGET_TOO_SMALL", "even an empty manifest page exceeds the budget")
        window = ids[start:start + page_size]
        for m in window:
            row = {"id": m, "rev": state[m][0], "blocks": self._block_count(m), "hash": state[m][1][:12]}
            out["modules"].append(row)
            if estimate_tokens(out) > limit:
                out["modules"].pop()
                break
        shown = len(out["modules"])
        _need(shown > 0 or not window, "BUDGET_TOO_SMALL", "budget cannot hold a single manifest row")
        rest = len(ids) - start - shown
        out["page"].update(next=out["modules"][-1]["id"] if rest > 0 and shown else None, omitted=rest)
        return self._finish(out, limit)

    # --- one module with neighbours ------------------------------------------------
    def module(self, module_id: str, *, depth: int = 1, blocks: list[str] | None = None,
               max_tokens: int = DEFAULT_TOKENS) -> dict:
        """The module, its dependency edges, scoped diagnostics and nearby modules, in priority order."""
        limit = _budget(max_tokens)
        _module_id(module_id)
        _need(module_id in self.store.modules(), "UNKNOWN_MODULE", f"unknown module {show(module_id)}")
        _need(type(depth) is int and 0 <= depth <= MAX_DEPTH, "BAD_DEPTH", f"depth must be 0..{MAX_DEPTH}")
        wanted = [] if blocks is None else blocks
        _need(isinstance(wanted, list) and len(wanted) <= MAX_REQUESTED_BLOCKS and all(isinstance(b, str) for b in wanted),
              "BAD_BLOCKS", f"blocks must be at most {MAX_REQUESTED_BLOCKS} ids")
        revision, data = self.store.snapshot(module_id)
        index = [{"id": b, "bytes": len(canonical(v).encode()), "hash": digest(v, 12)} for b, v in data.items()]
        out = {"kind": "module-context",
               "focus": {"id": module_id, "rev": revision, "hash": self.store.tail_hash(module_id)[:12],
                         "blockCount": len(data)},
               "dependencies": [], "dependents": [], "diagnostics": [], "neighbors": [], "blockIndex": [], "blockData": [],
               "omitted": {"dependencies": 0, "dependents": 0, "diagnostics": 0, "neighbors": 0, "blockIndex": 0, "blockData": 0},
               "budget": {"maxTokens": limit, "usedTokens": 0, "estimator": ESTIMATOR}}
        if self.assembly is None:
            out["assembly"] = "not supplied: no dependencies, diagnostics or neighbours available"
        _need(estimate_tokens(out) <= limit, "BUDGET_TOO_SMALL", "even the module header exceeds the budget")
        for key, items in (("dependencies", self._dependencies(module_id)), ("dependents", self._dependents(module_id)),
                           ("diagnostics", self._scoped_diagnostics(module_id)),
                           ("neighbors", self._neighbors(module_id, depth)),
                           ("blockIndex", index), ("blockData", self._block_data(data, wanted))):
            self._fill(out, key, items, limit)
        return self._finish(out, limit)

    # --- helpers ----------------------------------------------------------------
    @staticmethod
    def _fill(out: dict, key: str, items: list, limit: int) -> None:
        for item in items:
            out[key].append(item)
            if estimate_tokens(out) > limit:
                out[key].pop()
                break
        out["omitted"][key] = len(items) - len(out[key])

    PRIORITY = ("blockData", "blockIndex", "neighbors", "diagnostics", "dependents", "dependencies")  # cut first -> last

    @classmethod
    def _finish(cls, out: dict, limit: int) -> dict:
        """Stamp the used-token count; if the stamp itself tips it over, drop the least important item and retry."""
        while True:
            for _ in range(3):  # usedTokens' own digits can change the size; converges at once in practice
                out["budget"]["usedTokens"] = estimate_tokens(out)
            if out["budget"]["usedTokens"] <= limit:
                return out
            if out["kind"] == "manifest":
                _need(len(out["modules"]) > 1, "BUDGET_TOO_SMALL", "response cannot be cut below the budget")
                out["modules"].pop()
                out["page"]["omitted"] += 1
                out["page"]["next"] = out["modules"][-1]["id"]
                continue
            key = next((k for k in cls.PRIORITY if out[k]), None)
            _need(key is not None, "BUDGET_TOO_SMALL", "response cannot be cut below the budget")
            out[key].pop()
            out["omitted"][key] += 1

    def _assembly_module(self, module_id: str) -> dict | None:
        return None if self.assembly is None else self.assembly.modules.get(module_id)

    def _info(self, module_id: str) -> dict:
        have = module_id in self.store.modules()
        return {"id": module_id, "rev": self.store.revision(module_id) if have else None,
                "hash": self.store.tail_hash(module_id)[:12] if have else None}

    def _dependencies(self, module_id: str) -> list[dict]:
        m = self._assembly_module(module_id)
        if m is None:
            return []
        return [dict(self._info(d["moduleId"]), minRevision=d["minRevision"],
                     satisfied=self._info(d["moduleId"])["rev"] is not None
                     and self._info(d["moduleId"])["rev"] >= d["minRevision"])
                for d in sorted(m["dependencies"], key=lambda d: d["moduleId"])]

    def _dependents(self, module_id: str) -> list[dict]:
        if self.assembly is None:
            return []
        return [self._info(o) for o, m in sorted(self.assembly.modules.items())
                if any(d["moduleId"] == module_id for d in m["dependencies"])]

    def _scoped_diagnostics(self, module_id: str) -> list[dict]:
        if self.assembly is None:
            return []
        if self._diagnostics is None:
            self._diagnostics = validate_assembly(self.assembly).diagnostics
        mine = [d for d in self._diagnostics if module_id in (d.module_id, d.related_module_id)]
        mine.sort(key=lambda d: (d.severity != "ERROR", d.code, d.path))
        return [d.to_dict() for d in mine[:MAX_DIAGNOSTICS]]

    def _world_box(self, module_id: str) -> list[list[float]]:
        bounds = self.assembly.modules[module_id]["bounds"]
        lo, hi = bounds["min"], bounds["max"]
        corners = [dag.apply_point(self.assembly.world_transforms[module_id], (x, y, z))
                   for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        return [[round(min(c[i] for c in corners), 6) for i in range(3)], [round(max(c[i] for c in corners), 6) for i in range(3)]]

    def _neighbors(self, module_id: str, depth: int) -> list[dict]:
        if self.assembly is None or depth == 0 or module_id not in self.assembly.modules:
            return []
        seen, queue, result = {module_id}, deque([(module_id, 0)]), []
        while queue:
            current, d = queue.popleft()
            if d == depth:
                continue
            for other in self.assembly.neighbours(current):
                if other in seen:
                    continue
                seen.add(other)
                queue.append((other, d + 1))
                seams = [s for s in self.assembly.seams_of(other) if current in s.participants]
                result.append(dict(self._info(other), distance=d + 1, bounds=self._world_box(other),
                                   seams=[{"id": s.seam_id, "owner": s.owner,
                                           "ports": [list(p) for p in s.ports]} for s in seams]))
        return sorted(result, key=lambda n: (n["distance"], n["id"]))[:MAX_NEIGHBORS]

    @staticmethod
    def _block_data(data: dict, wanted: list[str]) -> list[dict]:
        out = []
        for b in wanted:
            if b not in data:
                out.append({"id": b, "missing": True})
                continue
            size = len(canonical(data[b]).encode())
            out.append({"id": b, "bytes": size, "data": data[b]} if size <= BLOCK_PREVIEW_BYTES
                       else {"id": b, "bytes": size, "truncated": True})
        return out

    # --- evidence ----------------------------------------------------------------
    def full_scene_tokens(self) -> int:
        """What dumping every module (all blocks and, if known, the typed modules) would cost: the thing avoided."""
        scene = {m: self.store.snapshot(m) for m in self.store.modules()}
        if self.assembly is not None:
            scene = {"journal": scene, "modules": self.assembly.modules}
        return estimate_tokens(scene)
