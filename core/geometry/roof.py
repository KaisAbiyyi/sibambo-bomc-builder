"""BMB-016: deterministic roof/ceiling shells and starter stair blocks.

All coordinates are module-local metres, +Z up. Geometry is polygonal
(not triangulated or encoded as BOMC). No boolean unions are claimed.
"""
from __future__ import annotations

import math
import re

from .floor import FloorError, build_floor_slab

_ID = re.compile(r"[a-z][a-z0-9-]*\Z")
_LIMIT = 1e4
_MIN = 1e-6
_FIELDS = {"kind", "opId", "footprint", "profile", "eaveElevation",
           "thickness", "rise", "ridgeAxis", "materialId"}
_STAIR_FIELDS = {"kind", "opId", "origin", "direction", "width",
                 "treadDepth", "riserHeight", "stepCount", "materialId"}


class RoofError(ValueError):
    """Malformed or unsupported roof, ceiling, or stair geometry."""


def _require(condition, detail):
    if not condition:
        raise RoofError(detail)


def _number(value, name, *, positive=False):
    _require(type(value) in (int, float), f"{name}: expected finite number")
    # Check integer magnitude before converting (very large ints raise OverflowError).
    _require(abs(value) <= _LIMIT, f"{name}: outside supported range")
    number = float(value)
    _require(math.isfinite(number) and (not positive or number >= _MIN),
             f"{name}: finite value of at least {_MIN} required")
    return number + 0.0


def _id(value, name):
    _require(isinstance(value, str) and len(value) <= 80 and _ID.fullmatch(value),
             f"{name}: invalid slug ID")
    return value


def _bounds(points):
    return {"min": [min(p[i] for p in points) for i in range(3)],
            "max": [max(p[i] for p in points) for i in range(3)]}


def _face(role, verts, outward):
    # Orient a planar face with its requested outward axis. Non-axial pitched
    # faces use +/-Z to disambiguate orientation. Newell is stable for concavity.
    vertices = [list(v) for v in verts]
    def area_normal():
        return [sum((a[(i + 1) % 3] - b[(i + 1) % 3]) *
                    (a[(i + 2) % 3] + b[(i + 2) % 3])
                    for a, b in zip(vertices, vertices[1:] + vertices[:1]))
                for i in range(3)]
    normal = area_normal()
    mag = math.sqrt(sum(v * v for v in normal))
    _require(mag > _MIN, f"{role}: degenerate face")
    if sum(n * o for n, o in zip(normal, outward)) < 0:
        vertices.reverse()
        normal = [-v for v in normal]
    _require(sum(n * o for n, o in zip(normal, outward)) > 0,
             f"{role}: invalid outward normal")
    return {"role": role, "vertices": vertices, "normal": [v / mag for v in normal]}


def _slab(op, *, role):
    try:
        slab = build_floor_slab({"kind": "floor-slab", "opId": op["opId"],
                                 "footprint": op["footprint"],
                                 "thickness": op["thickness"],
                                 "elevation": op["eaveElevation"],
                                 "role": role, "materialId": op.get("materialId")})
    except (FloorError, TypeError, KeyError) as exc:
        raise RoofError(f"invalid shell footprint or elevation: {exc}") from exc
    return {"opId": slab.op_id, "kind": role + "-shell", "profile": "flat",
            "materialId": slab.material_id, "footprint": [list(p) for p in slab.footprint],
            "eaveElevation": slab.elevation, "thickness": slab.thickness,
            "ridgeAxis": None, "rise": 0.0, "area": slab.area,
            "volume": slab.volume,
            "bounds": {"min": list(slab.bounds[0]), "max": list(slab.bounds[1])},
            "faces": [{"role": f.name, "vertices": [list(p) for p in f.vertices],
                       "normal": list(f.normal)} for f in slab.faces]}


def _rectangle(raw):
    _require(isinstance(raw, (tuple, list)) and len(raw) == 4,
             "gable footprint must have four rectangle corners")
    pts = []
    for i, point in enumerate(raw):
        _require(isinstance(point, (tuple, list)) and len(point) == 2,
                 f"footprint[{i}]: expected [x,y]")
        pts.append((_number(point[0], f"footprint[{i}].x"),
                    _number(point[1], f"footprint[{i}].y")))
    xs = sorted({p[0] for p in pts})
    ys = sorted({p[1] for p in pts})
    _require(len(xs) == 2 and len(ys) == 2 and
             xs[1] - xs[0] >= _MIN and ys[1] - ys[0] >= _MIN and
             set(pts) == {(x, y) for x in xs for y in ys},
             "gable footprint must be an axis-aligned nondegenerate rectangle")
    return xs, ys


