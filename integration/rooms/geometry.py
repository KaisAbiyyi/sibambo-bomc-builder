"""2D polygon helpers: exact-enough intersection area through triangulation (works for concave rooms)."""
from __future__ import annotations

from core.geometry.triangulation import triangulate_face

Point = tuple[float, float]
Triangle = tuple[Point, Point, Point]


def shoelace(points: list) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def triangles(points: list) -> list[Triangle]:
    """Counter-clockwise triangles covering the simple polygon (winding of the input does not matter)."""
    return [tuple((v[0], v[1]) for v in t.vertices) for t in triangulate_face([(x, y, 0.0) for x, y in points])]


def bbox(points: list) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def boxes_overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _clip(subject: list, a: Point, b: Point) -> list:
    """Keep the part of `subject` on the left of the directed edge a->b (Sutherland-Hodgman, convex clipper)."""
    def side(p: Point) -> float:
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])

    out = []
    for i, cur in enumerate(subject):
        prev = subject[i - 1]
        sc, sp = side(cur), side(prev)
        if sc >= 0:
            if sp < 0:
                out.append(_cross(prev, cur, sp, sc))
            out.append(cur)
        elif sp >= 0:
            out.append(_cross(prev, cur, sp, sc))
    return out


def _cross(p: Point, q: Point, sp: float, sq: float) -> Point:
    t = sp / (sp - sq)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def convex_intersection_area(t1: Triangle, t2: Triangle) -> float:
    poly = list(t1)
    for i in range(3):
        poly = _clip(poly, t2[i], t2[(i + 1) % 3])
        if not poly:
            return 0.0
    return shoelace(poly)


def intersection_area(tris_a: list, tris_b: list) -> float:
    """Area of the intersection of two polygons given as triangulations (sum over triangle pairs)."""
    return sum(convex_intersection_area(a, b) for a in tris_a for b in tris_b)
