# BMB-018 — Solid face semantics (authored module-IR subset)

This is a **clean-room authoring metadata contract** for a solid face. It does not
represent a triangulated surface, a BOMC mesh record, or native Editor / Model-Eval
semantic interoperability. Those depend on BMB-013–017, BMB-019/020 and independent
BMB-021 certification. The binary writer in BMB-019 still rejects geometry inputs.

## Contract

Add an optional `semanticFaces[]` property to each v1.0.0 module. Each record has
exactly `faceId`, `ownerOpId`, `role`, `label`, `frontMaterialId`, and
`backMaterialId`. Both front and back reference `materials[].materialId` **in
the same module**. One face may intentionally have identical materials on both
sides, or different materials. The two sides mean authored front/back assignments;
their outward normals and geometric winding are not determined here.

`role` is one of `wall`, `floor`, `roof`. The owner operation must exist,
and its role must match the face: `wall-run` for `wall`, `floor-slab` for
`floor` or `roof`. A flat roof annotated using a `floor-slab` with
`role="roof"` is only a bounded future construction intent, not the BMB-016
roof-shell implementation. Opening cuts cannot own solid face annotations. A
material's existing optional `semanticRole` describes a material's default
usage, **not** a per-face ownership claim, and is not used to override face role.

IDs are stable per module, not positional. Material, op and face IDs must be
unique within their respective namespaces. Unknown references, duplicate IDs,
mismatched roles, blank/control labels and unrecognized face fields fail closed.
For non-annotated old IR modules the property may be absent; no migration is
necessary. This is an additive optional v1 field, not an incompatible BOMC
wire-version change.

## Boundaries and testing

`core.geometry.semantics.inspect_semantic_faces` checks local references and
returns detached records sorted by `faceId`. `with_semantic_faces` applies a
change without mutating source state. `encode_semantic_module` /
`decode_semantic_module` give a canonical UTF-8 JSON roundtrip **for module IR**,
reject nonfinite numbers, invalid JSON, duplicate JSON keys and documents above
2 MiB. They are not a substitute for full Draft 2020-12 JSON Schema validation,
and do not provide BOMC binary read/write. Cross-module assembly and real topology
validation remain separate.

Synthetic test data: [three labeled faces with different front/back materials](../examples/module-ir-semantic-faces.json).
CI: `python -m unittest discover -s tests -p 'test_bmb018_semantics.py' -v`
with `jsonschema==4.23.0`, plus the existing module-IR schema suite. Positive
cross-consumer semantic readback / BMB-021 remains **NOT_RUN** until its gates.
