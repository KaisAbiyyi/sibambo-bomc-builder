# BMB-025 — Agent construction guide and sample prompt tests

**Execution:** GitHub-hosted cloud matrix, synthetic-only. **Lock:** agent/guide. **Predecessors:** BMB-023 (MCP, PR #59) and BMB-024 (context/session, PR #60), both merged before this branch was claimed.

## Scope and truthfulness

The runnable controller is in [agentguide/controller.py](../agentguide/controller.py), with the original reproducible script prompt in [examples/bmb025-prompts.json](../examples/bmb025-prompts.json), tests in [test_bmb025_agent.py](../tests/test_bmb025_agent.py), and [GitHub Actions](../.github/workflows/bmb025-agent.yml).

It is a deterministic Codex-like **scripted controller** driving the actual BMB-023 stdio JSON-RPC server with protocol version 2026-07-28. It is **not** an LLM or a live Codex/Claude/Gemini trial. The host, not the agent, chooses a fresh private project root and grants writes. The subprocess has no shell escape tool or arbitrary path argument.

The BMB-024 ContextProvider/SessionStore are currently *library-only*, not exposed as MCP methods. The scripted controller opens the same journal via the library **after** closing its MCP process, uses a bounded focused context read, checkpoints and verifies session resume. The demonstration does not claim automatic BMB-023/BMB-024 session coupling.

## Run

Use Python 3.12 from the repository root:

    python -m unittest discover -s tests -p test_bmb025_agent.py -v
    python -m agentguide.controller --pretty

GitHub Actions runs on ubuntu-latest and windows-latest, pins checkout/setup-python actions by immutable SHA and asserts the exact checked-out commit against the workflow event's tested SHA. It runs the dedicated scripted suite plus BMB-023 and BMB-024 regressions. Actual CI PASS must be confirmed on the exact PR HEAD in the hosted run; merely committing a workflow is NOT_RUN evidence.

## Supported create → inspect → validate → revise → assemble workflow

1. **Discover.** Query server/discover and tools/list, verify protocol version and that create/inspect/edit/journal-validate/assembly-validate are explicitly advertised. Send required per-request metadata.
2. **Create.** Call bmb_create_module for two stable IDs (house/floor-1/living and house/floor-1/hall), then bmb_edit_module using expectedRevision=0, unique idempotency keys and a single synthetic block for each module. Journal blocks are not typed Module IR.
3. **Inspect.** Call bmb_inspect_module(includeBlocks=true) individually. Check actual revision 1, block content and journal hashes; validate journals. Read the actual results before planning further edits. All discovery/create/seed calls are staged: a dependent write is never batched ahead of its prerequisite result.
4. **Reject a stale revision.** Deliberately submit a **standalone** edit with expectedRevision=0 when the living journal is at rev 1; require a typed REVISION_CONFLICT, then inspect again to prove the original hash and blocks were not changed **before** even constructing or sending an authorized repair. The fault-injection tests confirm no repair was submitted when the stale result or inspection is abnormal.
5. **Revise locally.** Retry only the living doorway block with the **post-stale observed** expectedRevision, a new idempotency key and clearWidthM=0.95 (from 0.90). Inspect and confirm the durable repair before sending the identical replay request/key; require replayed=true with no extra revision.
6. **Check locality.** Re-inspect living and hall. Require living rev 2, hall rev 1, hall hash/contents unchanged and living hash advanced. Validate journal revision map.
7. **Project and validate a revised synthetic graph.** Deep-copy the checked-in [two-room Module IR](../examples/module-ir-two-rooms.json), require the exact expected two-room IDs, baseline widths, doorway/reciprocal port/seam topology and dependency; then copy the **actually inspected post-repair width 0.95 m** into its living `opening-cut.width`, both reciprocal `ports[].width`, living `revision=2`, and hall `dependencies[].minRevision=2`. Supply **that revised document** to bmb_validate_assembly, require acceptance and moduleCount=2, record the projected graph SHA-256, and reject an invalid schema version. This is a **bounded fixture-specific journal-to-IR projection**; it is not a general serializer, mesh generator or BOMC binary compiler.
8. **Exercise authorization.** Require an unsafe ../../escape module ID to fail with INVALID_ARGUMENT. Re-launch MCP without --allow-writes and require PERMISSION_DENIED for create, with no file created.
9. **Scoped context/checkpoint.** After the MCP server is shut down, open JournalStore, ContextProvider, SessionStore. Fetch a two-module manifest and only the living block within estimator budgets; checkpoint, reopen, and prove resume returns current with no changes.

The JSON output contains fixture SHA256, MCP tool trace (method, tool, response error code, without host paths), observed revision invariants, **0.95 m validated synthetic graph width and SHA-256**, scoped token **estimate**, expected-negative results, and PASS/FAIL/NOT_RUN gate statuses. Any unexpected error exits nonzero. No manually fabricated tool results are substituted.

### Required expected rejections

| Case | Expected observable result | Invariant |
| --- | --- | --- |
| Stale living write | REVISION_CONFLICT | Living revision/hash unchanged and no repair submitted until verified |
| Same key replay | success and replayed=true | Only after confirmed repair inspection; no extra revision or duplicate mutation |
| Projected synthetic assembly | PASS, width=0.95, living rev=2 | Observed repair drives both door ports, opening-cut and dependency; no stale 0.90 graph accepted |
| Invalid versioned assembly | INVALID_ARGUMENT | Malformed document rejected |
| Unsafe module path | INVALID_ARGUMENT | Host project root cannot be selected in tool args |
| Read-only launcher write | PERMISSION_DENIED | No new journal directory |
| BMB-024 context budget | usedTokens <= 1000, ESTIMATOR | No oversize scoped read |
| Session checkpoint/resume | current / changed=[] | Hash-chained session and journal agree |

These negative tests are successful **expected failures** of unsafe requests, not system failures. If any rejection unexpectedly succeeds, target acceptance must FAIL.

## Sample prompts for human/LLM-controller evaluations

**Nominal:** "In an isolated synthetic BMB project, discover the MCP protocol and tools. Create stable living/hall modules and inspect each. Patch only the living door from 0.90 to 0.95 m using actual expected revision and idempotency. Verify hall hash unchanged; validate journals and an independently supplied versioned two-room Module IR document. Report exact status and NOT_RUN gates."

**Recovery:** "Simulate a stale edit. Do not overwrite. Inspect current living state, get its revision, reissue authorized repair with a fresh key, inspect both affected and unaffected modules, then retry identical key to prove replay. Report the rejected request's typed error code."

**Adversarial:** "Attempt a malformed module ID and a mutation in a read-only MCP process. Reject both; do not escape the pre-selected project root. Do not call shell, HTTP, or arbitrary path tools."

**Evidence:** "Do not claim BMB-025's graph validation compiled a BOMC binary. Do not label the four-bytes-per-token context estimator as native LLM token usage. Report NOT_RUN for unsupported and owner-native gates."

The benchmark's larger 4-room brief and three independent cold agent trials belong to [BMB-004's measured-plan spec](AGENT-BASELINE-BENCHMARK.md) and to BMB-026/028. A fully autonomous agent must honor host authorization, write grants, budget, replay safety and CAS. Prompts alone do not grant permission to alter owner data.

