# BMB-001 — Pinned BOMC producer contract (observed v1.2)

**Audit date:** 2026-10-23. **Source pin:** [`sibambo-bom-engine-plugin@988c4ef250e098d627f480a6f571693975227fee`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/commit/988c4ef250e098d627f480a6f571693975227fee).
**Mode:** cloud-only, read-only producer inspection, independently authored documentation per [BMB-003 clean-room policy](LICENSE-IP-FIXTURE-POLICY.md).
**Qualification:** code-inspection inventory, not a compiled fixture, independently verified wire conformance, or Editor acceptance certification. Do not silently replace this SHA with `main`.

## Source-of-truth hierarchy

1. [`bom_engine/bomc_format.rb`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_format.rb): container constants, header, section IDs, directory, compression and input validation.
2. [`bom_engine/bomc_writer.rb`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_writer.rb): actual exporter format version, emitted sections, sparsity, flags, profile behavior.
3. [`bom_engine/bomc_decoder.rb`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_decoder.rb): reference reader's required subset and optional decoding.
4. [`bom_engine/bomc_encoding_contract.rb`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_encoding_contract.rb): section 20 internal schema/profile/budget contract.
5. [`bom_engine/bomc_codecs.rb`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_codecs.rb) and [`bom_engine/decode_budget.rb`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/decode_budget.rb): geometry-specific codecs and parser resource limits.
6. [historical `BOM_COMPILED_FORMAT.md`](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/BOM_COMPILED_FORMAT.md): useful background, **describes 1.1**; source code at pinned SHA prevails on differences.
7. Cross-repo observation only: [Editor BOMC authoring README](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/README.md) and [Editor reader](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/src/reader.ts) refer to section **241**, **not** part of the pinned Ruby producer's section registry.

All evidence is specific to these source revisions; newer producer behavior requires a new pin and change audit.

## Container and directory — observed

| Field/property | Pinned implementation |
| --- | --- |
| Magic | eight bytes `42 4F 4D 43 0D 0A 1A 0A` (`BOMC\\r\\n\\x1a\\n`) |
| Version emitted by default | **1.2**, major `1`, minor `2`; writer explicitly passes minor `2` with compact directory |
| Legacy emission path | writer `compact_directory: false` produces **1.0**, 40-byte entries; format container supports selecting versions under existing rules, but this does not prove a 1.1 exporter profile was exercised |
| Header | 32 bytes: magic (8), major (u16 LE), minor (u16 LE), endian marker (u32 LE), flags (u32 LE), section count (u32 LE), directory offset (u64 LE) |
| Endian / alignment | marker `0x01020304`; little-endian; 8-byte aligned section payload offsets |
| Directory | compact flag set: **24 bytes**/descriptor, u32 offset/stored/raw/count; legacy: **40 bytes**, u64 offset/stored/raw, u32 count/checksum plus reserved field |
| Per-section descriptor | type u16, compression codec u8, section flags u8, payload offset, stored length, decoded length, logical count, CRC32 of **stored** bytes |
| Ordering | writer sorts sections by numeric ID (stable for equal IDs), directory immediately after header; payloads aligned, may have padding |
| Compression codec in directory | `0=STORE`, `1=zlib-wrapped DEFLATE`; deflate is selected only if shorter when compression is requested. Unknown container compression codec rejected by reference parser |
| Integrity | reader validates magic/version/endian, bounds, overlap, alignment, optional CRC32 (default on), expanded size and decoded length; CRC32 is accidental-corruption detection, **not authentication** |

