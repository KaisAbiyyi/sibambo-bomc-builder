# BMB-018 — Solid RGBA materials, semantic faces and labels

Cloud-only, clean-room authored-subset metadata. BMB-006 and BMB-007 are accepted. No BOMC writer or consumer certification is claimed.

Module IR v1 gains optional **faceAnnotations[]**. Each binding requires opId, faceKey, role (floor/wall/roof), frontMaterialId, backMaterialId and label. Existing materials[] provide RGBA, opacity and optional semanticRole. Both faces can use different solid materials; their references are module-local and fail closed if missing. All labels are bounded and must be nonblank without controls.

Supported **authored** face-key conventions:
- floor-slab with role floor or roof (flat-roof slab intent): top, bottom, side-N (N indexes footprint edges).
- wall-run with role wall: front-N, back-N, top-N, bottom-N (N indexes path segments) and start/end.
- opening-cut has no solid face semantics in this task.

The Python core API validates complete Module IR JSON Schema and cross-references; resolves face roles, labels, solid RGBA/opacity for front/back; and canonically encodes/decodes strict UTF-8 authored module JSON. Face ordering is stable; encoding does not mutate caller objects. Duplicate bindings, missing references, invalid geometry-key indices, role mismatches, duplicate IDs, invalid numeric/Unicode/JSON, unknown fields and unbounded inputs are rejected.

Verification: run python -m pip install jsonschema==4.23.0; then python -m unittest discover -s tests -p 'test_bmb018_semantics.py' -v and existing test_module_ir_schema.py. CI covers Ubuntu and Windows.

**Not delivered / NOT_RUN:** generated polygon mesh, normals/holes, pitched roof, BOMC 1.2 binary material emission, valid semantic goldens or positive Editor/Model-Eval face readback. Those gates are BMB-014/016/017, BMB-019/020 and BMB-021. The BMB-007 containers remain nonsemantic structural baselines.
