# Sibambo Stable — current execution checkpoint (2026-11-08)

> **CURRENT STATUS / READ FIRST.** This file supersedes **status and merge instructions only** in the historical SE-00 baseline audit, CP0 receipt, and v1.3/v1.5 planning snapshots. Do not reinterpret historical observations as today's gates. Preserve their test hashes and history. The GitHub issue heads and current main branches remain the live sources of truth for claims.

## Merged source-of-truth baseline

- **SE-00: DONE, issue #70 CLOSED.** Owner approved and merged all predecessor PRs.
- **Qualified merged Builder baseline (source-level CP0):** `8b3d7024838bb3dd64e6530becc1e33da77799b1` — [#90](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/90) then [#89](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/89), both merged.
- **Qualified merged Editor baseline:** `555aeafeafbb25599150f8fafa43644e6111cf21` — [#12](https://github.com/KaisAbiyyi/sibambo-editor/pull/12) then [#13](https://github.com/KaisAbiyyi/sibambo-editor/pull/13), both merged. Editor main tree equals #13's qualified tree, and #14 was already incorporated in #13.
- **Important:** Builder `main` may advance after this qualified baseline because of documentation-only status corrections. The stated SHA is the **exact tested CP0 baseline**, not a promise of the live `main` branch tip. Every implementing agent must run `git rev-parse origin/main` and inspect any intervening commits before claiming or branching. The exact generated/corpus/production source at the tested baseline remains untouched by these documentation updates.
- **Post-merge acceptance proof:** [GitHub Actions run 42466457352](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42466457352), SUCCESS: exact-source Builder-main → original Editor-main corpus check and 24 independent checker regressions. Proof artifact ID `13611961832`. [Editor main consumer run 42465787702](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42465787702) attempt 2 SUCCESS; initial Bun download 504 was external/transient.
- This is **CP0 source-level acceptance only**; Windows-native ACL, real Auth0, tunnel, WebSocket, remote MCP, owner Save and SE-11 are still downstream, not SE-00 blockers.

## Current work board

| Task | Current status | Board | Official issue |
| --- | --- | --- | --- |
| SE-00 | **Done** | Last Done | [Builder #70](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/70) |
| SE-01 | **Ready (unclaimed)** | Now | [Builder #71](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/71) |
| SE-04 | **Ready (unclaimed)** | Now | [Editor #15](https://github.com/KaisAbiyyi/sibambo-editor/issues/15) |
| SE-02 | Blocked by SE-01 | Up Next | its existing task issue |

**Readiness vs execution authority:** Owner approved the four SE-00 merges and the **D12 delivery method** for SE-01 and SE-04. D12 instructs HOW assigned agents must deliver; it should not be confused with evidence that a **separate explicit IMPLEMENT authorization** has already been recorded. If the initiating owner's current prompt explicitly authorizes “IMPLEMENT SE-01 and SE-04,” that is the required scope gate; a new agent may then claim only its own task/locks and create a task-owned PR. Otherwise reply "Ready, awaiting explicit IMPLEMENT instruction" rather than incorrectly asserting SE-00 is unmerged or blocked. Do not reopen CP0 audits.

## D12 — cloud agent finishes; owner follows a procedural SOP

For **SE-01** (Builder, locks `shared/ir; shared/compiler`) and **SE-04** (Editor, locks `stable/editor-onboarding; stable/auth-ui`), separately authorized agents may work concurrently without overlapping ownership.

The agent MUST complete all implementable production source, test fixes, unit/integration/negative/browser suites, hosted Ubuntu/Windows CI where supported, SHA-pinned evidence, and draft PR first. The agent MUST NOT offload coding or unresolved cloud-test failures onto the owner.

Before moving to **Review**, commit a beginner-friendly Indonesian step-by-step handoff at `docs/stable/owner-handoff/SE-01.md` / `SE-04.md` plus a safe PowerShell helper `scripts/owner_acceptance/se01.ps1` / `se04.ps1` when applicable. The SOP specifies tested commit SHA, required versions, exact copy/paste commands, preflight checks, expected visible results at each step, safe synthetic sample data, PASS/FAIL/NOT_RUN, redacted evidence output path, STOP conditions, retry/rollback and clean-up. Reserve manual native/visual/real OAuth acceptance for the owner, and label it NOT_RUN until performed. Merge, releases, paid resources, production deployment, Auth0 provisioning and tunnel activation require their respective explicit approvals.

**D11 demo first:** run canonical MCP/geometry actor on owner's Windows laptop with local stdio client and tunnelled Vercel Editor; Render Free is fallback. SE-01 owns typed geometry/projection (not SE-02 actor); SE-04 owns Editor onboarding/BFF (not SE-03 Builder auth endpoints). Remote MCP/WS/owner Save is not yet implemented.

**Authoritative references:** [Notion Master D12](https://app.notion.com/p/412c4a6aaf738117ac36c5101c01fae2) (not required for a GitHub-only reader), [SE-01 GitHub issue #71](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/71), [SE-04 GitHub issue #15](https://github.com/KaisAbiyyi/sibambo-editor/issues/15).
