"""BMB-017: bounded, dependency-free triangulation of planar faces with holes.

The vertical-slab decomposition handles concave rings and multiple disjoint holes
without bridging a hole through the outside.  All geometric predicates, sweep
intersections and area accounting use exact rationals of the supplied finite
float coordinates.  The public result is non-indexed, outward-wound 3D triangles.

This is a non-indexed conforming triangulation: sweep-boundary edges are split
at all incident vertices to eliminate T-junctions. Indexed solid/manifold
interoperability still requires downstream mesh-level verification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import NamedTuple

MAX_VERTICES = 1024
MAX_HOLES = 64
MAX_TRIANGLES = 20000
MAX_COORD = 1e4
MIN_EDGE = 1e-6
MIN_AREA = 1e-6
PLANE_TOLERANCE = 1e-7


class TriangulationError(ValueError):
    """Invalid, unsupported or numerically unsafe triangulation input."""


@dataclass(frozen=True)
class Triangle:
    vertices: tuple[tuple[float, float, float], ...]
    normal: tuple[float, float, float]


class _Point(NamedTuple):
    uv: tuple[Fraction, Fraction]
    xyz: tuple[Fraction, Fraction, Fraction]


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise TriangulationError(message)


def _vec3(raw: object, name: str) -> tuple[float, float, float]:
    _require(isinstance(raw, (tuple, list)) and len(raw) == 3,
             f"{name}: expected 3 coordinates")
    out = []
    for i, value in enumerate(raw):
        _require(type(value) in (int, float), f"{name}[{i}]: expected real number")
        # Guard very large Python integers before float() can throw OverflowError.
        _require(abs(value) <= MAX_COORD, f"{name}[{i}]: out of range")
        number = float(value)
        _require(math.isfinite(number), f"{name}[{i}]: must be finite")
        out.append(number + 0.0)
    return tuple(out)  # type: ignore[return-value]


def _normal(raw: object) -> tuple[tuple[float, float, float], int, tuple[int, int]]:
    _require(isinstance(raw, (tuple, list)) and len(raw) == 3,
             "normal: expected 3 coordinates")
    vals = []
    for value in raw:
        _require(type(value) in (int, float) and abs(value) <= 1e6,
                 "normal: invalid component")
        vals.append(float(value))
    _require(all(math.isfinite(x) for x in vals), "normal: must be finite")
    length = math.hypot(*vals)
    _require(length > 0, "normal: must be nonzero")
    n = tuple(x / length for x in vals)
    # Axis order chosen so uv-positive cross product points along +dominant axis.
    dominant = max(range(3), key=lambda axis: abs(n[axis]))
    axes = ((1, 2), (2, 0), (0, 1))[dominant]
    return n, dominant, axes


def _orient(a: _Point, b: _Point, c: _Point) -> Fraction:
    return ((b.uv[0] - a.uv[0]) * (c.uv[1] - a.uv[1])
            - (b.uv[1] - a.uv[1]) * (c.uv[0] - a.uv[0]))


def _area2(ring: tuple[_Point, ...]) -> Fraction:
    return sum((ring[i].uv[0] * ring[(i + 1) % len(ring)].uv[1]
                - ring[i].uv[1] * ring[(i + 1) % len(ring)].uv[0]
                for i in range(len(ring))), Fraction(0))


def _on_segment(a: _Point, b: _Point, p: _Point) -> bool:
    return (min(a.uv[0], b.uv[0]) <= p.uv[0] <= max(a.uv[0], b.uv[0])
            and min(a.uv[1], b.uv[1]) <= p.uv[1] <= max(a.uv[1], b.uv[1]))


def _touch(a: _Point, b: _Point, c: _Point, d: _Point) -> bool:
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if ((o1 > 0 > o2 or o2 > 0 > o1)
            and (o3 > 0 > o4 or o4 > 0 > o3)):
        return True
    return ((o1 == 0 and _on_segment(a, b, c))
            or (o2 == 0 and _on_segment(a, b, d))
            or (o3 == 0 and _on_segment(c, d, a))
            or (o4 == 0 and _on_segment(c, d, b)))


def _edges(ring: tuple[_Point, ...]):
    return tuple((ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))


def _simple(ring: tuple[_Point, ...], name: str) -> Fraction:
    edges = _edges(ring)
    for i, (a, b) in enumerate(edges):
        dx, dy = b.uv[0] - a.uv[0], b.uv[1] - a.uv[1]
        _require(math.hypot(float(dx), float(dy)) >= MIN_EDGE,
                 f"{name}: edge {i} is too short")
    for k in range(len(ring)):
        a, b, c = ring[k - 1], ring[k], ring[(k + 1) % len(ring)]
        if _orient(a, b, c) == 0:
            dot = ((b.uv[0] - a.uv[0]) * (c.uv[0] - b.uv[0])
                   + (b.uv[1] - a.uv[1]) * (c.uv[1] - b.uv[1]))
            _require(dot > 0, f"{name}: vertex {k} folds back")
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, len(edges)):
            if i == 0 and j == len(edges) - 1:
                continue
            c, d = edges[j]
            if (max(a.uv[0], b.uv[0]) < min(c.uv[0], d.uv[0])
                    or max(c.uv[0], d.uv[0]) < min(a.uv[0], b.uv[0])
                    or max(a.uv[1], b.uv[1]) < min(c.uv[1], d.uv[1])
                    or max(c.uv[1], d.uv[1]) < min(a.uv[1], b.uv[1])):
                continue
            _require(not _touch(a, b, c, d), f"{name}: self-intersection at edges {i},{j}")
    area = abs(_area2(ring)) / 2
    _require(area >= Fraction(MIN_AREA), f"{name}: zero or too-small area")
    return area


def _inside(p: _Point, ring: tuple[_Point, ...]) -> bool:
    """Strict even-odd containment; boundary is never inside."""
    inside = False
    x, y = p.uv
    for a, b in _edges(ring):
        if _orient(a, b, p) == 0 and _on_segment(a, b, p):
            return False
        ay, by = a.uv[1], b.uv[1]
        if (ay > y) != (by > y):
            ix = a.uv[0] + (y - ay) * (b.uv[0] - a.uv[0]) / (by - ay)
            if ix > x:
                inside = not inside
    return inside


def _ring(raw, name: str, axes, anchor, normal) -> tuple[_Point, ...]:
    _require(isinstance(raw, (tuple, list)) and 3 <= len(raw) <= MAX_VERTICES,
             f"{name}: expected 3..{MAX_VERTICES} vertices")
    out = []
    for i, value in enumerate(raw):
        xyz = _vec3(value, f"{name}[{i}]")
        delta = sum((xyz[k] - anchor[k]) * normal[k] for k in range(3))
        _require(abs(delta) <= PLANE_TOLERANCE,
                 f"{name}[{i}]: not on the face plane")
        out.append(_Point((Fraction(xyz[axes[0]]), Fraction(xyz[axes[1]])),
                          tuple(Fraction(v) for v in xyz)))
    return tuple(out)


def _intersection(a: _Point, b: _Point, x: Fraction) -> _Point:
    t = (x - a.uv[0]) / (b.uv[0] - a.uv[0])
    return _Point((x, a.uv[1] + t * (b.uv[1] - a.uv[1])),
                  tuple(a.xyz[k] + t * (b.xyz[k] - a.xyz[k]) for k in range(3)))


def triangulate_face(vertices, *, holes=(), normal=(0.0, 0.0, 1.0)) -> tuple[Triangle, ...]:
    """Triangulate a 3D planar face, including strictly internal disjoint holes.

    Winding of every input ring may be CW or CCW. Returned triangles are always
    wound toward the supplied outward normal; each has that unit normal. All
    coordinates use module-local metres. Holes may not touch each other or the
    outer boundary, overlap, or nest. Neither the IR nor its existing builders
    currently store holes: callers must explicitly provide their hole loops.
    """
    n, dominant, axes = _normal(normal)
    _require(isinstance(vertices, (tuple, list)) and len(vertices) >= 3,
             "outer: expected at least 3 vertices")
    anchor = _vec3(vertices[0], "outer[0]")
    outer = _ring(vertices, "outer", axes, anchor, n)
    _require(isinstance(holes, (tuple, list)) and len(holes) <= MAX_HOLES,
             f"holes: expected at most {MAX_HOLES} rings")
    rings = (outer,) + tuple(_ring(h, f"hole[{i}]", axes, anchor, n)
                             for i, h in enumerate(holes))
    _require(sum(len(r) for r in rings) <= MAX_VERTICES,
             f"total vertices exceed {MAX_VERTICES}")
    areas = [_simple(r, "outer" if i == 0 else f"hole[{i - 1}]")
             for i, r in enumerate(rings)]
    for i, hole in enumerate(rings[1:]):
        _require(_inside(hole[0], outer), f"hole[{i}]: outside outer ring")
        for j, other in enumerate(rings):
            if i + 1 == j:
                continue
            if j > 0:
                _require(not _inside(hole[0], other)
                         and not _inside(other[0], hole),
                         f"hole[{i}]: nested or overlapping hole[{j - 1}]")
            for a, b in _edges(hole):
                for c, d in _edges(other):
                    _require(not _touch(a, b, c, d),
                             f"hole[{i}]: touches/intersects another ring")
    expected = areas[0] - sum(areas[1:], Fraction(0))
    _require(expected >= Fraction(MIN_AREA), "face area is zero or too small")

    coords = sorted({p.uv[0] for ring in rings for p in ring})
    nonvertical = [(a, b) for ring in rings for a, b in _edges(ring)
                   if a.uv[0] != b.uv[0]]
    cells: list[tuple[_Point, _Point, _Point]] = []
    accounted = Fraction(0)
    for left, right in zip(coords, coords[1:]):
        mid = (left + right) / 2
        hits = []
        for a, b in nonvertical:
            if min(a.uv[0], b.uv[0]) < mid < max(a.uv[0], b.uv[0]):
                hits.append((_intersection(a, b, mid).uv[1], a, b))
        hits.sort(key=lambda hit: hit[0])
        _require(len(hits) % 2 == 0, "odd number of face-boundary intersections")
        for i in range(0, len(hits), 2):
            low, high = hits[i], hits[i + 1]
            _require(low[0] < high[0], "overlapping/collapsed boundary")
            p0 = _intersection(low[1], low[2], left)
            p1 = _intersection(low[1], low[2], right)
            p2 = _intersection(high[1], high[2], right)
            p3 = _intersection(high[1], high[2], left)
            for p, q, r in ((p0, p1, p2), (p0, p2, p3)):
                twice = _orient(p, q, r)
                _require(twice >= 0, "non-monotone sweep cell")
                if twice == 0:
                    continue  # triangular cell at a polygon vertex
                accounted += twice / 2
                if n[dominant] < 0:
                    q, r = r, q
                cells.append((p, q, r))
                _require(len(cells) <= MAX_TRIANGLES,
                         f"triangle budget exceeds {MAX_TRIANGLES}")
    _require(accounted == expected, "triangulated area does not match outer minus holes")
    _require(bool(cells), "no nonzero triangles")

    # Independent sweep strips can otherwise form T-junctions along the
    # vertical strip border (notably at a hole's leftmost/rightmost vertex).
    # Every border is split at *all* vertex heights on that line. Since any
    # nondegenerate sweep triangle has at most one vertical edge, a simple
    # fan from its opposite vertex partitions it into conforming subtriangles.
    border_points: dict[Fraction, dict[Fraction, _Point]] = {}
    for tri in cells:
        for p in tri:
            column = border_points.setdefault(p.uv[0], {})
            previous = column.setdefault(p.uv[1], p)
            _require(all(abs(float(previous.xyz[k] - p.xyz[k])) <= PLANE_TOLERANCE
                         for k in range(3)), "inconsistent coincident vertex")

    conforming = []
    for tri in cells:
        for edge in range(3):
            a, b, opposite = tri[edge], tri[(edge + 1) % 3], tri[(edge + 2) % 3]
            if a.uv[0] != b.uv[0]:
                continue
            lo, hi = sorted((a.uv[1], b.uv[1]))
            middles = [p for y, p in border_points[a.uv[0]].items() if lo < y < hi]
            middles.sort(key=lambda p: p.uv[1], reverse=a.uv[1] > b.uv[1])
            chain = [a, *middles, b]
            conforming.extend((chain[i], chain[i + 1], opposite)
                              for i in range(len(chain) - 1))
            break
        else:
            conforming.append(tri)
        _require(len(conforming) <= MAX_TRIANGLES,
                 f"conforming triangle budget exceeds {MAX_TRIANGLES}")

    triangles = []
    for tri in conforming:
        xyz = tuple(tuple(float(v) + 0.0 for v in pt.xyz) for pt in tri)
        u, v, w = xyz
        av = tuple(v[k] - u[k] for k in range(3))
        bv = tuple(w[k] - u[k] for k in range(3))
        cross = (av[1] * bv[2] - av[2] * bv[1],
                 av[2] * bv[0] - av[0] * bv[2],
                 av[0] * bv[1] - av[1] * bv[0])
        _require(sum(cross[k] * n[k] for k in range(3)) > 0,
                 "triangle collapsed on float conversion")
        triangles.append(Triangle(xyz, n))
    return tuple(triangles)
