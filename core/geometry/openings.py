"""BMB-015: topology-true, bounded rectangular cutouts on straight wall runs.

The returned wall is an oriented quad shell with *no wall faces or volume* inside
openings. Inserts are separate geometry; they never substitute for cutting.
Bent/branched walls and BOMC triangulation are deliberately out of scope.
"""
from __future__ import annotations

import math

from .wall import _EPS, _ID, _number, build_wall_run

_MAX_OPENINGS = 16
_MAX_GRID_CELLS = 2048


def _face(corners, normal, role, point):
    return {"role": role, "vertices": [point(*p) for p in corners],
            "normal": list(normal)}


def _box(x0, x1, y0, y1, z0, z1, role, point, tangent, left):
    """Six outward-oriented faces for one insert component, in wall-local axes."""
    if min(x1 - x0, y1 - y0, z1 - z0) <= _EPS:
        raise ValueError("insert component has degenerate dimensions")
    faces = [
        _face([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
              (-left[0], -left[1], 0), role + "-front", point),
        _face([(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
              (left[0], left[1], 0), role + "-back", point),
        _face([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
              (-tangent[0], -tangent[1], 0), role + "-start", point),
        _face([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
              (tangent[0], tangent[1], 0), role + "-end", point),
        _face([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
              (0, 0, -1), role + "-bottom", point),
        _face([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
              (0, 0, 1), role + "-top", point),
    ]
    corners = [point(x, y, z) for x in (x0, x1) for y in (y0, y1)
               for z in (z0, z1)]
    return {"role": role, "bounds": {
        "min": [min(c[i] for c in corners) for i in range(3)],
        "max": [max(c[i] for c in corners) for i in range(3)]},
        "faces": faces}


def _opening(raw, wall_id, length, base, top):
    if not isinstance(raw, dict) or raw.get("kind") != "opening-cut":
        raise ValueError("expected opening-cut Module IR operation")
    oid = raw.get("opId")
    if not isinstance(oid, str) or len(oid) > 80 or not _ID.fullmatch(oid):
        raise ValueError("invalid opening operation ID")
    if raw.get("targetWallOpId") != wall_id:
        raise ValueError("opening targetWallOpId does not match wall")
    kind = raw.get("openingType")
    if kind not in ("door", "window"):
        raise ValueError("openingType must be door or window")
    start = _number(raw.get("offset"), "offset")
    width = _number(raw.get("width"), "width", positive=True)
    height = _number(raw.get("height"), "height", positive=True)
    sill = _number(raw.get("sillHeight"), "sillHeight")
    if (start <= _EPS or start + width >= length - _EPS
            or sill < 0 or base + sill + height >= top - _EPS):
        raise ValueError("opening must have positive side piers and head")
    if kind == "door" and abs(sill) > _EPS:
        raise ValueError("door must meet wall base without a blocking threshold")
    if kind == "window" and sill <= _EPS:
        raise ValueError("window must retain a positive sill wall")
    return {"opId": oid, "openingType": kind, "start": start,
            "end": start + width, "bottom": base + sill,
            "top": base + sill + height, "width": width,
            "height": height, "sillHeight": sill}


def build_wall_with_openings(wall_op, opening_ops, *, minimum_door_clearance=0.70):
    """Cut actual voids and provide separate door/window insert solids.

    Straight centreline runs only. Geometry is in right-handed metres/+Z.
    The wall is a conforming quad mesh, watertight around any supported void.
    No triangulation, arbitrary boolean, or native consumer parity is implied.
    """
    wall = build_wall_run(wall_op)  # Reuse BMB-014 validation unchanged.
    if len(wall["path"]) != 2:
        raise ValueError("cutouts on bent wall-runs require future segment-aware topology")
    if not isinstance(opening_ops, (tuple, list)) or not 1 <= len(opening_ops) <= _MAX_OPENINGS:
        raise ValueError("opening count must be between 1 and 16")
    minimum = _number(minimum_door_clearance, "minimum_door_clearance", positive=True)
    start_point, end_point = wall["path"]
    length = wall["length"]
    tx = (end_point[0] - start_point[0]) / length
    ty = (end_point[1] - start_point[1]) / length
    tangent, left = (tx, ty), (-ty, tx)
    half = wall["thickness"] / 2
    base = wall["baseElevation"]
    top = base + wall["height"]

    def point(x, y, z):
        return [start_point[0] + tx * x - ty * y,
                start_point[1] + ty * x + tx * y, z]

    openings = [_opening(op, wall["opId"], length, base, top) for op in opening_ops]
    ids = [o["opId"] for o in openings]
    if len(set(ids)) != len(ids) or wall["opId"] in ids:
        raise ValueError("duplicate wall/opening operation IDs")
    openings.sort(key=lambda o: (o["start"], o["bottom"], o["opId"]))
    for i, a in enumerate(openings):
        for b in openings[i + 1:]:
            if (a["start"] <= b["end"] + _EPS and b["start"] <= a["end"] + _EPS
                    and a["bottom"] <= b["top"] + _EPS
                    and b["bottom"] <= a["top"] + _EPS):
                raise ValueError("opening cuts must not intersect or touch")

    xcuts = sorted({0.0, length, *(v for o in openings for v in (o["start"], o["end"]))})
    zcuts = sorted({base, top, *(v for o in openings for v in (o["bottom"], o["top"]))})
    if (len(xcuts) - 1) * (len(zcuts) - 1) > _MAX_GRID_CELLS:
        raise ValueError("too many opening topology cells")
    for cuts in (xcuts, zcuts):
        if any(b - a <= _EPS for a, b in zip(cuts, cuts[1:])):
            raise ValueError("sub-tolerance opening topology interval")
    occupied = [[not any(o["start"] <= xcuts[i] + _EPS
                         and xcuts[i + 1] <= o["end"] + _EPS
                         and o["bottom"] <= zcuts[j] + _EPS
                         and zcuts[j + 1] <= o["top"] + _EPS
                         for o in openings)
                 for j in range(len(zcuts) - 1)]
                for i in range(len(xcuts) - 1)]
    faces = []
    volume = 0.0
    for i in range(len(xcuts) - 1):
        x0, x1 = xcuts[i:i + 2]
        for j in range(len(zcuts) - 1):
            if not occupied[i][j]:
                continue
            z0, z1 = zcuts[j:j + 2]
            volume += (x1 - x0) * (z1 - z0) * wall["thickness"]
            # Front/back conforming quads; no face spans a missing cell.
            faces.append(_face([(x0, -half, z0), (x1, -half, z0),
                                (x1, -half, z1), (x0, -half, z1)],
                               (-left[0], -left[1], 0), "wall-front", point))
            faces.append(_face([(x0, half, z0), (x0, half, z1),
                                (x1, half, z1), (x1, half, z0)],
                               (left[0], left[1], 0), "wall-back", point))
            if i == 0 or not occupied[i - 1][j]:
                faces.append(_face([(x0, -half, z0), (x0, -half, z1),
                                    (x0, half, z1), (x0, half, z0)],
                                   (-tx, -ty, 0), "wall-start-or-jamb", point))
            if i == len(xcuts) - 2 or not occupied[i + 1][j]:
                faces.append(_face([(x1, -half, z0), (x1, half, z0),
                                    (x1, half, z1), (x1, -half, z1)],
                                   (tx, ty, 0), "wall-end-or-jamb", point))
            if j == 0 or not occupied[i][j - 1]:
                faces.append(_face([(x0, -half, z0), (x0, half, z0),
                                    (x1, half, z0), (x1, -half, z0)],
                                   (0, 0, -1), "wall-base-or-lintel", point))
            if j == len(zcuts) - 2 or not occupied[i][j + 1]:
                faces.append(_face([(x0, -half, z1), (x1, -half, z1),
                                    (x1, half, z1), (x0, half, z1)],
                                   (0, 0, 1), "wall-top-or-sill", point))

    inserts = []
    clearance = []
    for o in openings:
        a, b, low, high = (o[k] for k in ("start", "end", "bottom", "top"))
        fw = min(0.045, o["width"] / 12, o["height"] / 12, half / 2)
        y0, y1 = -half, half
        parts = [
            _box(a, a + fw, y0, y1, low, high, "frame-left", point, tangent, left),
            _box(b - fw, b, y0, y1, low, high, "frame-right", point, tangent, left),
            _box(a + fw, b - fw, y0, y1, high - fw, high,
                 "frame-head", point, tangent, left),
        ]
        if o["openingType"] == "window":
            parts.append(_box(a + fw, b - fw, y0, y1, low, low + fw,
                              "frame-sill", point, tangent, left))
            glass_half = min(0.004, half / 6)
            parts.append(_box(a + fw, b - fw, -glass_half, glass_half,
                              low + fw, high - fw,
                              "window-glazing", point, tangent, left))
        else:
            leaf_thickness = min(0.035, fw * 0.75)
            clear_width = o["width"] - 2 * fw - leaf_thickness
            clear_height = o["height"] - fw
            if clear_width + _EPS < minimum or clear_height + _EPS < 1.90:
                raise ValueError("door opening does not meet clear width/height")
            # Door leaf held open 90 degrees, outside the wall-depth passage.
            # The central clear route crosses the entire wall thickness.
            parts.append(_box(a + fw, a + fw + leaf_thickness,
                              -half - (o["width"] - 2 * fw), -half - 0.01,
                              low, high - fw, "door-leaf-open",
                              point, tangent, left))
            clearance.append({"opId": o["opId"], "width": clear_width,
                              "height": clear_height,
                              "localPassage": {"x": [a + fw + leaf_thickness, b - fw],
                                               "y": [-half, half],
                                               "z": [low, high - fw]}})
        inserts.append({"opId": o["opId"], "kind": o["openingType"] + "-insert",
                        "targetWallOpId": wall["opId"], "parts": parts})

    wall["faces"] = faces
    wall["volume"] = volume
    wall["openings"] = openings
    wall["topology"] = "conforming-quad-voids"
    return {"wall": wall, "inserts": inserts, "doorwayClearance": clearance}
