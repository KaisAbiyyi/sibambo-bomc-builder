"""BMB-016 synthetic roof/ceiling/stair geometry and failure gates."""
import copy
import json
import math
import unittest
from collections import Counter

from core.geometry.roof import (RoofError, assert_no_aabb_overlap,
                                build_ceiling_shell, build_roof_shell,
                                build_stair_flight, check_roof_wall_junction)
from core.geometry.wall import build_wall_run


def roof(**updates):
    op = {"kind": "roof-shell", "opId": "main-roof",
          "footprint": [[0, 0], [6, 0], [6, 4], [0, 4]],
          "profile": "gable", "eaveElevation": 3,
          "thickness": 0.2, "rise": 1.5, "ridgeAxis": "x"}
    op.update(updates)
    return op


def stair(**updates):
    op = {"kind": "stair-flight", "opId": "stair-a",
          "origin": [0, 0, 0.2], "direction": "+x", "width": 1,
          "treadDepth": 0.3, "riserHeight": 0.16, "stepCount": 4}
    op.update(updates)
    return op


def wall(points, height=3):
    return build_wall_run({"kind": "wall-run", "opId": "wall-a",
                           "path": points, "thickness": 0.2, "height": height,
                           "baseElevation": 0})


def watertight(test, solid):
    edges = Counter()
    for face in solid["faces"]:
        verts = [tuple(v) for v in face["vertices"]]
        test.assertGreaterEqual(len(verts), 4)
        normal = face["normal"]
        test.assertAlmostEqual(math.sqrt(sum(v*v for v in normal)), 1, places=9)
        area = [sum((a[(i+1)%3]-b[(i+1)%3]) *
                    (a[(i+2)%3]+b[(i+2)%3])
                    for a,b in zip(verts, verts[1:]+verts[:1])) for i in range(3)]
        test.assertGreater(sum(a*b for a,b in zip(area, normal)), 1e-8, face["role"])
        for a, b in zip(verts, verts[1:]+verts[:1]):
            test.assertNotEqual(a, b)
            edges[(a, b)] += 1
    test.assertTrue(edges)
    for (a, b), n in edges.items():
        test.assertEqual(n, 1, "duplicate directed edge")
        test.assertEqual(edges[(b, a)], 1, "unpaired mesh edge")


