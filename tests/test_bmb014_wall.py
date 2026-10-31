"""BMB-014: shape, seam and outward-normal acceptance tests (synthetic)."""
import copy
import json
import math
import pathlib
import unittest

from core.geometry.wall import build_wall_run, join_wall_runs


def wall(points=((0, 0), (4, 0)), *, op_id="wall-a", thickness=0.2,
         height=2.8, z=0.5):
    return {"kind": "wall-run", "opId": op_id, "path": [list(p) for p in points],
            "thickness": thickness, "height": height, "baseElevation": z}


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def check_watertight(test, solid):
    edges = {}
    for face in solid["faces"]:
        vertices = face["vertices"]
        test.assertGreaterEqual(len(vertices), 4)
        n = face["normal"]
        test.assertAlmostEqual(math.sqrt(dot(n, n)), 1)
        # A concave polygon's first three vertices can form a reflex corner.
        # Accumulate the full oriented area vector instead of trusting one triad.
        area_normal = tuple(sum(cross(vertices[i], vertices[(i + 1) % len(vertices)])[axis]
                                for i in range(len(vertices))) for axis in range(3))
        test.assertGreater(dot(area_normal, n), 1e-7, face["role"])
        for i, a in enumerate(vertices):
            b = vertices[(i + 1) % len(vertices)]
            ka = tuple(round(v, 9) for v in a)
            kb = tuple(round(v, 9) for v in b)
            test.assertNotEqual(ka, kb)
            key = tuple(sorted((ka, kb)))
            edges.setdefault(key, []).append((ka, kb))
    test.assertTrue(edges)
    for edge, directions in edges.items():
        test.assertEqual(len(directions), 2, f"unpaired seam {edge}")
        test.assertEqual(directions[0], tuple(reversed(directions[1])))


