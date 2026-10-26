# BMB-019 — Explicit BOMC 1.2 writer capability envelope

**Implementation:** `bomc/adapter/writer_v12.py`; Python 3.12 standard library only.
**Input:** standalone `bmb-writer-graph-v1` JSON authored node tree; **not** the
BMB-006 module IR, a building mesh, the Editor section-241 authoring envelope,
or the downstream BMB-020 full graph compiler. The adapter deliberately does
not silently down-convert a module IR geometry operation into an empty scene.

This release supports a single identity-transformed `root` model instance plus
up to 127 **empty group** instances, each owned by exactly one parent, with
finite invertible column-major 4×4 local-to-parent affine transforms. Child
definitions are unique per node; material/mesh/tag/texture/face/edge/scenes are
**not supported** and any such field or unknown kind is rejected. This
supports semantic metadata graph structure, **no visible geometry**. Root or
group names are UTF-8 and bounded; topological cycles, orphaned parents, duplicate
IDs, unsupported revisions, NaN/Infinity and singular/non-affine transforms
are rejected. Input and output are bounded at 1 MiB and 2 MiB respectively.

## Runnable synthetic minimal graph

```json
{
  "schemaVersion": "bmb-writer-graph-v1",
  "name": "Synthetic tree",
  "nodes": [
    {"id":"root","kind":"root","name":"Synthetic tree","parentId":null,
     "transform":[1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]},
    {"id":"child","kind":"group","name":"Empty group","parentId":"root",
     "transform":[1,0,0,0, 0,1,0,0, 0,0,1,0, 2,3,0,1]}
  ]
}
```

```bash
python -m bomc.adapter.writer_v12 --input synthetic.json --output synthetic.bomc
python -m unittest discover -s tests -p 'test_bmb019_writer.py' -v
```

## Wire profile and evidence boundaries

- BOMC 1.2 compact 24-byte descriptors; LE header, 8-byte alignment, stored
  CRC32, sorted noncompressed sections, production scope flags `0x11`.
- Real section payloads **1 model, 2 string dictionary, 11 definitions,
  12 instances, 13 Float64 3×4 transforms, 17 zero geometry coverage,
  20 encoding contract**. Section 20 is a 76-byte revision-1 exact profile
  with no originating SketchUp source. Counts and indices agree with payloads.
- The writer is deterministic for permutations of the JSON `nodes` array,
  with canonical sorted IDs (root first) and stable string order. No clock,
  random seeds, or non-canonical zlib compression.
- `PASS` can be asserted for the independent Python subset/structural tests
  **only after exact PR SHA cloud CI has passed**. Ruby producer/Editor/Model-Eval
  semantic readback, semantic geometry fidelity, native/visual acceptance,
  corruption certification, independent fixture oracle, and full BMB-006
  module IR conversion are **NOT_RUN**, assigned to BMB-020/021.
- GPL-3.0; clean-room independent Python code. **Synthetic-only** examples.
  No producer/Editor/Model-Eval implementation copied or linked into Builder.
