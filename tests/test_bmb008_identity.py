"""BMB-008 identity/revision/idempotency tests: synthetic data only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.identity import (  # noqa: E402
    IdempotencyConflictError, IdentityError, ModuleStore, StaleDependencyError,
    StaleRevisionError)

M = "house/living"


def add(block, **data):
    return {"op": "add", "id": block, "data": data or {"v": 1}}


def store():
    s = ModuleStore()
    s.create_module(M)
    return s


class RevisionTests(unittest.TestCase):
    def test_new_module_starts_at_zero_and_each_batch_bumps_once(self):
        s = store()
        self.assertEqual(s.revision(M), 0)
        r = s.apply(M, 0, "k1", [add("wall-a"), add("wall-b")])
        self.assertEqual((r.revision, r.replayed), (1, False))
        self.assertEqual(s.apply(M, 1, "k2", [{"op": "remove", "id": "wall-a"}]).revision, 2)
        self.assertEqual(list(s.snapshot(M)[1]), ["wall-b"])

    def test_stale_revision_fails_without_mutation(self):
        s = store()
        s.apply(M, 0, "k1", [add("wall-a")])
        before = s.snapshot(M)
        with self.assertRaises(StaleRevisionError) as cm:
            s.apply(M, 0, "k2", [add("wall-b"), {"op": "remove", "id": "wall-a"}])
        self.assertEqual((cm.exception.expected, cm.exception.actual), (0, 1))
        self.assertEqual(s.snapshot(M), before)
        # the failed key was not consumed
        self.assertEqual(s.apply(M, 1, "k2", [add("wall-b")]).revision, 2)

    def test_invalid_op_midway_leaves_no_partial_mutation(self):
        s = store()
        s.apply(M, 0, "k1", [add("wall-a")])
        before = s.snapshot(M)
        for ops in ([add("wall-b"), add("wall-a")],                      # duplicate id
                    [add("wall-b"), {"op": "replace", "id": "ghost", "data": {}}],
                    [add("wall-b"), {"op": "remove", "id": "ghost"}],
                    [add("wall-b"), add("wall-b")],                      # same id twice
                    [add("wall-b"), {"op": "add", "id": "wall-c", "data": {"x": float("nan")}}]):
            with self.assertRaises(IdentityError):
                s.apply(M, 1, "bad", ops)
            self.assertEqual(s.snapshot(M), before)
            self.assertEqual(s.revision(M), 1)

    def test_dependency_minimum_revision(self):
        s = store()
        s.create_module("house/kitchen")
        with self.assertRaises(StaleDependencyError):
            s.apply(M, 0, "k1", [add("wall-a")], {"house/kitchen": 1})
        self.assertEqual(s.revision(M), 0)
        s.apply("house/kitchen", 0, "kk", [add("wall-a")])
        self.assertEqual(s.apply(M, 0, "k1", [add("wall-a")], {"house/kitchen": 1}).revision, 1)
        with self.assertRaises(StaleDependencyError):
            s.apply(M, 1, "k2", [add("wall-b")], {"house/missing": 0})

    def test_malformed_falsy_min_revisions_fail_closed(self):
        s = store()
        s.create_module("house/kitchen")
        s.apply(M, 0, "k0", [add("wall-a")])
        before = s.snapshot(M)
        for bad in ([], False, 0, "", (), "x", 3, [("house/kitchen", 1)]):
            with self.assertRaises(IdentityError, msg=repr(bad)):
                s.apply(M, 1, "kbad", [add("wall-b")], bad)
            self.assertEqual((s.revision(M), s.snapshot(M)), (1, before))
        # the rejected key was not consumed: it still works once the guard is well-formed
        self.assertEqual(s.apply(M, 1, "kbad", [add("wall-b")], None).revision, 2)
        self.assertEqual(s.apply(M, 2, "kok", [add("wall-c")], {}).revision, 3)
        with self.assertRaises(StaleDependencyError):
            s.apply(M, 3, "kdep", [add("wall-d")], {"house/kitchen": 1})
        s.apply("house/kitchen", 0, "kk", [add("wall-a")])
        self.assertEqual(s.apply(M, 3, "kdep", [add("wall-d")], {"house/kitchen": 1}).revision, 4)


class IdempotencyTests(unittest.TestCase):
    def test_repeated_key_cannot_duplicate_blocks(self):
        s = store()
        first = s.apply(M, 0, "k1", [add("wall-a")])
        again = s.apply(M, 0, "k1", [add("wall-a")])
        self.assertEqual((again.revision, again.replayed), (first.revision, True))
        self.assertEqual(s.revision(M), 1)
        self.assertEqual(list(s.snapshot(M)[1]), ["wall-a"])

    def test_replay_succeeds_after_later_writes(self):
        s = store()
        s.apply(M, 0, "k1", [add("wall-a")])
        s.apply(M, 1, "k2", [add("wall-b")])
        r = s.apply(M, 0, "k1", [add("wall-a")])  # lost-response retry
        self.assertEqual((r.revision, r.replayed), (1, True))
        self.assertEqual(s.revision(M), 2)

    def test_key_reuse_with_different_request_is_rejected(self):
        s = store()
        s.apply(M, 0, "k1", [add("wall-a", h=3)])
        for ops, rev in (([add("wall-a", h=4)], 0), ([add("wall-b")], 0), ([add("wall-a", h=3)], 1)):
            with self.assertRaises(IdempotencyConflictError):
                s.apply(M, rev, "k1", ops)
        self.assertEqual(s.revision(M), 1)

    def test_keys_are_scoped_per_module(self):
        s = store()
        s.create_module("house/kitchen")
        s.apply(M, 0, "k1", [add("wall-a")])
        r = s.apply("house/kitchen", 0, "k1", [add("wall-a")])
        self.assertFalse(r.replayed)

    def test_snapshot_and_inputs_are_detached(self):
        s = store()
        data = {"pts": [1, 2]}
        s.apply(M, 0, "k1", [{"op": "add", "id": "wall-a", "data": data}])
        data["pts"].append(3)
        rev, blocks = s.snapshot(M)
        blocks["wall-a"]["pts"].append(9)
        self.assertEqual(s.snapshot(M)[1]["wall-a"], {"pts": [1, 2]})
        self.assertEqual(s.apply(M, 0, "k1", [{"op": "add", "id": "wall-a", "data": {"pts": [1, 2]}}]).replayed, True)


class ValidationTests(unittest.TestCase):
    def test_stable_id_syntax(self):
        s = ModuleStore()
        for bad in ("", "Living", "house", "house//x", "house/1x", "/house/x", None, 3):
            with self.assertRaises(IdentityError):
                s.create_module(bad)
        s.create_module(M)
        with self.assertRaises(IdentityError):
            s.create_module(M)
        for bad in ("Wall", "wall_a", "1wall", "", "w" * 81, None):
            with self.assertRaises(IdentityError):
                s.apply(M, 0, "k1", [{"op": "add", "id": bad, "data": {}}])

    def test_bad_request_shapes(self):
        s = store()
        for args in ((M, -1, "k", [add("a")]), (M, True, "k", [add("a")]), (M, 0, "bad key", [add("a")]),
                     (M, 0, "", [add("a")]), (M, 0, "k", []), (M, 0, "k", "x"),
                     ("house/nope", 0, "k", [add("a")]),
                     (M, 0, "k", [{"op": "upsert", "id": "a", "data": {}}]),
                     (M, 0, "k", [{"op": "remove", "id": "a", "data": {}}]),
                     (M, 0, "k", [{"op": "add", "id": "a", "data": []}]),
                     (M, 0, "k", [{"op": "add", "id": "a", "data": {"x": object()}}]),
                     (M, 0, "k", [{"op": "add", "id": "a", "data": {}, "extra": 1}])):
            with self.assertRaises(IdentityError, msg=args):
                s.apply(*args)
        self.assertEqual(s.revision(M), 0)

    def test_budgets(self):
        s = store()
        with self.assertRaises(IdentityError):
            s.apply(M, 0, "k", [add(f"b{i}") for i in range(257)])
        with self.assertRaises(IdentityError):
            s.apply(M, 0, "k", [{"op": "add", "id": "big", "data": {"s": "x" * 70_000}}])
        self.assertEqual(s.revision(M), 0)

    def test_snapshot_order_independent_of_insertion(self):
        a, b = store(), store()
        a.apply(M, 0, "k", [add("wall-b"), add("wall-a")])
        b.apply(M, 0, "k", [add("wall-a"), add("wall-b")])
        self.assertEqual(list(a.snapshot(M)[1]), list(b.snapshot(M)[1]))


if __name__ == "__main__":
    unittest.main()
