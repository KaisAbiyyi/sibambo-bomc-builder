# BMB-020 — Deterministic Module IR to BOMC 1.2 semantic compiler

Existing PR: [#55](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/55). Branch: work/bmb-020/deterministic-compiler-20261103. Resource lock: bomc/compiler. Strict cloud-only. Source: [graph_to_bomc.py](../bomc/compiler/graph_to_bomc.py) and [semantic_v12.py](../bomc/compiler/semantic_v12.py). BMB-019 metadata writer is unchanged. Python 3.12 and existing jsonschema==4.23.0.

## Supported source and geometry

The BMB-006 Module IR v1 envelope is validated through BMB-011 assembly and BMB-018 JSON schema/face semantics. BMB-013 floor-slab and BMB-014 wall-run primitives emit actual 3D polygon loops and BMB-017 triangulated topology. Supported straight-wall BMB-015 opening-cut removes the wall surface inside a door/window and emits distinct inserts. Geometry remains definition-local, and source local transforms are converted exactly once from BMB-009 row-major into BOMC column-major. Mirrors, shear, nested parent transforms, and nonuniform scales are retained.

Required sections: 1 MODEL, 2 STRINGS, 11 DEFINITIONS, 12 INSTANCES, 13 TRANSFORMS, 17 COVERAGE, 20 ENCODING_CONTRACT. Nonempty geometry adds 5 MESHES, 6 FACES, 7 POSITIONS (Float64 lossless), 8 TOPOLOGY (delta-varint loops and triangles), and 9 NORMALS (Float64 codec 3). If real materials exist, add section 3 MATERIALS, version-2 BOMC 1.2 solid-color table. No fake UVs, textures, visual edges or Editor 241 authoring records.

Definitions and module instances are sorted by stable identities; source operations and face annotations use canonical opId/faceKey ordering. String names are sorted and deduplicated; vertex coordinates are deduplicated exactly within each mesh and sorted numerically; oriented triangles are cyclically normalized and sorted. Distinct modules remain distinct because Module IR v1 has no qualified shared geometry-definition reference. BMB-009's in-memory DefinitionGraph supports deterministic reusable *empty group* placements; geometry reuse is not falsely invented.

Each material identity is scoped to moduleId/materialId and preserves authored RGBA and opacity. Real face front/back independent solid-color bindings, role and semantic label are emitted where source mappings exist. For straight uncut walls, BMB-018 face annotation aliases are mapped to BMB-014 polygon faces. Bent-wall top/bottom per-segment annotations and cut-wall face annotations are rejected pending an explicit adapter, not guessed. Stable source IDs inform deterministic face labels; full persistent/debug IDs and Editor editable metadata are not promised by the production profile.

## Coverage, bounds, and reproducibility

Coverage section 17 is computed from **actual emitted face records**: eligible = analytical = serializedFaceCount; fallback = excluded = unaccounted = 0; visualRetained = 0 because no visual edges are authored. Independent tests compare coverage to actual face tables and model counts. Empty geometry remains distinguishable: BMB-019 metadata-only output has zero geometric coverage.

Model bounds are recomputed from generated vertices transformed to assembly world coordinates, including nested mirrors/shear. Module-provided bounds are schema-validated hints and cannot override computed true geometry bounds.

Reproduce with public, wholly synthetic input fixtures:

    python -m pip install jsonschema==4.23.0
    python -m bomc.compiler.graph_to_bomc --input examples/bmb020-semantic-floor.json --output output.bomc
    python -m bomc.compiler.graph_to_bomc --input examples/module-ir-two-rooms.json --output rooms.bomc
    python -m unittest discover -s tests -p test_bmb020_semantic.py -v

The first fixture is an actual slab with distinct top front/back materials. The existing two-room fixture contains floor, wall, topology-true door cutout and an assembly with a single-owned shared seam. Tests also generate mirrored/sheared instance geometry, invalid feature cases, and two independent cold Python compilations of nonempty shapes with full-byte/SHA256 equality. The test reader independently parses binary metadata, mesh/face/loop/topology/normal/material sections, checks every reference and CRC, computes winding and triangle-vs-loop area, and verifies nonzero counts. This is independent Builder testing, **not** an original consumer acceptance claim.

CLI receipt: SHA256, byte size, node count, string count, section IDs, coverage, mesh/face/vertex/triangle/material counts, and geometrySemanticsValid. CLI writes to a sibling temporary file, fsyncs and atomically replaces only after complete successful compilation. On failure, an existing destination remains unchanged, with no advertised partial output. Strict JSON reader caps bytes at 1 MiB; the in-memory API uses the same canonical JSON byte limit. Output is capped at 2 MiB; count/geometry bounds prevent pathological allocation.

## Wire contract evidence

- [BMB-001 pinned producer contract](BOMC-PRODUCER-CONTRACT.md) establishes BOMC 1.2 compact directory, section registry and profile flags.
- [Historical BOMC 1.1 contract](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/BOM_COMPILED_FORMAT.md) documents the section 1–18 layouts. It is **not** an assertion that 1.1 documentation alone proves 1.2 compatibility. The current material version-2 table and normal codec 3 were checked against pinned 1.2 producer/decoder behavior.
- [BMB-017](BMB-017-TRIANGULATION.md) implements independent topology-safe triangulation; [BMB-018](BMB-018-FACE-SEMANTICS.md) validates authored front/back semantic references.
- All implementation is independently authored based on published/layout observations, within the GPL-3.0 clean-room/synthetic-only project policy. No private Editor/Ruby implementation code or private owner fixtures were copied.

## Explicit limitations / NOT_RUN

- BMB-017 primitive triangulation accepts holes, but BMB-006 Module IR v1 has **no hole-authoring field**; any unapproved input field fails closed. No claim of hole semantic BOMC parity yet.
- BMB-016 roof/ceiling/stair models have no matching approved operations in the current BMB-006 schema. General Boolean junctions, bent-wall cutouts, textured/UV materials, complex cut-wall annotations and persistent debug mappings remain unsupported and reject rather than downgrade.
- Original Editor E4 and Model-Eval positive semantic consumer imports, malformed section-241, broad corruption/expansion/adversarial original-consumer tests, and native owner/visual acceptance remain **NOT_RUN**. BMB-021 owns independent interoperability certification.
- Original Ruby producer, Editor and Model-Eval repositories are private; BMB-019's prior optional Actions checkout from Builder was denied (Repository not found). The Builder workflow cannot claim cross-repository positive readback without explicit scoped credentials or separately owner-authorized consumer workflows.

## Review boundary

This compiler provides a genuine, independently tested **nonempty** subset of BOMC 1.2 geometry, not a complete arbitrary building/Exact exporter. Exact-HEAD GitHub Actions evidence is mandatory. Keep PR #55 for independent owner review, do not self-merge and do not claim downstream BMB-021 passes. Track the unproven gates as NOT_RUN rather than PASS.
