"""Pure shared canonical face/triangle projection (SE-01).

The BOMC compiler and the live render projection both consume this single
intermediate. There is exactly one triangulator (core.geometry.triangulation)
and one face-shaping routine; nothing here emits bytes. Extracted verbatim from
bomc.compiler.semantic_v12 so compiled bytes for the pinned corpus are unchanged.
"""
from __future__ import annotations

import math

from core.geometry.floor import build_floor_slab
from core.geometry.wall import build_wall_run
from core.geometry.openings import build_wall_with_openings
from core.geometry.triangulation import triangulate_face
from core.geometry.semantics import validate_module_faces

MAX_FACES = 4096
MAX_VERTICES = 8192
MAX_TRIANGLES = 20000
MAX_MATERIALS = 254
MAX_STRINGS = 254
MAX_SOURCE_OPERATIONS = 128

SURFACES = {"wall": 1, "floor": 2, "ceiling": 3, "roof": 4,
            "opening": 7, "window": 8, "door": 9}
ROLES = {"wall": 1, "floor": 2, "ceiling": 3, "roof": 4,
         "opening": 5, "window": 6, "door": 7}


class GeometryEncodingError(ValueError):
    """The input is not a safe, representable BOMC 1.2 geometry profile."""


def _require(ok, message):
    if not ok:
        raise GeometryEncodingError(message)


def _scalar(v):
    _require(type(v) in (int, float) and abs(v) <= 10000, "geometry coordinate out of bounds")
    f = float(v)
    _require(math.isfinite(f), "non-finite geometry coordinate")
    return f + 0.0


def _vec(v):
    _require(isinstance(v, (tuple, list)) and len(v) == 3, "expected xyz coordinate")
    return tuple(_scalar(x) for x in v)


def _newell(vertices):
    x = y = z = 0.0
    for p, q in zip(vertices, vertices[1:] + vertices[:1]):
        x += (p[1] - q[1]) * (p[2] + q[2])
        y += (p[2] - q[2]) * (p[0] + q[0])
        z += (p[0] - q[0]) * (p[1] + q[1])
    return x, y, z


def _geometry_face(opid, key, vertices, normal, role, front, back, label):
    outer = tuple(_vec(v) for v in vertices)
    n = _vec(normal)
    _require(len(outer) >= 3, "degenerate face loop")
    winding = sum(a*b for a,b in zip(_newell(list(outer)), n))
    _require(abs(winding) > 1e-12, "face normal / winding degenerate")
    if winding < 0:
        outer = tuple(reversed(outer))
    # Existing independent BMB-017 algorithm supports concavity. Hole authoring
    # is absent from Module IR v1 and must not be invented at this layer.
    tris = triangulate_face(outer, normal=n)
    _require(len(tris) > 0, "face has no triangles")
    return {"opid": opid, "key": key, "outer": outer,
            "triangles": tuple(tuple(_vec(v) for v in t.vertices) for t in tris),
            "normal": n, "role": role, "front": front, "back": back, "label": label}


def _face_key(op, key):
    """Map BMB-018 wall semantic aliases onto BMB-014 polygon-face keys."""
    if op["kind"] != "wall-run":
        return key
    n = len(op["path"])
    if n != 2:
        _require(not key.startswith(("front-", "back-", "top-", "bottom-")) and
                 key not in ("start", "end"),
                 "bent wall face annotation mapping not established")
        return key
    return {"front-0": "side-0", "back-0": "side-2",
            "top-0": "top", "bottom-0": "bottom",
            "start": "side-3", "end": "side-1"}.get(key, key)

def _shape_faces(mid, module):
    """Produce audited, deterministic faces using existing Builder primitives."""
    ops = module["operations"]
    _require(isinstance(ops, list) and len(ops) <= MAX_SOURCE_OPERATIONS,
             "operation count exceeds compiler budget")
    opmap = {}
    for op in ops:
        _require(isinstance(op, dict) and isinstance(op.get("opId"), str),
                 "invalid source operation")
        _require(op["opId"] not in opmap, "duplicate source operation")
        opmap[op["opId"]] = op
    annotated = validate_module_faces(module)
    by_annotation = {}
    for ann in annotated:
        op = opmap[ann["opId"]]
        key = _face_key(op, ann["faceKey"])
        _require((ann["opId"], key) not in by_annotation, "annotation alias collision")
        by_annotation[(ann["opId"], key)] = ann

    opens = {}
    for op in ops:
        if op["kind"] == "opening-cut":
            opens.setdefault(op["targetWallOpId"], []).append(op)
    _require(all(k in opmap and opmap[k]["kind"] == "wall-run" for k in opens),
             "opening references nonexistent wall")

    faces, used = [], set()
    for opid, op in sorted(opmap.items()):
        if op["kind"] == "opening-cut":
            continue
        kind = op["kind"]
        _require(kind in ("floor-slab", "wall-run"),
                 f"{mid}/{opid}: unsupported primitive {kind}")
        role = op.get("role", "floor" if kind == "floor-slab" else "wall")
        _require(role in ("floor", "roof") if kind == "floor-slab" else role == "wall",
                 f"{mid}/{opid}: unrepresentable semantic role")
        materials = module["materials"]
        refs = {m["materialId"] for m in materials}
        default_mat = op.get("materialId")
        _require(default_mat is None or default_mat in refs, "unknown primitive material")
        if kind == "floor-slab":
            _require(opid not in opens, "opening can only cut a wall")
            slab = build_floor_slab(op)
            primitive_faces = [(f.name, f.vertices, f.normal, role, default_mat)
                               for f in slab.faces]
        elif opid not in opens:
            wall = build_wall_run(op)
            primitive_faces = [(f["role"], f["vertices"], f["normal"], role, default_mat)
                               for f in wall["faces"]]
        else:
            _require(not any(k[0] == opid for k in by_annotation),
                     "cut-wall face annotations require explicit cut mapping")
            result = build_wall_with_openings(op, opens[opid])
            primitive_faces = [(f"cut-{i}", f["vertices"], f["normal"], "wall", default_mat)
                               for i, f in enumerate(result["wall"]["faces"])]
            for insert in sorted(result["inserts"], key=lambda x: x["opId"]):
                source_op = opmap[insert["opId"]]
                irole = source_op["openingType"]
                material = source_op.get("materialId")
                _require(material is None or material in refs,
                         "unknown opening insert material")
                for pi, part in enumerate(insert["parts"]):
                    for fi, face in enumerate(part["faces"]):
                        primitive_faces.append((f"insert-{insert['opId']}-{pi}-{fi}",
                                                face["vertices"], face["normal"], irole, material))
        for key, ring, normal, surface, material in primitive_faces:
            ann = by_annotation.get((opid, key))
            if ann:
                _require(ann["role"] == role, "face annotation role mismatch")
                used.add((opid, key))
            front = ann["front"]["materialId"] if ann else material
            back = ann["back"]["materialId"] if ann else None
            label = ann["label"] if ann else f"{mid}/{opid}/{key}"
            _require(len(label) <= 240, "semantic label too long")
            faces.append(_geometry_face(opid, key, ring, normal, surface,
                                        front, back, label))
            _require(len(faces) <= MAX_FACES, "face budget exceeded")
    _require(set(by_annotation) == used, "source face annotation was not emitted")
    _require(faces or not module["materials"], "materials with no supported geometry")
    return faces


