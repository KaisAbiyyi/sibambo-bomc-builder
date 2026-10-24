# BMB-005 — Producer / Editor / Model-Eval compatibility matrix

**Evidence status (2026-10-24):** independently authored compatibility inventory and machine-readable gate matrix. This document does **not** certify executable interchange. Source snapshots are immutable pins, not moving main.

- SketchUp/Ruby producer: \`KaisAbiyyi/sibambo-bom-engine-plugin@988c4ef250e098d627f480a6f571693975227fee\`
- Editor authoring + viewer: \`KaisAbiyyi/sibambo-editor@641a6f84a28ba3ed50610aaabd47b76d913c4e22\`
- Model-Eval: \`KaisAbiyyi/sibambo-model-eval@7be03cdccc7ce2b390c639d4ceb7e16d7ecbb254\` (indexed reference only; no executed 1.2 acceptance evidence)
- Sources in this Builder: [Producer contract](BOMC-PRODUCER-CONTRACT.md), [Editor audit](EDITOR-AUTHORING-AUDIT.md), [Versioning](BOMC-VERSIONING.md), [Machine-readable matrix](../compatibility/bomc-1.2-matrix.json).

## Section policies and versions

| Writer or reader | Version | Required | Optional / conditional | Special case |
| --- | --- | --- | --- | --- |
| Pinned Ruby production **writer** | 1.2 compact | 1,2,11,12,13,17,20 | 3–10,14–16,18,19,21,240 when emitted | Not 241 |
| Pinned Ruby reference **decoder** | 1.0–1.2 | 1,2,11,12,13,17 | Including 20 | Writer requiredness != decoder requiredness |
| Editor private \`web-core-v1\` **writer** | 1.2 compact | 1,2,11,12,13,17,20,241 | 3,5–9,14 conditional | 241 is its private editable graph envelope |
| Editor \`readWebBomc\` editable **reader** | strict 1.2 / flags 0x11 | 1,2,11,12,13,17,20,241 | only narrow editor emission set | No arbitrary Ruby BOMC editing |
| Editor E4 **viewer** | separately gated | Must verify on each binary fixture | Broad viewer path != editable path | 241 handling requires executed readback |
| Model-Eval **viewer** | historical docs 1.0/1.1 | No new 1.2 certification | 1.2, 241, nested semantics to test | Pin and run actual reader for verdict |

Numbers denote **section types**, not nested geometry codec IDs. Compact directory 24 bytes and legacy 40 bytes are container profiles. The Ruby 1.2 writer requires section 20 in sparse output while its decoder only requires 1,2,11,12,13,17. Editor authoring additionally depends on 241. Treat 1.3 and 2.0 as unsupported until independently specified and tested.

## Interoperability verdict by pairing

| Writer -> consumer | Current evidence | Executable result |
| --- | --- | --- |
| Ruby 1.2 -> Ruby decoder | Source code includes corresponding v1.2 parser | **NOT_RUN** (source-only) |
| Ruby 1.2 -> Editor editable | **Unsupported by source**: missing section 241 | Not a valid editable-import path |
| Ruby 1.2 -> Editor E4 viewer | Plausible import path | **NOT_RUN** |
| Ruby 1.2 -> Model-Eval viewer | Historical contract insufficient to prove 1.2 | **NOT_RUN** |
| Editor \`web-core-v1\` 1.2 -> strict Editor editable | Source-defined writer+reader | **NOT_RUN** (source-only) |
| Editor 1.2 -> Editor E4 viewer | Test definitions exist, execution not verified | **NOT_RUN** |
| Editor 1.2 -> Model-Eval | Unknown 241/version semantics | **NOT_RUN** |
| Builder 1.2 -> all consumers | Writer deferred to BMB-019/020 | **NOT_RUN** |

Do not promote test **definitions** or structural parse to a PASS. The future Builder target subset is BOMC **1.2 compact**, a validated normalized graph with 1/2/11/12/13/17/20, optional face/geometry/material sections 3/5/6/7/8/9/14 when the writer is implemented; *authoring* 241 is **not a universal section**. Flat material, nested affine, winding/holes and analytics need explicit semantic parity checks. Do not silently drop scenes, UV/textures, clips, fallback, or unsupported authoring fields.

## Mandatory executable gates for BMB-007/019/021

For each consumer pin, fixture SHA and emitted version/profile, execute at least: minimal root, slab, concave and holed face, nested shared-definitions, mirror + shear, independent front/back materials, source count/transform/face/coverage readback, malformed CRC/codec/version, unknown header flags, malformed 241, truncation/overlap, resource budgets and consumer-specific rejection. Record SHA, command, exit code, error or measured stats. Never infer consumer support for 241 from its ability to skip unknown sections.

**Negative input rule:** corruption is tested *separately* at container integrity and semantic readback layers. An opaque synthetic payload with a sound CRC passes only the former. Real consumer-accepted goldens require independently encoded meaningful payloads under BMB-019/021.

## Current execution distinction

- **PASS:** document inventory based on pinned source audits (BMB-001/002); machine-readable matrix consistency if its CI runs green.
- **NOT_RUN:** new binary fixtures against Ruby/Editor/Model-Eval; 1.2 reader capability discovery; Windows native/visual, topology/material parity and performance.
- **Unsupported by source:** Ruby 1.2 -> strict Editor editable without section 241.
- A clean matrix CI is **not** a binary consumer qualification. See [fixture harness BMB-007](../tests/) when landed.

No implementation or fixture from private upstream consumers has been copied.
