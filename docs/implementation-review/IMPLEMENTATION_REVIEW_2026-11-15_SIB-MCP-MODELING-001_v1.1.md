# IMPLEMENTATION REVIEW — WP2 isolation corrections and final evidence

- Review ID **SIB-MCP-MODELING-001**, version **1.1**, **2026-11-15, Asia/Jakarta**.
- Scope: corrective Builder `a4f602f65256ebbcbbe22f00b3b030b17dbfdc3b` → implementation source **`7d6d86ca24362cd8a89dc810216ced0823bca5fb`**, PR #95; documentation reconciliation only afterward.
- Governing plan: current [v2.3](https://github.com/KaisAbiyyi/sibambo-editor/blob/988ac9a76f8042b4bb2882492e1a8c0258a4926a/docs/implementation-plan/MASTER_IMPLEMENTATION_PLAN_2026-11-15_SIB-MCP-MODELING-001_v2.3.md), whose WP2 transport remains unchanged from v2.1; explicit owner instruction to fix both isolation defects.
- Summary: [v1.4](../implementation-summary/IMPLEMENTATION_SUMMARY_2026-11-15_SIB-MCP-MODELING-001_v1.4.md).
- Author/provenance: Codex primary implementer; exact model ID unavailable. Evidence reconciliation and implementer self-check, **not independent approval**.
- Supersedes [v1.0](IMPLEMENTATION_REVIEW_2026-11-15_SIB-MCP-MODELING-001_v1.0.md) for current source evidence; preserves its historical WP3 counterexample. Revision history: v1.0 initial handoff/preflight; v1.1 two isolation corrections and current governance.
- Verdict: **P1/P2 corrected and automated CP2 PASS on the implementation source. No merge or approval.** Latest publication-HEAD verification is in the [stable final receipt](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/95#issuecomment-6888500849).

## Findings and disposition

| Priority | Original defect | Correction and proof |
|---|---|---|
| P1 | Add-on credential could send unmarked/unknown frames through `BridgeServer.dispatch` into the legacy `ProjectActor`. | Add-on-attached servers require `api=addon-1` and a relay-tool name before any actor call. Direct dispatch proves zero legacy invocations, authenticated TCP covers both slots/all eight legacy tools/unknown markers and unchanged actor state. A separate legacy server still works. |
| P2 | Discovery folder/file used default permissions. | Run root/private/existing file/temp are hardened before credential bytes are written. POSIX 0700/0600; Windows owner normalized to TokenUser, protected single-user DACL read back, broad/inherited ACEs removed. Permission failure prevents credential publication/READY. Both actual OS suites pass; Windows ACL assertions are active. |

Seven new negative/compatibility tests protect these boundaries. No confirmed unresolved finding in these two requested corrections remains in this scoped implementer check. The earlier Windows candidate failure (default TokenOwner differs from TokenUser for an elevated runner) was corrected without weakening owner/DACL verification. No new skip, raised timeout, changed historical receipt or private-kernel import.

## Verified evidence and limits

[CP2 run 43671671055](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43671671055) SUCCESS at `7d6d86ca24362cd8a89dc810216ced0823bca5fb`: targeted **34/34 PASS on both OS**; full **Ubuntu 821 PASS**, **Windows 816 PASS + five pre-existing platform skips**, zero failures. SE-03/SE-05 predecessor workflows on the same source SUCCESS. Targeted tests repeat in full discovery; counts are not summed as independent cases. The final receipt records the later documentation HEAD's own exact-SHA rerun.

Local dispatch regression is RED → GREEN. Local Windows permission operations do not persist inside the sandbox, including via `icacls`; verification therefore rejects writing rather than pretending to secure the file. Positive Windows ACL proof comes from hosted Windows CI, not the local user's physical environment. No second real OS account, native SketchUp/UI, real LLM-client session or owner acceptance was tested. Windows administrators/OS privileges are not represented as an unprivileged-account isolation guarantee.

## Independent re-review decision

Governance inspected: workspace AGENTS REVIEW section; Builder AGENTS universal task policy; master v2.3 Work Packages. Builder policy explicitly states **"independent reviewer is optional, never a required gate"**. The workspace and master make REVIEW optional absent a specific gate; WP2 has no independent-review requirement. The owner's request is conditional on governance requiring it. Consequently **no independent re-review request or reviewer assignment is made**. This does not claim independent PASS, dismiss a reviewer or authorize merge. PR #95 remains Draft/Review with the evidence handoff available.

If an independent reviewer is later selected, inspect only the requested isolation scope on the latest receipt SHA: reject every legacy/unmarked/unknown call before actor access; verify owner-only ACLs before secret write and after atomic replacement; preserve the separate legacy SDK path; verify failure-safe readiness and all full-suite evidence. Do not treat the historical `661685c` CP2 as proof of these fixes.

## Remaining scope

WP3 is not implemented here. Opus's v2.3 plan revises the prior rollback/journal blocker; it does not prove CP3. The next UI deliverable remains Agent panel + worker plumbing under that latest contract and fresh ownership check. Owner testing and deferred remote/security/ADR decisions remain separate. No new manual owner test is required for the WP2 isolation checkpoint.
