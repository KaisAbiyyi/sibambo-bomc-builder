"""Compare detected rooms with intended rooms. Pure, deterministic, exact enough, and every room is accounted for.

Invariant (tested): every intended and every detected room ends up either matched one-to-one or named by at least one
ERROR diagnostic. Nothing is silently dropped except detections below `min_confidence`, which get a WARNING.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from integration.rooms.geometry import boxes_overlap, intersection_area, bbox, shoelace, triangles

ERROR, WARNING = "ERROR", "WARNING"
_RANK = {ERROR: 0, WARNING: 1}


@dataclass(frozen=True)
class Policy:
    accept_iou: float = 0.95          # a matched pair must overlap at least this well (intersection over union)
    overlap_fraction: float = 0.30    # share of a room's area that counts as "this room covers that one"
    area_tolerance: float = 0.03      # relative area difference allowed for an accepted pair
    min_confidence: float = 0.5       # detections below this are ignored (and reported)
    level_tolerance: float = 0.25     # metres between the evidence elevation and a slab's walkable surface

    def __post_init__(self):
        for name, lo, hi in (("accept_iou", 0.5, 1.0), ("overlap_fraction", 0.05, 0.95), ("area_tolerance", 0.0, 0.5),
                             ("min_confidence", 0.0, 1.0), ("level_tolerance", 0.0, 5.0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not lo <= value <= hi:
                raise ValueError(f"policy.{name} must be a number in [{lo}, {hi}]")


@dataclass(frozen=True)
class RoomDiagnostic:
    code: str
    severity: str
    message: str
    intended_ids: tuple = ()
    detected_ids: tuple = ()

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message,
                "intendedIds": list(self.intended_ids), "detectedIds": list(self.detected_ids)}


@dataclass(frozen=True)
class RoomsReport:
    diagnostics: tuple
    matches: tuple
    policy: Policy
    intended_count: int
    detected_count: int
    detector: dict
    evidence_id: str
    skipped_intended: tuple = ()

    @property
    def ok(self) -> bool:
        return not any(d.severity == ERROR for d in self.diagnostics)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "evidenceId": self.evidence_id, "detector": self.detector, "policy": asdict(self.policy),
                "intendedRooms": self.intended_count, "detectedRooms": self.detected_count,
                "matches": [dict(m) for m in self.matches], "skippedIntended": [dict(s) for s in self.skipped_intended],
                "diagnostics": [d.to_dict() for d in self.diagnostics]}


def compare(intended: list, evidence: dict, policy: Policy | None = None, *, skipped: list | None = None) -> RoomsReport:
    policy = policy or Policy()
    out: list[RoomDiagnostic] = []
    detected = []
    for room in evidence["rooms"]:
        if room["confidence"] < policy.min_confidence:
            out.append(RoomDiagnostic("LOW_CONFIDENCE", WARNING, f"{room['id']}: confidence {room['confidence']:.2f} is below "
                                      f"{policy.min_confidence:.2f}; the detection is ignored", (), (room["id"],)))
            continue
        poly = [tuple(p) for p in room["polygon"]]
        detected.append({"id": room["id"], "polygon": poly, "area": shoelace(poly), "tris": triangles(poly), "box": bbox(poly)})

    inter: dict = {}
    for d in detected:
        for i in intended:
            if boxes_overlap(d["box"], i["box"]):
                area = intersection_area(d["tris"], i["tris"])
                if area > 1e-9:
                    inter[(d["id"], i["id"])] = area

    def frac_of_intended(d_id, i): return inter.get((d_id, i["id"]), 0.0) / i["area"]
    def frac_of_detected(d, i_id): return inter.get((d["id"], i_id), 0.0) / d["area"]
    def iou(d, i):
        x = inter.get((d["id"], i["id"]), 0.0)
        return x / (d["area"] + i["area"] - x)

    flagged_i, flagged_d = set(), set()
    f = policy.overlap_fraction
    for d in detected:                                                              # one detection spanning several rooms
        spans = [i["id"] for i in intended if frac_of_intended(d["id"], i) >= f]
        if len(spans) >= 2:
            out.append(RoomDiagnostic("ROOM_MERGED", ERROR, f"{d['id']} covers {len(spans)} intended rooms (at least {f:.0%} of each): "
                                      f"{', '.join(spans)}", tuple(spans), (d["id"],)))
            flagged_d.add(d["id"]); flagged_i.update(spans)
    for i in intended:                                                              # one room cut into several detections
        parts = [d["id"] for d in detected if frac_of_intended(d["id"], i) >= f]
        if len(parts) >= 2:
            out.append(RoomDiagnostic("ROOM_SPLIT", ERROR, f"{i['id']} is covered by {len(parts)} detections (at least {f:.0%} each): "
                                      f"{', '.join(parts)}", (i["id"],), tuple(parts)))
            flagged_i.add(i["id"]); flagged_d.update(parts)

    pairs = sorted(((iou(d, i), d["id"], i["id"]) for d in detected for i in intended if (d["id"], i["id"]) in inter), key=lambda t: (-t[0], t[1], t[2]))
    taken_d, taken_i, matches = set(), set(), []
    by_d, by_i = {d["id"]: d for d in detected}, {i["id"]: i for i in intended}
    for score, d_id, i_id in pairs:                                                 # greedy one-to-one, best overlap first
        if score < 0.5 or d_id in taken_d or i_id in taken_i or d_id in flagged_d or i_id in flagged_i:
            continue
        taken_d.add(d_id); taken_i.add(i_id)
        d, i = by_d[d_id], by_i[i_id]
        diff = abs(d["area"] - i["area"]) / i["area"]
        matches.append({"intendedId": i_id, "detectedId": d_id, "iou": round(score, 6), "areaDifference": round(diff, 6)})
        if score < policy.accept_iou:
            out.append(RoomDiagnostic("SHAPE_MISMATCH", ERROR, f"{d_id} matches {i_id} with overlap {score:.3f}, below {policy.accept_iou:.3f}",
                                      (i_id,), (d_id,)))
            flagged_i.add(i_id); flagged_d.add(d_id)
        elif diff > policy.area_tolerance:
            out.append(RoomDiagnostic("AREA_MISMATCH", ERROR, f"{d_id} has {d['area']:.3f} m2 but {i_id} intends {i['area']:.3f} m2 "
                                      f"({diff:.1%} apart, tolerance {policy.area_tolerance:.1%})", (i_id,), (d_id,)))
            flagged_i.add(i_id); flagged_d.add(d_id)

    for i in intended:                                                              # whatever is still unaccounted for
        if i["id"] in taken_i or i["id"] in flagged_i:
            continue
        covered = sum(v for (d_id, i_id), v in inter.items() if i_id == i["id"]) / i["area"]
        if covered < f:
            out.append(RoomDiagnostic("ROOM_MISSING", ERROR, f"{i['id']} has no detected room (only {covered:.0%} of it is covered)", (i["id"],), ()))
        else:
            out.append(RoomDiagnostic("ROOM_UNMATCHED", ERROR, f"{i['id']} is covered {covered:.0%} but by no single detection that "
                                      f"matches it (overlap below 0.5)", (i["id"],), ()))
        flagged_i.add(i["id"])
    for d in detected:
        if d["id"] in taken_d or d["id"] in flagged_d:
            continue
        covered = sum(v for (d_id, i_id), v in inter.items() if d_id == d["id"]) / d["area"]
        if covered < f:
            out.append(RoomDiagnostic("ROOM_UNEXPECTED", ERROR, f"{d['id']} matches no intended room (only {covered:.0%} of it overlaps one)", (), (d["id"],)))
        else:
            out.append(RoomDiagnostic("ROOM_UNMATCHED", ERROR, f"{d['id']} overlaps intended rooms {covered:.0%} but matches none of them "
                                      f"(overlap below 0.5)", (), (d["id"],)))
        flagged_d.add(d["id"])

    for a in range(len(detected)):                                                  # a detector contradicting itself
        for b in range(a + 1, len(detected)):
            da, db = detected[a], detected[b]
            if boxes_overlap(da["box"], db["box"]):
                x = intersection_area(da["tris"], db["tris"])
                if x > 0.05 * min(da["area"], db["area"]):
                    out.append(RoomDiagnostic("DETECTED_OVERLAP", WARNING, f"{da['id']} and {db['id']} overlap by {x:.3f} m2", (), (da["id"], db["id"])))

    for s in skipped or []:
        out.append(RoomDiagnostic("INTENDED_UNUSABLE", WARNING, f"{s['id']}: {s['reason']}; it was not compared", (s["id"],), ()))
    out.sort(key=lambda d: (_RANK[d.severity], d.code, d.intended_ids, d.detected_ids))
    return RoomsReport(tuple(out), tuple(sorted(matches, key=lambda m: m["intendedId"])), policy, len(intended), len(detected),
                       dict(evidence["detector"]), evidence["evidenceId"], tuple(skipped or ()))
