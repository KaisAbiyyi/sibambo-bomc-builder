"""BMB-018: fail-closed authoring metadata for solid semantic faces.

This is module IR (JSON), NOT a BOMC binary face encoder or tessellator.
The complete module IR JSON Schema remains a separate mandatory validation
boundary. This module validates semantic cross-references and roundtrips only.
"""
from __future__ import annotations

import copy
import json
import re

ID = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
ROLES = frozenset(("wall", "floor", "roof"))
FACE_FIELDS = frozenset((
    "faceId", "ownerOpId", "role", "label", "frontMaterialId", "backMaterialId",
))
MAX_FACES = 10_000
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


class SemanticFaceError(ValueError):
    """Invalid authoring semantic face, including ambiguous references."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise SemanticFaceError(message)


def _slug(value: object, context: str) -> str:
    _need(isinstance(value, str) and ID.fullmatch(value) is not None,
          f"{context}: expected bounded slug ID")
    return value


def _label(value: object) -> str:
    _need(isinstance(value, str) and 1 <= len(value) <= 160
          and value == value.strip()
          and not any(ord(ch) < 32 or 127 <= ord(ch) <= 159
                      or 0xD800 <= ord(ch) <= 0xDFFF for ch in value),
          "face label: expected nonblank trimmed text without controls")
    return value


def inspect_semantic_faces(module: dict) -> list[dict]:
    """Return detached, faceId-sorted metadata after checking local references.

    floor-slab with role 'roof' is a *flat roof authoring intent*, not a
    generated roof solid. wall-run is the only wall owner. No opening-cut face
    annotation and no cross-module face ownership are accepted.
    """
    _need(isinstance(module, dict), "module must be an object")
    materials = module.get("materials")
    operations = module.get("operations")
    faces = module.get("semanticFaces", [])
    _need(isinstance(materials, list) and isinstance(operations, list),
          "module requires material and operation arrays")
    _need(isinstance(faces, list) and len(faces) <= MAX_FACES,
          "semanticFaces must be a bounded array")

    mat_ids: set[str] = set()
    for entry in materials:
        _need(isinstance(entry, dict), "material must be an object")
        mid = _slug(entry.get("materialId"), "materialId")
        _need(mid not in mat_ids, f"duplicate materialId: {mid}")
        mat_ids.add(mid)

    ops: dict[str, dict] = {}
    for entry in operations:
        _need(isinstance(entry, dict), "operation must be an object")
        opid = _slug(entry.get("opId"), "opId")
        _need(opid not in ops, f"duplicate opId: {opid}")
        ops[opid] = entry

    face_ids: set[str] = set()
    result = []
    for entry in faces:
        _need(isinstance(entry, dict) and entry.keys() == FACE_FIELDS,
              "semantic face must have exactly the six declared fields")
        face_id = _slug(entry["faceId"], "faceId")
        _need(face_id not in face_ids, f"duplicate faceId: {face_id}")
        face_ids.add(face_id)
        owner = _slug(entry["ownerOpId"], "ownerOpId")
        _need(owner in ops, f"{face_id}: unknown ownerOpId: {owner}")
        role = entry["role"]
        _need(isinstance(role, str) and role in ROLES,
              f"{face_id}: unsupported face role")
        op = ops[owner]
        kind = op.get("kind")
        if kind == "wall-run":
            allowed = ("wall",)
            default_role = "wall"
        elif kind == "floor-slab":
            allowed = ("floor", "roof")
            default_role = "floor"
        else:
            raise SemanticFaceError(f"{face_id}: operation cannot own a solid face")
        _need(role in allowed and op.get("role", default_role) == role,
              f"{face_id}: role does not match owner operation")
        _label(entry["label"])
        for side in ("frontMaterialId", "backMaterialId"):
            mid = _slug(entry[side], side)
            _need(mid in mat_ids, f"{face_id}: unknown {side}: {mid}")
        result.append(copy.deepcopy(entry))
    return sorted(result, key=lambda face: face["faceId"])


def with_semantic_faces(module: dict, faces: list[dict]) -> dict:
    """Atomically return an annotated copy; never mutate the caller's module."""
    _need(isinstance(module, dict), "module must be an object")
    candidate = copy.deepcopy(module)
    candidate["semanticFaces"] = copy.deepcopy(faces)
    candidate["semanticFaces"] = inspect_semantic_faces(candidate)
    return candidate


def encode_semantic_module(module: dict) -> bytes:
    """Canonical JSON serialization for the scoped authoring module, not BOMC.

    Validate the full schema separately; only semantic references are checked
    here. Refuse NaN, unsupported Python values and oversized documents.
    """
    _need(isinstance(module, dict), "module must be an object")
    candidate = copy.deepcopy(module)
    canonical_faces = inspect_semantic_faces(candidate)
    if "semanticFaces" in candidate:
        candidate["semanticFaces"] = canonical_faces
    try:
        result = json.dumps(candidate, ensure_ascii=False, allow_nan=False,
                            sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise SemanticFaceError("module cannot be encoded as strict JSON") from exc
    _need(len(result) <= MAX_DOCUMENT_BYTES, "semantic module JSON byte budget exceeded")
    return result


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise SemanticFaceError(f"non-JSON numeric constant: {value}")


def decode_semantic_module(payload: bytes) -> dict:
    """Decode strict UTF-8 JSON with duplicate-key and semantic guards."""
    _need(isinstance(payload, bytes) and len(payload) <= MAX_DOCUMENT_BYTES,
          "semantic module requires bounded bytes")
    try:
        doc = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
                         parse_constant=_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise SemanticFaceError("invalid semantic module JSON") from exc
    _need(isinstance(doc, dict), "module JSON must be an object")
    inspect_semantic_faces(doc)
    return doc
