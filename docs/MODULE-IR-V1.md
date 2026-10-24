# BMB-006 — Builder module IR v1.0.0 (normative draft)

**Artifact:** [Draft 2020-12 JSON Schema](../schemas/module-ir-v1.schema.json) and [invented two-module example](../examples/module-ir-two-rooms.json). This is an independently authored **authoring format**. It is not BOMC on-wire, a geometry compiler, or proof of Editor/Model-Eval acceptance.

## Units and transforms

Coordinates are metres, right-handed, +Z up, +Y forward. Each module owns local operations; \`localFrame.transform\` is a **row-major 4×4 affine matrix** taking module coordinates to parent coordinates, with translation at indices 3/7/11 and last row \`[0,0,0,1]\`. Nested parent transforms compose parent×child; negative determinant permits mirrors, affine shear and nonuniform scales may be present. Validation of determinant, finite numeric values, cycles, world-space bounds and orientation happens in the semantic validator (BMB-009/012), **not solely in JSON Schema**. Do not transpose matrices when interoperating with another engine.

## Identity and transaction boundaries

IDs use stable slash-separated namespaces (\`house/floor-1/living\`); operation IDs, material IDs, port IDs and seam IDs are local slug identifiers. A module is independently persistable with \`schemaVersion\`, \`revision\`, \`parentId\`, \`dependencies[].minRevision\` and \`provenance\`. The envelope groups modules but is not a full journal. IDs are **not** array positions. Mutation CAS, idempotency and rollback belong to BMB-008/010.

## Operations and ownership

- \`floor-slab\`: 2D outline with explicit thickness and elevation; output triangulation is a separate step.
- \`wall-run\`: local polyline, thickness, height and base elevation.
- \`opening-cut\`: references its owner wall operation and specifies an **actual cutout intent**, not a painted rectangle; real boolean/triangulated result requires BMB-015/017.
- \`materials\`: independent color/opacity/semantic metadata. Unknown feature/role values are rejected by the schema.
- \`ports\`: spatially located, typed interfaces with local 4×4 affine frames, outward normals and explicit peer links.
- \`ownedSeams\`: a **single owner** records wall/seam construction; non-owning modules reference its seam via ports but do not duplicate the geometry. \`participants\` lists both modules. Pairwise port normal opposition, reciprocal peer links and surface association are semantic invariants.
- \`dependencies\`: explicit minimum source revisions for reproducible replay and stale-write detection.

## Mandatory semantic checks **not guaranteed by JSON Schema**

Unique module IDs in envelope; per-module uniqueness of op/material/port/seam IDs; non-self/cycle-free parent and dependency links; bounded and invertible matrices; positive 3D bounds; 2D simple winding/no self-intersections; opening within wall and clipping real topology; material and target wall references; exactly one seam owner across assembly; both peers exist and point back, opposing normals after transforming into world coordinates, port span tolerance, and revision availability. Fail closed rather than silently repairing. Geometry calculations will be implemented downstream.

BOMC version, compression, header flags, section 241, directory format and codec IDs **never appear** in persistent module IR; the output adapter negotiates them. Future IR migration is versioned independently of hypothetical BOMC 1.3/2.0.

## Test recipe

CI installs a pinned JSON Schema validator and runs \`python -m unittest discover -s tests -p 'test_module_ir_schema.py' -v\`: positive two-module example, malformed IDs, negative dimensions, unknown ops/fields, invalid affine final row, missing port peer and unrecognized schema versions. Real geometric validity / consumer readback are **NOT_RUN** until BMB-009/012/019/021.

The example is wholly synthetic and does not use a client's house, third-party geometry, or private Editor source.