def build_roof_shell(op):
    """Make a closed flat or symmetric gable shell with vertical thickness.

    Gables have two pitched top faces, two pitched bottom faces, eave
    fascias, and gable-end closure polygons. The ridge is shared, not capped.
    No wall clipping, dormers, overhangs, or triangular facets are fabricated.
    """
    _require(isinstance(op, dict), "roof operation must be an object")
    _require(op.get("kind") in ("roof-shell", "ceiling-shell"),
             "kind must be roof-shell or ceiling-shell")
    _require(set(op) <= _FIELDS, "unknown roof-shell fields")
    for field in ("opId", "footprint", "thickness", "eaveElevation"):
        _require(field in op, f"missing {field}")
    op_id = _id(op["opId"], "opId")
    material = op.get("materialId")
    if material is not None:
        _id(material, "materialId")
    ceiling = op["kind"] == "ceiling-shell"
    profile = op.get("profile", "flat")
    _require(profile in ("flat", "gable") and (not ceiling or profile == "flat"),
             "only flat ceiling or flat/gable roof supported")
    thickness = _number(op["thickness"], "thickness", positive=True)
    eave = _number(op["eaveElevation"], "eaveElevation")
    _require(thickness <= 100 and abs(eave + thickness) <= _LIMIT,
             "thickness or shell top out of range")
    rise = _number(op.get("rise", 0), "rise")
    axis = op.get("ridgeAxis")
    if profile == "flat":
        _require(rise == 0 and axis is None, "flat shell cannot have rise or ridgeAxis")
        return _slab(op, role="ceiling" if ceiling else "roof")
    _require(axis in ("x", "y"), "gable ridgeAxis must be 'x' or 'y'")
    _require(_MIN <= rise <= 100 and abs(eave + rise + thickness) <= _LIMIT,
             "gable rise or ridge outside supported range")

    xs, ys = _rectangle(op["footprint"])
    # t is the transverse axis, s runs along the ridge.
    cross_axis = 1 if axis == "x" else 0
    tmin, tmax = (ys if axis == "x" else xs)
    smin, smax = (xs if axis == "x" else ys)
    tvals = (tmin, (tmin + tmax) / 2, tmax)
    _require(tmin < tvals[1] < tmax, "ridge is unrepresentable at this precision")
    def point(t, s, high):
        z = eave + (rise if t == 1 else 0.0) + (thickness if high else 0.0)
        transverse, parallel = tvals[t], (smin if s == 0 else smax)
        if cross_axis == 0:
            return (transverse, parallel, z)
        return (parallel, transverse, z)

    faces = []
    for t in (0, 1):
        faces.append(_face(f"top-slope-{t}", [point(t, 0, True), point(t+1, 0, True),
                                            point(t+1, 1, True), point(t, 1, True)], (0, 0, 1)))
        faces.append(_face(f"underside-slope-{t}", [point(t, 0, False), point(t+1, 0, False),
                                                  point(t+1, 1, False), point(t, 1, False)], (0, 0, -1)))
    for t, sign in ((0, -1), (2, 1)):
        outward = (sign, 0, 0) if cross_axis == 0 else (0, sign, 0)
        faces.append(_face(f"eave-{t}", [point(t, 0, False), point(t, 1, False),
                                       point(t, 1, True), point(t, 0, True)], outward))
    for s, sign in ((0, -1), (1, 1)):
        outward = (0, sign, 0) if cross_axis == 0 else (sign, 0, 0)
        faces.append(_face(f"gable-end-{s}",
                           [point(t, s, False) for t in (0, 1, 2)] +
                           [point(t, s, True) for t in (2, 1, 0)], outward))
    vertices = [p for face in faces for p in face["vertices"]]
    area = (xs[1] - xs[0]) * (ys[1] - ys[0])
    return {"kind": "roof-shell", "opId": op_id, "materialId": material, "profile": "gable",
            "footprint": [[xs[0], ys[0]], [xs[1], ys[0]], [xs[1], ys[1]], [xs[0], ys[1]]],
            "eaveElevation": eave, "thickness": thickness,
            "ridgeAxis": axis, "rise": rise, "area": area,
            "volume": area * thickness, "bounds": _bounds(vertices), "faces": faces}


def build_ceiling_shell(op):
    """A flat closed ceiling solid. No implicit room/wall attachment."""
    _require(isinstance(op, dict) and op.get("kind") == "ceiling-shell",
             "kind must be ceiling-shell")
    return build_roof_shell(op)


