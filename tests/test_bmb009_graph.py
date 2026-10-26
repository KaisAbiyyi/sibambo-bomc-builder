"""BMB-009 definition-instance DAG tests: synthetic data only."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.graph import dag  # noqa: E402
from core.graph.dag import (  # noqa: E402
    CycleError, DefinitionGraph, GraphError, IDENTITY, apply_point, compose,
    invert, is_mirrored, mirror, rotation_z, scale, shear_xy, translation)


def close(a, b, tol=1e-9):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def nested():
    g = DefinitionGraph()
    for d in ("house", "wing", "room"):
        g.add_definition(d)
    g.add_instance("house", "wing-a", "wing", translation(10, 0, 0))
    g.add_instance("wing", "room-1", "room", translation(0, 5, 0))
    g.add_instance("wing", "room-2", "room", compose(translation(4, 0, 0), mirror("x")))
    return g


class MatrixTests(unittest.TestCase):
    def test_compose_order_and_inverse(self):
        m = compose(translation(1, 2, 3), rotation_z(90))
        self.assertTrue(close(apply_point(m, (1, 0, 0)), (1, 3, 3)))
        self.assertTrue(close(compose(m, invert(m)), IDENTITY))
        sh = compose(shear_xy(0.5), scale(2, 3, 4))
        self.assertTrue(close(compose(invert(sh), sh), IDENTITY))

    def test_rejects_bad_transforms(self):
        bad = [IDENTITY[:15], list(IDENTITY[:15]) + ["1"], scale(0, 1, 1),
               list(IDENTITY[:12]) + [0, 0, 1, 1],
               list(IDENTITY[:3]) + [math.nan] + list(IDENTITY[4:]),
               translation(2e6, 0, 0), list(IDENTITY[:3]) + [True] + list(IDENTITY[4:])]
        for m in bad:
            with self.subTest(m=m), self.assertRaises(GraphError):
                dag.validate_transform(m)


class GraphTests(unittest.TestCase):
    def test_nested_world_transforms(self):
        w = nested().world_transforms("house")
        self.assertEqual(list(w), ["wing-a", "wing-a/room-1", "wing-a/room-2"])
        self.assertTrue(close(apply_point(w["wing-a/room-1"], (0, 0, 0)), (10, 5, 0)))
        # mirrored child: local x=1 -> -1, then +4 inside wing, +10 for wing
        self.assertTrue(close(apply_point(w["wing-a/room-2"], (1, 0, 0)), (13, 0, 0)))
        self.assertTrue(is_mirrored(w["wing-a/room-2"]))
        self.assertFalse(is_mirrored(w["wing-a/room-1"]))

    def test_shared_definition_gets_distinct_paths(self):
        w = nested().world_transforms("house")
        self.assertNotEqual(w["wing-a/room-1"], w["wing-a/room-2"])

    def test_double_mirror_restores_handedness(self):
        g = DefinitionGraph()
        for d in ("a", "b", "c"):
            g.add_definition(d)
        g.add_instance("a", "m1", "b", mirror("x"))
        g.add_instance("b", "m2", "c", mirror("y"))
        w = g.world_transforms("a")["m1/m2"]
        self.assertFalse(is_mirrored(w))
        self.assertTrue(close(apply_point(w, (1, 2, 3)), (-1, -2, 3)))

    def test_sheared_nested(self):
        g = DefinitionGraph()
        for d in ("a", "b"):
            g.add_definition(d)
        g.add_instance("a", "s", "b", compose(shear_xy(1.0), translation(0, 0, 1)))
        w = g.world_transforms("a", scale(2, 1, 1))["s"]
        # local (0,1,0): translate -> (0,1,1), shear -> (1,1,1), scale -> (2,1,1)
        self.assertTrue(close(apply_point(w, (0, 1, 0)), (2, 1, 1)))
        self.assertAlmostEqual(dag.determinant(w), 2.0)

    def test_stable_across_insertion_order_and_runs(self):
        g1, g2 = nested(), DefinitionGraph()
        for d in ("room", "wing", "house"):
            g2.add_definition(d)
        g2.add_instance("wing", "room-2", "room", compose(translation(4, 0, 0), mirror("x")))
        g2.add_instance("wing", "room-1", "room", translation(0, 5, 0))
        g2.add_instance("house", "wing-a", "wing", translation(10, 0, 0))
        self.assertEqual(g1.world_transforms("house"), g2.world_transforms("house"))
        self.assertEqual(g1.world_transforms("house"), g1.world_transforms("house"))
        self.assertEqual(g1.topological_order(), ["room", "wing", "house"])

    def test_deep_chain_matches_closed_form(self):
        g = DefinitionGraph()
        n = 20
        for i in range(n):
            g.add_definition(f"d{i}")
        for i in range(n - 1):
            g.add_instance(f"d{i}", "next", f"d{i + 1}", translation(1, 0, 0))
        w = g.world_transforms("d0")
        self.assertEqual(len(w), n - 1)
        self.assertTrue(close(apply_point(w["/".join(["next"] * (n - 1))], (0, 0, 0)), (n - 1, 0, 0)))

    def test_cycle_rejected_without_mutation(self):
        g = nested()
        before = g.world_transforms("house")
        for owner, target in (("room", "house"), ("wing", "wing"), ("room", "wing")):
            with self.subTest(owner=owner), self.assertRaises(CycleError) as ctx:
                g.add_instance(owner, "back", target)
            self.assertEqual(ctx.exception.path[0], owner)
            self.assertEqual(ctx.exception.path[-1], owner)
        self.assertEqual(g.world_transforms("house"), before)
        self.assertEqual(g.instances("room"), [])
        self.assertIsNone(g.find_cycle())

    def test_preexisting_cycle_detected(self):
        g = nested()
        g._defs["room"]["bad"] = ("house", IDENTITY)  # bypass API as corrupted input
        self.assertEqual(g.find_cycle(), ["house", "wing", "room", "house"])
        with self.assertRaises(CycleError):
            g.world_transforms("house")
        with self.assertRaises(CycleError):
            g.topological_order()

    def test_failed_edits_do_not_mutate(self):
        g = nested()
        before = g.world_transforms("house")
        with self.assertRaises(GraphError):
            g.set_transform("wing", "room-1", scale(0, 1, 1))
        with self.assertRaises(GraphError):
            g.add_instance("wing", "room-1", "room")
        with self.assertRaises(GraphError):
            g.add_instance("wing", "ghost", "missing")
        with self.assertRaises(GraphError):
            g.add_instance("wing", "Bad Id", "room")
        self.assertEqual(g.world_transforms("house"), before)

    def test_set_transform_propagates_to_descendants_only(self):
        g = nested()
        before = g.world_transforms("house")
        g.set_transform("house", "wing-a", translation(20, 0, 0))
        after = g.world_transforms("house")
        self.assertTrue(close(apply_point(after["wing-a/room-1"], (0, 0, 0)), (20, 5, 0)))
        self.assertNotEqual(before, after)
        g.remove_instance("wing", "room-2")
        self.assertEqual(list(g.world_transforms("house")), ["wing-a", "wing-a/room-1"])

    def test_budgets(self):
        g = DefinitionGraph()
        n = 14
        for i in range(n):
            g.add_definition(f"d{i}")
        for i in range(n - 1):  # two instances per level -> 2^14 expansion
            g.add_instance(f"d{i}", "l", f"d{i + 1}")
            g.add_instance(f"d{i}", "r", f"d{i + 1}")
        with self.assertRaisesRegex(GraphError, "expanded instance budget"):
            g.world_transforms("d0")
        deep = DefinitionGraph()
        for i in range(dag.MAX_DEPTH + 3):
            deep.add_definition(f"d{i}")
        for i in range(dag.MAX_DEPTH + 2):
            deep.add_instance(f"d{i}", "n", f"d{i + 1}")
        with self.assertRaisesRegex(GraphError, "depth budget"):
            deep.world_transforms("d0")

    def test_unknown_root_and_duplicates(self):
        g = nested()
        with self.assertRaises(GraphError):
            g.world_transforms("nope")
        with self.assertRaises(GraphError):
            g.add_definition("house")


if __name__ == "__main__":
    unittest.main()
