"""BMB-018: authored solid-color face semantics, not BOMC wire geometry."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re

from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parents[2] / "schemas/module-ir-v1.schema.json"
MAX_BYTES = 2_000_000
MAX_FACES = 8192


class SemanticFaceError(ValueError):
    """Invalid authored face semantics."""


def _check_finite(value):
    if type(value) is float and not math.isfinite(value):
        raise SemanticFaceError("non-finite JSON number")
    if type(value) is list:
        for item in value:
            _check_finite(item)
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise SemanticFaceError("non-string JSON key")
            _check_finite(item)


def _valid_face_key(op, key):
    if op["kind"] == "floor-slab":
        if key in ("top", "bottom"):
            return True
        prefix, count = "side-", len(op["footprint"])
    elif op["kind"] == "wall-run":
        if key in ("start", "end"):
            return True
        prefix = next((p for p in ("front-", "back-", "top-", "bottom-")
                       if key.startswith(p)), None)
        count = len(op["path"]) - 1
    else:
        return False
    if not prefix or not key.startswith(prefix):
        return False
    suffix = key[len(prefix):]
    return bool(suffix and suffix.isascii() and suffix.isdecimal()
                and str(int(suffix)) == suffix and int(suffix) < count)


def validate_module_faces(module):
    """Validate Module IR and resolve front/back solid materials without mutation."""
    if type(module) is not dict:
        raise SemanticFaceError("module must be an object")
    _check_finite(module)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors({
        "schemaVersion": "1.0.0", "modules": [module]}))
    if errors:
        errors.sort(key=lambda e: (str(list(e.absolute_path)), e.message))
        raise SemanticFaceError("Module IR schema: " + errors[0].message)
    annotations = module.get("faceAnnotations", [])
    if len(annotations) > MAX_FACES:
        raise SemanticFaceError("face annotation count exceeds budget")
    operations = {}
    for op in module["operations"]:
        key = op["opId"]
        if key in operations:
            raise SemanticFaceError("duplicate operation ID: " + key)
        operations[key] = op
    materials = {}
    for mat in module["materials"]:
        key = mat["materialId"]
        if key in materials:
            raise SemanticFaceError("duplicate material ID: " + key)
        materials[key] = mat
    seen = set()
    resolved = []
    for face in annotations:
        op_id, key, role = face["opId"], face["faceKey"], face["role"]
        identity = (op_id, key)
        if identity in seen:
            raise SemanticFaceError(f"duplicate face binding: {op_id}/{key}")
        seen.add(identity)
        op = operations.get(op_id)
        if op is None or op["kind"] not in ("floor-slab", "wall-run"):
            raise SemanticFaceError(f"{op_id}: unsupported or missing solid operation")
        expected = op.get("role", "wall" if op["kind"] == "wall-run" else "floor")
        if role != expected:
            raise SemanticFaceError(f"{op_id}/{key}: role mismatch")
        if ((op["kind"] == "wall-run" and role != "wall") or
                (op["kind"] == "floor-slab" and role not in ("floor", "roof"))):
            raise SemanticFaceError(f"{op_id}: unsupported solid role")
        if not _valid_face_key(op, key):
            raise SemanticFaceError(f"{op_id}: invalid face key {key}")
        sides = {}
        for side in ("front", "back"):
            mat_id = face[side + "MaterialId"]
            mat = materials.get(mat_id)
            if mat is None:
                raise SemanticFaceError(f"{op_id}/{key}: missing {side} material")
            if mat.get("semanticRole", "other") not in ("other", role):
                raise SemanticFaceError(f"{op_id}/{key}: material role mismatch")
            sides[side] = {
                "materialId": mat_id, "rgba": list(mat["rgba"]),
                "opacity": mat["opacity"]}
        label = face["label"]
        if not label.strip() or any(ord(c) < 32 or ord(c) == 127 for c in label):
            raise SemanticFaceError(f"{op_id}/{key}: invalid label")
        try:
            label.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SemanticFaceError("invalid Unicode label") from exc
        resolved.append({
            "opId": op_id, "faceKey": key, "role": role, "label": label,
            "front": sides["front"], "back": sides["back"]})
    resolved.sort(key=lambda item: (item["opId"], item["faceKey"]))
    return tuple(resolved)


def encode_authored_module(module):
    """Canonical UTF-8 JSON roundtrip, not a BOMC binary writer."""
    validate_module_faces(module)
    clone = copy.deepcopy(module)
    clone["faceAnnotations"] = sorted(clone.get("faceAnnotations", []),
                                      key=lambda x: (x["opId"], x["faceKey"]))
    try:
        data = json.dumps(clone, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SemanticFaceError("invalid module serialization") from exc
    if len(data) > MAX_BYTES:
        raise SemanticFaceError("module exceeds byte budget")
    return data


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SemanticFaceError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise SemanticFaceError(f"invalid JSON constant: {value}")


def decode_authored_module(payload):
    """Reject duplicate keys, invalid UTF-8, nonfinite JSON and bad references."""
    if type(payload) is not bytes or len(payload) > MAX_BYTES:
        raise SemanticFaceError("payload must be bounded bytes")
    try:
        module = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
                            parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        if isinstance(exc, SemanticFaceError):
            raise
        raise SemanticFaceError("invalid UTF-8 JSON") from exc
    validate_module_faces(module)
    return module