def build_stair_flight(op):
    """Create non-overlapping, individually closed solid tread blocks.

    This is a bounded solid-step starter, not a monolithic staircase boolean
    union or handrail/riser construction. Every block has a shared base plane.
    """
    _require(isinstance(op, dict) and op.get("kind") == "stair-flight",
             "kind must be stair-flight")
    _require(set(op) <= _STAIR_FIELDS, "unknown stair-flight fields")
    _id(op.get("opId"), "opId")
    material = op.get("materialId")
    if material is not None:
        _id(material, "materialId")
    raw = op.get("origin")
    _require(isinstance(raw, (list, tuple)) and len(raw) == 3,
             "origin must be [x,y,z]")
    x, y, z = [_number(value, f"origin[{i}]") for i, value in enumerate(raw)]
    direction = op.get("direction")
    _require(direction in ("+x", "-x", "+y", "-y"), "unsupported stair direction")
    width = _number(op.get("width"), "width", positive=True)
    depth = _number(op.get("treadDepth"), "treadDepth", positive=True)
    riser = _number(op.get("riserHeight"), "riserHeight", positive=True)
    count = op.get("stepCount")
    _require(type(count) is int and 1 <= count <= 128, "stepCount must be 1..128")
    _require(count * depth <= 1000 and count * riser <= 100 and width <= 100,
             "stair dimensions exceed starter budget")
    dx, dy = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}[direction]
    parts = []
    for i in range(count):
        a, b = i * depth, (i + 1) * depth
        if dx:
            xa, xb = sorted((x + dx * a, x + dx * b))
            ya, yb = y, y + width
        else:
            ya, yb = sorted((y + dy * a, y + dy * b))
            xa, xb = x, x + width
        _require(all(abs(v) <= _LIMIT for v in (xa, xb, ya, yb, z + (i+1)*riser)),
                 "stair coordinates outside supported range")
        try:
            slab = build_floor_slab({"kind": "floor-slab", "opId": f"step-{i+1}",
                                     "footprint": [[xa, ya], [xb, ya], [xb, yb], [xa, yb]],
                                     "thickness": (i+1)*riser, "elevation": z,
                                     "role": "structural", "materialId": material})
        except FloorError as exc:
            raise RoofError(f"invalid stair step {i+1}: {exc}") from exc
        parts.append({"step": i+1, "topElevation": z+(i+1)*riser,
                      "bounds": {"min": list(slab.bounds[0]), "max": list(slab.bounds[1])},
                      "faces": [{"role": face.name,
                                 "vertices": [list(p) for p in face.vertices],
                                 "normal": list(face.normal)} for face in slab.faces]})
    vertices = [v for p in parts for face in p["faces"] for v in face["vertices"]]
    return {"kind": "stair-flight", "opId": op["opId"], "materialId": material,
            "origin": [x,y,z], "direction": direction, "width": width,
            "treadDepth": depth, "riserHeight": riser, "stepCount": count,
            "totalRun": depth*count, "totalRise": riser*count,
            "bounds": _bounds(vertices), "steps": parts}


def assert_no_aabb_overlap(a, b, *, tolerance=1e-7):
    """Conservative broad-phase collision rejection; touching is allowed.

    This can reject some geometrically disjoint sloped forms (false positives)
    and is NOT a substitute for BMB-012/017 narrow-phase intersection checks.
    """
    tol = _number(tolerance, "tolerance")
    _require(tol >= 0 and tol <= 0.01, "tolerance must be within [0, 0.01] m")
    for obj in (a, b):
        _require(isinstance(obj, dict) and isinstance(obj.get("bounds"), dict),
                 "expected geometry bounds")
        lo, hi = obj["bounds"].get("min"), obj["bounds"].get("max")
        _require(isinstance(lo, list) and isinstance(hi, list) and len(lo) == len(hi) == 3,
                 "bounds must contain min/max triples")
        for i in range(3):
            _number(lo[i], "bounds min")
            _number(hi[i], "bounds max")
            _require(hi[i] >= lo[i], "inverted bounds")
    overlap = all(min(a["bounds"]["max"][i], b["bounds"]["max"][i]) -
                  max(a["bounds"]["min"][i], b["bounds"]["min"][i]) > tol
                  for i in range(3))
    _require(not overlap, "potential volumetric collision (AABB broad phase)")
    return True


def check_roof_wall_junction(roof, wall, *, tolerance=1e-6):
    """Require a wall centreline to support one flat edge or gable eave.

    Gable-end walls under a pitched plane are NOT checked by this bounded
    contract; explicit shape clipping/face intersections belong downstream.
    """
    tol = _number(tolerance, "tolerance")
    _require(0 <= tol <= 0.01, "invalid tolerance")
    _require(isinstance(roof, dict) and roof.get("kind") == "roof-shell",
             "expected roof-shell")
    _require(isinstance(wall, dict) and wall.get("kind") == "wall-solid",
             "expected wall-solid")
    top = _number(wall["bounds"]["max"][2], "wall top")
    eave = _number(roof["eaveElevation"], "eaveElevation")
    _require(abs(top - eave) <= tol, "roof eave/wall top Z mismatch or collision")
    lo, hi = roof["bounds"]["min"], roof["bounds"]["max"]
    path = wall.get("path")
    _require(isinstance(path, list) and len(path) >= 2, "wall path missing")
    # For a gable, only the edges parallel to the ridge are constant-Z eaves.
    directions = (0, 1) if roof["profile"] == "flat" else ((1,) if roof["ridgeAxis"] == "x" else (0,))
    for transverse in directions:
        parallel = 1 - transverse
        for edge in (lo[transverse], hi[transverse]):
            if all(abs(p[transverse] - edge) <= tol and
                   lo[parallel] - tol <= p[parallel] <= hi[parallel] + tol
                   for p in path):
                _require(max(p[parallel] for p in path) - min(p[parallel] for p in path) > tol,
                         "zero-length roof/wall support")
                return True
    raise RoofError("wall centreline is not aligned with a supported roof eave")
