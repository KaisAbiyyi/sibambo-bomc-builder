"""Deterministic, metre-based wall-run solids for Builder IR v1.

No binary BOMC encoding, opening cuts, or cross-module ownership occurs here.
"""
from __future__ import annotations

import math
import re

_EPS = 1e-9
_LIMIT = 1e6
_ID = re.compile(r"^[a-z][a-z0-9-]*$")


def _number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric metres")
    value = float(value)
    if abs(value) > _LIMIT or (positive and value <= _EPS):
        raise ValueError(f"{name} outside supported metre range")
    return value


def _point(raw, name):
    if not isinstance(raw, (tuple, list)) or len(raw) != 2:
        raise ValueError(f"{name} must be a 2D point")
    return (_number(raw[0], name + ".x"), _number(raw[1], name + ".y"))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, n):
    return (a[0] * n, a[1] * n)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _length(v):
    return math.hypot(*v)


def _on_segment(a, b, p):
    return (abs(_cross(_sub(b, a), _sub(p, a))) <= _EPS
            and min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS)


def _touches(a, b, c, d):
    ab = _sub(b, a)
    cd = _sub(d, c)
    o1, o2 = _cross(ab, _sub(c, a)), _cross(ab, _sub(d, a))
    o3, o4 = _cross(cd, _sub(a, c)), _cross(cd, _sub(b, c))
    if ((o1 > _EPS and o2 < -_EPS or o1 < -_EPS and o2 > _EPS)
            and (o3 > _EPS and o4 < -_EPS or o3 < -_EPS and o4 > _EPS)):
        return True
    return any((_on_segment(a, b, c), _on_segment(a, b, d),
                _on_segment(c, d, a), _on_segment(c, d, b)))


def _simple(poly):
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        if _length(_sub(poly[(i + 1) % n], poly[i])) <= _EPS:
            return False
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _touches(poly[i], poly[(i + 1) % n],
                        poly[j], poly[(j + 1) % n]):
                return False
    return True


def _parse(op):
    if not isinstance(op, dict) or op.get("kind") != "wall-run":
        raise ValueError("expected wall-run Module IR operation")
    op_id = op.get("opId")
    if not isinstance(op_id, str) or not _ID.fullmatch(op_id) or len(op_id) > 80:
        raise ValueError("invalid wall operation ID")
    raw_path = op.get("path")
    if not isinstance(raw_path, (tuple, list)) or not 2 <= len(raw_path) <= 1024:
        raise ValueError("wall path must contain 2..1024 points")
    path = [_point(v, f"path[{i}]") for i, v in enumerate(raw_path)]
    thickness = _number(op.get("thickness"), "thickness", positive=True)
    height = _number(op.get("height"), "height", positive=True)
    base = _number(op.get("baseElevation"), "baseElevation")
    if base + height > _LIMIT:
        raise ValueError("wall top elevation outside supported metre range")
    # A run is a non-self-intersecting open chain. Backtracking is never
    # silently repaired; same-direction collinearity is canonicalized.
    cleaned = [path[0]]
    for p in path[1:]:
        if _length(_sub(p, cleaned[-1])) <= _EPS:
            raise ValueError("wall path contains duplicate consecutive points")
        while len(cleaned) >= 2:
            prev = _sub(cleaned[-1], cleaned[-2])
            nxt = _sub(p, cleaned[-1])
            if abs(_cross(prev, nxt)) > _EPS:
                break
            if _dot(prev, nxt) <= 0:
                raise ValueError("wall path reverses along a collinear segment")
            cleaned.pop()
        cleaned.append(p)
    for i in range(len(cleaned) - 1):
        for j in range(i + 2, len(cleaned) - 1):
            if _touches(cleaned[i], cleaned[i + 1], cleaned[j], cleaned[j + 1]):
                raise ValueError("wall path intersects or touches itself")
    if cleaned[0] == cleaned[-1]:
        raise ValueError("closed paths are not supported by wall-run")
    return cleaned, thickness, height, base


def _miter(path, tangents, normals, half, side):
    rail = [_add(path[0], _mul(normals[0], side * half))]
    junctions = []
    for i in range(1, len(path) - 1):
        u, v = tangents[i - 1], tangents[i]
        a = _add(path[i], _mul(normals[i - 1], side * half))
        b = _add(path[i], _mul(normals[i], side * half))
        divisor = _cross(u, v)
        if abs(divisor) <= 1e-12:
            raise ValueError("near-parallel corner is numerically unstable")
        distance = _cross(_sub(b, a), v) / divisor
        corner = _add(a, _mul(u, distance))
        if not all(math.isfinite(x) and abs(x) <= _LIMIT for x in corner):
            raise ValueError("wall corner exceeds coordinate bounds")
        if _length(_sub(corner, path[i])) > 4 * half + _EPS:
            raise ValueError("wall corner requires excessive miter length")
        rail.append(corner)
        junctions.append(corner)
    rail.append(_add(path[-1], _mul(normals[-1], side * half)))
    return rail, junctions


def _signed_area(poly):
    return 0.5 * sum(_cross(poly[i], poly[(i + 1) % len(poly)])
                     for i in range(len(poly)))


