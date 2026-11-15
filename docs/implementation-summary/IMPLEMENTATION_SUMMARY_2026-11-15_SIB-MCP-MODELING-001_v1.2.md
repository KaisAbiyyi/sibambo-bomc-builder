# IMPLEMENTATION SUMMARY — SIB-MCP-MODELING-001 WP2

- Version: **1.2**, 2026-11-15, Asia/Jakarta.
- Status: **WP2 source implemented; CP2 qualification in progress; WP3 NOT STARTED**.
- Governing plan: [v2.1](https://github.com/KaisAbiyyi/sibambo-editor/blob/5ec4e47ccd2fa744f640a9fdc7c8d24c827f5e7a/docs/implementation-plan/MASTER_IMPLEMENTATION_PLAN_2026-11-15_SIB-MCP-MODELING-001_v2.1.md), including unchanged WP2 C1–C4/C16 from v2.0.
- Supersedes: [summary v1.1](https://github.com/KaisAbiyyi/sibambo-editor/blob/5ec4e47ccd2fa744f640a9fdc7c8d24c827f5e7a/docs/implementation-summary/IMPLEMENTATION_SUMMARY_2026-11-15_SIB-MCP-MODELING-001_v1.1.md) for the current phase pointer only; its WP1A evidence remains intact.
- Implementer: Codex primary session `mcp-modeling-wp2-20261115`; exact model identifier not exposed by this runtime. No subagents. User explicitly authorized implementation; no model-equivalence claim.
- Revision history: v1.0 WP0/WP1 negative gate; v1.1 Opus WP1A; v1.2 Builder WP2 delivery and qualification ledger.

## Objective and phase

Parent objective: the owner's own agent edits the open Editor document, sharing its history and normal BOMC Save, with joined architecture, native edges, floor plans and text perception. Current phase: Phase 1 transport. Completed milestones: WP0, WP1 evidence, WP1A encoding proof, WP2 source. Remaining: CP2 full qualification, then WP3–WP12. The next usable owner deliverable requires the Editor add-on and later modelling packages; WP2 alone is not a working modelling UI.

## Prerequisite verification and ownership

Read workspace README, artifact indexes, v2.0, latest v2.1 and both Opus summaries. Historical CP1 E-L1 **FAIL remains FAIL**; v2.1 replaces the incompatible encoding and inserts CP1A. Independently reran `bun test ./unit/arch/admission-e-l2.test.ts` on Editor **5ec4e47ccd2fa744f640a9fdc7c8d24c827f5e7a**: **8 PASS, 0 FAIL, 66 assertions**; 64-module admission median **7.692 ms**. This verifies CP1A, not owner LLM behaviour. Opus's earlier Chromium/kernel evidence was inspected, not independently rerun here.

Builder base: **6c358422abfb42bf203a8ac795703ba6512c5fea**, branch `work/mcp-modeling-001/wp2-relay`, stacked [draft PR #95](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/95) on #94. [Claim generation 1](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/94#issuecomment-6882293750): `local/addon-relay`, `local/addon-stdio`, `local/session-recorder`. This owner-assigned, serialized claim does not pretend that issue comments are atomic locks. Existing SE-05/Opus work was inspected, not reassigned. Editor's existing untracked `tooling/testing/results/` remains untouched.

## Work-package ledger

| Package | Status | Evidence / remaining gate |
|---|---|---|
| WP0/WP1/WP1A | done in earlier summaries | CP1A independently rerun as above |
| WP2 relay, recorder, discovery, ten tools | partial: implemented, qualification pending | Exact-source CP2 and predecessor CI running |
| WP3 worker AGENT plumbing | not started | Requires CP2 PASS and fresh Editor claim check |
| WP4–WP12 | not started | Outside this delivery |

## Changed files and behaviour

- `service/agent_relay.py`: bounded FIFO (one active, eight waiting), serialized bridge calls, per-call timeouts, latest primary replacement, old-result fencing, disconnect/shutdown cleanup, immutable local project scope and existing ticket authority checks. `/agent` copies the actual DraftSocket Host/Origin/query/first-HELLO rules. The current source consumes hashed tickets from **DraftHub**, not the unused TicketStore named in the plan prose; consumption does not register a draft peer or disturb its primary/ACK. No geometry is computed or retained.
- `service/recorder.py`: default local recording, per-session JSONL sequence, recursive sensitive-key redaction, 50 MiB cap plus one terminal marker, failure isolation and Windows D: guard.
- `service/bridge.py`: optional relay/slot, authenticated `addon-1` dispatch, re-read bounded atomic discovery on every call, loopback-only address validation, add-on-only 4 MiB response bound. Legacy environment/1 MiB transport stays separate.
- `service/stdio_bridge.py`, `service/addon_tools.py`: both add-on environment keys select exactly ten typed tools with per-process UUID session; legacy environment selects the existing eight v1 tools. `read_guide` is served without service contact. Initial bundled topics: index, quickstart, errors; WP10 owns completion and runnable examples.
- `service/local_demo.py`: default slots claude-code/codex/other, relay/recorder wiring, atomic per-slot discovery, owned-file removal on stop, recording switches; no generated per-launch agent configurations. WP11 still owns stable playground registration/launcher changes.
- `service/app.py`: optional local relay wrapper; absent relay retains the existing remote application path.
- `service/errors.py`: additive **separate ADDON_CATALOG**; the historical CATALOG, descriptions, code count and expected receipt stay unchanged.
- Tests: `test_agent_relay.py`, `test_recorder.py`, `test_addon_protocol.py`, `test_addon_guide.py`; only permitted discovery/default-slot assertions changed in `test_local_demo.py`.
- `.github/workflows/mcp-modeling-addon.yml`: exact-SHA Ubuntu/Windows automated CP2 and all Builder suites, hash-locked dependencies, D: Windows artifacts. This supporting verification file extends the expected diff only to supply the frozen automated proof in a runnable environment.

## Checks and evidence limits

Initial source: **8f29757725427a2db88639fd86d43989822c98e4**. Fixture Host correction: **de8f9389a9d8665416e8b4faff4b61d6f794391a**. Scope/authority fencing: **83259802a0522c9fb0bae63db993773f9190d729**. Disconnect cancellation repair: **e2fc0351514fb530528f2844716fcd1cc5fee910**. Final qualification publication is recorded in the subsequent receipt, not inferred from this in-progress ledger.

- Local Python AST validation: **19 files PASS**; `git diff --check` PASS.
- Local recorder/guide tests: **5/5 PASS**, then ticket-scope negative + recorder/guide **6/6 PASS**. Supplemental non-D and large-response tests are being included in final qualification.
- Local full baseline attempt was **INTERRUPTED**, never a suite PASS: Python blocked in `_fallback_socketpair` → `accept` while creating the asyncio event loop, before the async relay tests. Captured traceback identifies the environment restriction. The connected terminal fallback was unavailable (disconnected tunnel). No timeout was raised, tests skipped or transport mocked to manufacture a PASS.
- Initial cloud run found the test fixture's default `ws://testserver` Host; changed fixture to the permitted loopback URL without changing Host policy. A Windows run then exposed ASGI cancellation racing normal disconnect; route cleanup now treats cancellation as disconnect.
- [Exact-source CP2 run 43628985117](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/43628985117) on `e2fc035…`: targeted relay/recorder/official-SDK protocol/local-demo tests **PASS on both OSes** when this ledger was written; full suites still running. It is **not yet CP2 PASS**.
- No Editor production code, Builder core/compiler/schemas/auth/draft/HTTP-tools code, pinned bytes, global registration, native host or LLM client changed/run.

Publication used the connected GitHub Git-data API because shell Git networking cannot resolve GitHub. Remote commits and draft PR contain the actual source; exact tree identity and local/remote reconciliation are recorded in the final publication receipt. No force update, merge, review approval or intentional deployment.

## Independent-review handoff

Review Builder base `6c358422…` through the final published qualification SHA, not main or the legacy #94 diff. Check bounded FIFO/cancellation, pending-result identity and current ticket authority, project isolation, per-call discovery rotation, response budgets, recorder failure/redaction/cap, and that v1 exact receipts and tool discovery stay unchanged. CP2 requires every new test and every pre-existing Builder suite PASS. No self-approval or independent approval is claimed. Any failed automated gate blocks WP3; owner behaviour remains separate.

## Manual tests / next action

No owner test is needed to complete the synthetic transport checkpoint. Real Editor connection/usability and all owner LLM tests remain **PENDING**. Do not ask the owner to qualify an incomplete WP2-only UI. Finish exact-source CP2; only after PASS may the originally authorized WP3 begin with a fresh lock check.

## User Test Card

1. **What changed:** the Builder can relay ten local MCP tools to one Editor tab and record redacted sessions; the Editor add-on is not delivered by WP2.
2. **How to start:** no new owner modelling session yet. WP3 and later packages, plus WP11's launcher/registration, provide that flow. Automated developers can run `python -m unittest tests.test_agent_relay tests.test_recorder tests.test_addon_protocol tests.test_addon_guide tests.test_local_demo -v` with TEMP/TMP on D:.
3. **What to look at:** qualification status of PR #95 and its exact-SHA CP2 job, not a claim that agent geometry works.
4. **Optional ideas:** none required at this checkpoint; the owner chooses future client/model/prompts freely.
5. **How to report:** after the usable add-on is delivered, hand back a named `outputs/mcp-sessions/...jsonl` recording. No owner LLM session was run here.
