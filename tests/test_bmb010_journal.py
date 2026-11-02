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
    ConcurrentWriteError, CorruptJournalError, DurabilityUncertainError, JournalStore, StorageError)
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


def fsync_fails(times=1):
    """fsync that raises OSError for the first `times` calls, then behaves normally."""
    real, state = os.fsync, {"left": times}

    def fsync(fd):
        if state["left"] > 0:
            state["left"] -= 1
            raise OSError("fsync failed")
        return real(fd)
    return mock.patch.object(journal_mod.os, "fsync", side_effect=fsync)


def fsync_always_fails():
    return mock.patch.object(journal_mod.os, "fsync", side_effect=OSError("fsync failed"))


class UncertainDurabilityTests(Base):
    """A fully written record whose fsync failed is neither 'failed' nor 'committed'."""

    def test_apply_with_failed_fsync_is_quarantined_not_silently_committed(self):
        s = self.fresh()
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.apply(M, 3, "k4", [add("wall-d")])
        self.assertTrue(issubclass(DurabilityUncertainError, StorageError))
        self.assertEqual(s.uncertain_modules(), [M])
        self.assertEqual(s.revision(M), 4)                      # memory matches the visible file
        self.assertEqual(len(self.path().read_bytes().split(b"\n")) - 1, 5)
        for call in (lambda: s.apply(M, 4, "k5", [add("wall-e")]),
                     lambda: s.apply(M, 3, "k4", [add("wall-d")]),   # a replay must not report success either
                     lambda: s.rollback(M, 4, "rb", 1)):
            with self.assertRaises(DurabilityUncertainError):
                call()
        self.assertEqual(s.revision(M), 4)

    def test_recover_rewrites_through_a_fresh_fsynced_file_and_lifts_the_quarantine(self):
        s = self.fresh()
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.apply(M, 3, "k4", [add("wall-d")])
        before = self.path().read_bytes()
        calls = []
        real_replace = os.replace
        with mock.patch.object(journal_mod.os, "replace", side_effect=lambda a, b: (calls.append((a, b)), real_replace(a, b))[1]):
            s.recover(M)
        self.assertEqual(len(calls), 1)                         # the journal was replaced, not just fsynced again
        self.assertEqual((s.uncertain_modules(), self.path().read_bytes()), ([], before))
        self.assertFalse(self.path().with_name("journal.jsonl.recover").exists())
        retry = s.apply(M, 3, "k4", [add("wall-d")])             # the caller's retry now replays
        self.assertEqual((retry.revision, retry.replayed), (4, True))
        self.assertEqual(s.apply(M, 4, "k5", [add("wall-e")]).revision, 5)
        self.assertEqual(JournalStore.open(self.root).revision(M), 5)

    def test_failed_recovery_keeps_the_quarantine_and_the_original_file(self):
        s = self.fresh()
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.apply(M, 3, "k4", [add("wall-d")])
        before = self.path().read_bytes()
        with fsync_always_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.recover(M)
        self.assertEqual((s.uncertain_modules(), self.path().read_bytes()), ([M], before))
        self.assertFalse(self.path().with_name("journal.jsonl.recover").exists())
        s.recover(M)                                            # works once fsync does
        self.assertEqual(s.uncertain_modules(), [])

    def test_create_with_failed_fsync_is_quarantined(self):
        s = JournalStore.open(self.root)
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.create_module(M)
        self.assertEqual((s.modules(), s.uncertain_modules(), s.revision(M)), ([M], [M], 0))
        with self.assertRaises(DurabilityUncertainError):
            s.apply(M, 0, "k1", [add("wall-a")])
        s.recover(M)
        self.assertEqual(s.apply(M, 0, "k1", [add("wall-a")]).revision, 1)
        self.assertEqual(JournalStore.open(self.root).revision(M), 1)

    def test_other_modules_are_unaffected_but_dependents_are_refused(self):
        s = self.fresh()
        s.create_module(K)
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.apply(K, 0, "kk", [add("wall-a")])
        self.assertEqual(s.apply(M, 3, "k4", [add("wall-d")]).revision, 4)   # independent module still writes
        with self.assertRaises(DurabilityUncertainError):
            s.apply(M, 4, "k5", [add("wall-e")], {K: 1})                      # must not depend on a maybe-lost revision
        self.assertEqual(s.revision(M), 4)
        s.recover(K)
        self.assertEqual(s.apply(M, 4, "k5", [add("wall-e")], {K: 1}).revision, 5)

    def test_reopen_after_uncertain_write_treats_visible_record_as_committed_and_retry_is_safe(self):
        s = self.fresh()
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.apply(M, 3, "k4", [add("wall-d")])
        r = JournalStore.open(self.root)                         # a new process sees the complete line
        self.assertEqual(r.revision(M), 4)
        self.assertEqual(r.apply(M, 3, "k4", [add("wall-d")]).replayed, True)
        # had the record been lost, the same retry would simply commit it (idempotency makes the retry safe)
        self.path().write_bytes(b"".join(line + b"\n" for line in self.path().read_bytes().split(b"\n")[:-2]))
        lost = JournalStore.open(self.root)
        self.assertEqual(lost.revision(M), 3)
        self.assertEqual(lost.apply(M, 3, "k4", [add("wall-d")]).revision, 4)

    def test_recover_on_healthy_or_unknown_module(self):
        s = self.fresh()
        s.recover(M)                                             # nothing to do
        with self.assertRaises(IdentityError):
            s.recover("house/none")

    def test_recover_detects_a_changed_file(self):
        s = self.fresh()
        with fsync_fails():
            with self.assertRaises(DurabilityUncertainError):
                s.apply(M, 3, "k4", [add("wall-d")])
        with open(self.path(), "ab") as f:
            f.write(b"x")
        with self.assertRaises(ConcurrentWriteError):
            s.recover(M)
        self.assertEqual(s.uncertain_modules(), [M])