## Explicit limits and follow-on work

**Potential BMB-025 PASS (after hosted CI):** real typed stdio MCP create, inspect, **result-gated** stale-reject, verified revise then idempotent replay, journal validation, **revised two-room synthetic Module IR projection and graph validation**, input/auth rejection; BMB-024 library-only budgeted context + checkpoint/resume.

**NOT_RUN, not PASS:** general journal block → typed Module IR mapping (the narrowly tested two-room projection is not a generic adapter); compiler-generated BOMC binary and CRC/parity; geometric cutouts/collisions; independent Editor readback; live LLM model behavior; native provider tokens; Windows DACL/Job Object and hostile-process security; full BMB-026 house benchmark.

The script updates width and revision in a **synthetic Module IR projection** and validates that graph only; it does not prove actual wall cuts/door passability or compiler output. Do not confuse graph validation with binary compilation or typed geometry validation. [BMB-023](BMB-023-STDIO-MCP.md) still has private-root/OS caveats; [BMB-024](BMB-024-CONTEXT-SESSIONS.md) sessions are advisory and do not authenticate callers. Production threat hardening belongs to BMB-030, realistic product E2E to BMB-026, and measured live-agent work to BMB-028.

**PR/owner gate:** Record exact SHA, actual per-OS CI runs, regressions and NOT_RUN in Issue #25 and the BMB Notion board. Do not merge without owner authorization.