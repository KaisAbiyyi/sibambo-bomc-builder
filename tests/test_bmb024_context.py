"""BMB-024 scoped context retrieval, token budgets, checkpoints, resume and replay: synthetic data only."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agentctx import (  # noqa: E402
    ContextError, ContextProvider, ReplayDivergence, SessionBudgetExceeded, SessionError, SessionStore,
    estimate_tokens)
from agentctx import evidence, retrieval, session as session_mod  # noqa: E402
from agentctx.evidence import BATH, HALL, LIV  # noqa: E402
from core.identity import StaleRevisionError  # noqa: E402
from core.storage import DurabilityUncertainError, StorageError  # noqa: E402
from core.storage import journal as journal_mod  # noqa: E402
from core.storage.journal import JournalStore  # noqa: E402


def block(n):
    return {"op": "add", "id": f"b-{n:03d}", "data": {"n": n}}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"

    def scene(self, filler=0, overlap=False):
        store, assembly = evidence.build_scene(self.root, filler=filler, overlap=overlap)
        return store, assembly, ContextProvider(store, assembly)


class ManifestTests(Base):
    def test_pages_cover_every_module_once_and_in_order(self):
        store, _, p = self.scene(filler=117)
        ids, cursor, seen = store.modules(), None, []
        while True:
            page = p.manifest(cursor=cursor, page_size=50)
            seen += [m["id"] for m in page["modules"]]
            self.assertLessEqual(page["budget"]["usedTokens"], page["budget"]["maxTokens"])
            self.assertEqual(page["totals"]["modules"], 120)
            cursor = page["page"]["next"]
            if cursor is None:
                break
        self.assertEqual(seen, ids)

    def test_manifest_rows_never_carry_block_contents(self):
        _, _, p = self.scene()
        row = p.manifest()["modules"][0]
        self.assertEqual(set(row), {"id", "rev", "blocks", "hash"})
        self.assertNotIn('"height"', json.dumps(p.manifest()))

    def test_tight_budget_cuts_rows_and_continues_without_gaps(self):
        store, _, p = self.scene(filler=40)
        ids, cursor, seen, pages = store.modules(), None, [], 0
        while True:
            page = p.manifest(cursor=cursor, page_size=50, max_tokens=250)
            self.assertLessEqual(estimate_tokens(page), 250)
            self.assertEqual(len(page["modules"]) + page["page"]["omitted"], len(ids) - len(seen))
            seen += [m["id"] for m in page["modules"]]
            pages += 1
            cursor = page["page"]["next"]
            if cursor is None:
                break
        self.assertEqual(seen, ids)
        self.assertGreater(pages, 3)

    def test_project_digest_tracks_state_not_history_of_calls(self):
        store, _, p = self.scene()
        first = p.project_digest()
        p.manifest(), p.module(HALL)
        self.assertEqual(p.project_digest(), first)
        store.apply(LIV, 1, "k2", [block(1)])
        self.assertNotEqual(p.project_digest(), first)

    def test_rejects_bad_requests(self):
        _, _, p = self.scene()
        for kwargs in ({"cursor": "../x"}, {"cursor": 5}, {"page_size": 0}, {"page_size": 51}, {"page_size": True},
                       {"max_tokens": 10}, {"max_tokens": 10 ** 9}, {"max_tokens": True}, {"max_tokens": "1500"}):
            with self.subTest(kwargs):
                with self.assertRaises(ContextError):
                    p.manifest(**kwargs)


class ModuleContextTests(Base):
    def test_focus_neighbours_dependencies_and_bounds(self):
        _, _, p = self.scene(filler=20)
        ctx = p.module(HALL)
        self.assertEqual((ctx["focus"]["id"], ctx["focus"]["rev"], ctx["focus"]["blockCount"]), (HALL, 1, 6))
        self.assertEqual([n["id"] for n in ctx["neighbors"]], [BATH, LIV])
        living = next(n for n in ctx["neighbors"] if n["id"] == LIV)
        self.assertEqual(living["bounds"], [[0.0, 0.0, 0.0], [4.0, 3.0, 2.8]])      # world AABB of the neighbour
        self.assertEqual(living["seams"][0]["id"], "east")
        self.assertEqual(living["seams"][0]["owner"], LIV)
        self.assertEqual([(d["id"], d["minRevision"], d["satisfied"]) for d in ctx["dependencies"]],
                         [(LIV, 1, True)])
        self.assertEqual([d["id"] for d in ctx["dependents"]], [BATH])
        self.assertTrue(all(not n["id"].startswith("site/") for n in ctx["neighbors"]))   # unrelated modules never appear
        self.assertEqual(ctx["diagnostics"], [])
        self.assertTrue(all(v == 0 for v in ctx["omitted"].values()))

    def test_depth_controls_how_far_the_context_reaches(self):
        _, _, p = self.scene()
        self.assertEqual(p.module(LIV, depth=0)["neighbors"], [])
        self.assertEqual([(n["id"], n["distance"]) for n in p.module(LIV, depth=1)["neighbors"]], [(HALL, 1)])
        self.assertEqual([(n["id"], n["distance"]) for n in p.module(LIV, depth=2)["neighbors"]], [(HALL, 1), (BATH, 2)])
        for depth in (-1, 3, True, "1"):
            with self.assertRaises(ContextError):
                p.module(LIV, depth=depth)

    def test_unsatisfied_dependency_is_visible(self):
        store, assembly, p = self.scene()
        assembly.modules[HALL]["dependencies"][0]["minRevision"] = 5
        self.assertFalse(p.module(HALL)["dependencies"][0]["satisfied"])

    def test_diagnostics_are_scoped_to_the_implicated_modules(self):
        _, _, p = self.scene(overlap=True)
        living, bath = p.module(LIV), p.module(BATH)
        self.assertTrue(living["diagnostics"])
        self.assertTrue(any("house/f1/closet" in (d["moduleId"], d["relatedModuleId"]) for d in living["diagnostics"]))
        self.assertEqual(bath["diagnostics"], [])
        self.assertEqual(p.module("house/f1/closet")["diagnostics"][0]["code"], living["diagnostics"][0]["code"])

    def test_block_data_is_only_returned_when_asked_and_is_bounded(self):
        store, assembly, p = self.scene()
        store.apply(HALL, 1, "big", [{"op": "add", "id": "huge", "data": {"text": "x" * 5000}}])
        ctx = p.module(HALL, blocks=["wall-1", "huge", "ghost"])
        data = {b["id"]: b for b in ctx["blockData"]}
        self.assertEqual(data["wall-1"]["data"]["k"], 1)
        self.assertTrue(data["huge"]["truncated"] and "data" not in data["huge"])
        self.assertTrue(data["ghost"]["missing"])
        self.assertEqual(len(ctx["blockIndex"]), 7)
        self.assertEqual(p.module(HALL)["blockData"], [])
        for bad in ("wall-1", [1], ["b"] * 17):
            with self.assertRaises(ContextError):
                p.module(HALL, blocks=bad)

    def test_without_an_assembly_only_journal_facts_are_returned(self):
        store, _, _ = self.scene()
        ctx = ContextProvider(store).module(HALL)
        self.assertEqual((ctx["neighbors"], ctx["dependencies"], ctx["diagnostics"]), ([], [], []))
        self.assertIn("not supplied", ctx["assembly"])
        self.assertEqual(ctx["focus"]["blockCount"], 6)

    def test_every_budget_is_respected_and_cuts_by_priority(self):
        store, _, p = self.scene()
        full = p.module(HALL, blocks=["wall-1", "wall-2"], max_tokens=8000)
        self.assertTrue(all(v == 0 for v in full["omitted"].values()))
        order = list(retrieval.ContextProvider.PRIORITY)       # least important first
        cut_sections = set()
        for limit in range(8000, 199, -37):
            ctx = p.module(HALL, blocks=["wall-1", "wall-2"], max_tokens=limit)
            self.assertLessEqual(estimate_tokens(ctx), limit)
            self.assertEqual(ctx["budget"]["usedTokens"], estimate_tokens(ctx))
            for key in order:
                self.assertEqual(len(ctx[key]) + ctx["omitted"][key], len(full[key]), (limit, key))
                self.assertEqual(ctx[key], full[key][:len(ctx[key])], (limit, key))        # a prefix: order is preserved
            cut_sections |= {k for k in order if ctx["omitted"][k]}
            if limit >= 600:                                    # small, high-priority facts survive moderate budgets
                self.assertEqual((len(ctx["dependencies"]), len(ctx["dependents"])), (1, 1), limit)
        self.assertTrue({"blockData", "blockIndex", "neighbors"} <= cut_sections)          # tight budgets cut real content
        # as the budget shrinks, the first thing to go is the least important section
        first = next(limit for limit in range(8000, 199, -1)
                     if any(p.module(HALL, blocks=["wall-1", "wall-2"], max_tokens=limit)["omitted"].values()))
        cut = p.module(HALL, blocks=["wall-1", "wall-2"], max_tokens=first)["omitted"]
        self.assertEqual([k for k in order if cut[k]], ["blockData"])

    def test_budget_too_small_is_an_error_not_a_silent_overrun(self):
        _, _, p = self.scene()
        with mock.patch.object(retrieval, "MIN_TOKENS", 1):
            for call in (lambda: p.module(HALL, max_tokens=5), lambda: p.manifest(max_tokens=5)):
                with self.assertRaises(ContextError) as ctx:
                    call()
                self.assertEqual(ctx.exception.code, "BUDGET_TOO_SMALL")

    def test_bad_ids_and_unknown_modules(self):
        _, _, p = self.scene()
        for module in ("../etc/passwd", "house", "House/F1", "", None, 5, "house/f1/none"):
            with self.subTest(module):
                with self.assertRaises(ContextError):
                    p.module(module)

    def test_reads_never_change_the_journal(self):
        store, _, p = self.scene(filler=5)
        before = {m: (Path(store._root) / "modules" / m.replace("/", "__") / "journal.jsonl").read_bytes() for m in store.modules()}
        p.manifest(), p.module(LIV, depth=2, blocks=["wall-0"]), p.full_scene_tokens(), p.project_digest()
        after = {m: (Path(store._root) / "modules" / m.replace("/", "__") / "journal.jsonl").read_bytes() for m in store.modules()}
        self.assertEqual(before, after)

    def test_output_is_deterministic(self):
        _, _, p = self.scene(filler=10)
        self.assertEqual(json.dumps(p.module(HALL, depth=2), sort_keys=True), json.dumps(p.module(HALL, depth=2), sort_keys=True))


class TokenEvidenceTests(unittest.TestCase):
    def test_scoped_context_does_not_grow_with_the_scene_but_a_dump_does(self):
        rows = evidence.measure((3, 30, 120))
        self.assertEqual(len({r["moduleContextTokens"] for r in rows}), 1)                # constant in scene size
        self.assertLessEqual(rows[-1]["manifestPageTokens"], 600)                          # one page, whatever the size
        self.assertGreater(rows[1]["fullSceneTokens"], 5 * rows[0]["fullSceneTokens"])
        self.assertGreater(rows[2]["fullSceneTokens"], 3 * rows[1]["fullSceneTokens"])
        self.assertGreater(rows[2]["reduction"], 50)                                       # 120 modules: >50x cheaper
        self.assertTrue(all(r["moduleContextTokens"] <= retrieval.DEFAULT_TOKENS for r in rows))


class SessionBase(Base):
    def open_session(self, name="agent-1", **kw):
        store, assembly, provider = self.scene()
        sessions = SessionStore(self.root)
        return store, assembly, provider, sessions, sessions.create(name, **kw)


class SessionFileTests(SessionBase):
    def test_create_open_and_reject_bad_ids(self):
        _, _, _, sessions, s = self.open_session()
        self.assertTrue(sessions.path("agent-1").is_file())
        self.assertEqual(sessions.sessions(), ["agent-1"])
        with self.assertRaises(SessionError):
            sessions.create("agent-1")
        for bad in ("../x", "A", "", "a/b", "a" * 65, None):
            with self.subTest(bad):
                with self.assertRaises(SessionError):
                    sessions.create(bad)
        with self.assertRaises(SessionError):
            sessions.open("missing")
        self.assertEqual(sessions.open("agent-1").token_cap, session_mod.DEFAULT_TOKEN_CAP)

    def test_session_files_live_outside_the_module_tree(self):
        store, _, _, sessions, s = self.open_session()
        self.assertEqual(JournalStore.open(self.root).modules(), store.modules())     # sessions/ is not a module

    def test_reopen_restores_steps_tokens_and_checkpoint(self):
        store, _, provider, sessions, s = self.open_session()
        s.manifest(provider)
        s.module(provider, HALL)
        s.apply(store, LIV, 1, "k2", [block(1)])
        cp = s.checkpoint(provider, "after-living")
        again = sessions.open("agent-1")
        self.assertEqual((again.tokens_used, len(again.steps()), again.last_checkpoint()["seq"]), (s.tokens_used, 3, cp["seq"]))
        self.assertEqual(again.last_checkpoint()["label"], "after-living")

    def test_corruption_is_detected(self):
        store, _, provider, sessions, s = self.open_session()
        s.manifest(provider)
        s.checkpoint(provider)
        path = sessions.path("agent-1")
        good = path.read_bytes()
        lines = good.split(b"\n")[:-1]
        cases = {
            "flipped byte": good.replace(b'"tokens"', b'"tokenz"', 1),
            "dropped line": b"\n".join(lines[:1] + lines[2:]) + b"\n",
            "reordered": b"\n".join([lines[0], lines[2], lines[1]]) + b"\n",
            "garbage line": good + b"not json\n",
            "duplicate keys": good + b'{"seq":3,"seq":3}\n',
            "NaN": good.replace(b'"tokenCap":50000', b'"tokenCap":NaN', 1),
            "empty": b"",
        }
        for label, data in cases.items():
            with self.subTest(label):
                path.write_bytes(data)
                with self.assertRaises(SessionError):
                    sessions.open("agent-1")
        path.write_bytes(good)
        self.assertEqual(len(sessions.open("agent-1").steps()), 1)

    def test_torn_tail_is_dropped_on_open(self):
        store, _, provider, sessions, s = self.open_session()
        s.manifest(provider)
        good = sessions.path("agent-1").read_bytes()
        s.checkpoint(provider)
        full = sessions.path("agent-1").read_bytes()
        sessions.path("agent-1").write_bytes(full[:len(good) + 40])
        again = sessions.open("agent-1")
        self.assertEqual((again.last_checkpoint(), sessions.path("agent-1").read_bytes()), (None, good))

    def test_second_writer_and_failed_write_break_the_session(self):
        store, _, provider, sessions, s = self.open_session()
        other = sessions.open("agent-1")
        s.manifest(provider)
        with self.assertRaises(SessionError):
            other.checkpoint(provider)                       # the file moved on under it
        with self.assertRaises(SessionError):
            other.manifest(provider)                         # and it stays refused
        s2 = sessions.open("agent-1")
        with mock.patch.object(session_mod.os, "fsync", side_effect=OSError("disk")):
            with self.assertRaises(SessionError):
                s2.checkpoint(provider)
        with self.assertRaises(SessionError):
            s2.checkpoint(provider)                          # outcome unknown: refuse until reopened
        sessions.open("agent-1").checkpoint(provider)


class SessionBudgetTests(SessionBase):
    def test_cumulative_cap_is_enforced_before_a_response_is_delivered(self):
        store, _, provider, sessions, s = self.open_session(token_cap=1000)
        used = []
        with self.assertRaises(SessionBudgetExceeded):
            for _ in range(20):
                response = s.module(provider, HALL)
                used.append(response["budget"]["usedTokens"])
                self.assertLessEqual(s.tokens_used, 1000)
        self.assertGreaterEqual(len(used), 2)
        self.assertLessEqual(s.tokens_used, 1000)
        self.assertEqual(sessions.open("agent-1").tokens_used, s.tokens_used)

    def test_late_requests_are_shrunk_to_what_is_left(self):
        store, _, provider, sessions, s = self.open_session(token_cap=900)
        first = s.module(provider, HALL, max_tokens=600)
        left = s.remaining_tokens()
        second = s.module(provider, HALL, max_tokens=2000)
        self.assertLessEqual(second["budget"]["usedTokens"], left)
        self.assertEqual(second["budget"]["maxTokens"], left)
        self.assertLessEqual(first["budget"]["usedTokens"], 600)

    def test_cap_must_be_sane(self):
        _, _, _, sessions, _ = self.open_session()
        for cap in (10, 10 ** 9, True, "5000"):
            with self.assertRaises(SessionError):
                sessions.create("other", token_cap=cap)


class CheckpointResumeTests(SessionBase):
    def test_unchanged_project_resumes_in_constant_cost(self):
        store, _, provider, sessions, s = self.open_session()
        s.checkpoint(provider)
        report = s.resume(provider)
        self.assertEqual((report["status"], report["changed"]), ("current", []))
        self.assertLess(estimate_tokens(report), estimate_tokens(provider.manifest()))
        with self.assertRaises(SessionError):
            sessions.create("fresh").resume(provider)       # no checkpoint yet

    def test_only_changed_modules_are_reported(self):
        store, _, provider, sessions, s = self.open_session()
        s.checkpoint(provider)
        store.apply(HALL, 1, "k2", [block(1)])
        store.apply(HALL, 2, "k3", [block(2)])
        store.rollback(BATH, 1, "undo", 0)
        store.create_module("house/f1/new")
        report = sessions.open("agent-1").resume(provider)
        self.assertEqual(report["status"], "advanced")
        self.assertEqual(report["advanced"], [{"id": BATH, "from": 1, "to": 2}, {"id": HALL, "from": 1, "to": 3}])
        self.assertEqual((report["unchanged"], report["new"], report["diverged"], report["missing"]), (1, ["house/f1/new"], [], []))
        self.assertEqual(report["changed"], sorted([BATH, HALL, "house/f1/new"]))

    def test_diverged_and_missing_modules(self):
        store, _, provider, sessions, s = self.open_session()
        s.checkpoint(provider)
        other = JournalStore.open(Path(self._tmp.name) / "elsewhere")
        for mid in (LIV, HALL):                              # same ids and revision numbers, different living history
            other.create_module(mid)
            data = {"height": 3.4} if mid == LIV else {"height": 2.8, "thickness": 0.15, "k": 0}
            other.apply(mid, 0, "seed-1", [{"op": "add", "id": "wall-0", "data": data}])
        report = s.resume(ContextProvider(other))
        self.assertEqual(report["status"], "diverged")
        self.assertEqual(report["diverged"], [HALL, LIV])    # hall differs too: it never had wall-1..5
        self.assertEqual(report["missing"], [BATH])
        self.assertEqual(report["unchanged"], 0)

    def test_a_longer_but_different_history_is_diverged_not_advanced(self):
        store, _, provider, sessions, s = self.open_session()
        s.checkpoint(provider)                                       # living is at revision 1 here
        other = JournalStore.open(Path(self._tmp.name) / "elsewhere")
        other.create_module(LIV)
        other.apply(LIV, 0, "seed-1", [{"op": "add", "id": "wall-0", "data": {"height": 3.4}}])
        other.apply(LIV, 1, "more", [block(1)])                     # revision 2, so newer, but its revision 1 differs
        report = s.resume(ContextProvider(other))
        self.assertEqual((report["diverged"], report["advanced"]), ([LIV], []))
        store.apply(LIV, 1, "more", [block(1)])                     # a true continuation of the checkpointed history
        self.assertEqual(s.resume(provider)["advanced"], [{"id": LIV, "from": 1, "to": 2}])

    def test_resume_needs_far_fewer_tokens_than_rereading_the_scene(self):
        store, _, provider, sessions, s = self.open_session()
        for i in range(60):
            store.create_module(f"site/b-{i:03d}")
        provider = ContextProvider(store, provider.assembly)
        s.checkpoint(provider)
        store.apply(HALL, 1, "k2", [block(1)])
        report = s.resume(provider)
        self.assertEqual(report["changed"], [HALL])
        self.assertLess(estimate_tokens(report) * 10, provider.full_scene_tokens())

    def test_resume_works_in_a_cold_process(self):
        store, _, provider, sessions, s = self.open_session()
        s.checkpoint(provider)
        store.apply(HALL, 1, "k2", [block(1)])
        code = ("import json,sys; sys.path.insert(0,%r); from agentctx import ContextProvider, SessionStore; "
                "from core.storage.journal import JournalStore; s=SessionStore(%r).open('agent-1'); "
                "print(json.dumps(s.resume(ContextProvider(JournalStore.open(%r))), sort_keys=True))"
                % (str(ROOT), str(self.root), str(self.root)))
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
        self.assertEqual(json.loads(out.stdout), json.loads(json.dumps(sessions.open("agent-1").resume(ContextProvider(store)), sort_keys=True)))


class RecordBase(Base):
    def record(self, root):
        store = JournalStore.open(root)
        sessions = SessionStore(root)
        s = sessions.create("agent-1")
        for m in ("house/f1/a", "house/f1/b"):
            s.create_module(store, m)
        s.apply(store, "house/f1/a", 0, "a1", [block(1), block(2)])
        s.apply(store, "house/f1/b", 0, "b1", [block(1)], None)
        s.apply(store, "house/f1/b", 1, "b2", [block(2)], {"house/f1/a": 1})
        s.rollback(store, "house/f1/a", 1, "a-undo", 0)
        return store, sessions, s


class RecordedWriteAndReplayTests(RecordBase):
    def test_only_effective_writes_are_logged(self):
        store, sessions, s = self.record(self.root)
        count = len(s.steps())
        self.assertEqual(count, 6)
        from core.identity import StaleRevisionError
        with self.assertRaises(StaleRevisionError):
            s.apply(store, "house/f1/a", 0, "stale", [block(3)])
        again = s.apply(store, "house/f1/b", 0, "b1", [block(1)])              # idempotent retry
        self.assertTrue(again.replayed)
        self.assertEqual(len(s.steps()), count)

    def test_replay_into_an_empty_store_is_byte_identical(self):
        store, sessions, s = self.record(self.root)
        target = JournalStore.open(Path(self._tmp.name) / "replayed")
        report = sessions.open("agent-1").replay_into(target)
        self.assertEqual(report["replayedWrites"], 6)
        for m in store.modules():
            self.assertEqual(target.tail_hash(m), store.tail_hash(m))
            self.assertEqual(target.snapshot(m), store.snapshot(m))
        for m in store.modules():
            name = m.replace("/", "__")
            self.assertEqual((Path(self._tmp.name) / "replayed" / "modules" / name / "journal.jsonl").read_bytes(),
                             (self.root / "modules" / name / "journal.jsonl").read_bytes())

    def test_replay_into_the_original_is_a_no_op(self):
        store, sessions, s = self.record(self.root)
        before = {m: store.tail_hash(m) for m in store.modules()}
        report = sessions.open("agent-1").replay_into(store)
        self.assertEqual(report["replayedWrites"], 6)
        self.assertEqual({m: store.tail_hash(m) for m in store.modules()}, before)

    def test_tampered_recording_is_caught_as_a_divergence(self):
        store, sessions, s = self.record(self.root)
        path = sessions.path("agent-1")
        entries = [json.loads(line) for line in path.read_bytes().split(b"\n")[:-1]]
        target_step = next(e for e in entries if e.get("tool") == "apply")
        target_step["request"]["ops"][0]["data"] = {"n": 999}           # a forged edit, with every hash re-chained
        prev, out = session_mod.GENESIS, []
        for e in entries:
            e["prev"] = prev
            e["hash"] = session_mod._entry_hash(e)
            prev = e["hash"]
            out.append(session_mod.canonical(e).encode())
        path.write_bytes(b"\n".join(out) + b"\n")
        with self.assertRaises(ReplayDivergence):
            sessions.open("agent-1").replay_into(JournalStore.open(Path(self._tmp.name) / "forged"))

    def test_oversized_request_is_refused_before_the_journal_changes(self):
        store, sessions, s = self.record(self.root)
        before = store.tail_hash("house/f1/a")
        ops = [{"op": "add", "id": f"huge-{i}", "data": {"x": "y" * 30000}} for i in range(4)]
        with self.assertRaises(SessionError):
            s.apply(store, "house/f1/a", 2, "too-big", ops)
        self.assertEqual(store.tail_hash("house/f1/a"), before)


class WriteAheadTests(Base):
    """The journal must never change without the session knowing (or being able to find out)."""

    def setUp(self):
        super().setUp()
        self.store = JournalStore.open(self.root)
        self.sessions = SessionStore(self.root)
        self.s = self.sessions.create("agent-1")
        self.s.create_module(self.store, "house/f1/a")
        self.m = "house/f1/a"

    def journal_state(self):
        return self.store.revision(self.m), self.store.tail_hash(self.m)

    def lines(self):
        return [json.loads(x) for x in self.sessions.path("agent-1").read_bytes().split(b"\n")[:-1]]

    def test_a_full_session_refuses_the_write_before_the_journal_changes(self):
        before = self.journal_state()
        n = self.s._seq + 1                                                          # entries written so far
        with mock.patch.object(session_mod, "MAX_ENTRIES", n + 2):                   # room for the intent and one more, not for the reserve
            with self.assertRaises(SessionError):
                self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        self.assertEqual(self.journal_state(), before)
        self.assertEqual(self.s.pending(), [])
        with mock.patch.object(session_mod, "MAX_FILE_BYTES", self.s._size + 700):  # the outcome reserve does not fit
            with self.assertRaises(SessionError):
                self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        self.assertEqual(self.journal_state(), before)
        with mock.patch.object(session_mod, "MAX_ENTRIES", n + 3):                   # exactly enough: intent plus the reserved outcome and marker
            self.assertEqual(self.s.apply(self.store, self.m, 0, "k1", [block(1)]).revision, 1)
        self.assertEqual((len(self.s.steps()), self.s.pending()), (2, []))

    def test_a_broken_session_refuses_before_mutating(self):
        with mock.patch.object(session_mod.os, "fsync", side_effect=OSError("disk")):
            with self.assertRaises(SessionError):
                self.s.manifest(ContextProvider(self.store))
        before = self.journal_state()
        with self.assertRaises(SessionError):
            self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        self.assertEqual(self.journal_state(), before)

    def test_an_outcome_that_cannot_be_recorded_is_recovered_by_reconcile(self):
        original = session_mod.Session._append

        def fail_outcome(session, fields, *args, **kwargs):
            if fields["type"] == "outcome":
                session._broken = True
                raise SessionError("session write failed (disk full); reopen it")
            return original(session, fields, *args, **kwargs)

        with mock.patch.object(session_mod.Session, "_append", fail_outcome):
            with self.assertRaises(SessionError) as ctx:
                self.s.apply(self.store, self.m, 0, "k1", [block(1), block(2)])
        self.assertIn("reconcile", str(ctx.exception))
        self.assertEqual(self.store.revision(self.m), 1)                      # the journal did change
        reopened = self.sessions.open("agent-1")
        self.assertEqual([p["tool"] for p in reopened.pending()], ["apply"])
        self.assertEqual(len(reopened.steps()), 1)                            # only the create is a step so far
        with self.assertRaises(SessionError):                                 # writes are refused until reconciled
            reopened.apply(self.store, self.m, 1, "k2", [block(3)])
        reopened.manifest(ContextProvider(self.store))                        # reads still work
        report = reopened.reconcile(self.store)
        self.assertEqual(report, {"resolved": [{"intent": report["resolved"][0]["intent"], "status": "applied"}], "open": [], "pending": 0})
        self.assertEqual(reopened.reconcile(self.store)["resolved"], [])      # idempotent
        write = [s for s in reopened.steps() if s["tool"] == "apply"][0]
        self.assertEqual((write["result"]["revision"], write["result"]["tail"]), self.journal_state())
        self.assertEqual(reopened.apply(self.store, self.m, 1, "k2", [block(3)]).revision, 2)
        target = JournalStore.open(Path(self._tmp.name) / "copy")                 # and the recovered history replays exactly
        self.assertEqual(self.sessions.open("agent-1").replay_into(target)["replayedWrites"], 3)
        self.assertEqual(target.tail_hash(self.m), self.store.tail_hash(self.m))

    def test_an_intent_whose_write_never_happened_is_abandoned(self):
        before = self.journal_state()
        with mock.patch.object(self.store, "apply", side_effect=StorageError("storage unavailable")):
            with self.assertRaises(StorageError):
                self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        self.assertEqual(self.journal_state(), before)
        self.assertEqual(len(self.s.pending()), 1)
        with self.assertRaises(SessionError):
            self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        self.assertEqual(self.s.reconcile(self.store)["resolved"][0]["status"], "abandoned")
        self.assertEqual(self.s.apply(self.store, self.m, 0, "k1", [block(1)]).revision, 1)   # retry now works
        self.assertEqual([s["tool"] for s in self.s.steps()], ["create_module", "apply"])

    def uncertain_write(self, key="k1"):
        """An apply whose journal fsync fails after the line is written: visible, not known to be durable."""
        calls = {"n": 0}
        real = os.fsync

        def second_fsync_fails(fd):
            calls["n"] += 1
            if calls["n"] == 2:                  # 1 = the session intent, 2 = the journal's commit
                raise OSError("fsync failed")
            return real(fd)

        with mock.patch.object(journal_mod.os, "fsync", side_effect=second_fsync_fails):
            with self.assertRaises(DurabilityUncertainError):
                self.s.apply(self.store, self.m, 0, key, [block(1)])

    def test_a_visible_but_not_durable_write_is_never_certified_during_quarantine(self):
        self.uncertain_write()
        self.assertEqual(self.store.uncertain_modules(), [self.m])
        self.assertTrue(self.s.pending()[0]["durabilityUncertain"])           # the session logged the uncertainty
        steps_before = len(self.s.steps())
        with mock.patch.object(journal_mod.os, "fsync", side_effect=OSError("still failing")):
            report = self.s.reconcile(self.store)                             # recovery is attempted and fails
        self.assertEqual(report["resolved"], [])
        self.assertTrue(report["open"][0]["reason"].startswith("DURABILITY_UNCERTAIN"))
        self.assertEqual((len(self.s.steps()), len(self.s.pending()), self.store.uncertain_modules()), (steps_before, 1, [self.m]))
        with self.assertRaises(SessionError):                                  # and nothing else is written meanwhile
            self.s.apply(self.store, self.m, 1, "k2", [block(2)])
        target = JournalStore.open(Path(self._tmp.name) / "copy")
        self.assertEqual(self.s.replay_into(target)["replayedWrites"], 1)    # only the certified create is replayed
        self.assertNotIn(self.m, [] if self.m not in target.modules() else [m for m in target.modules() if target.revision(m) > 0])

    def test_recovery_makes_the_write_durable_and_only_then_records_it(self):
        self.uncertain_write()
        report = self.s.reconcile(self.store)                                  # fsync works again: recover() runs first
        self.assertEqual([r["status"] for r in report["resolved"]], ["applied"])
        self.assertEqual((self.store.uncertain_modules(), self.s.pending()), ([], []))
        step = [x for x in self.s.steps() if x["tool"] == "apply"][0]
        self.assertEqual((step["result"]["revision"], step["result"]["tail"], step["result"]["durable"]), (1, self.store.tail_hash(self.m), True))
        self.assertEqual(self.s.replay_into(JournalStore.open(Path(self._tmp.name) / "copy"))["nonDurableSteps"], 0)

    def test_after_a_restart_the_logged_uncertainty_still_blocks_certification(self):
        self.uncertain_write()
        reopened_store = JournalStore.open(self.root)                         # the new store no longer knows about the quarantine
        self.assertEqual(reopened_store.uncertain_modules(), [])
        session = self.sessions.open("agent-1")
        self.assertTrue(session.pending()[0]["durabilityUncertain"])
        report = session.reconcile(reopened_store)
        self.assertEqual(report["resolved"], [])
        self.assertTrue(report["open"][0]["reason"].startswith("DURABILITY_UNCONFIRMED"))
        with self.assertRaises(SessionError):
            session.apply(reopened_store, self.m, 1, "k2", [block(2)])
        accepted = session.reconcile(reopened_store, accept_unconfirmed=[self.m])   # an explicit, recorded decision
        self.assertEqual([r["status"] for r in accepted["resolved"]], ["applied"])
        step = [x for x in session.steps() if x["tool"] == "apply"][0]
        self.assertFalse(step["result"]["durable"])                            # and it stays flagged
        report = session.replay_into(JournalStore.open(Path(self._tmp.name) / "copy"))
        self.assertEqual((report["replayedWrites"], report["nonDurableSteps"]), (2, 1))
        self.assertEqual(session.apply(reopened_store, self.m, 1, "k2", [block(2)]).revision, 2)

    def test_the_uncertain_marker_survives_a_broken_session(self):
        self.uncertain_write()
        again = self.sessions.open("agent-1")
        self.assertEqual([e["type"] for e in self.lines()][-2:], ["intent", "uncertain"])
        self.assertEqual(again.pending()[0]["intent"], self.s.pending()[0]["intent"])

    def uncertain_create(self, module="house/f1/b"):
        """A new module's genesis line is visible after fsync fails, but may not be durable."""
        calls = {"n": 0}
        real = os.fsync

        def fail_genesis_fsync(fd):
            calls["n"] += 1
            if calls["n"] == 2:  # 1 = session intent; 2 = journal create entry
                raise OSError("create journal fsync failed")
            return real(fd)

        with mock.patch.object(journal_mod.os, "fsync", side_effect=fail_genesis_fsync):
            with self.assertRaises(DurabilityUncertainError):
                self.s.create_module(self.store, module)
        self.assertEqual(self.store.uncertain_modules(), [module])
        self.assertTrue(self.s.pending()[0]["durabilityUncertain"])
        return module

    def test_uncertain_create_reopened_requires_adopt_and_unconfirmed_acceptance(self):
        module = self.uncertain_create()
        reopened_store = JournalStore.open(self.root)
        self.assertEqual(reopened_store.uncertain_modules(), [])  # in-memory quarantine did not survive restart
        session = self.sessions.open("agent-1")
        self.assertTrue(session.pending()[0]["durabilityUncertain"])

        only_adopt = session.reconcile(reopened_store, adopt=[module])
        self.assertEqual(only_adopt["resolved"], [])
        self.assertTrue(only_adopt["open"][0]["reason"].startswith("DURABILITY_UNCONFIRMED"))
        with self.assertRaises(SessionError):
            session.apply(reopened_store, self.m, 0, "blocked", [block(1)])

        only_accept = session.reconcile(reopened_store, accept_unconfirmed=[module])
        self.assertEqual(only_accept["resolved"], [])
        self.assertTrue(only_accept["open"][0]["reason"].startswith("UNVERIFIED_CREATE"))

        accepted = session.reconcile(reopened_store, adopt=[module], accept_unconfirmed=[module])
        self.assertEqual((accepted["resolved"][0]["status"], accepted["pending"]), ("applied", 0))
        step = next(s for s in session.steps() if s["tool"] == "create_module" and s["request"]["module"] == module)
        self.assertTrue(step["result"]["adopted"])
        self.assertFalse(step["result"]["durable"])
        report = session.replay_into(JournalStore.open(Path(self._tmp.name) / "uncertain-create-replay"))
        self.assertEqual((report["replayedWrites"], report["nonDurableSteps"]), (2, 1))

    def test_uncertain_create_same_store_recovery_precedes_durable_adoption(self):
        module = self.uncertain_create()
        with mock.patch.object(journal_mod.os, "fsync", side_effect=OSError("recovery still failing")):
            failed = self.s.reconcile(self.store, adopt=[module])
        self.assertEqual(failed["resolved"], [])
        self.assertTrue(failed["open"][0]["reason"].startswith("DURABILITY_UNCERTAIN"))
        self.assertEqual(self.store.uncertain_modules(), [module])
        self.assertEqual(len(self.s.steps()), 1)

        succeeded = self.s.reconcile(self.store, adopt=[module])
        self.assertEqual((succeeded["resolved"][0]["status"], succeeded["pending"]), ("applied", 0))
        self.assertEqual(self.store.uncertain_modules(), [])
        step = next(s for s in self.s.steps() if s["tool"] == "create_module" and s["request"]["module"] == module)
        self.assertEqual((step["result"]["adopted"], step["result"]["durable"]), (True, True))
        self.assertEqual(self.s.replay_into(JournalStore.open(Path(self._tmp.name) / "recovered-create-replay"))["nonDurableSteps"], 0)

    def test_a_create_cannot_be_attributed_to_a_pre_existing_module(self):
        other = JournalStore.open(self.root, modules=[])
        other.create_module("house/f1/older")                                  # exists before the intent
        with mock.patch.object(self.store, "create_module", side_effect=StorageError("interrupted")):
            with self.assertRaises(StorageError):
                self.s.create_module(self.store, "house/f1/older")
        self.assertTrue([e for e in self.lines() if e["type"] == "intent"][-1]["before"]["moduleExists"])
        report = self.s.reconcile(JournalStore.open(self.root))
        self.assertEqual(report["resolved"][0]["status"], "abandoned")
        self.assertEqual([x["tool"] for x in self.s.steps()], ["create_module"])        # not recorded as this session's create

    def test_a_create_by_another_writer_is_not_claimed_unless_the_host_decides(self):
        with mock.patch.object(self.store, "create_module", side_effect=StorageError("interrupted before the journal call")):
            with self.assertRaises(StorageError):
                self.s.create_module(self.store, "house/f1/b")
        JournalStore.open(self.root, modules=[]).create_module("house/f1/b")    # a foreign writer creates it meanwhile
        fresh = JournalStore.open(self.root)
        report = self.s.reconcile(fresh)
        self.assertEqual(report["resolved"], [])
        self.assertTrue(report["open"][0]["reason"].startswith("UNVERIFIED_CREATE"))
        with self.assertRaises(SessionError):
            self.s.apply(fresh, "house/f1/a", 0, "k1", [block(1)])               # blocked until the host decides
        adopted = self.sessions.open("agent-1")
        self.assertEqual(adopted.reconcile(fresh, adopt=["house/f1/b"])["resolved"][0]["status"], "applied")
        step = [x for x in adopted.steps() if x["request"]["module"] == "house/f1/b"][0]
        self.assertTrue(step["result"]["adopted"])                               # the audit trail says it was adopted
        self.assertEqual(adopted.replay_into(JournalStore.open(Path(self._tmp.name) / "copy"))["replayedWrites"], 2)

    def test_discarding_an_unverified_create_unblocks_the_session(self):
        with mock.patch.object(self.store, "create_module", side_effect=StorageError("interrupted")):
            with self.assertRaises(StorageError):
                self.s.create_module(self.store, "house/f1/b")
        JournalStore.open(self.root, modules=[]).create_module("house/f1/b")
        fresh = JournalStore.open(self.root)
        self.assertEqual(self.s.reconcile(fresh, discard=["house/f1/b"])["resolved"][0]["status"], "abandoned")
        self.assertEqual(self.s.apply(fresh, "house/f1/a", 0, "k1", [block(1)]).revision, 1)
        self.assertEqual([x["tool"] for x in self.s.steps()], ["create_module", "apply"])

    def test_our_own_create_whose_outcome_was_lost_needs_an_explicit_decision_too(self):
        original = session_mod.Session._append

        def fail_outcome(session, fields, *args, **kwargs):
            if fields["type"] == "outcome":
                session._broken = True
                raise SessionError("session write failed (disk full); reopen it")
            return original(session, fields, *args, **kwargs)

        with mock.patch.object(session_mod.Session, "_append", fail_outcome):
            with self.assertRaises(SessionError):
                self.s.create_module(self.store, "house/f1/b")
        session = self.sessions.open("agent-1")
        fresh = JournalStore.open(self.root)
        self.assertTrue(session.reconcile(fresh)["open"][0]["reason"].startswith("UNVERIFIED_CREATE"))
        self.assertEqual(session.reconcile(fresh, adopt=["house/f1/b"])["resolved"][0]["status"], "applied")
        copy = JournalStore.open(Path(self._tmp.name) / "copy")
        session.replay_into(copy)
        self.assertEqual(copy.tail_hash("house/f1/b"), fresh.tail_hash("house/f1/b"))

    def test_entry_limit_is_exact_and_matches_what_load_accepts(self):
        n = self.s._seq + 1                                                   # entries in the file
        provider = ContextProvider(self.store)
        with mock.patch.object(session_mod, "MAX_ENTRIES", n):
            with self.assertRaises(SessionError):
                self.s.checkpoint(provider)                                   # entry n+1 would exceed MAX_ENTRIES = n
        with mock.patch.object(session_mod, "MAX_ENTRIES", n + 1):
            self.s.checkpoint(provider)                                       # exactly one more fits
            with self.assertRaises(SessionError):
                self.s.checkpoint(provider)                                   # and the next does not
            self.assertEqual(len(self.sessions.open("agent-1").steps()), 1)   # _load accepts a file of exactly MAX_ENTRIES entries
        with mock.patch.object(session_mod, "MAX_ENTRIES", n):
            with self.assertRaises(SessionError):
                self.sessions.open("agent-1")                                 # one over the limit is refused on load

    def test_a_different_request_under_the_same_key_is_a_conflict_and_is_never_replayed(self):
        real_apply = self.store.apply

        def other_ops_then_fail(module, expected, key, ops, mins=None):
            real_apply(module, expected, key, [block(99)], mins)       # the journal gets different operations ...
            raise StorageError("lost the answer")                      # ... and the caller never hears back

        with mock.patch.object(self.store, "apply", side_effect=other_ops_then_fail):
            with self.assertRaises(StorageError):
                self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        self.assertEqual(self.s.reconcile(self.store)["resolved"][0]["status"], "conflict")
        self.assertEqual([x["tool"] for x in self.s.steps()], ["create_module"])
        self.assertEqual(self.s.replay_into(JournalStore.open(Path(self._tmp.name) / "copy"))["replayedWrites"], 1)

    def test_rejected_and_idempotent_calls_resolve_immediately(self):
        self.s.apply(self.store, self.m, 0, "k1", [block(1)])
        with self.assertRaises(StaleRevisionError):
            self.s.apply(self.store, self.m, 0, "k2", [block(2)])
        self.assertTrue(self.s.apply(self.store, self.m, 0, "k1", [block(1)]).replayed)
        self.assertEqual(self.s.pending(), [])
        statuses = [e["status"] for e in self.lines() if e["type"] == "outcome"]
        self.assertEqual(statuses, ["applied", "applied", "rejected", "noop"])
        self.assertEqual(len(self.s.steps()), 2)


