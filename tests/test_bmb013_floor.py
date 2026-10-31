"""BMB-013 floor slab tests: synthetic data only."""
import json
import math
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.geometry import FloorError, build_floor_slab  # noqa: E402


def op(footprint=((0, 0), (4, 0), (4, 3), (0, 3)), **kw):
    d = {"kind": "floor-slab", "opId": "floor-1", "footprint": [list(p) for p in footprint],
         "thickness": 0.15, "elevation": 0}
    d.update(kw)
    return d


def face_normal(vs):
    """Newell normal of a planar loop, normalised."""
    nx = ny = nz = 0.0
    for i, a in enumerate(vs):
        b = vs[(i + 1) % len(vs)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    m = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx / m, ny / m, nz / m)


L_SHAPE = ((0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3))


class SlabTests(unittest.TestCase):
    def test_rectangle_bounds_area_volume(self):
        s = build_floor_slab(op(elevation=2.5))
        self.assertEqual(s.bounds, ((0, 0, 2.5), (4, 3, 2.65)))
        self.assertAlmostEqual(s.area, 12.0)
        self.assertAlmostEqual(s.volume, 1.8)
        self.assertEqual((s.role, s.material_id), ("floor", None))
        self.assertEqual(len(s.faces), 6)

    def test_concave_l_shape(self):
        s = build_floor_slab(op(L_SHAPE, materialId="tile", role="structural"))
        self.assertAlmostEqual(s.area, 6.0)
        self.assertEqual(s.bounds, ((0, 0, 0), (4, 3, 0.15)))
        self.assertEqual((s.material_id, s.role, len(s.faces)), ("tile", "structural", 8))

    def test_clockwise_input_is_normalised_ccw(self):
        cw = build_floor_slab(op(L_SHAPE[::-1]))
        ccw = build_floor_slab(op(L_SHAPE))
        self.assertAlmostEqual(cw.area, 6.0)
        self.assertEqual(cw.footprint[0], L_SHAPE[::-1][0])
        self.assertEqual(sorted(cw.footprint), sorted(ccw.footprint))
        top = next(f for f in cw.faces if f.name == "top")
        self.assertGreater(face_normal(top.vertices)[2], 0.99)

    def test_every_face_winding_matches_its_outward_normal(self):
        for fp in (((0, 0), (4, 0), (4, 3), (0, 3)), L_SHAPE, L_SHAPE[::-1]):
            s = build_floor_slab(op(fp))
            cx = sum(p[0] for p in s.footprint) / len(s.footprint)
            cy = sum(p[1] for p in s.footprint) / len(s.footprint)
            for f in s.faces:
                n = face_normal(f.vertices)
                for a, b in zip(n, f.normal):
                    self.assertAlmostEqual(a, b, places=9, msg=f.name)
                if f.name.startswith("side"):  # outward for a convex-ish probe: away from the slab plane
                    self.assertEqual(f.normal[2], 0.0)
                    self.assertAlmostEqual(math.hypot(f.normal[0], f.normal[1]), 1.0)

    def test_closed_manifold_each_edge_shared_by_two_opposite_faces(self):
        for fp in (((0, 0), (4, 0), (4, 3), (0, 3)), L_SHAPE):
            s = build_floor_slab(op(fp))
            directed = Counter()
            for f in s.faces:
                for i, a in enumerate(f.vertices):
                    directed[(a, f.vertices[(i + 1) % len(f.vertices)])] += 1
            self.assertTrue(all(c == 1 for c in directed.values()))
            self.assertTrue(all(directed[(b, a)] == 1 for (a, b) in directed))
            n = len(s.footprint)
            self.assertEqual((len(s.faces), len(directed) // 2), (n + 2, 3 * n))  # Euler: V-E+F = 2n-3n+n+2

    def test_signed_volume_from_faces_matches(self):
        s = build_floor_slab(op(L_SHAPE, elevation=1.0))
        vol = 0.0
        for f in s.faces:  # divergence theorem over fan-triangulated faces
            v0 = f.vertices[0]
            for i in range(1, len(f.vertices) - 1):
                a, b, c = v0, f.vertices[i], f.vertices[i + 1]
                vol += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                        + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        # fan triangulation of a concave top/bottom is only exact for the net signed sum
        self.assertAlmostEqual(vol, s.volume, places=9)

    def test_collinear_vertex_allowed(self):
        s = build_floor_slab(op(((0, 0), (2, 0), (4, 0), (4, 3), (0, 3))))
        self.assertAlmostEqual(s.area, 12.0)

    def test_collinear_vertex_at_every_index_and_orientation(self):
        ring = [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)]  # (2,0) is straight-through
        for rev in (False, True):
            base = ring[::-1] if rev else ring
            for k in range(len(base)):  # every rotation puts the collinear vertex at a different index
                s = build_floor_slab(op(base[k:] + base[:k]))
                self.assertAlmostEqual(s.area, 12.0)
        self.assertAlmostEqual(build_floor_slab(op(((2, 0), (4, 0), (4, 3), (0, 3), (0, 0)))).area, 12.0)

    def test_spike_rejected_at_every_index(self):
        ring = [(0, 0), (4, 0), (2, 0), (2, 3)]  # (4,0)->(2,0) folds back
        for k in range(len(ring)):
            with self.assertRaises(FloorError, msg=str(k)):
                build_floor_slab(op(ring[k:] + ring[:k]))

    def test_deterministic(self):
        self.assertEqual(build_floor_slab(op(L_SHAPE)), build_floor_slab(op(L_SHAPE)))

    def test_example_ir_floor_ops_build(self):
        ir = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text())
        built = [build_floor_slab(o) for m in ir["modules"] for o in m["operations"] if o["kind"] == "floor-slab"]
        self.assertEqual(len(built), 2)
        self.assertEqual([round(b.area, 6) for b in built], [12.0, 6.0])