class MetadataTests(Base):
    """Hash-consistent entries whose recorded request metadata contradicts itself must not load."""

    def rewrite(self, index, edit):
        """Edit entry `index`, then re-chain every later entry so all hashes are valid."""
        entries = [json.loads(line) for line in self.path().read_bytes().split(b"\n")[:-1]]
        edit(entries[index])
        prev = journal_mod.GENESIS
        out = []
        for entry in entries:
            entry["prev"] = prev
            entry["hash"] = journal_mod._digest(entry)
            prev = entry["hash"]
            out.append(journal_mod._canonical(entry).encode())
        self.path().write_bytes(b"\n".join(out) + b"\n")

    def assertLoads(self):
        return JournalStore.open(self.root)

    def assertCorrupt(self):
        with self.assertRaises(CorruptJournalError):
            JournalStore.open(self.root)

    def test_untouched_rewrite_still_loads(self):
        self.fresh().rollback(M, 3, "rb1", 1)
        self.rewrite(1, lambda e: None)
        self.assertEqual(self.assertLoads().revision(M), 4)

    def test_malformed_dependency_minimums(self):
        for bad in ("x", [], None, {"Bad Id": 1}, {K: -1}, {K: True}, {K: "1"}, {"house/a": 1.5}):
            self.fresh()
            self.rewrite(2, lambda e, bad=bad: e.update(mins=bad))
            self.assertCorrupt()
            self._tmp.cleanup()
            self.setUp()

    def test_minimums_that_do_not_match_the_recorded_fingerprint(self):
        self.fresh()
        self.rewrite(2, lambda e: e.update(mins={K: 1}))
        self.assertCorrupt()

    def test_valid_minimums_round_trip_with_fingerprint(self):
        s = self.fresh()
        s.create_module(K)
        s.apply(K, 0, "kk", [add("wall-a")])
        s.apply(M, 3, "dep", [add("wall-d")], {K: 1})
        r = JournalStore.open(self.root)
        self.assertEqual(r.apply(M, 3, "dep", [add("wall-d")], {K: 1}).replayed, True)
        with self.assertRaises(IdempotencyConflictError):
            r.apply(M, 3, "dep", [add("wall-d")], {K: 0})

    def test_foreign_fingerprint_is_not_trusted(self):
        self.fresh()
        self.rewrite(2, lambda e: e.update(fp="0" * 64))
        self.assertCorrupt()

    def test_rollback_metadata_must_match(self):
        s = self.fresh()
        s.rollback(M, 3, "rb1", 1)  # entry index 4
        fp = lambda to, rev=3: journal_mod._fingerprint(M, rev, [{"op": "rollback", "to": to}], {})
        # rollbackTo changed but fingerprint left alone
        self.rewrite(4, lambda e: e.update(rollbackTo=2))
        self.assertCorrupt()
        # rollbackTo and fingerprint consistently changed, but the ops still restore revision 1
        self.rewrite(4, lambda e: e.update(rollbackTo=2, fp=fp(2)))
        self.assertCorrupt()

    def test_rollback_target_range_and_type(self):
        for bad in (-1, 3, 4, 9, True, "1", None, 1.0):
            self.fresh().rollback(M, 3, "rb1", 1)
            self.rewrite(4, lambda e, bad=bad: e.update(rollbackTo=bad))
            self.assertCorrupt()
            self._tmp.cleanup()
            self.setUp()

    def test_rollback_with_dependency_minimums_is_rejected(self):
        self.fresh().rollback(M, 3, "rb1", 1)
        self.rewrite(4, lambda e: e.update(mins={K: 0}))
        self.assertCorrupt()

    def test_rollback_ops_that_do_not_restore_the_target(self):
        self.fresh().rollback(M, 3, "rb1", 1)
        self.rewrite(4, lambda e: e.update(ops=e["ops"][:-1]))   # drops one restoring op
        self.assertCorrupt()

    def test_corrupt_metadata_leaves_other_modules_loadable(self):
        s = self.fresh()
        s.create_module(K)
        s.apply(K, 0, "kk", [add("wall-a")])
        self.rewrite(2, lambda e: e.update(fp="1" * 64))
        self.assertCorrupt()
        self.assertEqual(JournalStore.open(self.root, modules=[K]).revision(K), 1)