class ReplayContractTests(RecordBase):
    def test_replay_into_the_original_verifies_history_and_reports_extra_revisions(self):
        store, sessions, s = self.record(self.root)
        clean = sessions.open("agent-1").replay_into(store)
        self.assertEqual((clean["historyVerified"], clean["finalStateMatches"], clean["extraRevisions"]), (True, True, {}))
        store.apply("house/f1/b", 2, "later", [block(7)])             # a legitimate change after the session
        report = sessions.open("agent-1").replay_into(store)
        self.assertEqual((report["historyVerified"], report["finalStateMatches"], report["extraRevisions"]),
                         (True, False, {"house/f1/b": 1}))
        with self.assertRaises(ReplayDivergence):
            sessions.open("agent-1").replay_into(store, require_final_state=True)

    def test_an_already_applied_write_is_checked_against_its_journal_hash(self):
        store, sessions, s = self.record(self.root)
        wrong = ["0" * 64] * 10
        with mock.patch.object(ContextProvider, "revision_hashes", return_value=wrong):
            with self.assertRaises(ReplayDivergence):
                sessions.open("agent-1").replay_into(store)
        self.assertEqual(sessions.open("agent-1").replay_into(store)["replayedWrites"], 6)

    def test_replay_into_an_empty_store_matches_the_final_state(self):
        store, sessions, s = self.record(self.root)
        report = sessions.open("agent-1").replay_into(JournalStore.open(Path(self._tmp.name) / "fresh"), require_final_state=True)
        self.assertEqual((report["finalStateMatches"], report["extraRevisions"], report["modules"]), (True, {}, 2))


