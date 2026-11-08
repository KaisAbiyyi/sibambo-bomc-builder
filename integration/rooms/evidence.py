"""rooms-evidence-v1: what a room detector hands the adapter. A PROPOSED, versioned interface (not any real detector's format).

The evidence is hostile input (another program's output): strict allowlist, finite and bounded numbers, strict slugs, a
size cap, polygons that must be simple (checked by the core triangulator), and every problem a typed EvidenceError.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from agentctx.budget import canonical
from core.geometry.triangulation import TriangulationError, triangulate_face
from core.textsafe import show

SCHEMA = "rooms-evidence-v1"
MAX_BYTES = 256 * 1024
MAX_ROOMS = 64
MAX_VERTICES = 256
MAX_TOTAL_VERTICES = 4096
# The vertex limits alone do not bound the work: the core triangulator's output (and time) grows roughly with the square of
# the vertex count for a star-shaped room (256 vertices give about 4000 triangles, a few tenths of a second each). The
# triangles of every room in the evidence therefore have a total budget, counted as the rooms are checked; going over it is a
# typed refusal, so a hostile evidence file cannot make the adapter spend its time triangulating.
MAX_TOTAL_TRIANGLES = 8000
MAX_COORD_M = 10_000.0
MIN_AREA_M2 = 0.01
SLUG = re.compile(r"[a-z][a-z0-9-]{0,35}\Z")         # \Z, never $: "$" also matches before a final newline


class EvidenceError(ValueError):
    """Evidence that must not be compared."""


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise EvidenceError(why)


def _object(value: object, required: set, optional: set, where: str) -> dict:
    _need(isinstance(value, dict), f"{where}: expected an object")
    _need(all(isinstance(k, str) for k in value), f"{where}: non-string field name")
    missing, extra = required - value.keys(), value.keys() - required - optional
    _need(not missing, f"{where}: missing {sorted(missing)}")
    _need(not extra, f"{where}: unsupported {sorted(show(k) for k in extra)}")
    return value


def _number(value: object, lo: float, hi: float, where: str) -> float:
    _need(type(value) in (int, float), f"{where}: expected a number")
    _need(isinstance(value, int) and abs(value) < 2 ** 53 or isinstance(value, float) and math.isfinite(value),
          f"{where}: not a finite number")
    result = float(value)
    _need(lo <= result <= hi, f"{where}: {show(value)} outside [{lo}, {hi}]")
    return result


def _slug(value: object, where: str) -> str:
    _need(isinstance(value, str) and SLUG.match(value) is not None, f"{where}: invalid identifier {show(value)}")
    return value


def _text(value: object, where: str, limit: int) -> str:
    _need(isinstance(value, str) and 1 <= len(value) <= limit and all(c.isprintable() for c in value),
          f"{where}: expected 1..{limit} printable characters")
    return value


def _area(points: list) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def validate_evidence(value: object) -> dict:
    """Return the normalized evidence (floats, rooms sorted by id) or raise EvidenceError."""
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError) as exc:
        raise EvidenceError("evidence is not representable as JSON") from exc
    _need(size <= MAX_BYTES, f"evidence is larger than {MAX_BYTES} bytes")
    data = _object(value, {"schemaVersion", "evidenceId", "detector", "rooms"}, {"elevationM"}, "evidence")
    _need(data["schemaVersion"] == SCHEMA, f"evidence: schemaVersion must be {SCHEMA!r}")
    detector = _object(data["detector"], {"name", "version"}, set(), "detector")
    rooms_in = data["rooms"]
    _need(isinstance(rooms_in, list) and 1 <= len(rooms_in) <= MAX_ROOMS, f"rooms: expected 1..{MAX_ROOMS} rooms")
    rooms, seen, total, total_triangles = [], set(), 0, 0
    for i, raw in enumerate(rooms_in):
        room = _object(raw, {"id", "polygon"}, {"confidence", "label"}, f"rooms[{i}]")
        rid = _slug(room["id"], f"rooms[{i}].id")
        _need(rid not in seen, f"rooms[{i}].id: duplicate {show(rid)}")
        seen.add(rid)
        poly_in = room["polygon"]
        _need(isinstance(poly_in, list) and 3 <= len(poly_in) <= MAX_VERTICES,
              f"rooms[{i}].polygon: expected 3..{MAX_VERTICES} vertices")
        total += len(poly_in)
        _need(total <= MAX_TOTAL_VERTICES, f"evidence has more than {MAX_TOTAL_VERTICES} vertices in total")
        poly = []
        for j, point in enumerate(poly_in):
            _need(isinstance(point, list) and len(point) == 2, f"rooms[{i}].polygon[{j}]: expected [x, y]")
            poly.append([_number(point[0], -MAX_COORD_M, MAX_COORD_M, f"rooms[{i}].polygon[{j}][0]"),
                         _number(point[1], -MAX_COORD_M, MAX_COORD_M, f"rooms[{i}].polygon[{j}][1]")])
        try:
            pieces = triangulate_face([(x, y, 0.0) for x, y in poly])  # rejects self-intersecting / degenerate rings
        except TriangulationError as exc:
            raise EvidenceError(f"rooms[{i}].polygon: not a simple polygon ({exc})") from exc
        total_triangles += len(pieces)
        _need(total_triangles <= MAX_TOTAL_TRIANGLES,
              f"evidence is too complex: its rooms need more than {MAX_TOTAL_TRIANGLES} triangles in total")
        _need(_area(poly) >= MIN_AREA_M2, f"rooms[{i}].polygon: area below {MIN_AREA_M2} m2")
        normalized = {"id": rid, "polygon": poly,
                      "confidence": _number(room.get("confidence", 1.0), 0.0, 1.0, f"rooms[{i}].confidence")}
        if "label" in room:
            normalized["label"] = _text(room["label"], f"rooms[{i}].label", 80)
        rooms.append(normalized)
    return {"schemaVersion": SCHEMA, "evidenceId": _slug(data["evidenceId"], "evidenceId"),
            "detector": {"name": _text(detector["name"], "detector.name", 80),
                         "version": _text(detector["version"], "detector.version", 40)},
            "elevationM": _number(data.get("elevationM", 0.0), -1000.0, 1000.0, "elevationM"),
            "rooms": sorted(rooms, key=lambda r: r["id"])}


def digest(normalized: dict) -> str:
    """SHA-256 of evidence that `validate_evidence` already returned (no second validation, so no second triangulation)."""
    return hashlib.sha256(canonical(normalized).encode("utf-8")).hexdigest()


def evidence_sha256(evidence: dict) -> str:
    return digest(validate_evidence(evidence))
