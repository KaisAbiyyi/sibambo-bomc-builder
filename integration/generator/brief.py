"""Canonical room-brief v1, the survey/form normalizers and the deterministic lowering to Module IR.

A brief is hostile input: it comes from another program (or a person filling in a form). It is
validated against an allowlist before anything is derived from it, every number is finite and
bounded, every identifier is a strict slug (so it can become a module id and nothing else), and the
result is normalized (all numbers floats, rooms in row order) so equal briefs hash equally.

Scope of v1, stated so nobody over-reads it: rectangular rooms laid out in ONE row along +X, all
sharing one depth, each adjacent pair joined by a party wall owned by the left room. Floors and
party walls (with an optional doorway) are emitted. Exterior walls, roofs, stairs and non-rectangular
or multi-row plans are not part of v1.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from agentctx.budget import canonical
from core.textsafe import show

SCHEMA = "room-brief-v1"
SURVEY = "survey-v1"
FORM = "form-v1"

MAX_BYTES = 64 * 1024
MAX_ROOMS = 12
# \Z, never $: "$" also matches before a trailing newline, so "a\n" would pass as a slug.
SLUG = re.compile(r"[a-z][a-z0-9-]{0,35}\Z")   # 36 max: seam ids are "<left>-to-<right>" and must fit 80
KINDS = ("living", "bedroom", "bath", "hall", "kitchen", "other")

MIN_ROOM_M, MAX_ROOM_M = 1.5, 12.0
MIN_WALL_H, MAX_WALL_H, DEFAULT_WALL_H = 2.4, 4.0, 2.8
# A doorway is the OPENING cut in the wall. The 0.15 m wall the lowering emits leaves a frame and an open leaf,
# and core.geometry.openings needs 0.70 m clear width and 1.90 m clear height after them: that is 0.81 m wide
# and 1.95 m high at the smallest (probed at 1 cm steps against the real builder, see the tests).
MIN_DOOR_W, MAX_DOOR_W, MIN_DOOR_H, DEFAULT_DOOR_H = 0.81, 2.0, 1.95, 2.1
DOOR_MARGIN_M = 0.1          # clear wall left on each side of a doorway
SLAB_M = 0.15                # floor slab and wall thickness used by the lowering

# Survey answers are mapped through these fixed tables (the proposed v1 handoff shape).
SIZES = {"compact": {"living": 4.0, "bedroom": 3.0, "bath": 2.0, "depth": 3.0},
         "standard": {"living": 5.0, "bedroom": 3.5, "bath": 2.4, "depth": 3.5}}


class BriefError(ValueError):
    """A brief, survey or form that must not reach the builder."""


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise BriefError(why)


def _object(value: object, required: set, optional: set, where: str) -> dict:
    _need(isinstance(value, dict), f"{where}: expected an object")
    names = [k for k in value]
    _need(all(isinstance(k, str) for k in names), f"{where}: non-string field name")
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


def _text(value: object, where: str, limit: int = 80) -> str:
    _need(isinstance(value, str) and 1 <= len(value) <= limit
          and all(c.isprintable() for c in value), f"{where}: expected 1..{limit} printable characters")
    return value


def _integer(value: object, lo: int, hi: int, where: str) -> int:
    _need(type(value) is int and lo <= value <= hi, f"{where}: expected an integer in [{lo}, {hi}]")
    return value


def _round(value: float) -> float:
    return round(value, 3)


def validate_brief(value: object) -> dict:
    """Return the normalized brief (numbers as floats, rooms in row order) or raise BriefError."""
    brief = _object(value, {"schemaVersion", "briefId", "project", "floorId", "depthM", "rooms"},
                    {"wallHeightM", "doors"}, "brief")
    _need(brief["schemaVersion"] == SCHEMA, f"brief: schemaVersion must be {SCHEMA!r}")
    depth = _number(brief["depthM"], MIN_ROOM_M, MAX_ROOM_M, "depthM")
    wall_h = _number(brief.get("wallHeightM", DEFAULT_WALL_H), MIN_WALL_H, MAX_WALL_H, "wallHeightM")
    rooms_in = brief["rooms"]
    _need(isinstance(rooms_in, list) and 1 <= len(rooms_in) <= MAX_ROOMS, f"rooms: expected 1..{MAX_ROOMS} rooms")
    rooms, seen = [], set()
    for i, raw in enumerate(rooms_in):
        room = _object(raw, {"id", "name", "kind", "widthM"}, set(), f"rooms[{i}]")
        rid = _slug(room["id"], f"rooms[{i}].id")
        _need(rid not in seen, f"rooms[{i}].id: duplicate {show(rid)}")
        seen.add(rid)
        _need(room["kind"] in KINDS, f"rooms[{i}].kind: unsupported {show(room['kind'])}")
        rooms.append({"id": rid, "name": _text(room["name"], f"rooms[{i}].name"), "kind": room["kind"],
                      "widthM": _number(room["widthM"], MIN_ROOM_M, MAX_ROOM_M, f"rooms[{i}].widthM")})
    index = {r["id"]: n for n, r in enumerate(rooms)}
    doors_in = brief.get("doors", [])
    _need(isinstance(doors_in, list) and len(doors_in) <= MAX_ROOMS, "doors: expected a short list")
    by_pair: dict[int, dict] = {}
    for i, raw in enumerate(doors_in):
        door = _object(raw, {"between", "widthM"}, {"offsetM", "heightM"}, f"doors[{i}]")
        pair = door["between"]
        _need(isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) for p in pair)
              and all(p in index for p in pair), f"doors[{i}].between: expected two room ids")
        a, b = sorted(index[p] for p in pair)
        _need(b == a + 1, f"doors[{i}].between: rooms must be neighbours in the row")
        _need(a not in by_pair, f"doors[{i}]: more than one door between {rooms[a]['id']} and {rooms[b]['id']}")
        width = _number(door["widthM"], MIN_DOOR_W, MAX_DOOR_W, f"doors[{i}].widthM")
        height = _number(door.get("heightM", DEFAULT_DOOR_H), MIN_DOOR_H, wall_h - 0.1, f"doors[{i}].heightM")
        room_room = rooms[a]["id"], rooms[b]["id"]
        _need(width + 2 * DOOR_MARGIN_M <= depth, f"doors[{i}]: wider than the shared wall allows")
        offset = _round((depth - width) / 2) if "offsetM" not in door else _number(
            door["offsetM"], DOOR_MARGIN_M, depth, f"doors[{i}].offsetM")
        _need(DOOR_MARGIN_M <= offset and offset + width <= depth - DOOR_MARGIN_M + 1e-9,
              f"doors[{i}]: opening leaves less than {DOOR_MARGIN_M} m of wall at an end")
        by_pair[a] = {"between": list(room_room), "widthM": width, "heightM": height, "offsetM": _round(offset)}
    return {"schemaVersion": SCHEMA, "briefId": _slug(brief["briefId"], "briefId"),
            "project": _slug(brief["project"], "project"), "floorId": _slug(brief["floorId"], "floorId"),
            "depthM": depth, "wallHeightM": wall_h, "rooms": rooms,
            "doors": [by_pair[k] for k in sorted(by_pair)]}


def brief_sha256(brief: dict) -> str:
    """Digest of the NORMALIZED brief (so 3 and 3.0 are the same brief)."""
    return hashlib.sha256(canonical(validate_brief(brief)).encode("utf-8")).hexdigest()


def _bytes_ok(value: object, where: str) -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError) as exc:
        raise BriefError(f"{where}: not representable as JSON") from exc
    _need(size <= MAX_BYTES, f"{where}: larger than {MAX_BYTES} bytes")


def normalize_survey(value: object) -> dict:
    """survey-v1 -> room-brief-v1 through the fixed SIZES table (living, then bedrooms, then baths)."""
    _bytes_ok(value, "survey")
    survey = _object(value, {"schemaVersion", "surveyId", "answers"}, set(), "survey")
    _need(survey["schemaVersion"] == SURVEY, f"survey: schemaVersion must be {SURVEY!r}")
    answers = _object(survey["answers"], {"bedrooms", "bathrooms", "size"}, set(), "answers")
    beds = _integer(answers["bedrooms"], 0, 6, "answers.bedrooms")
    baths = _integer(answers["bathrooms"], 0, 4, "answers.bathrooms")
    _need(isinstance(answers["size"], str) and answers["size"] in SIZES,
          f"answers.size: expected one of {sorted(SIZES)}")
    table = SIZES[answers["size"]]
    rooms = [{"id": "living", "name": "Living room", "kind": "living", "widthM": table["living"]}]
    rooms += [{"id": f"bedroom-{n}", "name": f"Bedroom {n}", "kind": "bedroom", "widthM": table["bedroom"]}
              for n in range(1, beds + 1)]
    rooms += [{"id": f"bath-{n}", "name": f"Bathroom {n}", "kind": "bath", "widthM": table["bath"]}
              for n in range(1, baths + 1)]
    doors = [{"between": [rooms[i]["id"], rooms[i + 1]["id"]], "widthM": 0.9} for i in range(len(rooms) - 1)]
    return validate_brief({"schemaVersion": SCHEMA, "briefId": _slug(survey["surveyId"], "surveyId"),
                           "project": "house", "floorId": "floor-1", "depthM": table["depth"],
                           "rooms": rooms, "doors": doors})


def _slugify(name: str, kind: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-")
    if not text:
        text = kind
    return text if re.match(r"[a-z]", text) else f"room-{text}"[:36]


def normalize_form(value: object) -> dict:
    """form-v1 -> room-brief-v1: room ids come from the names (ASCII slug, de-duplicated)."""
    _bytes_ok(value, "form")
    form = _object(value, {"schemaVersion", "formId", "depthM", "rooms"},
                   {"project", "floorId", "doorWidthM", "wallHeightM"}, "form")
    _need(form["schemaVersion"] == FORM, f"form: schemaVersion must be {FORM!r}")
    raw_rooms = form["rooms"]
    _need(isinstance(raw_rooms, list) and 1 <= len(raw_rooms) <= MAX_ROOMS, f"rooms: expected 1..{MAX_ROOMS} rooms")
    rooms, used = [], set()
    for i, raw in enumerate(raw_rooms):
        entry = _object(raw, {"name", "type", "widthM"}, set(), f"rooms[{i}]")
        name = _text(entry["name"], f"rooms[{i}].name")
        _need(entry["type"] in KINDS, f"rooms[{i}].type: unsupported {show(entry['type'])}")
        base = _slugify(name, entry["type"])
        rid, n = base, 1
        while rid in used:
            n += 1
            rid = f"{base[:32]}-{n}"
        used.add(rid)
        rooms.append({"id": rid, "name": name, "kind": entry["type"], "widthM": entry["widthM"]})
    door_w = form.get("doorWidthM", 0.9)
    doors = [{"between": [rooms[i]["id"], rooms[i + 1]["id"]], "widthM": door_w} for i in range(len(rooms) - 1)]
    brief = {"schemaVersion": SCHEMA, "briefId": form["formId"], "project": form.get("project", "house"),
             "floorId": form.get("floorId", "floor-1"), "depthM": form["depthM"], "rooms": rooms, "doors": doors}
    if "wallHeightM" in form:
        brief["wallHeightM"] = form["wallHeightM"]
    return validate_brief(brief)


def to_brief(value: object) -> dict:
    """Accept a room-brief, a survey or a form (chosen by schemaVersion) and return the normalized brief."""
    _bytes_ok(value, "input")
    _need(isinstance(value, dict), "input: expected an object")
    kind = value.get("schemaVersion")
    if kind == SCHEMA:
        return validate_brief(value)
    if kind == SURVEY:
        return normalize_survey(value)
    if kind == FORM:
        return normalize_form(value)
    raise BriefError(f"input: unsupported schemaVersion {show(kind)}")


# ---- deterministic lowering to Module IR v1 ------------------------------------------------------

def module_id(brief: dict, room_id: str) -> str:
    return f"{brief['project']}/{brief['floorId']}/{room_id}"


def _translation(x: float, y: float, z: float) -> list:
    return [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]


def lower(brief: dict) -> dict:
    """Normalized brief -> {"schemaVersion": "1.0.0", "modules": [...]} (the Module IR envelope)."""
    brief = validate_brief(brief)
    rooms, depth, height = brief["rooms"], brief["depthM"], brief["wallHeightM"]
    doors = {(d["between"][0]): d for d in brief["doors"]}      # keyed by the LEFT room of the pair
    modules, x0 = [], 0.0
    for i, room in enumerate(rooms):
        width, mid = room["widthM"], module_id(brief, room["id"])
        has_next, has_prev = i + 1 < len(rooms), i > 0
        ops = [{"kind": "floor-slab", "opId": "floor-1", "role": "floor", "materialId": "concrete",
                "footprint": [[0, 0], [width, 0], [width, depth], [0, depth]],
                "thickness": SLAB_M, "elevation": 0}]
        ports, owned, deps = [], [], []
        if has_next:
            nxt, door = module_id(brief, rooms[i + 1]["id"]), doors.get(room["id"])
            seam = f"{room['id']}-to-{rooms[i + 1]['id']}"
            ops.append({"kind": "wall-run", "opId": "east-wall", "role": "wall", "materialId": "plaster",
                        "path": [[width, 0], [width, depth]], "thickness": SLAB_M, "height": height,
                        "baseElevation": 0})
            if door:
                ops.append({"kind": "opening-cut", "opId": "door-east", "role": "opening",
                            "targetWallOpId": "east-wall", "offset": door["offsetM"], "width": door["widthM"],
                            "height": door["heightM"], "sillHeight": 0, "openingType": "door"})
            kind, span, rise, off = (("doorway", door["widthM"], door["heightM"], door["offsetM"]) if door
                                     else ("shared-boundary", depth, height, 0.0))
            ports.append({"portId": "east-link", "kind": kind, "normal": [1, 0, 0],
                          "localTransform": _translation(width, off, 0), "width": span, "height": rise,
                          "peer": {"moduleId": nxt, "portId": "west-link"}, "seamId": seam})
            owned.append({"seamId": seam, "ownerModuleId": mid, "participants": [mid, nxt],
                          "surfaceOpId": "east-wall"})
        if has_prev:
            prev = module_id(brief, rooms[i - 1]["id"])
            door = doors.get(rooms[i - 1]["id"])
            seam = f"{rooms[i - 1]['id']}-to-{room['id']}"
            kind, span, rise, off = (("doorway", door["widthM"], door["heightM"], door["offsetM"]) if door
                                     else ("shared-boundary", depth, height, 0.0))
            ports.append({"portId": "west-link", "kind": kind, "normal": [-1, 0, 0],
                          "localTransform": _translation(0, off, 0), "width": span, "height": rise,
                          "peer": {"moduleId": prev, "portId": "east-link"}, "seamId": seam})
            deps.append({"moduleId": prev, "minRevision": 1})
        modules.append({
            "schemaVersion": "1.0.0", "moduleId": mid, "parentId": f"{brief['project']}/{brief['floorId']}",
            "revision": 1,
            "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z", "forwardAxis": "+Y",
                           "transform": _translation(x0, 0, 0)},
            "bounds": {"min": [0, 0, 0], "max": [width, depth, height]},
            "operations": ops,
            "materials": [{"materialId": "concrete", "rgba": [180, 180, 180, 255], "opacity": 1,
                           "semanticRole": "floor"}]
                         + ([{"materialId": "plaster", "rgba": [245, 244, 242, 255], "opacity": 1,
                              "semanticRole": "wall"}] if has_next else []),   # an unreferenced material is rejected
            "ports": ports, "ownedSeams": owned, "dependencies": deps,
            "provenance": {"origin": "synthetic", "generator": "bmb032-room-brief-v1",
                           "note": f"brief {brief['briefId']}"}})
        x0 += width
    return {"schemaVersion": "1.0.0", "modules": modules}


def journal_blocks(brief: dict) -> dict:
    """moduleId -> {blockId: data}: the intent the generator records in each module's journal.

    The typed geometry travels as Module IR (see `lower`); the journal records WHY (which brief, which
    room, which door the module owns). No block carries a digest of the WHOLE brief: that would change
    every module on every edit, and a localized change must touch one module's journal only.
    """
    brief = validate_brief(brief)
    doors = {d["between"][0]: d for d in brief["doors"]}
    result = {}
    for order, room in enumerate(brief["rooms"]):
        blocks = {"room": {"briefId": brief["briefId"], "roomId": room["id"],
                           "kind": room["kind"], "name": room["name"], "widthM": room["widthM"],
                           "depthM": brief["depthM"], "order": order}}
        door = doors.get(room["id"])
        if door:
            blocks["door-east"] = {"widthM": door["widthM"], "heightM": door["heightM"], "offsetM": door["offsetM"],
                                   "toRoom": door["between"][1]}
        result[module_id(brief, room["id"])] = blocks
    return result