@unittest.skipUnless(os.name == "posix", "POSIX permission bits; Windows ACLs are not validated")
class PermissionTests(Base):
    def mode(self, path):
        return stat.S_IMODE(os.lstat(path).st_mode)

    def test_files_and_directory_are_owner_only_even_with_a_permissive_umask(self):
        old = os.umask(0)
        try:
            sessions = SessionStore(self.root)
            s = sessions.create("agent-1")
            s.checkpoint(ContextProvider(JournalStore.open(self.root)))
        finally:
            os.umask(old)
        self.assertEqual(self.mode(sessions.root), 0o700)
        self.assertEqual(self.mode(sessions.path("agent-1")), 0o600)

    def test_loose_existing_permissions_are_tightened(self):
        sessions = SessionStore(self.root)
        sessions.root.mkdir(parents=True)
        os.chmod(sessions.root, 0o755)
        s = sessions.create("agent-1")
        self.assertEqual(self.mode(sessions.root), 0o700)
        os.chmod(sessions.path("agent-1"), 0o644)               # e.g. left by an older version
        os.chmod(sessions.root, 0o777)
        sessions.open("agent-1")
        self.assertEqual((self.mode(sessions.root), self.mode(sessions.path("agent-1"))), (0o700, 0o600))

    def test_symlinked_session_file_or_directory_is_refused(self):
        sessions = SessionStore(self.root)
        s = sessions.create("agent-1")
        elsewhere = Path(self._tmp.name) / "elsewhere.jsonl"
        elsewhere.write_bytes(sessions.path("agent-1").read_bytes())
        sessions.path("agent-1").unlink()
        sessions.path("agent-1").symlink_to(elsewhere)
        with self.assertRaises(SessionError):
            sessions.open("agent-1")
        with self.assertRaises(SessionError):                   # an open handle must not follow a swapped-in link either
            s.checkpoint(ContextProvider(JournalStore.open(self.root)))
        self.assertEqual(elsewhere.read_bytes().count(b"\n"), 1)
        real = Path(self._tmp.name) / "other-root"
        (real / "sessions").mkdir(parents=True)
        link_root = Path(self._tmp.name) / "link-root"
        link_root.mkdir()
        (link_root / "sessions").symlink_to(real / "sessions")
        with self.assertRaises(SessionError):
            SessionStore(link_root).create("agent-1")


if __name__ == "__main__":
    unittest.main()
