"""BMB-017 synthetic acceptance: holes, normals, geometry rejection and regression."""
import copy
import json
import math
import unittest

from core.geometry.floor import build_floor_slab
from core.geometry.triangulation import TriangulationError, triangulate_face
from core.geometry.wall import build_wall_run


def square(x0=0, y0=0, x1=6, y1=6, z=0):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def area(triangles):
    total = 0.0
    for triangle in triangles:
        a, b, c = triangle.vertices
        u = [b[k] - a[k] for k in range(3)]
        v = [c[k] - a[k] for k in range(3)]
        cross = (u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0])
        dot = sum(cross[i] * triangle.normal[i] for i in range(3))
        assert dot > 0, (triangle, dot)
        assert abs(sum(v * v for v in triangle.normal) - 1) < 1e-10
        total += dot / 2
    return total


def centroids(triangles):
    return [tuple(sum(p[k] for p in tri.vertices) / 3 for k in range(3))
            for tri in triangles]


def no_t_junctions(triangles):
    """Every vertex lying on an existing XY edge must be an endpoint."""
    points = {tuple(p[:2]) for tri in triangles for p in tri.vertices}
    for tri in triangles:
        verts = [tuple(p[:2]) for p in tri.vertices]
        for a, b in zip(verts, verts[1:] + verts[:1]):
            for p in points:
                if p == a or p == b:
                    continue
                dx, dy = b[0] - a[0], b[1] - a[1]
                cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
                if cross == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]):
                    return False
    return True


class AcceptedTests(unittest.TestCase):
    def test_rectangle_no_holes_and_upward_winding(self):
        ts = triangulate_face(square(z=2.5))
        self.assertEqual(len(ts), 2)
        self.assertAlmostEqual(area(ts), 36)
        self.assertTrue(all(t.normal == (0.0, 0.0, 1.0) for t in ts))
        self.assertEqual(json.dumps(ts, default=lambda x: vars(x), sort_keys=True),
                         json.dumps(triangulate_face(square(z=2.5)),
                                    default=lambda x: vars(x), sort_keys=True))

    def test_concave_l_shape_is_not_fan_triangulated(self):
        l = [(0, 0, 0), (4, 0, 0), (4, 1, 0),
             (1, 1, 0), (1, 3, 0), (0, 3, 0)]
        ts = triangulate_face(l)
        self.assertAlmostEqual(area(ts), 6)
        self.assertTrue(all(not (x > 1 and y > 1)
                            for x, y, _ in centroids(ts)))

    def test_one_hole_real_open_void_not_filled(self):
        hole = square(2, 2, 4, 4)
        ts = triangulate_face(square(), holes=[hole])
        self.assertAlmostEqual(area(ts), 32)
        self.assertTrue(no_t_junctions(ts), 'hole boundary creates a nonconforming seam')
        self.assertTrue(all(not (2 < x < 4 and 2 < y < 4)
                            for x, y, _ in centroids(ts)))
        self.assertTrue(all(t.normal[2] == 1 for t in ts))

    def test_two_disjoint_holes(self):
        outer = square(0, 0, 10, 8)
        a = square(1, 1, 3, 3)
        b = square(6, 4, 8, 6)
        ts = triangulate_face(outer, holes=(a, b))
        self.assertAlmostEqual(area(ts), 72)
        self.assertTrue(no_t_junctions(ts))
        for x, y, _ in centroids(ts):
            self.assertFalse(1 < x < 3 and 1 < y < 3)
            self.assertFalse(6 < x < 8 and 4 < y < 6)

    def test_ring_winding_does_not_change_outward_normals(self):
        outer, hole = square(), square(2, 2, 4, 4)
        for a in (outer, outer[::-1]):
            for b in (hole, hole[::-1]):
                self.assertAlmostEqual(area(triangulate_face(a, holes=(b,))), 32)
                self.assertAlmostEqual(area(triangulate_face(a, holes=(b,), normal=(0, 0, -1))), 32)
                self.assertTrue(all(t.normal[2] == -1
                                    for t in triangulate_face(a, holes=(b,), normal=(0, 0, -1))))

    def test_negative_coordinate_and_collinear_extra_vertex(self):
        ring = [(-3, -3, 0), (-1, -3, 0), (1, -3, 0),
                (1, 1, 0), (-3, 1, 0)]
        self.assertAlmostEqual(area(triangulate_face(ring)), 16)

    def test_thin_concave_neck_is_not_incorrectly_bridged(self):
        outer = [(0, 0, 0), (8, 0, 0), (8, 8, 0), (5, 8, 0),
                 (5, 2, 0), (3, 2, 0), (3, 8, 0), (0, 8, 0)]
        left_hole = square(0.5, 3, 2.5, 5)
        right_hole = square(5.5, 3, 7.5, 5)
        ts = triangulate_face(outer, holes=[left_hole, right_hole])
        self.assertAlmostEqual(area(ts), 44)
        self.assertTrue(no_t_junctions(ts))
        self.assertTrue(all(not (3 < x < 5 and y > 2)
                            for x, y, _ in centroids(ts)))

    def test_floor_and_wall_faces_are_consumable_without_mutation(self):
        slab = build_floor_slab({"kind": "floor-slab", "opId": "floor-a",
                                 "footprint": [[0, 0], [4, 0], [4, 1],
                                               [1, 1], [1, 3], [0, 3]],
                                 "thickness": 0.15, "elevation": 1.0})
        original = copy.deepcopy(slab)
        for face in slab.faces:
            ts = triangulate_face(face.vertices, normal=face.normal)
            self.assertGreater(area(ts), 0)
            self.assertTrue(all(t.normal == face.normal for t in ts))
        self.assertEqual(slab, original)
        wall = build_wall_run({"kind": "wall-run", "opId": "wall-a",
                               "path": [[0, 0], [3, 0], [3, 2]],
                               "thickness": 0.2, "height": 2.8, "baseElevation": 0})
        for face in wall["faces"]:
            ts = triangulate_face(face["vertices"], normal=face["normal"])
            self.assertGreater(area(ts), 0)

    def test_oblique_plane_unit_normals(self):
        ring = [(0, 0, 0), (2, 0, 0), (2, 2, 2), (0, 2, 2)]
        ts = triangulate_face(ring, normal=(0, -1, 1))
        self.assertAlmostEqual(area(ts), 4 * math.sqrt(2))

    def test_repeatability_and_no_input_mutation(self):
        original = square()
        hole = square(2, 2, 4, 4)
        before = copy.deepcopy((original, hole))
        first = triangulate_face(original, holes=[hole])
        self.assertEqual(first, triangulate_face(original, holes=[hole]))
        self.assertEqual((original, hole), before)