class RoofTest(unittest.TestCase):
    def test_flat_roof_and_ceiling(self):
        flat = build_roof_shell(roof(profile="flat", rise=0, ridgeAxis=None))
        ceiling = build_ceiling_shell({**roof(profile="flat", rise=0, ridgeAxis=None),
                                        "kind": "ceiling-shell", "opId": "ceiling"})
        self.assertEqual(flat["bounds"], {"min": [0,0,3], "max": [6,4,3.2]})
        self.assertEqual(ceiling["kind"], "ceiling-shell")
        self.assertEqual(len(flat["faces"]), 6)
        self.assertEqual(len(ceiling["faces"]), 6)
        self.assertAlmostEqual(flat["volume"], 4.8)
        watertight(self, flat)
        watertight(self, ceiling)

    def test_gable_both_axes_are_closed_and_oriented(self):
        for axis in ("x", "y"):
            with self.subTest(axis=axis):
                solid = build_roof_shell(roof(ridgeAxis=axis))
                self.assertEqual(len(solid["faces"]), 8)
                self.assertEqual(solid["bounds"], {"min": [0,0,3], "max": [6,4,4.7]})
                self.assertAlmostEqual(solid["area"], 24)
                self.assertAlmostEqual(solid["volume"], 4.8)
                self.assertEqual(len([f for f in solid["faces"]
                                      if f["role"].startswith("top-slope-")]), 2)
                watertight(self, solid)

    def test_gable_input_order_canonical(self):
        op = roof()
        a = build_roof_shell(op)
        b = build_roof_shell(roof(footprint=list(reversed(op["footprint"]))))
        c = build_roof_shell(roof(footprint=op["footprint"][2:] + op["footprint"][:2]))
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(copy.deepcopy(a), sort_keys=True))

    def test_gable_ridge_and_eave_have_correct_z(self):
        g = build_roof_shell(roof(eaveElevation=2.5, rise=2, thickness=0.3))
        top = [f for f in g["faces"] if f["role"].startswith("top-slope")]
        under = [f for f in g["faces"] if f["role"].startswith("underside")]
        self.assertEqual(max(p[2] for f in top for p in f["vertices"]), 4.8)
        self.assertEqual(max(p[2] for f in under for p in f["vertices"]), 4.5)
        self.assertEqual(min(p[2] for f in under for p in f["vertices"]), 2.5)

    def test_reject_incompatible_profiles_footprints_and_unknown_fields(self):
        cases = [
            roof(profile="bad"), roof(profile="flat"),
            roof(ridgeAxis=None), roof(rise=0), roof(rise=-2),
            roof(footprint=[[0,0],[4,0],[3,4],[0,4]]),
            roof(footprint=[[0,0],[6,0],[6,4],[0,0]]),
            roof(footprint=[[0,0],[6,0],[6,4],[0,4],[1,1]]),
            roof(opId="../bad"), roof(materialId="Bad"),
            roof(eaveElevation=math.inf), roof(thickness=True),
            roof(thickness=0), roof(thickness=101),
            roof(eaveElevation=9999.9, rise=2), roof(unknown=True),
            roof(footprint=[[0,0],[6,0],[6,4],[10**400,4]]),
            {**roof(), "kind": "wall-run"},
            {**roof(profile="flat", rise=0, ridgeAxis=None), "kind": "ceiling-shell",
             "profile": "gable"},
        ]
        for op in cases:
            with self.subTest(op=str(op)[:100]), self.assertRaises(RoofError):
                build_roof_shell(op)

    def test_flat_roof_preserves_concave_slab(self):
        poly = [[0,0],[4,0],[4,1],[1,1],[1,3],[0,3]]
        s = build_roof_shell(roof(profile="flat", rise=0, ridgeAxis=None, footprint=poly))
        self.assertAlmostEqual(s["area"], 6)
        watertight(self, s)

    def test_eave_junction_accepts_exact_roof_support(self):
        g = build_roof_shell(roof())
        self.assertTrue(check_roof_wall_junction(g, wall([[0,0],[6,0]])))
        self.assertTrue(check_roof_wall_junction(g, wall([[6,4],[0,4]])))
        yroof = build_roof_shell(roof(ridgeAxis="y"))
        self.assertTrue(check_roof_wall_junction(yroof, wall([[0,0],[0,4]])))
        flat = build_roof_shell(roof(profile="flat", rise=0, ridgeAxis=None))
        self.assertTrue(check_roof_wall_junction(flat, wall([[0,0],[0,4]])))

    def test_junction_rejects_mismatch_endwall_and_inside(self):
        g = build_roof_shell(roof())
        for candidate in (wall([[0,0],[6,0]], height=3.1),
                          wall([[0,0],[6,0]], height=2.9),
                          wall([[0,1],[6,1]]),
                          wall([[0,0],[0,4]]),
                          wall([[0,-1],[6,-1]])):
            with self.subTest(path=candidate["path"]), self.assertRaises(RoofError):
                check_roof_wall_junction(g, candidate)

    def test_broad_phase_rejects_overlap_allows_touch(self):
        roof_solid = build_roof_shell(roof(profile="flat", rise=0, ridgeAxis=None))
        adjacent = build_roof_shell(roof(profile="flat", rise=0, ridgeAxis=None,
                                        eaveElevation=3.2))
        self.assertTrue(assert_no_aabb_overlap(roof_solid, adjacent))
        with self.assertRaises(RoofError):
            assert_no_aabb_overlap(roof_solid, build_roof_shell(roof(profile="flat", rise=0,
                                                                     ridgeAxis=None,
                                                                     eaveElevation=3.1)))


class StairsTest(unittest.TestCase):
    def test_run_rise_and_step_volumes(self):
        s = build_stair_flight(stair())
        self.assertEqual((s["totalRun"], s["totalRise"]), (1.2, 0.64))
        self.assertEqual(s["bounds"], {"min": [0,0,0.2],
                                        "max": [1.2,1,0.8400000000000001]})
        self.assertEqual(len(s["steps"]), 4)
        self.assertEqual([round(p["topElevation"],2) for p in s["steps"]], [.36,.52,.68,.84])
        for part in s["steps"]:
            watertight(self, {"faces": part["faces"]})
        for left, right in zip(s["steps"], s["steps"][1:]):
            self.assertTrue(assert_no_aabb_overlap(left, right))

    def test_all_directions_and_determinism(self):
        for direction in ("+x", "-x", "+y", "-y"):
            with self.subTest(direction=direction):
                result = build_stair_flight(stair(direction=direction))
                self.assertEqual(result, build_stair_flight(stair(direction=direction)))
                for part in result["steps"]:
                    watertight(self, {"faces": part["faces"]})

    def test_reject_invalid_stairs(self):
        cases = [
            stair(direction="z"), stair(width=0), stair(treadDepth=-1),
            stair(riserHeight=0), stair(stepCount=0), stair(stepCount=129),
            stair(stepCount=True), stair(stepCount=3.5), stair(stepCount=10**400),
            stair(origin=[0,0]), stair(origin=[0,0,math.nan]),
            stair(origin=[10**400,0,0]), stair(origin=[9999,0,0], direction="+x"),
            stair(opId=".."), stair(materialId="Invalid"),
            stair(width=101), stair(riserHeight=0.9, stepCount=128),
            stair(treadDepth=9, stepCount=128), stair(extra=1),
            stair(width=1e-6, treadDepth=1e-6)
        ]
        for op in cases:
            with self.subTest(op=str(op)[:100]), self.assertRaises(RoofError):
                build_stair_flight(op)


if __name__ == "__main__":
    unittest.main()
