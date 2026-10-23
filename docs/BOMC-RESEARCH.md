# BOMC Research and Evidence Ledger — 2026-10-23

This is a **source-backed planning assessment**, not an implemented builder or a certified BOMC writer. The target is an actual 3D compiled BOMC output, but intermediate Lego-like modules live in an independent authoring IR.

## Source findings
1. **Container**: producer source currently declares BOMC version **1.2**, magic BOMC + CR LF 1A LF, 32-byte little-endian header, eight-byte alignment, 24-byte compact or 40-byte legacy directory, section lengths/codecs/counts/CRC32. Current code is newer than the old 1.1 spec. See [producer primitives](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/main/bom_engine/bomc_format.rb) and [historical format spec](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/main/BOM_COMPILED_FORMAT.md).
2. **Graph**: shared definitions and definition-local meshes with nested instances and affine transforms enable reuse without flattening. Face metadata is analytical; positions/topology/normals/UV/texture/visual sections serve distinct needs. Surface roles, front/back materials, coverage and scene metadata must be handled with explicit support policy. See [producer BOMC writer](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/main/bom_engine/bomc_writer.rb).
3. **Coordinates**: existing Model-Eval contract describes right-handed, +Z-up, metres; conversions to Three.js must be explicit and fixture-tested. See [Model-Eval BOMC](https://github.com/KaisAbiyyi/sibambo-model-eval/blob/main/docs/BOMC_MODEL_EVAL.md).
4. **Existing authoring**: Editor contains the private **@sibambo/bomc-document** authoring kernel. It can edit a typed graph and read/write a **web-core-v1** subset of BOMC 1.2. Supports supplied polygon loops/holes and valid triangulations, mesh-backed extrusions, flat RGBA/opacity, shared definitions and affine transforms. It **does not** triangulate or repair topology, edit arbitrary imported E4, author texture/UV/scenes/tags/clips/fallback media. Its package.json sets private:true. See [package contract](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/packages/bomc-document/README.md), [types](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/packages/bomc-document/src/types.ts).
5. **Readers**: Editor e4-import checks magic/version, section bounds/CRC/decode; Model-Eval is an independent BOMC consumer. Never claim compatibility until a pinned golden file passes both. See [Editor container](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/packages/e4-import/src/container.ts).
6. **BMB-003 owner decision:** retain GPL-3.0; owner attests original code ownership; implement Builder independently without copying existing implementation; public fixtures must be synthetic-only. Third-party permissions still require checking. See [decision and audit limits](LICENSE-IP-FIXTURE-POLICY.md).

## Architectural conclusion
- **Authoring transport ≠ BOMC binary**. Store tiny, versioned, agent-diffable modules and one building manifest. Validate/merge a graph, then compile one BOMC with a deterministic writer. Byte-append of individually generated BOMC containers would break offsets, references, deduplication and ownership.
- **Flexible granularity**: wall / room / floor / whole building modules must share stable IDs, local transforms, references, revision hashes, adjacency ports and shared-wall ownership.
- **Avoid a Rooms dependency**: Sibambo Rooms can later provide better spatial validation, but an LLM plus deterministic geometry primitives can create synthetic room shells now.
- **Do not equate builder output with exporter Exact lossless-from-SKP profile**. The builder authors new geometry; release promise is valid deterministic BOMC in declared subset, not automatic fidelity to a non-existent SKP source.
- **Do not equate MCP with spatial intelligence**. It exposes tools; the actual work is geometry primitives, planning rules, validation and localized repair.

## Unknowns / blockers before production code
- BMB-001: pin producer HEAD and enumerate v1.2+ section versions and required writer rules, beyond historical 1.1 prose.
- BMB-002: establish interoperable editor authoring subset and whether source sharing is authorized; distinguish reuse-vs-clean-room adapter.
- BMB-003: decision recorded in [License/IP/Fixture Policy](LICENSE-IP-FIXTURE-POLICY.md); per-change provenance checks remain open.
- BMB-005/007: synthetic public fixtures and cross-repo golden import matrix.
- Surface triangulation, door openings, shared wall seams, and consumers' tolerance for authoring metadata remain unproven.

## Acceptance evidence
Synthetic golden models: empty; one floor; one room shell; two rooms with a single shared wall and a real door opening; nested and mirrored instance; tiny roof. Compile twice with identical SHA, inspect section integrity, import into Editor/Model-Eval, verify geometry/analytic faces/transform/material counts, and reject CRC/offset/invalid refs/oversized payload. Mark human visual/Windows gates **NOT_RUN** until they happen.

External reference: [MCP July 2026 spec announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/).