class RejectedTests(unittest.TestCase):
    def rejected(self, outer, holes=(), normal=(0, 0, 1)):
        with self.assertRaises(TriangulationError):
            triangulate_face(outer, holes=holes, normal=normal)

    def test_self_intersections_and_zero_area_outer(self):
        self.rejected([(0, 0, 0), (4, 4, 0), (0, 4, 0), (4, 0, 0)])
        self.rejected([(0, 0, 0), (1, 0, 0), (2, 0, 0)])
        self.rejected([(0, 0, 0), (4, 0, 0), (2, 0, 0), (0, 3, 0)])
        self.rejected(square() + [square()[0]])
        self.rejected(square(0, 0, 0.0001, 0.0001))

    def test_invalid_hole_topology(self):
        outer = square()
        self.rejected(outer, holes=[[(2, 2, 0), (4, 4, 0), (2, 4, 0), (4, 2, 0)]])
        self.rejected(outer, holes=[square(7, 7, 8, 8)])
        self.rejected(outer, holes=[square(5, 2, 7, 4)])
        self.rejected(outer, holes=[square(0, 2, 2, 4)])
        self.rejected(outer, holes=[square(1, 1, 4, 4), square(3, 3, 5, 5)])
        self.rejected(outer, holes=[square(1, 1, 5, 5), square(2, 2, 3, 3)])
        self.rejected(outer, holes=[square(1, 1, 3, 3), square(3, 1, 5, 3)])
        self.rejected(outer, holes=[square(2, 2, 4, 4), square(2, 2, 4, 4)])

    def test_bad_shapes_coordinates_and_plane(self):
        for p in (None, "wrong", [], [(0, 0, 0)], [(0, 0, 0), (1, 1, 0)]):
            self.rejected(p)
        for invalid in (math.nan, math.inf, True, "1", 1e8, 10 ** 400):
            ring = square()
            ring[1] = (invalid, 0, 0)
            self.rejected(ring)
        self.rejected([(0, 0, 0), (4, 0, 0), (4, 3, 0.01), (0, 3, 0)])
        for normal in ((0, 0, 0), (math.nan, 0, 1), (0, 0, True), (0, 0, "1")):
            self.rejected(square(), normal=normal)
        self.rejected(square(), holes="not-a-list")
        self.rejected(square(), holes=[[1, 2, 3]])

    def test_vertex_budget(self):
        ring = [(math.cos(2 * math.pi * i / 1025),
                 math.sin(2 * math.pi * i / 1025), 0) for i in range(1025)]
        self.rejected(ring)
        self.rejected(square(), holes=[square(1, 1, 2, 2)] * 65)


if __name__ == "__main__":
    unittest.main()