class SizeBudgetTests(Base):
    def test_commits_never_exceed_the_file_budget_open_accepts(self):
        probe = JournalStore.open(self.root)
        probe.create_module(M)
        create_size = self.path().stat().st_size
        probe.apply(M, 0, "k1", [add("wall-a")])
        exact = self.path().stat().st_size                   # size after one commit
        self._tmp.cleanup()
        self.setUp()
        with mock.patch.object(journal_mod, "MAX_FILE_BYTES", exact):
            s = JournalStore.open(self.root)
            s.create_module(M)
            self.assertEqual(s.apply(M, 0, "k1", [add("wall-a")]).revision, 1)   # lands exactly on the budget
            before = self.path().read_bytes()
            self.assertEqual(len(before), exact)
            with self.assertRaises(StorageError):
                s.apply(M, 1, "k2", [add("wall-b")])
            self.assertEqual((s.revision(M), self.path().read_bytes()), (1, before))
            with self.assertRaises(StorageError):
                s.rollback(M, 1, "rb", 0)
            self.assertEqual(JournalStore.open(self.root).revision(M), 1)         # still opens
            self.assertGreater(exact, create_size)

    def test_create_over_the_budget_leaves_nothing(self):
        with mock.patch.object(journal_mod, "MAX_FILE_BYTES", 10):
            s = JournalStore.open(self.root)
            with self.assertRaises(StorageError):
                s.create_module(M)
        self.assertEqual(s.modules(), [])
        self.assertFalse(self.path().exists())
        self.assertEqual(JournalStore.open(self.root).modules(), [])

    def test_failed_budget_check_does_not_consume_the_key(self):
        s = self.fresh()
        size = self.path().stat().st_size
        with mock.patch.object(journal_mod, "MAX_FILE_BYTES", size):
            with self.assertRaises(StorageError):
                s.apply(M, 3, "k4", [add("wall-d")])
        self.assertEqual(s.apply(M, 3, "k4", [add("wall-d")]).revision, 4)


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
