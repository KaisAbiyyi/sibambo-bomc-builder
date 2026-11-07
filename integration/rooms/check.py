"""The feature-flagged entry point: the core validator's report, optionally enhanced with room-evidence diagnostics.

OFF (the default): `validate_with_rooms` returns exactly what `core.validator.validate_assembly` returns, and the evidence
is never read, parsed or validated. ON and evidence given: the core report is still computed first and unchanged; the room
comparison is added beside it, never merged into it. The core knows nothing about this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.assembly import AssemblyError
from core.validator import ValidationReport, validate_assembly
from integration.rooms import flag
from integration.rooms.compare import ERROR, Policy, RoomDiagnostic, RoomsReport, compare
from integration.rooms.evidence import digest, validate_evidence
from integration.rooms.intended import intended_rooms


@dataclass(frozen=True)
class EnhancedReport:
    core: ValidationReport
    rooms: RoomsReport
    evidence_sha256: str

    @property
    def ok(self) -> bool:
        return self.core.ok and self.rooms.ok

    def to_dict(self) -> dict:
        return {"ok": self.ok, "enabled": True, "evidenceSha256": self.evidence_sha256, "core": self.core.to_dict(),
                "rooms": self.rooms.to_dict()}


def validate_with_rooms(modules, evidence=None, *, enabled=None, policy: Policy | None = None, **core_options):
    """Core report when the adapter is off or no evidence is given; an EnhancedReport otherwise. Raises EvidenceError
    for evidence that must not be compared (only when the adapter is on)."""
    core = validate_assembly(modules, **core_options)
    if evidence is None or not flag.enabled(enabled):
        return core
    normalized = validate_evidence(evidence)
    policy = policy or Policy()
    try:
        rooms, skipped = intended_rooms(modules, elevation_m=normalized["elevationM"], level_tolerance=policy.level_tolerance)
    except AssemblyError as exc:
        empty = RoomsReport((RoomDiagnostic("ASSEMBLY_INVALID", ERROR, f"the assembly cannot be placed, so no room can be compared: {exc}"),),
                            (), policy, 0, len(normalized["rooms"]), dict(normalized["detector"]), normalized["evidenceId"])
        return EnhancedReport(core, empty, digest(normalized))
    return EnhancedReport(core, compare(rooms, normalized, policy, skipped=skipped), digest(normalized))
