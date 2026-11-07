"""The rooms a Module IR intends: one per floor slab, placed in the assembly frame.

A floor slab's walkable surface is its top (elevation + thickness) transformed by the module's world transform; only slabs
whose surface lies within `level_tolerance` of the evidence's elevation are compared. Floors are assumed horizontal: a
tilted slab is reported and skipped, never guessed at.
"""
from __future__ import annotations

from core.assembly import assemble
from core.geometry.triangulation import TriangulationError
from integration.rooms.geometry import bbox, shoelace, triangles

HORIZONTAL_TOL_M = 0.01


def _place(m: tuple, x: float, y: float, z: float) -> tuple[float, float, float]:
    return (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11])


def intended_rooms(modules: list, *, elevation_m: float, level_tolerance: float) -> tuple[list, list]:
    """(rooms, skipped). `rooms` items: id, moduleId, opId, polygon, area, tris, box. `skipped` items: id, reason."""
    asm = assemble(modules)
    found, skipped = [], []
    for mid in sorted(asm.modules):
        slabs = [op for op in asm.modules[mid]["operations"] if op.get("kind") == "floor-slab"]
        placed = []
        for op in slabs:
            top = op["elevation"] + op["thickness"]
            points = [_place(asm.world_transforms[mid], p[0], p[1], top) for p in op["footprint"]]
            zs = [p[2] for p in points]
            label = mid if len(slabs) == 1 else f"{mid}#{op['opId']}"
            if max(zs) - min(zs) > HORIZONTAL_TOL_M:
                skipped.append({"id": label, "reason": "floor is not horizontal in the assembly frame"})
                continue
            if abs(sum(zs) / len(zs) - elevation_m) > level_tolerance:
                continue                                                    # another level: not part of this comparison
            xy = [(p[0], p[1]) for p in points]
            try:
                tris = triangles(xy)
            except TriangulationError as exc:
                skipped.append({"id": label, "reason": f"floor footprint is not usable ({exc})"})
                continue
            placed.append({"id": label, "moduleId": mid, "opId": op["opId"], "polygon": xy, "area": shoelace(xy),
                           "tris": tris, "box": bbox(xy)})
        found.extend(placed)
    return found, skipped
