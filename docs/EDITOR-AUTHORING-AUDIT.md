# BMB-002 — Pinned Editor authoring kernel / writer boundary audit

**Status:** P0 research contract, cloud-only **read-only** source audit (2026-10-24); **not** a new Builder implementation, consumer certification, or performed executable test.  
**Editor source pin:** [`KaisAbiyyi/sibambo-editor@641a6f84a28ba3ed50610aaabd47b76d913c4e22`](https://github.com/KaisAbiyyi/sibambo-editor/commit/641a6f84a28ba3ed50610aaabd47b76d913c4e22) (`main` observed at audit). Never silently switch this evidence to moving `main`.  
**Builder target:** `KaisAbiyyi/sibambo-bomc-builder`; lock `research/authoring`.  
**Companion decisions:** [BMB-001 producer contract](BOMC-PRODUCER-CONTRACT.md), [BMB-003 owner-approved clean-room/IP/fixture policy](LICENSE-IP-FIXTURE-POLICY.md), [BOMC version adapter policy](BOMC-VERSIONING.md).

## 1. Which kernel is being audited?

The Editor workspace's [package contract](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/README.md) identifies `@sibambo/bomc-document@0.1.0` as a **private workspace package** and calls its restricted authoring profile **`web-core-v1`**. Its [package manifest](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/package.json) sets `private: true` and depends on `fflate ~0.8.2`. It is separate from the Editor's general-purpose **E4 BOMC import/viewing loader**; being viewable in Editor does **not** imply the file can be opened into an editable `BomcDocument`.

Source modules pinned for this decision:

| Source | Observed responsibility |
| --- | --- |
| [`src/types.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/types.ts) | Narrow graph shape, eight typed edit commands plus rename, revision tokens, error families and write results |
| [`src/document.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/document.ts) | Graph ownership, validation, canonical order, atomic transactions, revision and bounds |
| [`src/writer.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/writer.ts) | BOMC serialization, warm/section caches, compression, atomic publication, SHA-256 |
| [`src/section-codec.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/section-codec.ts) | Declared section emission and restricted web graph encode/decode |
| [`src/reader.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/reader.ts) | Strict `web-core-v1` restoration from known section 241 |
| [`src/binary.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/binary.ts) | BOMC 1.2 header/directory, CRC and stored section bounds/codec enforcement |
| [`src/source-envelope.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/source-envelope.ts) | Unmodified source-envelope retention; no semantic edits |
| [`src/consumer-compatibility.test.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/consumer-compatibility.test.ts) | In-repo test **definitions** covering Editor, Rooms and Benchmark *viewer* loaders, not an execution receipt |
| [`src/roundtrip.test.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/roundtrip.test.ts) | In-repo authoring graph round-trip test definitions |
| [`src/writer-cache.test.ts`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/writer-cache.test.ts) | In-repo cache/abort/observer safety test definitions |

These are interface/behavior observations. **No code, test fixtures, or implementation from the private package is copied or vendored into Builder.**

## 2. Supported graph edits and their validity boundary

The canonical [graph type](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/types.ts) has `documentId`, `name`, a root definition and root instance, plus **materials, definitions, meshes, instances**. Faces belong to definition-local meshes; instance rows reference reusable definitions; all numeric vertex positions are JavaScript number / Float64 in authoring memory. The graph has no explicit wall, door, room, roof, module-port, or shared-wall ownership primitive.

| Supported command / behavior | Boundary relevant to Builder |
| --- | --- |
| `set-name` | Renames document. |
| `put-material`, `delete-material` | Solid RGBA (8-bit channels), separate 16-bit opacity. Face front/back material and instance material references must resolve. |
| `put-definition`, `delete-definition` | `model` root, `component` and `group` definitions with optional single mesh reference; graph must keep **one** root model definition. |
| `put-mesh`, `delete-mesh` | Position triples and faces with supplied outer loop, zero or more hole loops, **supplied** triangles, unit normal, front/back material, hidden flag, numeric surface/role code and optional label. No triangulation is generated by this transaction API. |
| `put-instance`, `delete-instance` | Nested group/component occurrences, local 4×4 affine matrices (including nonuniform scale, shear and mirror), visibility, material, labels, role code; root instance identity is fixed. |
| `transact(edits[])` | Ordered batch applies to a draft, full graph validated and committed atomically. On failure, graph/revision stay unchanged; no-op preserves revision. Not a journal, cross-module transaction, durable rollback log or concurrency API. |
| `snapshot()`, `fromGraph()`, `create()`, `dispose()` | Immutable owned snapshot, canonical record order, root creation, validate on admit, explicit lifetime. Revision counters and change-specific tokens support writer-cache invalidation but **do not** implement caller-supplied compare-and-swap/idempotency keys. |
| Bounds / graph traversal | Nested transformed bounds are derived; invisible geometry may still count in derived bounds; unreachable definition geometry is excluded. Bounds are not a collision/seam/door-clearance validator. |

[Document implementation](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/document.ts) requires global unique IDs across material/definition/mesh/face/instance records, cross-references and a root pair, matching instance/definition kinds and an acyclic definition-instantiation DAG. It checks affine bottom-row, invertible/finitely representable transformations, finite positions, face index/ring shape, triangle orientation against the normal, unit normals (within 1e-9) and face planarity (tolerance `1e-9 × max(1, local diagonal)`). The triangles must reference ring vertices and have positive orientation; this **does not** prove full polygon topology, hole coverage, manifoldness, connectedness, adjacency, door passability or self-intersection repair.

**Authoring exclusion:** unknown graph keys, unsupported edit types, non-ordinary arrays/records and unsupported semantic fields are rejected rather than silently persisted. Geometry and material editing is constrained to exactly the declared graph; arbitrary imported E4 data is not editable by this kernel.

## 3. BOMC write profile: proven-by-source behavior, not cross-consumer certification

The pinned [writer](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/writer.ts) writes `BOMC 1.2`, using [`web-core-v1` codec definitions](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/section-codec.ts) and a **24-byte compact directory**, **32-byte header**, eight-byte section alignment, and exact header flags `0x11`. Directory codecs are **0 STORE** or **1 zlib DEFLATE**; section flags are zero; stored bytes receive CRC32; bytes are SHA-256 hashed. Output result labels itself `profile: 'exact'`, but this is **not** evidence that an unrelated SketchUp source was re-exported losslessly or that BOM Engine Exact has full feature parity.

| Section IDs | Emission condition |
| --- | --- |
| `1, 2, 11, 12, 13, 17, 20, 241` | Always emitted, including a blank graph |
| `3` | Only when materials exist |
| `5, 6, 7, 8, 9, 14` | Only when meshes exist |

Section **241** is the Editor's BWEB **editable authoring payload**, **not** a section produced by the pinned Ruby BOM Engine at [BMB-001](BOMC-PRODUCER-CONTRACT.md). The other section IDs are ordinary visual/analytical BOMC sections. Metadata unsupported by this profile (tags `4`, UV `10`, textures `15/16`, fallback `18`, scenes `19`, clips `21`, debug `240`) is **not emitted**; no silent claim of preserving them through an edited re-export.

The writer supports `compressionMode: 'auto' | 'store-only'` (`auto` considers DEFLATE for raw sections at least 64 bytes and keeps it only when shorter), progress callbacks, abort signal, one active write at a time, private returned copies, and revision/section caches. A successful serial write emits a new 1.2 container with its own section directory; it does **not** concatenate separately authored BOMC files. A checked `Uint32` offset/length/count ceiling and actual allocation limits still apply; **there is no demonstrated safe memory/time acceptance budget for arbitrary huge house graphs**. Stated timings and peak estimates in the write result are instrumentation, not benchmark guarantees.

## 4. Read/import operations are deliberately narrower than viewing

**Editable restoration:** [`readWebBomc`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/reader.ts) copies input, requires BOMC **major 1, minor 2**, web compact flags **`0x11`**, exact allowed section set, mandatory **`1,2,11,12,13,17,20,241`**, and a recognized BWEB section **241**. It validates section types/order/counts, per-section CRC, bounds, decompression length and decoded graph. A sectioned Ruby-produced 1.2 BOMC *without 241* is **not** consequently editable by this API. It does not promise reading versions **1.0/1.1/1.3/2.0**, or a future/unrecognized BWEB schema.

**Unchanged byte retention:** [`retainBomcSource`](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/source-envelope.ts) accepts a structurally valid **1.2** source envelope (including wider directory and a broader subset of codec/section flags) and can return an unchanged byte-for-byte copy. Its declared integrity level is **`directory-and-stored-crc`**: container boundaries and stored CRC are checked, **not** full graph semantics, decompressed payload validity, render suitability or editability. It must not be treated as a way to inject edits into imported opaque sections.

**Viewer-loader distinction:** the Editor's broad [E4 import loader](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/e4-import/src/bomc-loader.ts) is different from the private author's strict `readWebBomc`. The pinned in-repo [consumer-compatibility test definitions](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/consumer-compatibility.test.ts) attempt to load **12 synthetic graph variants** in **Editor, Rooms and Benchmark** using external loader paths and check geometry/counts/materials/occurrences. This test source is useful precedent but **was inspected, not executed by this BMB-002 session**; it does **not** include Model-Eval as a proven reader, and its relative sibling-repo paths are not guaranteed to exist in every cloud CI checkout.

### Feature/capability decision table

| Capability | Editor `web-core-v1` source status | Builder decision |
| --- | --- | --- |
| Stable definitions/instances, nested affine transforms | Supported under graph invariants | Specify independently in BMB-006/009; synthetic test cases |
| Flat RGBA, front/back material, hidden/role/label face metadata | Narrow supported subset | Target as future compatible subset; semantic mapping tests BMB-018 |
| Polygon loops/holes/extruded meshes | Accepted **only with supplied valid triangles** | Independently create + triangulate/validate in BMB-013–017 |
| Editable imported arbitrary BOMC / opaque section preservation after edits | **Not** supported | Fail closed; do not offer editing by `copyUnchanged` |
| Tags, UVs, textures, scene/clip state, fallback, arbitrary E4 features | Unsupported in authoring profile | Exclude from MVP; explicit capability error rather than drop |
| BSON or future BOMC versions 1.3/2.0 | No evidence of support | Version-dispatch adapters only after new pinned schema + golden tests |
| Atomic graph edit, cache invalidation | Supported within one in-memory document | Independent Builder mutation core + durable module journal/revision discipline; no source reuse |
| Production consumer compatibility | Existing test definitions for three viewer loaders; not run here | BMB-005 matrix and BMB-007/021 actual fixture+consumer CI gates |

## 5. Reuse-vs-independent adapter selection (owner decision applied)

**Selected:** **independent clean-room Builder IR and BOMC 1.2 adapter**, using documented format and *observable behavior* as an interoperability target. License remains **GPL-3.0**, public fixture policy remains **synthetic-only**, as decided in BMB-003. The owner's original-code ownership statement does **not** override the instruction against implementation copying.

| Candidate | Choice | Reason/gate |
| --- | --- | --- |
| Import `@sibambo/bomc-document` directly or copy, port, vendor its source/test fixtures | **Rejected** | Package is private and BMB-003 mandates clean-room independently authored code |
| Fork shared implementation or mechanically translate private TypeScript codec | **Rejected** | Violates selected independent implementation strategy, even when author asserts ownership |
| Observe the pinned field/section/capability contract, document requirements and write new adapter | **Chosen** | Separates reusable behavior contract from implementation provenance and allows later adapter versioning |
| Use Editor's public read/view API **as an external test consumer**, not runtime writer | **Candidate, gated** | Valid only with pinned consumer SHA, lawful synthetic fixtures, executable CI readback and count/material/transform checks |
| Preserve original input bytes untouched as an optional independent read-only pass-through | **Deferred** | Not a replacement for authored-graph BOMC and not permission to mutate opaque sections |

This code-inspection audit **does not certify a formally independent two-team legal clean-room process**. Implementation tasks must separately record provenance, write original code rather than translate inspected routines, and use independently generated synthetic fixtures.

## 6. Explicit handoff and measurable gates

1. **BMB-005:** Build producer / Editor-`web-core` / Editor-E4-viewer / Model-Eval matrix. Pin each consumer source SHA separately, test whether section 241 is accepted/ignored, header flags, required/optional IDs and exact readback of transforms, topology, material roles. Distinguish static source claims from executed PASS. Do not mistake the `consumer-compatibility.test.ts` existence for current successful CI.
2. **BMB-006:** Define version-independent Builder module IR: unique ID namespaces, ownership, stable local transforms, graph DAG, supplied/generated triangulation contracts, explicit typed capabilities, semantic materials, intended spatial ports; `BOMC 1.2` specifics belong only in output adapter.
3. **BMB-007:** Generate new **synthetic-only** golden graphs/files. Minimum: empty, solid floor, holed wall, concave face, nested/mirrored/sheared instances, independent face materials, bad CRC, bad section 241, unknown header flags/version, plus corruption and resource-budget cases. Record reproducible seeds and two-cold-write byte hashes. Avoid sourcing any private real-house geometry.
4. **BMB-019/021:** Author BOMC writer independently from the approved wire spec, then run *real* Editor and Model-Eval tests at pinned consumer SHAs before declaring interoperability. Keep unsupported features as typed failures and ensure section 241 is never claimed as a universal format requirement.
5. **Upgrade path:** New BOMC 1.3/2.0 adapters require independently approved wire schema, capability negotiation, migration/fixture coverage and consumer acceptance. IR and geometry core must not embed `241` or legacy directory layout as universal invariants.

## 7. BMB-002 execution evidence boundaries

- **PASS (source inspection):** pinned Editor `641a6f84a28ba3ed50610aaabd47b76d913c4e22`; package boundary, graph commands/invariants, write section inventory, read vs source-envelope semantics, reuse-vs-independent decision and downstream gates cross-checked against named sources.
- **NOT_RUN:** Bun document/roundtrip/cache tests, standalone executable synthetic binary generation, three viewer-loader compatibility tests, Model-Eval consumer acceptance, Windows/native visual review and resource-fuzz/performance benchmarking in **this** task. In-repo test definitions cannot establish an executed PASS.
- **CI:** inspect the exact Builder PR head and workflow/check results when submitted; missing checks = **NOT_RUN**, never PASS. Docs-only acceptance does not imply the actual writer works.
- **No Editor/producer/Rooms files mutated.** Only the Builder's new documentation artifact is authorized by lock `research/authoring`.

[Task #2](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/2) · [Notion BMB-002](https://app.notion.com/p/402c4a6aaf73811cacccef6506c3814a).