class WallRunTest(unittest.TestCase):
    def test_straight_dimensions_area_and_volume(self):
        solid = build_wall_run(wall())
        self.assertEqual(solid["kind"], "wall-solid")
        self.assertEqual(len(solid["faces"]), 6)
        self.assertEqual(solid["bounds"], {"min": [0.0, -0.1, 0.5],
                                            "max": [4.0, 0.1, 3.3]})
        self.assertAlmostEqual(solid["length"], 4)
        self.assertAlmostEqual(solid["footprintArea"], 0.8)
        self.assertAlmostEqual(solid["volume"], 0.8 * 2.8)
        self.assertEqual(solid["junctions"], [])
        check_watertight(self, solid)

    def test_right_angle_miter_has_no_crack(self):
        solid = build_wall_run(wall(((0, 0), (4, 0), (4, 3))))
        self.assertEqual(len(solid["junctions"]), 1)
        j = solid["junctions"][0]
        self.assertEqual(j["kind"], "miter")
        self.assertAlmostEqual(j["left"][0], 3.9)
        self.assertAlmostEqual(j["left"][1], 0.1)
        self.assertAlmostEqual(j["right"][0], 4.1)
        self.assertAlmostEqual(j["right"][1], -0.1)
        self.assertAlmostEqual(solid["footprintArea"], 7 * 0.2)
        check_watertight(self, solid)

    def test_inside_and_outside_turns(self):
        for points in (
            ((0, 0), (3, 0), (3, 3), (6, 3)),
            ((0, 0), (3, 0), (3, -3), (6, -3)),
            ((0, 0), (2, 0), (3, 1)),
            ((0, 0), (3, 0), (3, 3), (0, 3)),
        ):
            with self.subTest(points=points):
                solid = build_wall_run(wall(points))
                self.assertEqual(len(solid["junctions"]), len(points) - 2)
                self.assertGreater(solid["footprintArea"], 0)
                check_watertight(self, solid)

    def test_negative_direction_normal_orientation(self):
        for p in (((4, 2), (0, 2)), ((3, 3), (3, -2)), ((2, 2), (-1, 0))):
            with self.subTest(p=p):
                check_watertight(self, build_wall_run(wall(p)))

    def test_collinear_extra_waypoint_is_canonical(self):
        a = build_wall_run(wall(((0, 0), (2, 0), (4, 0))))
        b = build_wall_run(wall(((0, 0), (4, 0))))
        self.assertEqual(a, b)

    def test_repeated_same_input_identical_serialization(self):
        op = wall(((1, -1), (4, -1), (4, 2)), z=-0.3)
        a = json.dumps(build_wall_run(op), separators=(",", ":"), sort_keys=True)
        b = json.dumps(build_wall_run(copy.deepcopy(op)), separators=(",", ":"), sort_keys=True)
        self.assertEqual(a, b)

    def test_real_module_ir_wall_operation(self):
        file = pathlib.Path(__file__).resolve().parents[1] / "examples/module-ir-two-rooms.json"
        envelope = json.loads(file.read_text(encoding="utf-8"))
        op = next(op for op in envelope["modules"][0]["operations"]
                  if op["kind"] == "wall-run")
        solid = build_wall_run(op)
        self.assertEqual(solid["opId"], "east-wall")
        self.assertAlmostEqual(solid["volume"], 3 * 0.15 * 2.8)
        check_watertight(self, solid)

    def test_two_separate_endpoint_join_has_single_shared_cap_removed(self):
        a = wall(((0, 0), (3, 0)), op_id="w-a")
        b = wall(((3, 0), (3, 2)), op_id="w-b")
        solid = join_wall_runs([a, b])
        self.assertEqual(solid["sourceOpIds"], ["w-a", "w-b"])
        self.assertEqual(solid["junctions"][0]["kind"], "miter")
        self.assertEqual(len(solid["faces"]), 8)
        check_watertight(self, solid)

    def test_join_permutation_and_orientation_are_deterministic(self):
        a = wall(((0, 0), (3, 0)), op_id="w-a")
        b = wall(((3, 2), (3, 0)), op_id="w-b")
        c = wall(((5, 2), (3, 2)), op_id="w-c")
        first = join_wall_runs([c, b, a])
        second = join_wall_runs([a, b, c])
        self.assertEqual(first, second)
        self.assertEqual(first["sourceOpIds"], ["w-a", "w-b", "w-c"])
        check_watertight(self, first)

    def test_collinear_join_has_no_internal_split_or_overlap(self):
        a = wall(((0, 0), (3, 0)), op_id="w-a")
        b = wall(((7, 0), (3, 0)), op_id="w-b")
        joined = join_wall_runs([b, a])
        self.assertEqual(len(joined["faces"]), 6)
        self.assertEqual(joined["junctions"], [])
        self.assertAlmostEqual(joined["volume"], 7 * 0.2 * 2.8)
        check_watertight(self, joined)

    def test_reject_bad_kinds_and_invalid_dimensions(self):
        invalid = [
            {"kind": "floor-slab"}, wall(thickness=0), wall(height=-2),
            wall(z=float("inf")), wall(thickness=float("nan")), wall(height=True),
            wall(z=1e6), wall(thickness=1e7),
        ]
        for op in invalid:
            with self.subTest(op=op), self.assertRaises(ValueError):
                build_wall_run(op)

    def test_reject_bad_paths_and_out_of_bounds(self):
        cases = [
            [], [(0, 0)], [(0, 0), (0, 0)],
            [(0, 0), (1, 0), (0, 0)],
            [(0, 0), (1, 0), (0.5, 0)],
            [(0, 0), (3, 3), (0, 3), (3, 0)],
            [(0, 0), (float("nan"), 1)],
            [(0, 0), (1e7, 0)],
            [(0, 0), (1, 0), (1, 2), (0, 2), (0, 0)],
        ]
        for path in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                build_wall_run(wall(path))

    def test_reject_nearly_reversed_miter(self):
        with self.assertRaises(ValueError):
            build_wall_run(wall(((0, 0), (3, 0), (0.01, 0.001))))

    def test_reject_overlapping_thickened_hairpin(self):
        with self.assertRaises(ValueError):
            build_wall_run(wall(((0, 0), (2, 0), (2, 1), (0, 1)), thickness=1.5))

    def test_reject_branch_disconnected_loop_and_duplicate_ids(self):
        base = wall(((0, 0), (2, 0)), op_id="base")
        branch = wall(((2, 0), (2, 3)), op_id="branch")
        extra = wall(((2, 0), (4, 0)), op_id="extra")
        far = wall(((9, 9), (10, 9)), op_id="far")
        last = wall(((2, 3), (0, 0)), op_id="last")
        for ops in ([base, branch, extra], [base, far],
                    [base, branch, last], [base, base]):
            with self.subTest(ops=[o["opId"] for o in ops]), self.assertRaises(ValueError):
                join_wall_runs(ops)

    def test_reject_join_mismatch_and_crossing(self):
        a = wall(((0, 0), (3, 0)), op_id="a")
        for b in (
            wall(((3, 0), (3, 2)), op_id="b", thickness=0.3),
            wall(((3, 0), (3, 2)), op_id="b", height=3),
            wall(((1, 0), (1, 2)), op_id="b"),  # T crossing, not end-to-end
        ):
            with self.subTest(b=b), self.assertRaises(ValueError):
                join_wall_runs([a, b])

    def test_reject_op_id_invalid_and_oversized(self):
        for op_id in ("../x", "Bad", "x" * 81, ""):
            with self.subTest(op_id=op_id), self.assertRaises(ValueError):
                build_wall_run(wall(op_id=op_id))


if __name__ == "__main__":
    unittest.main()
