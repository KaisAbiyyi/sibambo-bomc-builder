# BMB-016 — Flat/gable roof shells, ceiling, and simple stairs

## Bounded geometry contract

Headless, independently authored Python 3.12 primitives in core.geometry.roof operate in module-local right-handed metres (+Z up). This is a **geometry starter**, not a versioned Module IR v1 schema extension or binary BOMC writer. Existing BMB-013 slab construction is reused; no private Sibambo Editor source or customer model is copied.

- **build_roof_shell(op)** creates a closed flat or gable shell with outward-oriented polygon faces. Flat accepts BMB-013's simple polygon footprint (including concave outlines); gable accepts only a four-corner axis-aligned rectangle. eaveElevation is the **underside** at eaves; thickness is measured vertically; rise is underside ridge height above eaves; ridgeAxis (x/y) names the horizontal ridge direction. Neither overhang nor dormers are implied. The gable's sloped top faces share a ridge, as do underside slopes, without duplicate cap faces. Bounds, footprint area and shell volume are returned.
- **build_ceiling_shell(op)** creates an explicit flat ceiling shell with the same underside-elevation rule. It is not implicitly attached or deduplicated with the roof.
- **build_stair_flight(op)** creates 1..128 contiguous, nonoverlapping individually closed step prisms. origin defines the first tread's run origin and base Z; direction is +x/-x/+y/-y; width, treadDepth and riserHeight are positive metres. Each step top has Z equal to origin.z plus step index times riserHeight. The blocks share their common bottom elevation; no boolean union, landing, handrail or accessibility claim.
- **check_roof_wall_junction(roof, wall)** checks wall top Z against roof underside eave Z and requires wall centreline alignment with a constant-elevation supported eave. For gables, only edges parallel to the ridge qualify; gable-end walls beneath pitched faces require later clipping and are rejected.
- **assert_no_aabb_overlap(a,b)** rejects positive-volume AABB overlap and permits surface touching. This is **conservative broad-phase only**, not a narrow-phase collision or exact volume-intersection proof. BMB-012/017 own general assembly and triangulated checks.

All primitives reject invalid/nonfinite booleans/NaNs/huge integers, out-of-budget coordinates, malformed IDs and dimensions, and unsupported geometry. No silent repair. Faces are polygon loops, not triangulated meshes or BOMC binary. The kinds roof-shell, ceiling-shell and stair-flight are **internal geometry API** contracts; BMB-006's Module IR v1 schema does not yet admit these operations. Persisting/compiling them requires a separately approved schema evolution.

## Synthetic example

~~~python
from core.geometry.roof import build_roof_shell, build_ceiling_shell, build_stair_flight

roof = build_roof_shell({
    "kind": "roof-shell", "opId": "gable-1", "profile": "gable",
    "footprint": [[0, 0], [6, 0], [6, 4], [0, 4]],
    "eaveElevation": 3.0, "thickness": 0.2, "rise": 1.5, "ridgeAxis": "x"
})
ceiling = build_ceiling_shell({
    "kind": "ceiling-shell", "opId": "ceiling-1",
    "footprint": [[0, 0], [6, 0], [6, 4], [0, 4]],
    "eaveElevation": 2.8, "thickness": 0.1
})
stairs = build_stair_flight({
    "kind": "stair-flight", "opId": "stairs-1", "origin": [0, 0, 0.2],
    "direction": "+x", "width": 1.0, "treadDepth": 0.3,
    "riserHeight": 0.16, "stepCount": 4
})
~~~

## Cloud qualification and remaining gates

The BMB-016 GitHub Actions workflow runs Python 3.12 on Ubuntu and Windows:

~~~sh
python -m pip install 'jsonschema==4.23.0'
python -m unittest discover -s tests -p 'test_bmb016_roof.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
~~~

The PR records exact source HEAD, hosted run IDs, and PASS/FAIL/NOT_RUN per gate. Native Editor/Model-Eval import, BOMC material/binary generation, triangulation and semantic roundtrip are explicitly **NOT_RUN** until downstream BMB-017/019/020/021/026.
