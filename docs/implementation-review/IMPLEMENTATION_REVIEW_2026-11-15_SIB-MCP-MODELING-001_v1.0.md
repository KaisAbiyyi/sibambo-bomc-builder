# IMPLEMENTATION REVIEW — SIB-MCP-MODELING-001 WP2 and WP3 preflight

- Review ID: **SIB-MCP-MODELING-001**, version **1.0**, date **2026-11-15, Asia/Jakarta**.
- Author/provenance: Codex primary implementer, session `mcp-modeling-wp2-20261115`; exact underlying model ID unavailable. This is the required implementer check and independent-review handoff, **not independent approval or self-approval**.
- Governing plan: [v2.1](https://github.com/KaisAbiyyi/sibambo-editor/blob/5ec4e47ccd2fa744f640a9fdc7c8d24c827f5e7a/docs/implementation-plan/MASTER_IMPLEMENTATION_PLAN_2026-11-15_SIB-MCP-MODELING-001_v2.1.md), retaining v2.0 WP2 transport contracts.
- Governing summary: [v1.3](../implementation-summary/IMPLEMENTATION_SUMMARY_2026-11-15_SIB-MCP-MODELING-001_v1.3.md); prior [in-progress v1.2](../implementation-summary/IMPLEMENTATION_SUMMARY_2026-11-15_SIB-MCP-MODELING-001_v1.2.md).
- Scope: Builder base **6c358422abfb42bf203a8ac795703ba6512c5fea** → tested source **661685cdc371656823af60e6450d08c473a9eada**, [draft PR #95](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/95); read-only Editor preflight at **5ec4e47ccd2fa744f640a9fdc7c8d24c827f5e7a**.
- Gate verdict: **WP2 CP2 PASS. WP3 BLOCKED → REVIEW/PLAN** because its rollback-helper contract contradicts invariant 3. No merge or review approval.
- Supersedes: none; new review topic. Revision history: v1.0 first implementer source check / independent-review handoff.

## Verified checks and limits

[CP2 run 43630237670](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43630237670) **SUCCESS** on source `661685cdc371656823af60e6450d08c473a9eada`:

| Automated check | Ubuntu | Windows |
|---|---|---|
| Targeted WP2 + local-demo | 27 PASS / 0 FAIL | 27 PASS / 0 FAIL |
| Full Builder discovery | 814 PASS / 0 FAIL | 809 PASS / 0 FAIL / 5 existing platform skips (814 discovered) |

[SE-03 predecessor run 43630362534](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43630362534) and [SE-05 run 43630362526](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43630362526) also SUCCESS. Windows skips concern four POSIX permission/symlink checks and stdlib child-peak memory; no new skip was added. The targeted tests repeat within full discovery. Local source tree matches the published tree; diff/hash-lock/Git connectivity checks PASS.

Independent local reruns of Opus prerequisites: E-L2 **8/8 PASS, 66 assertions**, median 64-module admission **7.692 ms**; E-K1 plus historical E-L1 characterizations **7/7 PASS, 37 assertions**. Historical E-L1 remains a failed v2.0 design; v2.1 CP1A replaces that encoding. No repeated Chromium kernel run, owner-client run or native host test is claimed.

Local async qualification was blocked in the Python event loop's internal socketpair accept; the hosted tests above provide real automated transport evidence. The bridge timeout regression was observed **RED** (`SERVICE_OFFLINE` instead of `EDITOR_TIMEOUT`) and then **GREEN** after the repair. Earlier cloud failures and source identities remain in summary v1.2 and Actions history. No timeouts, thresholds, historical expected hashes or platform skips were changed to obtain a PASS.

## Prioritized findings

### P1 — WP3's prescribed rollback cannot preserve the current document revision and owner redo

**Ownership/scope:** frozen Editor contract and the next WP3 rollback helper; not a defect in the Builder relay delivered by WP2.

**Evidence:** v2.1 C5 and C11 prescribe undoing successful operations when a later operation in the same call fails. Invariant 3 and T-E7 require every rejected call to leave snapshot/revision/history unchanged. Current `AuthoringHistory.execute` calls `document.transact`, pushes the entry and clears the redo stack. `AuthoringHistory.undo` calls `document.transact(entry.inverse)` and moves that entry into redo. `BomcDocument.transact` increments revision on a real change. Normal Undo therefore cannot be a transaction-abort primitive.

A bounded probe against the real Editor implementations starts with an owner redo entry, executes a successful simulated agent rectangle and uses the prescribed Undo recovery. Result: **geometry restored=true; revision 2 → 4; history preserved=false; owner redo preserved=false**. It is not an LLM or UI test. Receipt: `outputs/2026-11-15-mcp-modeling-wp2/rollback-contract-receipt.json`, SHA-256 **a681240c716ed73236665a5370788e5e857e45eb4bcfba9a5acfc0d2b1af52dd**. Reproducer: `outputs/2026-11-15-mcp-modeling-wp2/editor-preflight/rollback-contract-probe.ts`.

**Required handoff:** revise/freeze C5/C11 and the WP3 rollback-helper contract before implementation. The revised mechanism must explicitly preserve canonical graph, revision/tokens, operation sequence, both history stacks and savedGraph on every rejected multi-operation call, while retaining one history entry per successful model op. Keep owner Undo/Redo and existing document format unchanged. Name the exact state owner and failure/cleanup boundary and require a regression with a pre-existing owner redo entry plus failure of a later op. Do not reinterpret invariant 3 as graph-only equality or change `BomcDocument`'s normal revision rules.

**Stop rule:** no WP3 product changes were made and CP3 is NOT_RUN. This finding routes the dependent implementation to PLAN; it does not reopen or downgrade the separate transport checkpoint.

## WP2 source check

- Ticket attachment enforces current project/tenant, epoch/authority, TTL, single use and the existing Origin/Host/query/HELLO policy; it consumes the actual DraftHub store without becoming a legacy draft viewer. Read-only remote/auth/core files remain byte-identical to base.
- Relay FIFO is bounded to eight waiting calls plus one active. Pending IDs and old-primary results are fenced. Cancellation, disconnect, supersession and shutdown retire futures/tasks. Repeated ASGI cancellation is shielded during teardown; bridge timeouts report uncertain completion and require describe_scene before retry.
- Per-slot discovery is atomically replaced, re-read per call and removed only when its secret still belongs to this service. Host is pinned to 127.0.0.1. Request/reply bounds stay separate from v1.
- Recorder is best effort, recursively redacts sensitive keys, bounds file size and disables a failed session without failing the tool call; Windows non-D roots refuse recording. Guide access does not contact the relay.
- Local add-on discovery has exactly ten tools. Legacy stdio keeps its original registration path, guide and catalogue; remote HTTP receives no add-on wrapper unless explicitly constructed with a relay.
- Final diff adds only WP2 source/tests, supporting exact-source CI and delivery documentation. No geometry/compiler changes, Editor edits, playground/global client changes, remote implementation or LLM harness.

No additional confirmed blocking WP2 source finding remains in this scoped implementer check. This statement does not claim an independent audit.

## Independent reviewer instructions

Use PR #95's bounded base-to-tested-source range, not the entire predecessor SE-05 diff. Deliberately examine FIFO/cancellation/primary replacement, ticket project/authority and stale-result boundaries, discovery rotation/deletion ownership, 256 KiB/4 MiB limits, recorder redaction/error/cap, offline guide and v1 exact receipts. Reproduce the WP3 contract counterexample on the pinned Editor source before authoring a plan correction. Record your own exact SHA and verdict; no independent reviewer has yet approved this work.

## Remaining claims and next deliverable

Parent objective: shared-document owner-tested modelling. Phase 1 completed milestones: WP0/WP1 evidence, WP1A admission proof, WP2 transport. Remaining: corrected WP3 contract, WP3 AGENT/panel plumbing, WP4–WP12 geometry/perception/guide/launcher/browser qualification and owner sessions. The next visible deliverable is a local Agent panel connected to the relay and the real worker, with pause/busy/revision/history boundaries proven; its definition of done is CP3 on the corrected frozen contract. Owner LLM behaviour, browser usability, arbitrary-model geometry, Save/reopen of agent-built architecture and deferred remote/security acceptance remain unverified.
