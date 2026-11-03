"""BMB-012: deterministic, non-mutating assembly validation with typed diagnostics.

Input is Module IR v1 modules or a BMB-011 Assembly. Metres throughout.
An invalid merge never turns into a partial geometry result. World-bounds
collision uses convex SAT for affine (including sheared/mirrored) module boxes;
it is NOT an exact operation-mesh or Boolean collision certification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from core.assembly import Assembly, AssemblyError, assemble
from core.graph import dag

DEFAULT_TOLERANCE_M = 0.001
MAX_DIAGNOSTICS = 512


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    module_id: str | None
    path: str
    message: str
    related_module_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity,
                "moduleId": self.module_id, "path": self.path,
                "message": self.message, "relatedModuleId": self.related_module_id}


@dataclass(frozen=True)
class ValidationReport:
    diagnostics: tuple[Diagnostic, ...]
    tolerance_m: float
    collision_model: str = "world-affine-module-bounds-SAT"

    @property
    def ok(self) -> bool:
        return not any(d.severity == "ERROR" for d in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "toleranceM": self.tolerance_m,
                "collisionModel": self.collision_model,
                "diagnostics": [d.to_dict() for d in self.diagnostics]}


def _finite(value: object) -> bool:
    return type(value) in (int, float) and abs(value) <= dag.MAX_ABS_VALUE


def _vec(value: object, size: int) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return None
    if not all(_finite(v) for v in value):
        return None
    return tuple(float(v) for v in value)


def _items(module: dict, key: str) -> list:
    value = module.get(key)
    return value if isinstance(value, list) else []


def _add(out: list[Diagnostic], code: str, mid: str | None, path: str,
         message: str, other: str | None = None) -> None:
    if len(out) < MAX_DIAGNOSTICS:
        out.append(Diagnostic(code, "ERROR", mid, path, message, other))


def _preflight(modules: object, out: list[Diagnostic], tol: float) -> None:
    """Recover actionable typed references/seams even if BMB-011 rejects input."""
    if not isinstance(modules, (list, tuple)) or len(modules) > 1024:
        return
    by_id: dict[str, dict] = {}
    for m in modules:
        if isinstance(m, dict) and isinstance(m.get("moduleId"), str):
            by_id.setdefault(m["moduleId"], m)
    ports: dict[tuple[str, str], dict] = {}
    owned: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for mid in sorted(by_id):
        module = by_id[mid]
        ops: dict[str, dict] = {}
        materials: set[str] = set()
        for mat in _items(module, "materials")[:256]:
            if not isinstance(mat, dict) or not isinstance(mat.get("materialId"), str):
                continue
            sid = mat["materialId"]
            if sid in materials:
                _add(out, "MATERIAL_DUPLICATE", mid, "materials", "duplicate material " + sid)
            materials.add(sid)
        for op in _items(module, "operations")[:10000]:
            if not isinstance(op, dict) or not isinstance(op.get("opId"), str):
                continue
            oid = op["opId"]
            if oid in ops:
                _add(out, "OPERATION_DUPLICATE", mid, "operations", "duplicate operation " + oid)
            ops[oid] = op
        for oid, op in sorted(ops.items()):
            path = "operations." + oid
            mat = op.get("materialId")
            if mat is not None and (not isinstance(mat, str) or mat not in materials):
                _add(out, "MATERIAL_MISSING", mid, path + ".materialId", "missing material reference")
            if op.get("kind") == "opening-cut":
                wall = op.get("targetWallOpId")
                if not isinstance(wall, str) or wall not in ops or ops[wall].get("kind") != "wall-run":
                    _add(out, "WALL_MISSING", mid, path + ".targetWallOpId",
                         "opening target must reference a wall-run in its module")
        for dep in _items(module, "dependencies")[:256]:
            if isinstance(dep, dict) and isinstance(dep.get("moduleId"), str):
                if dep["moduleId"] not in by_id:
                    _add(out, "DEPENDENCY_MISSING", mid, "dependencies", "missing dependency " + dep["moduleId"])
        for port in _items(module, "ports")[:256]:
            if isinstance(port, dict) and isinstance(port.get("portId"), str):
                pid = port["portId"]
                key = mid, pid
                if key in ports:
                    _add(out, "PORT_DUPLICATE", mid, "ports." + pid, "duplicate port identifier")
                ports[key] = port
                # The merge may reject mismatched peer frames before full
                # geometry validation: still return a typed local port error.
                bounds = module.get("bounds")
                lo = _vec(bounds.get("min"), 3) if isinstance(bounds, dict) else None
                hi = _vec(bounds.get("max"), 3) if isinstance(bounds, dict) else None
                frame = port.get("localTransform")
                if lo and hi and isinstance(frame, list) and len(frame) == 16 and all(_finite(v) for v in frame):
                    if any(not _inside(frame[3 + 4 * i], lo[i], hi[i], tol) for i in range(3)):
                        _add(out, "PORT_OUT_OF_BOUNDS", mid, "ports." + pid,
                             "port origin exceeds module-local bounds")
        for seam in _items(module, "ownedSeams")[:256]:
            if not isinstance(seam, dict) or not isinstance(seam.get("seamId"), str):
                continue
            sid = seam["seamId"]
            parts = seam.get("participants")
            scope = tuple(sorted(parts)) if isinstance(parts, list) and len(parts) == 2 and all(isinstance(p, str) for p in parts) else ()
            owned.setdefault((sid, scope), []).append(mid)
            if not isinstance(seam.get("surfaceOpId"), str) or seam["surfaceOpId"] not in ops:
                _add(out, "SEAM_SURFACE_MISSING", mid, "ownedSeams." + sid, "seam surface operation missing")
    pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for key, p in sorted(ports.items()):
        mid, pid = key
        peer, sid = p.get("peer"), p.get("seamId")
        if peer is None and sid is None:
            continue  # explicit exterior/unpaired port is legal
        if not isinstance(peer, dict) or not isinstance(peer.get("moduleId"), str) or not isinstance(peer.get("portId"), str):
            _add(out, "PORT_UNRESOLVED", mid, "ports." + pid, "port peer is missing or malformed")
            continue
        target = peer["moduleId"], peer["portId"]
        other = ports.get(target)
        if other is None:
            _add(out, "PORT_UNRESOLVED", mid, "ports." + pid, "peer port does not exist", target[0])
            continue
        if other.get("peer") != {"moduleId": mid, "portId": pid}:
            _add(out, "PORT_NOT_RECIPROCAL", mid, "ports." + pid, "peer does not point back", target[0])
            continue
        if sid is None or sid != other.get("seamId"):
            _add(out, "SEAM_UNRESOLVED", mid, "ports." + pid, "reciprocal ports lack a matching seamId", target[0])
            continue
        pairs.add(tuple(sorted((key, target))))
    for pair in sorted(pairs):
        sid = ports[pair[0]].get("seamId")
        if not isinstance(sid, str):
            continue
        members = {pair[0][0], pair[1][0]}
        owners = [m for m in owned.get((sid, tuple(sorted(members))), ()) if m in members]
        if len(owners) != 1:
            _add(out, "SEAM_UNRESOLVED", pair[0][0], "ports." + pair[0][1],
                 "reciprocal seam requires exactly one participant owner", pair[1][0])
    for (sid, _members), owners in sorted(owned.items()):
        if len(owners) > 1:
            _add(out, "SEAM_DUPLICATE_OWNER", sorted(owners)[0], "ownedSeams." + sid,
                 "seam is declared by multiple modules")


def _bounds(module: dict, mid: str, out: list[Diagnostic]) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    bounds = module.get("bounds")
    lo = _vec(bounds.get("min"), 3) if isinstance(bounds, dict) else None
    hi = _vec(bounds.get("max"), 3) if isinstance(bounds, dict) else None
    if lo is None or hi is None or any(a >= b for a, b in zip(lo, hi)):
        _add(out, "BOUNDS_INVALID", mid, "bounds", "bounds must contain finite min < max in all axes")
        return None
    return lo, hi


def _inside(value: float, low: float, high: float, tol: float) -> bool:
    return low - tol <= value <= high + tol


def _geometry(module: dict, mid: str, lo: tuple[float, ...], hi: tuple[float, ...],
              tol: float, out: list[Diagnostic]) -> None:
    ops = {o["opId"]: o for o in _items(module, "operations")
           if isinstance(o, dict) and isinstance(o.get("opId"), str)}
    for oid, op in sorted(ops.items()):
        kind = op.get("kind")
        path = "operations." + oid
        if kind in ("wall-run", "floor-slab"):
            key = "path" if kind == "wall-run" else "footprint"
            points = op.get(key)
            if not isinstance(points, list) or len(points) < (2 if kind == "wall-run" else 3) or len(points) > 4096 or any(_vec(p, 2) is None for p in points):
                _add(out, "GEOMETRY_INVALID", mid, path + "." + key, "invalid 2D polygon/polyline")
                continue
            for p in points:
                x, y = _vec(p, 2)
                if not _inside(x, lo[0], hi[0], tol) or not _inside(y, lo[1], hi[1], tol):
                    _add(out, "OPERATION_OUT_OF_BOUNDS", mid, path, "operation coordinates exceed module bounds")
                    break
            z = op.get("baseElevation" if kind == "wall-run" else "elevation")
            extent = op.get("height" if kind == "wall-run" else "thickness")
            if not _finite(z) or not _finite(extent) or extent <= 0:
                _add(out, "GEOMETRY_INVALID", mid, path, "invalid vertical extent")
            elif not (_inside(z, lo[2], hi[2], tol) and _inside(z + extent, lo[2], hi[2], tol)):
                _add(out, "OPERATION_OUT_OF_BOUNDS", mid, path, "vertical extent exceeds module bounds")
        elif kind == "opening-cut":
            wall = ops.get(op.get("targetWallOpId")) if isinstance(op.get("targetWallOpId"), str) else None
            if wall is None or wall.get("kind") != "wall-run":
                continue  # typed WALL_MISSING already supplied by preflight
            pts = wall.get("path")
            if not isinstance(pts, list) or len(pts) < 2 or any(_vec(p, 2) is None for p in pts):
                continue
            length = sum(math.dist(_vec(a, 2), _vec(b, 2)) for a, b in zip(pts, pts[1:]))
            offset, width = op.get("offset"), op.get("width")
            sill, height = op.get("sillHeight"), op.get("height")
            wh = wall.get("height")
            if not all(_finite(v) for v in (offset, width, sill, height, wh)) or width <= 0 or height <= 0:
                _add(out, "GEOMETRY_INVALID", mid, path, "invalid opening dimensions")
            elif offset < -tol or offset + width > length + tol or sill < -tol or sill + height > wh + tol:
                _add(out, "OPENING_OUT_OF_WALL", mid, path, "opening exceeds target wall span or height")
        else:
            _add(out, "OPERATION_UNSUPPORTED", mid, path, "unknown Module IR v1 operation")
    for port in _items(module, "ports"):
        if not isinstance(port, dict):
            continue
        frame = port.get("localTransform")
        if not isinstance(frame, list) or len(frame) != 16 or not all(_finite(x) for x in frame):
            continue  # merge catches malformed frame
        pos = frame[3], frame[7], frame[11]
        if any(not _inside(pos[i], lo[i], hi[i], tol) for i in range(3)):
            _add(out, "PORT_OUT_OF_BOUNDS", mid, "ports." + str(port.get("portId")),
                 "port origin exceeds module-local bounds")


def _world_box(matrix: tuple[float, ...], lo: tuple[float, ...], hi: tuple[float, ...]):
    origin = dag.apply_point(matrix, lo)
    edges = tuple(tuple(matrix[r * 4 + i] * (hi[i] - lo[i]) for r in range(3)) for i in range(3))
    corners = tuple(tuple(origin[r] + sum(edges[i][r] * bool(mask & (1 << i)) for i in range(3))
                          for r in range(3)) for mask in range(8))
    aabb = tuple((min(p[i] for p in corners), max(p[i] for p in corners)) for i in range(3))
    return corners, edges, aabb


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _overlap(box_a, box_b, tol: float) -> bool:
    """SAT for two general affine parallelepipeds, no AABB-only false positives."""
    ca, ea, aa = box_a
    cb, eb, ab = box_b
    if any(min(aa[i][1], ab[i][1]) - max(aa[i][0], ab[i][0]) <= tol for i in range(3)):
        return False
    axes = [_cross(ea[i], ea[j]) for i, j in ((0, 1), (1, 2), (2, 0))]
    axes += [_cross(eb[i], eb[j]) for i, j in ((0, 1), (1, 2), (2, 0))]
    axes += [_cross(a, b) for a in ea for b in eb]
    for axis in axes:
        norm = math.hypot(*axis)
        if norm <= 1e-12:
            continue  # parallel edges yield a zero cross-product
        n = tuple(x / norm for x in axis)
        pa = [sum(x * y for x, y in zip(p, n)) for p in ca]
        pb = [sum(x * y for x, y in zip(p, n)) for p in cb]
        if min(max(pa), max(pb)) - max(min(pa), min(pb)) <= tol:
            return False
    return True


def validate_assembly(source: Assembly | list[dict] | tuple[dict, ...],
                      *, tolerance_m: float = DEFAULT_TOLERANCE_M) -> ValidationReport:
    """Collect stable, module-scoped errors without mutating the source.

    BMB-011 merge prerequisites must hold; if they do not, typed preflight
    diagnostics are returned and geometry/collision checks are not attempted.
    """
    out: list[Diagnostic] = []
    if not _finite(tolerance_m) or not 0 < tolerance_m <= 0.1:
        _add(out, "CONFIG_INVALID", None, "tolerance_m", "tolerance must be in (0, 0.1] metres")
        return ValidationReport(tuple(out), DEFAULT_TOLERANCE_M)
    tol = float(tolerance_m)
    modules = list(source.modules.values()) if isinstance(source, Assembly) else source
    _preflight(modules, out, tol)
    try:
        assembly = assemble(modules)
    except AssemblyError as exc:
        message = str(exc)
        mid = next((m.get("moduleId") for m in modules if isinstance(m, dict)
                    and isinstance(m.get("moduleId"), str) and m["moduleId"] in message),
                   None) if isinstance(modules, (list, tuple)) else None
        _add(out, "ASSEMBLY_INVALID", mid, "assembly", message)
        return _report(out, tol)
    boxes: dict[str, tuple] = {}
    for mid, module in sorted(assembly.modules.items()):
        bounds = _bounds(module, mid, out)
        if bounds is None:
            continue
        lo, hi = bounds
        _geometry(module, mid, lo, hi, tol, out)
        if _items(module, "operations"):  # empty container/group frames are not solids
            boxes[mid] = _world_box(assembly.world_transforms[mid], lo, hi)
    # Sorted order + module-scoped pairing makes result independent of input order.
    for a, b in combinations(sorted(boxes), 2):
        if _overlap(boxes[a], boxes[b], tol):
            _add(out, "MODULE_BOUNDS_COLLISION", a, "bounds",
                 "module volume bounds overlap beyond tolerance (not an exact mesh collision)", b)
    return _report(out, tol)


def _report(out: list[Diagnostic], tol: float) -> ValidationReport:
    distinct = {(d.code, d.severity, d.module_id, d.path, d.message, d.related_module_id): d for d in out}
    values = sorted(distinct.values(), key=lambda d: (d.module_id or "", d.path, d.code,
                                                       d.related_module_id or "", d.message))
    return ValidationReport(tuple(values), tol)
