"""BMB-010 journal persistence, recovery and rollback tests: synthetic data only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.identity import IdempotencyConflictError, IdentityError, StaleRevisionError  # noqa: E402
from core.storage import (  # noqa: E402
    ConcurrentWriteError, CorruptJournalError, JournalStore, StorageError)
from core.storage import journal as journal_mod  # noqa: E402

M = "house/living"
K = "house/kitchen"


def add(block, **data):
    return {"op": "add", "id": block, "data": data or {"v": 1}}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"

    def path(self, module=M):
        return self.root / "modules" / module.replace("/", "__") / "journal.jsonl"

    def fresh(self):
        s = JournalStore.open(self.root)
        s.create_module(M)
        s.apply(M, 0, "k1", [add("wall-a", h=1), add("wall-b", h=2)])
        s.apply(M, 1, "k2", [{"op": "replace", "id": "wall-a", "data": {"h": 9}}, add("wall-c")])
        s.apply(M, 2, "k3", [{"op": "remove", "id": "wall-b"}])
        return s


class PersistenceTests(Base):
    def test_reopen_restores_state_and_idempotency(self):
        s = self.fresh()
        want = s.snapshot(M)
        tail = s.tail_hash(M)
        r = JournalStore.open(self.root)
        self.assertEqual((r.snapshot(M), r.tail_hash(M)), (want, tail))
        self.assertEqual(r.apply(M, 0, "k1", [add("wall-a", h=1), add("wall-b", h=2)]).replayed, True)
        with self.assertRaises(IdempotencyConflictError):
            r.apply(M, 3, "k1", [add("wall-z")])
        self.assertEqual(r.apply(M, 3, "k4", [add("wall-d")]).revision, 4)
        self.assertEqual(JournalStore.open(self.root).revision(M), 4)

    def test_same_operations_give_byte_identical_journal(self):
        self.fresh()
        first = self.path().read_bytes()
        self.root = Path(self._tmp.name) / "second"
        self.fresh()
        self.assertEqual(self.path().read_bytes(), first)

    def test_rejected_edits_do_not_touch_the_file(self):
        s = self.fresh()
        before = self.path().read_bytes()
        for call in (lambda: s.apply(M, 0, "x1", [add("wall-q")]),                  # stale
                     lambda: s.apply(M, 3, "x2", [add("wall-a")]),                  # duplicate block
                     lambda: s.apply(M, 3, "x3", [add("wall-q")], {K: 1}),          # missing dependency
                     lambda: s.apply(M, 3, "bad key", [add("wall-q")])):
            with self.assertRaises(IdentityError):
                call()
        self.assertEqual(self.path().read_bytes(), before)
        self.assertEqual(s.revision(M), 3)

    def test_modules_reload_independently(self):
        s = self.fresh()
        s.create_module(K)
        s.apply(K, 0, "kk", [add("wall-a")])
        self.path(K).write_bytes(b"garbage\n")          # corrupt kitchen only
        only = JournalStore.open(self.root, modules=[M])
        self.assertEqual(only.modules(), [M])
        self.assertEqual(only.revision(M), 3)
        with self.assertRaises(CorruptJournalError):
            JournalStore.open(self.root)
        with self.assertRaises(StorageError):
            JournalStore.open(self.root, modules=["house/missing"])

    def test_dependency_minimum_uses_loaded_modules(self):
        s = self.fresh()
        s.create_module(K)
        s.apply(K, 0, "kk", [add("wall-a")])
        r = JournalStore.open(self.root)
        self.assertEqual(r.apply(M, 3, "dep", [add("wall-d")], {K: 1}).revision, 4)
        r2 = JournalStore.open(self.root)
        self.assertEqual(r2.revision(M), 4)
        self.assertEqual(r2.apply(M, 3, "dep", [add("wall-d")], {K: 1}).replayed, True)

    def test_unsafe_module_ids_never_reach_the_filesystem(self):
        s = JournalStore.open(self.root)
        for bad in ("../evil", "house/../x", "/abs/path", "house\\x", "a/b/", ""):
            with self.assertRaises(IdentityError):
                s.create_module(bad)
        self.assertEqual([p.name for p in (self.root / "modules").iterdir()], [])

    def test_duplicate_module_across_stores(self):
        self.fresh()
        other = JournalStore.open(self.root, modules=[])
        with self.assertRaises(StorageError):
            other.create_module(M)
        self.assertEqual(other.modules(), [])


class RecoveryTests(Base):
    def test_torn_tail_is_dropped_and_commit_resumes(self):
        s = self.fresh()
        complete = self.path().read_bytes()
        s.apply(M, 3, "k4", [add("wall-d")])
        full = self.path().read_bytes()
        for cut in (len(complete) + 1, len(complete) + 40, len(full) - 1):
            self.path().write_bytes(full[:cut])
            r = JournalStore.open(self.root)
            self.assertEqual(r.revision(M), 3, msg=cut)
            self.assertEqual(self.path().read_bytes(), complete)
            self.assertEqual(r.apply(M, 3, "k4", [add("wall-d")]).revision, 4)
            self.assertEqual(self.path().read_bytes(), full)

    def test_incomplete_create_is_ignored_and_can_be_redone(self):
        s = JournalStore.open(self.root)
        s.create_module(M)
        self.path().write_bytes(self.path().read_bytes()[:-5])
        r = JournalStore.open(self.root)
        self.assertEqual(r.modules(), [])
        self.assertFalse(self.path().exists())
        r.create_module(M)
        self.assertEqual(JournalStore.open(self.root).revision(M), 0)

    def test_failed_write_leaves_committed_state_untouched(self):
        s = self.fresh()
        before = self.path().read_bytes()
        with mock.patch.object(journal_mod.os, "write", side_effect=OSError("disk full")):
            with self.assertRaises(StorageError):
                s.apply(M, 3, "k4", [add("wall-d")])
        self.assertEqual((s.revision(M), self.path().read_bytes()), (3, before))
        self.assertEqual(s.apply(M, 3, "k4", [add("wall-d")]).revision, 4)  # key was not consumed

    def test_partial_write_is_discarded_on_failure(self):
        s = self.fresh()
        before = self.path().read_bytes()
        real = os.write

        def half(fd, data):
            real(fd, bytes(data[:len(data) // 2]))
            raise OSError("interrupted")
        with mock.patch.object(journal_mod.os, "write", side_effect=half):
            with self.assertRaises(StorageError):
                s.apply(M, 3, "k4", [add("wall-d")])
        self.assertEqual((s.revision(M), self.path().read_bytes()), (3, before))
        self.assertEqual(s.apply(M, 3, "k5", [add("wall-e")]).revision, 4)
        self.assertEqual(JournalStore.open(self.root).revision(M), 4)

    def test_failed_create_leaves_nothing(self):
        s = JournalStore.open(self.root)
        with mock.patch.object(journal_mod.os, "write", side_effect=OSError("disk full")):
            with self.assertRaises(StorageError):
                s.create_module(M)
        self.assertEqual(s.modules(), [])
        self.path().unlink(missing_ok=True)
        s.create_module(M)

    def test_second_writer_is_detected(self):
        a = self.fresh()
        b = JournalStore.open(self.root)
        a.apply(M, 3, "ka", [add("wall-a2")])
        before = self.path().read_bytes()
        with self.assertRaises(ConcurrentWriteError):
            b.apply(M, 3, "kb", [add("wall-b2")])
        self.assertEqual(self.path().read_bytes(), before)
        self.assertEqual(b.revision(M), 4)  # reloaded from disk after the failure
        self.assertEqual(b.apply(M, 4, "kb", [add("wall-b2")]).revision, 5)


class CorruptionTests(Base):
    def lines(self):
        return self.path().read_bytes().split(b"\n")[:-1]

    def write(self, lines):
        self.path().write_bytes(b"\n".join(lines) + b"\n")

    def assertCorrupt(self):
        with self.assertRaises(CorruptJournalError):
            JournalStore.open(self.root)

    def test_tampered_payload_fails_hash_check(self):
        self.fresh()
        ls = self.lines()
        ls[1] = ls[1].replace(b'"h":1', b'"h":7')
        self.write(ls)
        self.assertCorrupt()

    def test_removed_reordered_or_duplicated_entries_fail(self):
        self.fresh()
        ls = self.lines()
        for edited in (ls[:1] + ls[2:], [ls[0], ls[2], ls[1], ls[3]], ls + [ls[-1]], ls[1:]):
            self.write(edited)
            self.assertCorrupt()

    def test_complete_garbage_and_non_json_lines_fail(self):
        self.fresh()
        ls = self.lines()
        for edited in (ls + [b"not json"], ls + [b"{}"], ls + [b"[]"], ls[:2] + [b"\xff\xfe"] + ls[2:]):
            self.write(edited)
            self.assertCorrupt()

    def test_non_finite_numbers_and_wrong_module_fail(self):
        self.fresh()
        ls = self.lines()
        self.write(ls[:1] + [ls[1].replace(b'"h":1', b'"h":NaN')] + ls[2:])
        self.assertCorrupt()
        moved = self.root / "modules" / "house__other"
        moved.mkdir()
        (moved / "journal.jsonl").write_bytes(b"\n".join(ls) + b"\n")
        with self.assertRaises(CorruptJournalError):
            JournalStore.open(self.root, modules=["house/other"])

    def test_stray_directory_name_fails_closed(self):
        self.fresh()
        (self.root / "modules" / "Bad Name").mkdir()
        with self.assertRaises(CorruptJournalError):
            JournalStore.open(self.root)

    def test_failed_load_leaves_no_partial_module(self):
        self.fresh()
        ls = self.lines()
        self.write(ls[:3] + [b"{}"])
        s = JournalStore(self.root)
        with self.assertRaises(CorruptJournalError):
            s._load(M)
        self.assertEqual(s.modules(), [])


class RollbackTests(Base):
    def test_rollback_restores_earlier_blocks_and_keeps_history(self):
        s = self.fresh()  # r1 {a:1,b:2}  r2 {a:9,b:2,c}  r3 {a:9,c}
        r1 = {"wall-a": {"h": 1}, "wall-b": {"h": 2}}
        r = s.rollback(M, 3, "rb1", 1)
        self.assertEqual((r.revision, r.replayed), (4, False))
        self.assertEqual(s.snapshot(M), (4, r1))
        self.assertEqual(len(self.path().read_bytes().split(b"\n")) - 1, 5)  # create + 4 commits
        again = JournalStore.open(self.root)
        self.assertEqual(again.snapshot(M), (4, r1))
        self.assertEqual(again.tail_hash(M), s.tail_hash(M))
        s.rollback(M, 4, "rb2", 3)  # rolling back a rollback restores r3
        self.assertEqual(s.snapshot(M)[1], {"wall-a": {"h": 9}, "wall-c": {"v": 1}})

    def test_rollback_to_empty_and_after_reopen(self):
        s = self.fresh()
        self.assertEqual(s.rollback(M, 3, "rb0", 0).revision, 4)
        self.assertEqual(s.snapshot(M), (4, {}))
        r = JournalStore.open(self.root)
        self.assertEqual(r.snapshot(M), (4, {}))
        self.assertEqual(r.rollback(M, 4, "rb3", 2).revision, 5)
        self.assertEqual(sorted(r.snapshot(M)[1]), ["wall-a", "wall-b", "wall-c"])

    def test_rollback_is_deterministic(self):
        self.fresh().rollback(M, 3, "rb1", 1)
        first = self.path().read_bytes()
        self.root = Path(self._tmp.name) / "second"
        self.fresh().rollback(M, 3, "rb1", 1)
        self.assertEqual(self.path().read_bytes(), first)

    def test_rollback_idempotency(self):
        s = self.fresh()
        s.rollback(M, 3, "rb1", 1)
        s.apply(M, 4, "k9", [add("wall-z")])
        before = self.path().read_bytes()
        again = s.rollback(M, 3, "rb1", 1)       # retried after later writes
        self.assertEqual((again.revision, again.replayed), (4, True))
        self.assertEqual(JournalStore.open(self.root).rollback(M, 3, "rb1", 1).replayed, True)
        with self.assertRaises(IdempotencyConflictError):
            s.rollback(M, 3, "rb1", 2)
        with self.assertRaises(IdempotencyConflictError):
            s.apply(M, 5, "rb1", [add("wall-q")])
        self.assertEqual(self.path().read_bytes(), before)

    def test_rollback_rejections_change_nothing(self):
        s = self.fresh()
        before = self.path().read_bytes()
        cases = [(M, 2, "r", 1, StaleRevisionError), (M, 3, "r", 3, IdentityError),
                 (M, 3, "r", 9, IdentityError), (M, 3, "r", -1, IdentityError),
                 (M, 3, "r", True, IdentityError), (M, 3, "bad key", 1, IdentityError),
                 (M, True, "r", 1, IdentityError), ("house/none", 3, "r", 1, IdentityError)]
        for module, exp, key, to, exc in cases:
            with self.assertRaises(exc, msg=str((exp, key, to))):
                s.rollback(module, exp, key, to)
        self.assertEqual((s.revision(M), self.path().read_bytes()), (3, before))

    def test_rollback_to_identical_state_is_rejected(self):
        s = JournalStore.open(self.root)
        s.create_module(M)
        s.apply(M, 0, "k1", [add("wall-a")])
        s.apply(M, 1, "k2", [{"op": "replace", "id": "wall-a", "data": {"v": 1}}])
        with self.assertRaises(IdentityError):
            s.rollback(M, 2, "rb", 1)

    def test_rollback_write_failure_leaves_state_unchanged(self):
        s = self.fresh()
        before = self.path().read_bytes()
        with mock.patch.object(journal_mod.os, "write", side_effect=OSError("disk full")):
            with self.assertRaises(StorageError):
                s.rollback(M, 3, "rb1", 1)
        self.assertEqual((s.revision(M), self.path().read_bytes()), (3, before))
        self.assertEqual(s.rollback(M, 3, "rb1", 1).revision, 4)

    def test_entries_have_no_wallclock_fields(self):
        self.fresh().rollback(M, 3, "rb1", 1)
        for line in self.path().read_bytes().split(b"\n")[:-1]:
            self.assertFalse({"time", "ts", "timestamp", "date"} & set(json.loads(line)))


if __name__ == "__main__":
    unittest.main()
