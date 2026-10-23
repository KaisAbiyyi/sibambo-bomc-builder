# BOMC version evolution — Builder compatibility contract (proposed architecture)

**Design outcome of BMB-001, 2026-10-23.** This is a **forward-compatibility design**, not an implemented BOMC 1.3/2.0 adapter. Current pinned producer emits 1.2; see [observed contract](BOMC-PRODUCER-CONTRACT.md).

## Principle and ownership boundaries

`Agent/CLI/MCP → versioned Builder module IR → validated normalized scene graph → capability-negotiated BOMC adapter (1.2 / future 1.x / future 2.x) → file → independent consumer test`

The **IR, geometry primitives, transforms, stable IDs, ownership/seams, revision journal, and spatial validation** MUST NOT encode BOMC header offsets, section numbers, compression codec IDs, binary size limits, or private Editor authoring section 241 as persistent IR facts. Encoding versions belong solely to binary adapters. IR migrations (if independently needed) are versioned separately.

The construction core is allowed to exist before a binary writer. The Builder produces one canonical graph and each versioned backend compiles from that same graph. No naive concatenation of binary `.bomc` files, and no hidden rewriting of established fixtures.

## Proposed adapter boundary (not executable yet)

```text
NormalizedAssemblyIR (own schemaVersion) + BuildIntent + Limits
  -> negotiate(target BOMC version, required features, consumer capability evidence)
  -> BomcBackend (pinned implementation, version-specific)
  -> { artifactBytes, formatVersion, usedSections, usedCodecs,
       effectiveFeatures, explicitlyDroppedFeatures, sourceSpecCommit,
       compilerVersion, sha256, validationReceipt }
```

**Interfaces to specify at BMB-006/019**, not invented implemented APIs:

- `supports(major,minor,features,consumerProfile)` returns `supported | unsupported | needs-evidence` and explicit reason.
- `validateFeatureCoverage(IR, target)` distinguishes required vs optional authoring features, semantic loss, topology/UV/material/scene preservation. Default: fail on unsupported required features, **never silent loss**. Opt-in lossy export must be explicit and report exactly what is dropped.
- `encode(IR, targetVersion, declaredProfile)` chooses pinned backend; `decode/inspect` is a **separate** optional capability, not implied by writing.
- `verifyArtifact` validates header, directory, CRC, bounds, references, deterministic hashes, geometry invariants and supported-version provenance; independent Editor/Model-Eval round-trip is an additional gate.
- Adapter registry keyed by **exact** `major.minor` plus build revision/profile/feature set; no optimistic `if major == 1 accept minor >= 2` checks.

## Upgrading versions safely

| Change | Policy | Required evidence |
| --- | --- | --- |
| BOMC 1.2 today | Pin source/spec revision. Implement separately authored `bomc-1.2` adapter; preserve compatibility and golden SHA | Unit writer/reader corruption tests, synthetic fixtures and independent consumer acceptance |
| BOMC 1.3 (hypothetical) | New specification revision, inventory added/changed sections/flags/codecs/required fields and reader acceptance. Add `bomc-1.3` adapter or proven safe extension while **retaining 1.2** | New synthetic 1.3 goldens, backward/forward matrix per consumer, semantic parity vs 1.2 on shared features |
| BOMC 2.0 (hypothetical) | **Assume breaking** until a signed-off contract exists; may change header, directory, byte order, ID widths, payload semantics. Implement a separate backend/parser, not minor-version arithmetic | Version-specific parser/serializer tests, malformed input guards, version migration policy, independently pinned readers |
| Unknown/future input version | Identify **only within documented safe header bounds**, then fail gracefully with `UNSUPPORTED_BOMC_VERSION` and context, or route to explicitly installed parser | Negative tests for 1.3/2.0/invalid magic/truncation without OOB access |
| New unknown section/flag/codec | No blanket “ignore unknown”. Allow skipping a section **only if** that target version explicitly marks it optional and safely skippable; unknown critical flags/encoding reject | Compatibility spec + optional/critical differential fixtures |
| Consumer only accepts 1.2 | Offer/export 1.2 **only when all requested features can be represented**; otherwise return incompatibility with corrective options | Pinned Editor/Model-Eval readback for actual chosen version |

Do **not** call a 1.3 or 2.0 format “supported” because a magic value, header length, and CRC still parse. Preserve the exact original format on reading where required; conversion may be lossless, partially lossless, or unsupported and must be declared explicitly. For major-version changes, no automatic binary roundtrip guarantee.

## Consumer negotiation and release gates

Every supported BOMC adapter gets a matrix row keyed by `producerSpecSha, builderWriterSha, outputVersion, profile, requiredFeatures, consumerName, consumerSha, fixtureSha`. Values must include `PASS / FAIL / NOT_RUN`, limits and explicit unsupported cases. App capability is **per consumer and version**, never inferred from Builder output alone.

Release of a new output version requires: documented normative revision, clean-room/third-party provenance check, synthetic goldens (with seed/script/hash), deterministic same-input SHA under pinned toolchain, corruption/fuzz tests, geometry and metadata semantic parity, verified independent consumers, and a downgrade/no-downgrade decision. Visual/Windows gate remains NOT_RUN until actually performed.

**Fallback semantics:** `auto` output version may select the latest **proven** version common to requested capabilities and target consumers, not the latest label present in source; explicit output pins override auto and fail if incompatible. Legacy exports remain selectable until explicitly retired with migration notice. Do not auto-downgrade and discard scenes, textures, or analytical topology.

**Change detection:** when upstream BOMC producer HEAD changes, re-audit source and compare version constants, section ID map, flags, codec map, required section policy and reader guards before a version support claim. CI should detect contract drift and *fail/flag* rather than silently accepting changed specs. Version declaration is not proof that a feature exists.

## Scope and honesty

BMB-001 has **documented** pinned v1.2 facts and forward-compatible architecture guidance, but implemented zero adapters. The decision is compatible with both incremental v1.3 and breaking v2.0 in architecture; actual acceptance is gated on future specs and tests. BMB-006 owns IR schema; BMB-005 owns concrete producer–consumer compatibility; BMB-007 owns synthetic fixture harness; BMB-019/020 own binary writer/compiler implementation. No private source copied; see [BMB-003 license policy](LICENSE-IP-FIXTURE-POLICY.md).
