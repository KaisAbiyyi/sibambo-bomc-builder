"""BMB-013: parametric floor slab primitive.

Turns a Module IR `floor-slab` operation (docs/MODULE-IR-V1.md) into a
closed prism: a 2D footprint extruded +Z from `elevation` (the slab's bottom
face) by `thickness`, in module-local metres. Faces are returned as planar
polygon loops with outward normals and counter-clockwise winding seen from
outside; triangulation is BMB-017. Pure Python; every rejection raises
before anything is returned.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction

ID_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
ROLES = ("floor", "wall", "ceiling", "roof", "opening", "door", "window", "structural", "other")
MAX_VERTICES = 1024          # stricter than the schema's 4096: the simplicity check is O(n^2)
MAX_ABS_VALUE = 1e4          # metres
MAX_THICKNESS = 100.0
MIN_EDGE = 1e-6              # metres
MIN_AREA = 1e-6              # square metres
FIELDS = {"kind", "opId", "materialId", "role", "footprint", "thickness", "elevation"}


class FloorError(ValueError):
    """Rejected floor-slab input."""


def _need(test: bool, reason: str) -> None:
    if not test:
        raise FloorError(reason)


def _number(value: object, label: str) -> float:
    _need(type(value) in (int, float), f"{label}: must be a number")
    if type(value) is int:  # reject before float(): huge ints raise OverflowError
        _need(abs(value) <= MAX_ABS_VALUE, f"{label}: non-finite or out of range")
    v = float(value)
    _need(math.isfinite(v) and abs(v) <= MAX_ABS_VALUE, f"{label}: non-finite or out of range")
    return v + 0.0


@dataclass(frozen=True)
class Face:
    name: str
    normal: tuple[float, float, float]
    vertices: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class FloorSlab:
    op_id: str
    material_id: str | None
    role: str
    footprint: tuple[tuple[float, float], ...]   # counter-clockwise
    thickness: float
    elevation: float
    faces: tuple[Face, ...]
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    area: float
    volume: float


def _orient(a, b, c) -> Fraction:
    return (Fraction(b[0]) - Fraction(a[0])) * (Fraction(c[1]) - Fraction(a[1])) - \
           (Fraction(b[1]) - Fraction(a[1])) * (Fraction(c[0]) - Fraction(a[0]))


def _on_segment(a, b, p) -> bool:
    return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def _segments_touch(a, b, c, d) -> bool:
    """True if closed segments ab and cd share any point (exact arithmetic)."""
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if ((o1 > 0) != (o2 > 0) and o1 != 0 and o2 != 0) and ((o3 > 0) != (o4 > 0) and o3 != 0 and o4 != 0):
        return True
    return ((o1 == 0 and _on_segment(a, b, c)) or (o2 == 0 and _on_segment(a, b, d))
            or (o3 == 0 and _on_segment(c, d, a)) or (o4 == 0 and _on_segment(c, d, b)))


def _check_simple(pts: list[tuple[float, float]]) -> None:
    n = len(pts)
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        a, b = edges[i]
        _need(math.hypot(b[0] - a[0], b[1] - a[1]) >= MIN_EDGE, f"edge {i}: shorter than {MIN_EDGE} m")
    # consecutive edges (including the closing wraparound) share one vertex; a collinear
    # reversal there is a spike. Straight-through collinear vertices are fine at any index.
    for k in range(n):
        p, v, q = pts[k - 1], pts[k], pts[(k + 1) % n]
        if _orient(p, v, q) == 0:
            dot = (Fraction(v[0]) - Fraction(p[0])) * (Fraction(q[0]) - Fraction(v[0])) \
                + (Fraction(v[1]) - Fraction(p[1])) * (Fraction(q[1]) - Fraction(v[1]))
            _need(dot > 0, f"vertex {k}: edges fold back on each other")
    for i in range(n):
        a, b = edges[i]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # adjacent through the wraparound vertex, handled above
            c, d = edges[j]
            if (max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0])
                    or max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1])):
                continue
            _need(not _segments_touch(a, b, c, d), f"edges {i} and {j}: footprint self-intersects")


def _signed_area2(pts) -> Fraction:
    n = len(pts)
    return sum((Fraction(pts[i][0]) * Fraction(pts[(i + 1) % n][1])
                - Fraction(pts[(i + 1) % n][0]) * Fraction(pts[i][1]) for i in range(n)), Fraction(0))


def build_floor_slab(op: dict) -> FloorSlab:
    _need(isinstance(op, dict), "operation must be an object")
    _need(op.get("kind") == "floor-slab", "kind must be 'floor-slab'")
    _need(set(op) <= FIELDS, f"unknown field(s): {sorted(set(op) - FIELDS)}")
    for key in ("opId", "footprint", "thickness", "elevation"):
        _need(key in op, f"missing {key}")
    op_id = op["opId"]
    _need(isinstance(op_id, str) and len(op_id) <= 80 and ID_RE.match(op_id), f"invalid opId {op_id!r}")
    material = op.get("materialId")
    _need(material is None or (isinstance(material, str) and len(material) <= 80 and ID_RE.match(material)),
          f"invalid materialId {material!r}")
    role = op.get("role", "floor")
    _need(role in ROLES, f"invalid role {role!r}")
    thickness = _number(op["thickness"], "thickness")
    _need(0 < thickness <= MAX_THICKNESS, f"thickness must be in (0, {MAX_THICKNESS}] m")
    z0 = _number(op["elevation"], "elevation")
    z1 = z0 + thickness
    _need(abs(z1) <= MAX_ABS_VALUE, "top elevation out of range")

    raw = op["footprint"]
    _need(isinstance(raw, (list, tuple)) and 3 <= len(raw) <= MAX_VERTICES,
          f"footprint needs 3..{MAX_VERTICES} vertices")
    pts = []
    for i, p in enumerate(raw):
        _need(isinstance(p, (list, tuple)) and len(p) == 2, f"footprint[{i}]: expected [x, y]")
        pts.append((_number(p[0], f"footprint[{i}].x"), _number(p[1], f"footprint[{i}].y")))
    _check_simple(pts)
    area2 = _signed_area2(pts)
    _need(abs(area2) / 2 >= Fraction(MIN_AREA), "footprint area is zero or too small")
    if area2 < 0:  # normalise to CCW, keeping the first vertex first
        pts = [pts[0]] + pts[:0:-1]
    n = len(pts)

    top = tuple((x, y, z1) for x, y in pts)
    bottom = tuple((x, y, z0) for x, y in reversed(pts))
    faces = [Face("top", (0.0, 0.0, 1.0), top), Face("bottom", (0.0, 0.0, -1.0), bottom)]
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        length = math.hypot(x1 - x0, y1 - y0)
        normal = ((y1 - y0) / length + 0.0, -(x1 - x0) / length + 0.0, 0.0)
        faces.append(Face(f"side-{i}", normal, ((x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1))))

    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    area = float(abs(area2) / 2)
    return FloorSlab(op_id, material, role, tuple(pts), thickness, z0, tuple(faces),
                     ((min(xs), min(ys), z0), (max(xs), max(ys), z1)), area, area * thickness)
