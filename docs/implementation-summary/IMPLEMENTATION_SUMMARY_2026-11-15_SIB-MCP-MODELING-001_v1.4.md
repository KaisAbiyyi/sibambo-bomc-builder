# IMPLEMENTATION SUMMARY — WP2 isolation correction and final evidence

- ID **SIB-MCP-MODELING-001**, version **1.4**, **2026-11-15, Asia/Jakarta**.
- Status: **both requested isolation fixes implemented; CP2 PASS on corrective implementation source**. WP2 remains Draft/Review, without merge or approval.
- Supersedes [v1.3](IMPLEMENTATION_SUMMARY_2026-11-15_SIB-MCP-MODELING-001_v1.3.md) for the current WP2 source and qualification; older evidence is preserved as historical.
- Governing transport: v2.1 C1–C4/C16, restated unchanged in [current master v2.3](https://github.com/KaisAbiyyi/sibambo-editor/blob/988ac9a76f8042b4bb2882492e1a8c0258a4926a/docs/implementation-plan/MASTER_IMPLEMENTATION_PLAN_2026-11-15_SIB-MCP-MODELING-001_v2.3.md), plus the owner's explicit isolation-fix instruction. No WP3 implementation is included.
- Implementer: Codex primary, continuing its own WP2 claim, corrective checkpoint `20261115-isolation`; exact model ID unavailable. No subagents or independent-approval claim.
- Revision history: v1.0–1.1 Opus prerequisites; v1.2–1.3 initial WP2; v1.4 isolation corrections, fresh CP2 and governance reconciliation.

## Exact source and final publication receipt

| Item | Identity |
|---|---|
| Corrective base | `a4f602f65256ebbcbbe22f00b3b030b17dbfdc3b` |
| Corrective implementation / tested source | **`7d6d86ca24362cd8a89dc810216ced0823bca5fb`** |
| First corrective candidate, Windows qualification FAIL | `74bb9542abe0785e9fcd456307079811c735d96d` |
| Branch | `work/mcp-modeling-001/wp2-relay` |
| Draft PR | [Builder #95](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/95) |
| Fresh CP2 | [run 43671671055](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43671671055) |
| Latest publication HEAD and exact-HEAD requalification | [stable final receipt](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/95#issuecomment-6888500849) |
| Corrective claim | [owner-assigned continuation](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/95#issuecomment-6888358508) |

This document records implementation-source evidence. Its publication commit changes only documentation/evidence. The linked final receipt records that publication's own SHA and CP2 result after it exists; no self-referential commit SHA or unrun check is invented here. Local and remote source objects were hash-verified and reconciled without force updates. Shell Git networking is unavailable; publication uses the connected GitHub Git-data API.

## Requested fixes

**P1 — add-on credential isolation.** `service/bridge.py::BridgeServer.dispatch` now rejects unmarked/unknown API frames and non-add-on tool names whenever the server has an add-on relay. The bound server slot remains authoritative. A discovery credential cannot fall through to `Tools.call` or the legacy Builder `ProjectActor`. The separate legacy server without a relay retains its v1 behaviour and tests.

**P2 — discovery credential isolation.** `service/local_demo.py::_secure_private_path` hardens and reads back the dedicated run root, `private` directory, pre-existing discovery file and newly created temporary file before writing the new secret. POSIX directories/files are owner-owned 0700/0600. Windows uses the already hash-locked pywin32 to assign the process user SID and a protected DACL containing exactly one full-control user ACE; directory inheritance is OI/CI, file inheritance is absent. A process's Windows default TokenOwner is accepted only alongside TokenUser and normalized to TokenUser; foreign owners are rejected. Symlinks/reparse points are rejected. Temporary files are random, exclusively created and atomically replaced. A protection/verification failure aborts publication; the runner does not announce READY and stops with a non-success result.

Windows CI exposed the elevated-runner default-owner case in candidate `74bb954…`; its failure is preserved. The correction in `7d6d86c…` kept all ACL readback assertions. No broad-principal ACE, permissive fallback or skipped ACL verification was introduced.

## Changed paths

- `service/bridge.py`: add-on-only protocol/tool boundary.
- `service/local_demo.py`: verified owner-only storage, exclusive temporary creation and failure-safe readiness.
- `tests/test_addon_isolation.py`: seven tests, including both slots over authenticated TCP, legacy/unknown marker denial, all eight legacy tools, actor-state preservation, separate legacy positive case, permissive umask, broad existing permissions and protection failure.
- `tests/test_local_demo.py`: correct add-on denial expectation; positive secret-file compatibility uses a genuinely separate legacy bridge.
- `.github/workflows/mcp-modeling-addon.yml`: includes the new isolation suite in the targeted gate.
- Versioned summary/review and machine-readable evidence.

Unchanged: remote auth/HTTP/draft/owner APIs, `core/**`, `bomc/**`, `schemas/**`, dependency lock, legacy receipt/byte pins, Editor production code, ten-tool inventory, deferred remote behaviour and owner-only LLM-testing policy.

## Fresh automated evidence

CP2 run **43671671055**, exact source `7d6d86ca24362cd8a89dc810216ced0823bca5fb`, **SUCCESS**:

| Check | Ubuntu | Windows |
|---|---|---|
| Targeted WP2 + isolation + local-demo | **34 PASS / 0 FAIL** | **34 PASS / 0 FAIL** |
| Full Builder discovery | **821 PASS / 0 FAIL**, 260.516 s | **816 PASS / 0 FAIL / 5 pre-existing skips**, 264.962 s (821 discovered) |

Seven tests were added; no skip or timeout was added. Targeted cases repeat inside full discovery and are not additional independent scenarios. The five Windows skips belong to historical POSIX/context and child-memory checks. **The new WP2 Windows DACL tests ran and passed**, including the intentionally broad existing ACL and pre-publication temporary-file assertions.

[SE-03 run 43671670997](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43671670997) and [SE-05 run 43671670973](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43671670973) also SUCCESS on the same source. Duplicate push/PR instances are not separate scenario counts. Final publication-HEAD qualification is recorded separately in the linked final receipt.

Local reproduction observed the original routing tests FAIL twice and storage tests FAIL three times, before implementation. Routing tests then passed 3/3. AST/diff/hash/connectivity checks passed. This local sandbox reports successful ACL mutations while readback remains unchanged, including through independent `icacls`; it also blocks asyncio's internal socketpair. Consequently no successful local ACL/full-transport qualification is claimed. The implementation fails closed there; actual Windows/Linux CI supplies the positive permission and transport evidence above.

## Governance and handoff

[Evidence/self-check v1.1](../implementation-review/IMPLEMENTATION_REVIEW_2026-11-15_SIB-MCP-MODELING-001_v1.1.md) records the two corrected findings and precise evidence. Builder AGENTS explicitly says **independent reviewer is optional, never a required gate**; workspace REVIEW is optional unless required by the plan; master v2.3 also makes the Phase-1 review optional. No WP2-specific independent re-review gate is present. Therefore an independent reviewer was **not auto-assigned or requested as a mandatory dependency**. The exact-SHA handoff remains available in PR #95. This is an implementer check, not independent approval. No merge or self-approval.

## Parent progress and next deliverable

Parent objective: shared-document owner-tested Editor modelling. Current phase: Phase 1, WP2 transport/security complete at its automated checkpoint. WP0/WP1/WP1A remain completed; WP2 corrective source is done; WP3–WP12 are not implemented by this task. The prior rollback-design blocker is historical: Opus's current v2.3 revises the WP3 atomicity/journal contract. That plan revision is not implementation or CP3 proof. Do not start WP3 or claim its resources from this final-evidence task; the next implementer must check the latest plan, owner scope and live claim.

Next visible deliverable: the Editor Agent panel connected to the real worker and this relay. Definition of done: CP3, including the current v2.3 atomicity/history tests and existing authoring regressions. Remote/ADR decisions and all future owner LLM/usability tests remain separate.

## User Test Card

1. **What changed:** add-on credentials cannot reach legacy tools; discovery credentials have verified owner-only permissions.
2. **How to start:** no new manual owner test is needed for this backend checkpoint. Developers may run `python -m unittest tests.test_addon_isolation -v`, with temp/cache/output on D: on Windows; full CP2 is recorded above.
3. **What to look at:** exact-HEAD receipt and the real Windows ACL/negative routing tests in PR #95.
4. **Optional ideas:** none required; future LLM clients, models and prompts remain the owner's choice.
5. **How to report:** once the later usable add-on is available, name a flight-recorder session for analysis. No owner LLM test was run or claimed here.
