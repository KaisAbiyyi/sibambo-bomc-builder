# BMB execution task index — detailed 32-task WBS

[Notion standalone project hub](https://app.notion.com/p/402c4a6aaf738181adf0eb95320ff947) | [Notion task database](https://app.notion.com/p/2e112a1b046641b6a5cb35589ed14b8f) | [Roadmap](ROADMAP.md).

**As of 2026-10-24 (after baseline merges):** BMB-005 PR #38 and BMB-007 PR #40 are DONE for scoped **evidence matrix** and **container-only** fixture acceptance, respectively. Semantic cross-consumer proof is NOT_RUN and belongs to BMB-021 after writer/compiler. Eligible Now: BMB-008,009,013,014,018,019 (all distinct locks, Ready unless claimed after this snapshot). Direct-successor Up Next: BMB-010,011,015,016,017. Task status is independent of Focus Lane; use live Notion for current claims and readiness. No count cap on Now/Up Next. No private code or real-house fixtures.

| ID | Phase | Small deliverable | Depends on BMB IDs | Exclusive lock |
|---|---|---|---|---|
| BMB-001 | P0 | Pin current BOMC 1.2 producer contract | — | research/producer |
| BMB-002 | P0 | Audit Editor authoring kernel subset and reuse options | — | research/authoring |
| BMB-003 | P0 | License/IP/fixture publication decision | — | governance/license |
| BMB-004 | P0 | MCP threat model and agent baseline design | — | research/agent |
| BMB-005 | P0 | Evidence-classified producer/editor/evaluator matrix baseline (NOT semantic interchange certification) | 001,002 | contract/compatibility |
| BMB-006 | P1 | Versioned module IR and spatial port schema | 001,002 | contract/module-ir |
| BMB-007 | P1 | Deterministic **container-only** synthetic fixture harness (NOT geometry goldens) | 001,002 | tests/fixtures |
| BMB-008 | P1 | Stable IDs, revisions, idempotency and stale-write detection | 006 | core/identity |
| BMB-009 | P1 | Definition-instance DAG and nested transform operations | 006 | core/graph |
| BMB-010 | P1 | Module journal with reopen/rollback | 008 | core/storage |
| BMB-011 | P1 | Assembly merge and shared-wall seam ownership | 008,009 | core/assembly |
| BMB-012 | P1 | Assembly validation API and typed diagnostics | 011 | core/validator |
| BMB-013 | P2 | Parametric floor slab primitive | 006,007 | geometry/floor |
| BMB-014 | P2 | Parametric wall runs and junctions | 006,007 | geometry/wall |
| BMB-015 | P2 | Real door/window topology cutouts | 014 | geometry/openings |
| BMB-016 | P2 | Roof/ceiling shell and simple stairs starter | 013,014 | geometry/roof |
| BMB-017 | P2 | Polygon triangulation with holes and normals | 013,014 | geometry/triangulation |
| BMB-018 | P2 | Solid materials, semantic faces and labels | 006,007 | geometry/semantics |
| BMB-019 | P3 | BOMC writer adapter for proven subset | 005,007 | bomc/adapter |
| BMB-020 | P3 | Deterministic graph-to-BOMC compiler | 011,019 | bomc/compiler |
| BMB-021 | P3 | Independent **semantic** BOMC interoperability, positive roundtrip and real consumer corruption certification | 020 | tests/interop |
| BMB-022 | P4 | Headless CLI create/inspect/edit/validate | 006,011 | agent/cli |
| BMB-023 | P4 | Stdio MCP server with bounded typed tools | 004,022 | agent/mcp |
| BMB-024 | P4 | Scoped context retrieval and resumable sessions | 008,022 | agent/context |
| BMB-025 | P4 | Agent construction guide and sample prompt tests | 023,024 | agent/guide |
| BMB-026 | P5 | End-to-end 3–4-room house with localized revision | 015,016,017,018,020,025 | e2e/house |
| BMB-027 | P5 | Sibambo Editor extension integration seam | 021,026 | integration/editor |
| BMB-028 | P6 | Measured agent workflow benchmarks | 026 | evaluation/metrics |
| BMB-029 | P6 | Optional Rooms evidence adapter interface | 028 | integration/rooms |
| BMB-030 | P6 | Fuzz, limits and MCP adversarial QA | 021,023 | qa/security |
| BMB-031 | P7 | Release packaging and license/owner acceptance | 003,028,030 | release/checklist |
| BMB-032 | P7 | silabs-generator integration handoff contract | 026 | integration/generator |

## Atomic acceptance and execution notes

### BMB-001 — Pin current BOMC 1.2 producer contract
**Prereqs:** none. **Lock:** research/producer. **Execution:** Cloud-first.
**Acceptance:** Pin exact exporter HEAD SHA; enumerate sections 1–21 and 240/241 where supported, version/codec flags, no undocumented assumptions. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-002 — Audit Editor authoring kernel subset and reuse options
**Prereqs:** none. **Lock:** research/authoring. **Execution:** Cloud-first.
**Acceptance:** Record supported graph edits, write/read limits, pin consumer SHA, choose reuse-vs-independent adapter candidates without copying private code. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-003 — License/IP/fixture publication decision
**Prereqs:** none. **Lock:** governance/license. **Execution:** Cloud analysis, owner decision/approval.
**Acceptance:** Inventory GPL-3.0 and private code authorship, seek explicit owner decision on license and permission; synthetic fixtures only until cleared. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-004 — MCP threat model and agent baseline design
**Prereqs:** none. **Lock:** research/agent. **Execution:** Cloud-first.
**Acceptance:** Define path containment, resource budgets, idempotency and benchmark method with baseline scripted prompt. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-005 — Evidence-classified compatibility matrix baseline (DONE)
**Prereqs:** 001,002. **Lock:** contract/compatibility. **Execution:** Cloud-first.
**Acceptance:** Source-pinned BOMC 1.2 required/optional sections, Editor section 241 authoring boundary, Builder target subset, explicit writer/reader **PASS / SOURCE_ONLY / NOT_RUN / UNSUPPORTED** matrix and negative-case inventory; consistency CI green at exact SHA. Only original-consumer-native tested pairings may be PASS. **Ruby/Editor/Builder cross-writer positive semantic import, geometry/material parity and target-consumer corruption gates are deferred to BMB-021.** No false interoperability claims. [PR #38](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/38) squash merged `e29de3446a3a5ec5d82ec9013f2874288bd3d32f`, [CI PASS 40099126783](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/40099126783).

### BMB-006 — Versioned module IR and spatial port schema
**Prereqs:** 001,002. **Lock:** contract/module-ir. **Execution:** Cloud-first.
**Acceptance:** JSON Schema and examples for IDs, local axes, transforms, typed ops, ports, ownership and dependencies. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-007 — Deterministic synthetic container-only fixture harness (DONE)
**Prereqs:** 001,002. **Lock:** tests/fixtures. **Execution:** Cloud-first.
**Acceptance:** Six valid-structure **nonsemantic** synthetic BOMC 1.2 byte containers, SHA/CRC/counters manifest, 10 malformed structural inputs, bounded checker, two cold runs and original Editor/Model-Eval **negative semantic admission** tests. These are NOT valid geometry goldens. **Independent meaningful semantic goldens, cross-consumer positive readback, transformations/face/material parity and malformed section 241 are deferred to BMB-021.** [PR #40](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/40) squash merged `975b06d55622760c43c64b0a057acb89764cc204`, [CI PASS 40099128459](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/40099128459).

### BMB-008 — Stable IDs, revisions, idempotency and stale-write detection
**Prereqs:** 006. **Lock:** core/identity. **Execution:** Cloud-first.
**Acceptance:** Conflicting revisions fail without partial mutation; repeated idempotency key cannot duplicate blocks. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-009 — Definition-instance DAG and nested transform operations
**Prereqs:** 006. **Lock:** core/graph. **Execution:** Cloud-first.
**Acceptance:** Nested/mirrored/sheared instance tests, cycle detection and stable world transforms. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-010 — Module journal with reopen/rollback
**Prereqs:** 008. **Lock:** core/storage. **Execution:** Cloud-first.
**Acceptance:** Persistent independently reloadable small modules, atomic commit and deterministic rollback. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-011 — Assembly merge and shared-wall seam ownership
**Prereqs:** 008,009. **Lock:** core/assembly. **Execution:** Cloud-first.
**Acceptance:** Merge disjoint modules and shared seam into one consistent graph; duplicate wall ownership rejected. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-012 — Assembly validation API and typed diagnostics
**Prereqs:** 011. **Lock:** core/validator. **Execution:** Cloud-first.
**Acceptance:** Check references, bounds, collisions, ports and unresolved seams with metre tolerances and module-scoped errors. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-013 — Parametric floor slab primitive
**Prereqs:** 006,007. **Lock:** geometry/floor. **Execution:** Cloud-first.
**Acceptance:** Validated positive thickness, correctly wound faces and predictable bounds fixture. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-014 — Parametric wall runs and junctions
**Prereqs:** 006,007. **Lock:** geometry/wall. **Execution:** Cloud-first.
**Acceptance:** Wall thickness/height, corners, joins and normals pass shape and seam tests. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-015 — Real door/window topology cutouts
**Prereqs:** 014. **Lock:** geometry/openings. **Execution:** Cloud-first.
**Acceptance:** Cut wall opening and insert door/window; no visually fake solid-wall doors; doorway clearance tested. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-016 — Roof/ceiling shell and simple stairs starter
**Prereqs:** 013,014. **Lock:** geometry/roof. **Execution:** Cloud-first.
**Acceptance:** At least simple gable/flat roof, correct z elevation, junction/collision checks. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-017 — Polygon triangulation with holes and normals
**Prereqs:** 013,014. **Lock:** geometry/triangulation. **Execution:** Cloud-first.
**Acceptance:** Triangulation preserves holes/winding and rejects self intersections/zero area. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-018 — Solid materials, semantic faces and labels
**Prereqs:** 006,007. **Lock:** geometry/semantics. **Execution:** Cloud-first.
**Acceptance:** Front/back material and wall/floor/roof role roundtrip in authored subset. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-019 — BOMC writer adapter for proven subset
**Prereqs:** 005,007. **Lock:** bomc/adapter. **Execution:** Cloud-first.
**Acceptance:** Compile a minimal authored graph into documented BOMC 1.2 profile; reject unsupported features explicitly. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-020 — Deterministic graph-to-BOMC compiler
**Prereqs:** 011,019. **Lock:** bomc/compiler. **Execution:** Cloud-first.
**Acceptance:** Canonical sort/dedup and two cold-compiles identical byte SHA with valid coverages. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-021 — Independent semantic BOMC interoperability and corruption certification
**Prereqs:** 020 (via 019, which consumes *baseline* 005/007). **Lock:** tests/interop. **Execution:** Cloud-first; native owner gates distinct.
**Acceptance:** Independently authored **valid semantic** synthetic BOMC 1.2 goldens and repeatable SHA/count ledger; actual Builder→Editor E4, Builder→Model-Eval, Ruby→Editor E4/Model-Eval, Editor→Model-Eval positive acceptance and face/hole/transform/material/counter parity for supported profiles. Exercise malformed 241/CRC/version/codec/flags/directory/budgets on real target consumers and record each exact fixture/source SHA + CI result (PASS/FAIL/NOT_RUN). Ruby→strict Editor editable remains unsupported by source without 241. This task explicitly inherits BMB-005/007 deferred semantic gates; it is **not** their prerequisite. Self-review exact SHA and sync GitHub/Notion before acceptance.

### BMB-022 — Headless CLI create/inspect/edit/validate
**Prereqs:** 006,011. **Lock:** agent/cli. **Execution:** Cloud-first.
**Acceptance:** CLI commands invoke single shared core; JSON output, stable errors and rollback tests. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-023 — Stdio MCP server with bounded typed tools
**Prereqs:** 004,022. **Lock:** agent/mcp. **Execution:** Cloud-first.
**Acceptance:** Typed schemas, safe paths, counts/bytes/time budgets, error propagation, no shell escape. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-024 — Scoped context retrieval and resumable sessions
**Prereqs:** 008,022. **Lock:** agent/context. **Execution:** Cloud-first.
**Acceptance:** Manifest+neighbors read avoids dumping full scene; checkpoint/replay and token budget evidence. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-025 — Agent construction guide and sample prompt tests
**Prereqs:** 023,024. **Lock:** agent/guide. **Execution:** Cloud-first.
**Acceptance:** Scripted Codex-like controller reproduces create-inspect-validate-revise-assemble; failures documented. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-026 — End-to-end 3–4-room house with localized revision
**Prereqs:** 015,016,017,018,020,025. **Lock:** e2e/house. **Execution:** Cloud-first.
**Acceptance:** 4-room example (2 bedrooms, living, bath), shared walls and doorway, module A revision without other modules rewrite, BOMC import. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-027 — Sibambo Editor extension integration seam
**Prereqs:** 021,026. **Lock:** integration/editor. **Execution:** Separate Editor repository, cloud CI.
**Acceptance:** Independent Editor PR with preview/inspect boundaries; no duplicated construction logic or private->public source leakage. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-028 — Measured agent workflow benchmarks
**Prereqs:** 026. **Lock:** evaluation/metrics. **Execution:** Cloud-first.
**Acceptance:** Reproducible token count, calls, retries, elapsed, memory, model size, geometric acceptance results. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-029 — Optional Rooms evidence adapter interface
**Prereqs:** 028. **Lock:** integration/rooms. **Execution:** Cloud-first.
**Acceptance:** Feature-flagged room detector validator enhancement; entirely optional no core dependency. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-030 — Fuzz, limits and MCP adversarial QA
**Prereqs:** 021,023. **Lock:** qa/security. **Execution:** Cloud-first.
**Acceptance:** Bad indices/CRC/compression bomb/path traversal/deep DAG requests rejected within resource limits. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-031 — Release packaging and license/owner acceptance
**Prereqs:** 003,028,030. **Lock:** release/checklist. **Execution:** Cloud analysis, owner decision/approval.
**Acceptance:** Versioned install docs, provenance, CI evidence; release approval/visual gates recorded as PASS or NOT_RUN honestly. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

### BMB-032 — silabs-generator integration handoff contract
**Prereqs:** 026. **Lock:** integration/generator. **Execution:** Cloud-first.
**Acceptance:** Document survey/form/room-brief -> same agent builder API; no paid LLM requirement for initial proof. Self-review exact SHA, run stated tests, record PASS/FAIL/NOT_RUN, PR/merge evidence, and sync GitHub + Notion.

## Governance
Statuses: Planned (prereqs not met) → Ready (eligible) → Claimed (= In Progress, named agent/session/branch/lock) → Review (tests, CI, implementor self-review, merge/owner gates) → Done only with evidence. Reclaim only for a genuinely blocked prior implementor, not for CI running. Now and Up Next may show multiple truly parallel tasks, not an arbitrary WIP cap. Review is **self-review by implementor**; no other reviewer is mandatory. For every PR: exact HEAD/base diff, code/security/deps, tests/CI, failure gates and native/owner gates; no fabricated PASS. Merge when all applicable gates pass and update Notion/GitHub in the same session.