class RejectionTests(unittest.TestCase):
    def bad(self, o):
        with self.assertRaises(FloorError, msg=str(o)[:80]):
            build_floor_slab(o)

    def test_thickness(self):
        for t in (0, -0.1, math.nan, math.inf, "0.1", None, True, 101, 1e300):
            self.bad(op(thickness=t))

    def test_giant_integers_raise_floorerror_not_overflow(self):
        for big in (10 ** 400, -10 ** 400, 10 ** 5):
            self.bad(op(thickness=big))
            self.bad(op(elevation=big))
            self.bad(op(((0, 0), (big, 0), (big, 3), (0, 3))))

    def test_elevation_and_numbers(self):
        for e in (math.nan, "0", None, 1e9):
            self.bad(op(elevation=e))
        self.bad(op(((0, 0), (4, 0), (4, math.nan), (0, 3))))
        self.bad(op(((0, 0), (4, 0), (4, "3"), (0, 3))))

    def test_footprint_shape_and_budget(self):
        for fp in ([], [[0, 0], [1, 0]], "abc", None):
            self.bad({**op(), "footprint": fp})
        self.bad({**op(), "footprint": [[0, 0], [1, 0, 0], [1, 1]]})
        n = 1025
        ring = [[math.cos(2 * math.pi * i / n) * 100, math.sin(2 * math.pi * i / n) * 100] for i in range(n)]
        self.bad({**op(), "footprint": ring})

    def test_degenerate_footprints(self):
        self.bad(op(((0, 0), (1, 0), (2, 0))))                       # zero area
        self.bad(op(((0, 0), (0, 0), (1, 0), (1, 1))))               # duplicate vertex
        self.bad(op(((0, 0), (4, 0), (4, 3), (0, 3), (0, 0))))       # closed ring repeating first point
        self.bad(op(((0, 0), (1e-7, 0), (1e-7, 1e-7))))              # tiny
        self.bad(op(((0, 0), (4, 0), (2, 0), (2, 3))))               # spike folds back along edge

    def test_self_intersections(self):
        self.bad(op(((0, 0), (4, 3), (4, 0), (0, 3))))               # bowtie
        self.bad(op(((0, 0), (4, 0), (4, 3), (2, 0), (0, 3))))       # vertex lies on another edge
        self.bad(op(((0, 0), (4, 0), (4, 4), (2, 4), (2, 0), (1, 1))))

    def test_ids_role_and_fields(self):
        for kw in ({"opId": "Floor"}, {"opId": ""}, {"opId": "a" * 81}, {"materialId": "Bad_Id"},
                   {"role": "garden"}, {"extra": 1}, {"kind": "wall-run"}):
            self.bad(op(**kw))
        for missing in ("opId", "footprint", "thickness", "elevation"):
            o = op()
            del o[missing]
            self.bad(o)
        self.bad([])


if __name__ == "__main__":
    unittest.main()