def build_wall_run(op):
    """Extrude a single open centreline into one closed CCW-footprint wall solid.

    Returns metre coordinates, polygon faces with outward unit normals, bounds,
    volume, length, and miter junctions. No triangulation or openings.
    """
    path, thickness, height, base = _parse(op)
    vectors = [_sub(path[i + 1], path[i]) for i in range(len(path) - 1)]
    lengths = [_length(v) for v in vectors]
    tangents = [_mul(v, 1 / length) for v, length in zip(vectors, lengths)]
    normals = [(-u[1], u[0]) for u in tangents]
    half = thickness / 2
    if len(path) == 2:
        left = [_add(path[i], _mul(normals[0], half)) for i in (0, 1)]
        right = [_add(path[i], _mul(normals[0], -half)) for i in (0, 1)]
        corners = []
    else:
        left, lc = _miter(path, tangents, normals, half, +1)
        right, rc = _miter(path, tangents, normals, half, -1)
        corners = [{"centre": list(path[i + 1]), "left": list(lc[i]),
                    "right": list(rc[i]), "kind": "miter"}
                   for i in range(len(lc))]
    outline = right + list(reversed(left))
    if not _simple(outline):
        raise ValueError("wall thickness/joins yield self-intersecting footprint")
    area = _signed_area(outline)
    if not math.isfinite(area) or area <= _EPS:
        raise ValueError("wall footprint has invalid orientation or area")
    bottom = [[x, y, base] for x, y in outline]
    top = [[x, y, base + height] for x, y in outline]
    faces = [
        {"role": "bottom", "vertices": list(reversed(bottom)), "normal": [0.0, 0.0, -1.0]},
        {"role": "top", "vertices": top, "normal": [0.0, 0.0, 1.0]},
    ]
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        edge = _sub(outline[j], outline[i])
        edge_len = _length(edge)
        faces.append({"role": f"side-{i}",
                      "vertices": [bottom[i], bottom[j], top[j], top[i]],
                      "normal": [edge[1] / edge_len, -edge[0] / edge_len, 0.0]})
    return {
        "opId": op["opId"], "kind": "wall-solid",
        "path": [list(p) for p in path],
        "footprint": [list(p) for p in outline],
        "thickness": thickness, "height": height, "baseElevation": base,
        "length": sum(lengths), "footprintArea": area, "volume": area * height,
        "bounds": {"min": [min(p[0] for p in outline), min(p[1] for p in outline), base],
                   "max": [max(p[0] for p in outline), max(p[1] for p in outline), base + height]},
        "junctions": corners, "faces": faces,
    }


def join_wall_runs(operations, *, op_id="joined-wall"):
    """Merge a connected end-to-end open chain into ONE watertight solid.

    Inputs are order-independent. Exact shared endpoints and matching elevation,
    dimensions, and optional appearance are required. T/X branches, loops,
    crossings and multi-owner overlaps are rejected (BMB-011 owns seams).
    """
    if not isinstance(operations, (tuple, list)) or not 2 <= len(operations) <= 64:
        raise ValueError("join requires 2..64 wall-run operations")
    parsed = [_parse(op) for op in operations]
    ids = [op["opId"] for op in operations]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate source operation ID")
    first = operations[0]
    for op, (_, t, h, z) in zip(operations, parsed):
        if (t, h, z) != (parsed[0][1], parsed[0][2], parsed[0][3]):
            raise ValueError("joining walls must have identical thickness/height/elevation")
        if op.get("materialId") != first.get("materialId") or op.get("role") != first.get("role"):
            raise ValueError("joining walls must have identical material and semantic role")
    links = {}
    for index, (path, _, _, _) in enumerate(parsed):
        for endpoint in (path[0], path[-1]):
            links.setdefault(endpoint, []).append(index)
    if any(len(indices) > 2 for indices in links.values()):
        raise ValueError("branch junction requires separate seam/ownership validation")
    ends = sorted(p for p, indices in links.items() if len(indices) == 1)
    if len(ends) != 2:
        raise ValueError("walls must form a connected, open, nonbranching chain")
    current = ends[0]
    seen = set()
    joined = [current]
    ordered_ids = []
    while True:
        options = [i for i in links[current] if i not in seen]
        if not options:
            break
        if len(options) != 1:
            raise ValueError("ambiguous wall junction")
        i = options[0]
        path = parsed[i][0]
        if current == path[-1]:
            path = list(reversed(path))
        elif current != path[0]:
            raise ValueError("junction must match an exact endpoint")
        joined.extend(path[1:])
        seen.add(i)
        ordered_ids.append(operations[i]["opId"])
        current = path[-1]
    if len(seen) != len(operations) or current != ends[1]:
        raise ValueError("walls are disconnected or cyclic")
    combined = {"kind": "wall-run", "opId": op_id, "path": joined,
                "thickness": parsed[0][1], "height": parsed[0][2],
                "baseElevation": parsed[0][3]}
    solid = build_wall_run(combined)
    solid["sourceOpIds"] = ordered_ids
    return solid