def collect_module_faces(assembly):
    """Faces per module, sorted by (opId, faceKey). Shared by compiler and live view."""
    module_faces = {}
    for mid, module in sorted(assembly.modules.items()):
        faces_for_module = _shape_faces(mid, module)
        if faces_for_module:
            faces_for_module.sort(key=lambda f: (f["opid"], f["key"]))
            module_faces[mid] = faces_for_module
        elif any(module.get(k) for k in ("operations", "faceAnnotations")):
            raise GeometryEncodingError("source geometry produced no faces")
    _require(module_faces, "semantic compile requires at least one face")
    return module_faces


def mesh_intermediate(faces):
    """Canonical vertex dedup per definition, lossless Float64 positions.

    Returns (coords, flat_loops, flat_triangles, logical, per_face_triangles) where
    per_face_triangles[i] is the sorted tuple of rotated index triples of face i.
    """
    points = set()
    for f in faces:
        points.update(f["outer"])
        for t in f["triangles"]:
            points.update(t)
    coords = sorted(points)
    _require(len(coords) <= MAX_VERTICES, "vertex budget exceeded")
    ids = {v: i for i, v in enumerate(coords)}
    flat_loops, flat_triangles, logical, per_face_all = [], [], [], []
    for f in faces:
        outer = [ids[p] for p in f["outer"]]
        flat_loops.extend(outer)
        per_face = []
        for tri in f["triangles"]:
            tr = [ids[p] for p in tri]
            _require(len(set(tr)) == 3, "triangle has duplicate vertices")
            k = tr.index(min(tr))
            per_face.append(tuple(tr[k:] + tr[:k]))
        per_face.sort()
        for tri in per_face:
            flat_triangles.extend(tri)
        logical.append((len(outer), len(per_face) * 3))
        per_face_all.append(tuple(per_face))
    _require(len(flat_triangles) // 3 <= MAX_TRIANGLES, "triangle count budget exceeded")
    return coords, flat_loops, flat_triangles, logical, per_face_all


def face_id(mid, face):
    """Stable face ID: module/operation/face-key (labels are NOT unique IDs)."""
    return f"{mid}/{face['opid']}/{face['key']}"


def project_assembly(assembly):
    """Pure live render projection (draft-view-v1), no bytes, no GPU conversion.

    Positions are module-local Float64 metre/+Z; the consumer applies the module
    row-major world transform exactly once. Triangle indices address the module's
    own vertex table.
    """
    module_faces = collect_module_faces(assembly)
    modules = []
    for mid, faces in sorted(module_faces.items()):
        coords, _loops, _flat, _logical, per_face = mesh_intermediate(faces)
        material_defs = {m["materialId"]: m for m in assembly.modules[mid]["materials"]}
        out_faces = []
        for f, tris in zip(faces, per_face):
            out_faces.append({
                "faceId": face_id(mid, f), "opId": f["opid"], "faceKey": f["key"],
                "role": f["role"], "label": f["label"],
                "frontMaterialId": f["front"], "backMaterialId": f["back"],
                "normal": list(f["normal"]),
                "triangles": [list(t) for t in tris],
            })
        used = sorted({m for f in faces for m in (f["front"], f["back"]) if m})
        modules.append({
            "moduleId": mid, "revision": assembly.modules[mid]["revision"],
            "worldTransform": list(assembly.world_transforms[mid]),
            "positions": [list(c) for c in coords],
            "materials": [{"materialId": m, "rgba": list(material_defs[m]["rgba"]),
                           "opacity": material_defs[m]["opacity"]} for m in used],
            "faces": out_faces,
        })
    return {"schemaVersion": "1.0.0", "units": "m", "upAxis": "+Z",
            "transformConvention": "row-major module-to-assembly; apply once to local Float64 positions",
            "modules": modules}
