"""BMB-015 synthetic geometric acceptance: real cuts, inserts, clear door route."""
import copy
import json
import math
import pathlib
import unittest

from core.geometry.openings import build_wall_with_openings


def wall(path=((0, 0), (4, 0)), height=2.8, base=0.0, thickness=0.2):
    return {"kind": "wall-run", "opId": "wall-a",
            "path": [list(p) for p in path], "thickness": thickness,
            "height": height, "baseElevation": base}


def opening(kind="door", offset=1.0, width=0.9, height=2.1, sill=0.0, oid="cut-a"):
    return {"kind": "opening-cut", "opId": oid, "targetWallOpId": "wall-a",
            "offset": offset, "width": width, "height": height,
            "sillHeight": sill, "openingType": kind}


def _sub(a, b):
    return tuple(v - w for v, w in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def assert_watertight(test, faces):
    edges = {}
    for f in faces:
        p, normal = f["vertices"], f["normal"]
        test.assertEqual(len(p), 4)
        test.assertAlmostEqual(math.sqrt(_dot(normal, normal)), 1, places=7)
        area = tuple(sum(_cross(p[k], p[(k + 1) % 4])[axis]
                         for k in range(4)) for axis in range(3))
        test.assertGreater(_dot(area, normal), 1e-8, f["role"])
        for i in range(4):
            a = tuple(round(v, 8) for v in p[i])
            b = tuple(round(v, 8) for v in p[(i + 1) % 4])
            test.assertNotEqual(a, b)
            edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
    for edge, directions in edges.items():
        test.assertEqual(len(directions), 2, f"non-manifold mesh edge: {edge}")
        test.assertEqual(directions[0], tuple(reversed(directions[1])))


def check_assembly(test, result):
    assert_watertight(test, result["wall"]["faces"])
    for obj in result["inserts"]:
        for part in obj["parts"]:
            assert_watertight(test, part["faces"])


class OpeningGeometryTest(unittest.TestCase):
    def test_real_door_void_volume_and_clearance(self):
        model = build_wall_with_openings(wall(), [opening()])
        shell = model["wall"]
        self.assertEqual(shell["topology"], "conforming-quad-voids")
        self.assertAlmostEqual(shell["volume"], 4 * 0.2 * 2.8 - 0.9 * 0.2 * 2.1)
        self.assertLess(shell["volume"], 4 * 0.2 * 2.8)
        self.assertTrue(any(f["role"] == "wall-base-or-lintel" for f in shell["faces"]))
        self.assertTrue(any("jamb" in f["role"] for f in shell["faces"]))
        # No surface may cross the cutout mid-plane, not just a metadata marker.
        for face in shell["faces"]:
            vertices = face["vertices"]
            if all(abs(p[1]) == 0.1 for p in vertices):
                # Front/back faces at the original wall skins.
                if max(p[1] for p in vertices) == min(p[1] for p in vertices):
                    midx = (min(p[0] for p in vertices) + max(p[0] for p in vertices)) / 2
                    midz = (min(p[2] for p in vertices) + max(p[2] for p in vertices)) / 2
                    self.assertFalse(1.0 < midx < 1.9 and 0 < midz < 2.1)
        clear = model["doorwayClearance"][0]
        self.assertGreaterEqual(clear["width"], 0.70)
        self.assertGreaterEqual(clear["height"], 1.90)
        self.assertEqual(model["inserts"][0]["kind"], "door-insert")
        self.assertIn("door-leaf-open", [p["role"] for p in model["inserts"][0]["parts"]])
        check_assembly(self, model)

    def test_window_void_retains_sill_and_has_glazing(self):
        op = opening("window", offset=2.0, width=1.2, height=1.0,
                     sill=0.9, oid="window-a")
        result = build_wall_with_openings(wall(), [op])
        self.assertAlmostEqual(result["wall"]["volume"], 4 * 0.2 * 2.8 - 1.2 * 0.2)
        self.assertEqual(result["doorwayClearance"], [])
        self.assertEqual(result["inserts"][0]["kind"], "window-insert")
        roles = [p["role"] for p in result["inserts"][0]["parts"]]
        self.assertIn("frame-sill", roles)
        self.assertIn("window-glazing", roles)
        check_assembly(self, result)

    def test_two_separate_door_and_window_cuts(self):
        ops = [opening(offset=0.5, width=0.9),
               opening("window", offset=2.2, width=1.0, height=1.0,
                       sill=1.0, oid="win-b")]
        result = build_wall_with_openings(wall(), ops)
        self.assertAlmostEqual(result["wall"]["volume"],
                               (4 * 2.8 - 0.9 * 2.1 - 1.0 * 1.0) * 0.2)
        self.assertEqual(len(result["inserts"]), 2)
        check_assembly(self, result)
        self.assertEqual(json.dumps(result, sort_keys=True),
                         json.dumps(build_wall_with_openings(
                             copy.deepcopy(wall()), list(reversed(copy.deepcopy(ops)))),
                             sort_keys=True))

    def test_diag_reverse_wall_coordinate_orientation(self):
        for p in [((4, 0), (0, 0)), ((0, 0), (0, 4)),
                  ((1, 2), (5, 2)), ((0, 0), (2.4, 3.2))]:
            with self.subTest(path=p):
                result = build_wall_with_openings(wall(p), [opening()])
                check_assembly(self, result)

    def test_real_module_ir_opening_and_target(self):
        fixture = pathlib.Path(__file__).resolve().parents[1] / "examples/module-ir-two-rooms.json"
        envelope = json.loads(fixture.read_text(encoding="utf-8"))
        ops = envelope["modules"][0]["operations"]
        w = next(op for op in ops if op["kind"] == "wall-run")
        cuts = [op for op in ops if op["kind"] == "opening-cut"]
        model = build_wall_with_openings(w, cuts)
        self.assertEqual(model["wall"]["opId"], "east-wall")
        self.assertAlmostEqual(model["wall"]["volume"],
                               (3 * 2.8 - 0.9 * 2.1) * 0.15)
        check_assembly(self, model)

    def test_reject_wrong_targets_invalid_numbers_and_types(self):
        for patch in [
            {"targetWallOpId": "other"}, {"openingType": "arch"},
            {"kind": "door"}, {"opId": "Not valid"},
            {"offset": float("nan")}, {"offset": True},
            {"width": 0}, {"height": -1}, {"sillHeight": -1},
            {"width": float("inf")}, {"offset": -0.1},
            {"offset": 3.8}, {"width": 4.0}, {"height": 2.8},
            {"sillHeight": 1.0},  # Door blocked by a threshold.
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                build_wall_with_openings(wall(), [{**opening(), **patch}])

    def test_reject_window_without_sill_and_opening_without_head(self):
        for op in [opening("window", sill=0),
                   opening("window", sill=1.8, height=1.0)]:
            with self.assertRaises(ValueError):
                build_wall_with_openings(wall(), [op])

    def test_reject_duplicate_overlap_touch_and_excessive_counts(self):
        a = opening()
        cases = [[a, copy.deepcopy(a)],
                 [a, opening(offset=1.5, oid="cut-b")],
                 [a, opening(offset=1.9, oid="cut-b")],
                 [opening(oid=f"cut-{i}", offset=0.1 + i * 0.2,
                          width=0.1) for i in range(17)]]
        for ops in cases:
            with self.subTest(count=len(ops)), self.assertRaises(ValueError):
                build_wall_with_openings(wall(), ops)

    def test_reject_narrow_doorway_and_nonpositive_clearance(self):
        with self.assertRaises(ValueError):
            build_wall_with_openings(wall(), [opening(width=0.65)])
        with self.assertRaises(ValueError):
            build_wall_with_openings(wall(), [opening()], minimum_door_clearance=0)
        with self.assertRaises(ValueError):
            build_wall_with_openings(wall(), [opening(height=1.8)])

    def test_reject_bent_wall_until_segment_aware_cutout_exists(self):
        with self.assertRaisesRegex(ValueError, "bent"):
            build_wall_with_openings(wall(((0, 0), (3, 0), (3, 3))), [opening()])

    def test_reject_empty_and_nonsensical_inputs(self):
        for ops in ([], None, {}, "door"):
            with self.assertRaises(ValueError):
                build_wall_with_openings(wall(), ops)


if __name__ == "__main__":
    unittest.main()
