# BMB-012 — Typed assembly validation (cloud-only)

Implementation: core/validator/validation.py; import from core.validator.
Prerequisite: BMB-011 merged assembly graph. This API does not change the
Module IR v1 schema, BMB-011 port-frame convention, or any on-wire BOMC bytes.

## Contract

    validate_assembly(modules_or_assembly, *, tolerance_m=0.001) -> ValidationReport

Accepts Module IR v1 module list/tuple or a BMB-011 Assembly. Re-assembles to
check the input (including mutable Assembly objects) before geometric checks.
Returns frozen diagnostics, never mutates caller input. The report provides
ok, tolerance_m, collision_model and to_dict() for stable JSON consumption.
Each Diagnostic has code, severity=ERROR, module_id, path, message, optional
related_module_id; to_dict uses camelCase. Deterministic by module ID.

The validator checks:
- References: material IDs, duplicate operation/material IDs, missing target
  wall operations, dependency IDs, port peers and reciprocal links.
- Seams: missing/mismatched peer seam IDs, missing or duplicate seam owners,
  missing seam surface operation; the full ownership invariant remains BMB-011.
- Local geometry: finite ordered 3D bounds, floor/wall footprint endpoints and
  vertical extents, and opening dimensions fitting the wall run.
- Port origins: module-local port frame origin within the module bound.
- World volume collisions: exact SAT intersection for transformed *module
  bounds* (affine scale/mirror/shear/rotation) with a 1-mm default penetration
  allowance; touching faces are allowed. Empty-operation container frames are
  excluded from solid collisions.

Malformed BMB-011 inputs produce a typed ASSEMBLY_INVALID plus any safe
preflight reference diagnostics; geometry and collision do not run on an
unassembled graph. Diagnostic cap is 512 (fixed bounded response). Tolerance
must be real, finite and in (0, 0.1] metres. Distinct reports retain stable
codes and source module identifiers. World computations reuse BMB-009's
row-major affine transforms, never world-axis-only AABB intersection.

## Limits and evidence classification

**Collision is module-bounds overlap, not per-operation mesh collision.** It
may report intentional overlapping spatial envelopes (false positives relative
to actual solids); it cannot prove exact wall/floor/roof self-intersections,
Boolean cutouts or leak-free mesh topology. Operation-specific narrow-phase
and consumer BOMC interoperability remain NOT_RUN downstream. This stage must
not be represented as full geometric certification.

Port orientation/normal checks are performed by BMB-011 and use its
provisional +Y width / +Z height convention, pending owner ratification.

Run synthetic focused tests:

    python -m unittest discover -s tests -p test_bmb012_validator.py -v

Hosted CI runs these and the full suite on Ubuntu and Windows for the exact PR
head. All evidence must be recorded as PASS/FAIL/NOT_RUN; no owner-local data or
consumer application required for this cloud scope.