**Version gate:** pinned `Container.read_directory` accepts **only major 1, minor 0–2**, explicitly rejecting 1.3 / 2.0. Merely bumping a version field is not supported interoperability. [Source](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_format.rb#L344-L361).

**Reference decoder's current limits, not permanent BOMC format limits:** max input 80 MiB, expanded bytes 120 MiB, allocation 256 MiB, sections 64, depth 64 ([decode_budget.rb](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/decode_budget.rb)). These are implementation safety budgets; must not be mistaken for wire-format maxima or promised large-model acceptance. In the compact layout, u32 offsets/lengths additionally constrain section byte ranges. Consumers can impose different limits.

## Header flags: declared values

| Value | Meaning | Pinned writer behavior |
| --- | --- | --- |
| `0x00000001` | production profile | set unless debug |
| `0x00000002` | debug profile | set for debug |
| `0x00000010` | compact 24-byte directory | set by container when compact |
| `0x00000100` | active/active_scene scope | conditional |
| `0x00000200` | all/all_scenes scope | conditional (including nonempty scenes) |
| `0x00000400` | scenes present | set for nonempty scene list |

Source: [constants](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_format.rb#L19-L27); [writer flags and version](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_writer.rb#L227-L241). Bits not listed here are **not specified** by this audit. No claim that unrecognized flags are safe.

## Section registry and emission conditions

The table captures **all defined section IDs** from the pinned producer and whether they are included unconditionally, subject to sparsity, or conditionally. A definition is not proof every output includes that section. With default `sparse:true`, required sections remain even at zero count; nonrequired empty sections are omitted.

| ID | Producer symbol / purpose | Emit policy at pinned writer |
| ---: | --- | --- |
| 1 | MODEL — model/root metadata | Required |
| 2 | STRINGS — string table | Required |
| 3 | MATERIALS — material records | If nonempty; omitted when sparse and count 0 |
| 4 | TAGS — tag records | If nonempty |
| 5 | MESHES — mesh records | If nonempty |
| 6 | FACES — analytical face rows | If nonempty |
| 7 | POSITIONS — vertex positions | If nonempty |
| 8 | TOPOLOGY — polygon/triangle topology | If nonempty |
| 9 | NORMALS — normal blocks | If nonempty |
| 10 | UVS — UV blocks | If nonempty |
| 11 | DEFINITIONS — reusable definitions | Required |
| 12 | INSTANCES — hierarchy/occurrences | Required |
| 13 | TRANSFORMS — affine transforms | Required |
| 14 | VISUAL_EDGES — display edges | If nonempty |
| 15 | TEXTURE_TABLE — texture metadata | If nonempty |
| 16 | TEXTURE_BLOBS — embedded texture bytes | If nonempty; special conditional compression |
| 17 | COVERAGE — analytic coverage | Required |
| 18 | FALLBACK — fallback objects | If nonempty |
| 19 | SCENES — scene states | Added only if scene list nonempty |
| 20 | ENCODING_CONTRACT — fidelity/profile contract | **Required by writer** |
| 21 | CLIP_PLANES — scene clip planes | Added only if clip list nonempty |
| 240 | DEBUG — debug metadata | Added only for debug profile |
| 241 | **No producer constant or exporter emission** at this SHA; Editor's private `web-core-v1` authoring section | **Editor-specific observation**, never treat as canonical producer section or required general BOMC 1.2 |

Evidence: [section constants](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_format.rb#L29-L50), [writer registry](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_writer.rb#L22-L45), [writer assembly and sparsity](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_writer.rb#L185-L226), [Editor contract](https://github.com/KaisAbiyyi/sibambo-editor/blob/641a6f84a28ba3ed50610aaabd47b76d913c4e22/packages/bomc-document/README.md).

**Required distinction:** pinned Ruby exporter requires section IDs **1, 2, 11, 12, 13, 17, 20** when `sparse:true`; its **reference decoder** requires **1, 2, 11, 12, 13, 17** and treats **20** as optional. Therefore “required” is contextual, **not** a universal schema rule. The editor's authoring reader has its own narrower required set including 241. [Ruby reader source](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_decoder.rb#L12-L17), [optional section 20](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_decoder.rb#L122-L128).

## Nested block codecs are a separate namespace

The per-**section compression** values 0/1 must not be confused with **geometry encoding** values inside section payloads. Observed codec enums:

| Logical blocks | Codes from pinned `bomc_codecs.rb` |
| --- | --- |
| Positions | 1 Float64 absolute; 2 Float32 local; 3 Int32 quantized; 4 Int16 quantized; 5 delta-varint |
| Normals | 1 Float32; 2 octahedral Int16; 3 Float64 |
| UVs | 1 Float32; 2 Float16; 3 Int16 quantized; 4 delta-varint; 5 Float64 |
| Transforms | 1 Float64 3x4; 2 Float32 3x4; 3 decomposed Float32; 4 decomposed quantized; 5 hybrid; 6 Float64 4x4 |

Source: [codec definitions](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_codecs.rb). This is an ID inventory, **not** a complete normative byte-level schema for every nested block. Implementations need explicit per-codec framing, error limits and fixture tests.

**Section 20**: schema version `1`, encoded length **76 bytes**, internal profile IDs `1=exact`, `2=research`, `3=visual`, texture policy IDs 1–3, encoder revision 1. This is profile metadata inside BOMC 1.2, **not** the container's major/minor. Source: [encoding contract](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/988c4ef250e098d627f480a6f571693975227fee/bom_engine/bomc_encoding_contract.rb). Pinned producer still contains a `research` enum; do not infer from it which UI profiles are currently active.

## Current behavior, unknowns and BMB-005/007 handoff

**Verified by source inspection:** default exporter major/minor, flags, section registry 1–21/240, optional sparse emission, two per-section compression codecs, geometry codec IDs, section 20 schema, reference reader's strict version rejection, and Editor section-241 distinction.

**Not proven:** cross-consumer 1.2 readback at pinned Editor/Model-Eval commits; wire behavior of every nested payload (requires targeted contract archaeology + fixtures); robustness against malicious future flags/unknown sections across all consumers; large-file acceptance beyond reference decoder budgets; new BOMC 1.3 or 2.0 specs (none approved here); release-level clean-room implementation. **No synthetic fixture binary or executable tests were created by BMB-001.**

**Follow-up:** BMB-002 must verify Editor authoring subset without copying implementation; BMB-005 must version-pin actual consumer HEADs and create evidence rows per version+profile+section; BMB-007 must create **synthetic-only** fixtures, deterministic hashes, corruption/unknown-version tests, and real consumer round-trip. Any new producer revision needs a new contract inventory and source pin.

See [future-version architecture policy](BOMC-VERSIONING.md).