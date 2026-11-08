# Execution task contracts — SIB-TWO-PHASE-001 v1.0

No product implementation was performed by publication of this ledger.

| Task | Repository | AND dependencies | Priority | Resource locks |
|---|---|---|---|---|
| [SE-00](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/70) · Reconcile stacked baselines and authorize the Stable slice | builder | owner gate | P0 | stable/baseline |
| [SE-01](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/71) · Typed geometry authoring contract and shared render projection | builder | SE-00 | P0 | shared/ir; shared/compiler |
| [SE-02](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/72) · Volatile project actor, revisions and fenced write ownership | builder | SE-01 | P0 | stable/project-actor |
| [SE-03](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/73) · Authenticated remote Streamable HTTP MCP adapter | builder | SE-02 | P0 | stable/mcp; stable/auth-resource |
| [SE-04](https://github.com/KaisAbiyyi/sibambo-editor/issues/15) · MCP Extension onboarding, pairing and agent management | editor | SE-00 | P0 | stable/editor-onboarding; stable/auth-ui |
| [SE-05](https://github.com/KaisAbiyyi/sibambo-editor/issues/16) · Live draft WebSocket synchronization and lifecycle | editor | SE-03, SE-04 | P0 | stable/editor-sync |
| [SE-06](https://github.com/KaisAbiyyi/sibambo-editor/issues/17) · Render every acknowledged construction operation live | editor | SE-01, SE-05 | P0 | stable/editor-render |
| [SE-07](https://github.com/KaisAbiyyi/sibambo-editor/issues/18) · Explicit Save, frozen revision compile and original Editor reopen | editor | SE-06 | P0 | stable/save; shared/compiler |
| [SE-08](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/74) · Reconnect, actor recovery and multi-agent error semantics | builder | SE-02, SE-05, SE-07 | P1 | stable/project-actor; stable/recovery |
| [SE-09](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/75) · Cross-application security and bounded remote execution | builder | SE-03, SE-04, SE-05, SE-07 | P1 | stable/auth-resource; stable/security |
| [SE-10](https://github.com/KaisAbiyyi/sibambo-editor/issues/19) · Measured live rendering performance and onboarding usability | editor | SE-06, SE-08, SE-09 | P1 | stable/editor-performance; stable/ux-evidence |
| [SE-11](https://github.com/KaisAbiyyi/sibambo-editor/issues/20) · Real remote AI construction → live owner view → Save → reopen gate | editor | SE-07, SE-08, SE-09, SE-10 | P0 | stable/product-acceptance |
| [XB-00](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/76) · EXPERIMENTAL charter, future repository split and evaluation protocol | builder | owner gate | P2 | experimental/charter |
| [XB-01](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/77) · Exact-location map and evidence provenance experiment | builder | XB-00 | P2 | experimental/site |
| [XB-02](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/78) · Room-program onboarding and constraint interpretation | builder | XB-00 | P2 | experimental/room-program |
| [XB-03](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/79) · Client interview and desired-feeling research | builder | XB-00 | P2 | experimental/client-interview |
| [XB-04](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/80) · BYOK provider abstraction, credential safety and 27B Colab benchmark | builder | XB-00 | P2 | experimental/providers |
| [XB-05](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/81) · Native internal agent state machine and research synthesis | builder | XB-01, XB-02, XB-03, XB-04 | P2 | experimental/orchestrator |
| [XB-06](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/82) · Zoning and floor-plan algorithm comparison experiment | builder | XB-05 | P2 | experimental/spatial-planning |
| [XB-07](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/83) · Verified floor plan → Module IR → 3D/BOMC geometry | builder | XB-06, SE-01 | P2 | experimental/geometry-lowering |
| [XB-08](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/84) · Independent evaluation, environmental constraints and uncertainty | builder | XB-07 | P2 | experimental/evaluation |
| [XB-09](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/85) · Separate application split and three-stage onboarding prototype | builder | XB-01, XB-02, XB-03, XB-04, XB-08 | P2 | experimental/app-split |
| [XB-10](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/86) · Human feedback, localized revision and valid BOMC export | builder | XB-09 | P2 | experimental/feedback |
| [XB-11](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/87) · EXPERIMENTAL end-to-end pilot and provider go/no-go | builder | XB-10 | P2 | experimental/pilot |


## WORK PACKAGE SE-00 · Reconcile stacked baselines and authorize the Stable slice

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 0 · Contract & baseline**.
State: **NOT STARTED / Blocked**. Owner gate: approve exact baseline disposition, service/IdP inputs and separate IMPLEMENT scope
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **Owner gate only**.
Resource lock(s): `stable/baseline`. Claim is unassigned; no lock is held by this plan. Execution: Owner Gate. Estimate: 0.5–1 engineer-day plus owner decision (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

READ ONLY: Builder #62 at 8fc6ebb; Editor #12 b5f46a7, #13 at current 98b01dc (contains #14), Editor main 04e4c1d, Builder main 7cd6ca7. MUST: docs/two-phase/BASELINE-DISPOSITION.md and pinned contract manifest.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Record owner disposition for existing unmerged predecessors; do not merge them in this planning session. For future IMPLEMENT, integrate their task-owned necessary fixes through explicit owner-approved PRs, preserving original receipts and attribution. Compare both source bases before touching production. Freeze cross-repo schema hashes, compiler source hashes, exact consumer SHA and supported four-room corpus. Resolve accepted Notion BMB-026 Done versus draft/unmerged code as accepted bounded evidence, not main readiness. Authorize the named Stable implementation batch and nonproduction live-agent test environment; no deployment authority follows.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

STATIC/INTEGRATION: baseline manifest names actual target commits and proves required original E4 material/directory-count behavior plus four-room compile/readback on those commits; all inherited failures remain listed. No downstream implementation until disposition and authorization recorded.

Negative assertion: **Do not silently retarget, merge, cherry-pick unrelated patches, relabel old tasks incomplete, or assume merged #14 reached main.**

## Manual gate — owner / expected result

Owner: approve exact baseline integration disposition and Stable IMPLEMENT scope; expected explicit decision, no release/merge automation in this session.

## CHECKPOINT SE-00

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73817a95c4f924aeb464ab?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/70


## WORK PACKAGE SE-01 · Typed geometry authoring contract and shared render projection

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 0 · Contract & baseline**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-00; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **SE-00**.
Resource lock(s): `shared/ir; shared/compiler`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–4 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: core/project/operations.py, core/project/projection.py, schemas/draft-operation-v1.schema.json, schemas/draft-view-v1.schema.json, tests/test_draft_operations.py. MUST MODIFY: bomc/compiler/semantic_v12.py::_shape_faces, _mesh, encode_semantic to extract one pure shared projection. READ ONLY geometry builders and Module IR 1.0 schema.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Define v1 replace_module and remove_module with full validated Module IR for exactly one module; typed helper tools add_floor/add_wall/add_opening/update_operation lower to replace_module through existing geometry builders. No arbitrary Python/shell/code evaluation. Render projection and compiler both consume the same canonical face/triangle intermediate, using stable module/operation/face IDs. Preserve encode_semantic bytes for the pinned corpus. Deletion rejects live dependent/seam references. Preview carries metre/+Z Float64 source positions and triangle indices; GPU conversion belongs to Editor. Reserve module revision, project revision and idempotency fields per master contract.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT tests/test_draft_operations.py: four-room walls, concave floor, real door/window cutout, mirrored/nested transforms; compiled golden bytes unchanged by extraction; projection faces/triangles/materials numerically equal independent BOMC decode. Schema rejects NaN, missing seam owner, invalid references and unsupported operations before state mutation.

Negative assertion: **No box proxy as final geometry; no second triangulator, raised compiler limits, lost faces/material labels, or journal JSON guessed to be typed IR.**

## Manual gate — owner / expected result

Developer: inspect operation list and matching rendered semantic face IDs in a nonproduction sample; owner visual gate remains SE-11.

## CHECKPOINT SE-01

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738116964dc411de6377b0?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/71


## WORK PACKAGE SE-02 · Volatile project actor, revisions and fenced write ownership

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 0 · Contract & baseline**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-01; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **SE-01**.
Resource lock(s): `stable/project-actor`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–3 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: core/project/actor.py, core/project/state.py, tests/test_project_actor.py. READ ONLY: core/identity/store.py::ModuleStore, core/storage/journal.py::JournalStore, agentctx/session.py.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. One in-memory actor per tenant/project/epoch; use ModuleStore CAS/idempotency in a staged copy and canonical typed IR map, never JournalStore for unsaved designs. Project-global revision starts 0. Under actor mutex validate grant, owner heartbeat, lease fence, expectedProjectRevision and touched dependency revisions; validate and project candidate before swapping all actor state once. Cache operationId+request hash+outcome atomically with swap. Same key/hash returns prior outcome before stale-revision check; different hash conflicts. One agent writer lease at a time; readers concurrent. Owner pause takes priority at next operation boundary and increments fence. No multi-module atomic mutation in v1.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT tests/test_project_actor.py: race two agents from same revision (one accepted, other REVISION_CONFLICT); repeat exact op once; key reuse mismatch; crash-before-swap unchanged; pause/revoke fenced write rejected; rejected geometry leaves all state/digests unchanged. Test no project writes to disk.

Negative assertion: **No last-write-wins, actor race, cross-tenant lookup, fsync draft journal, or unbounded operation queue.**

## Manual gate — owner / expected result

Developer: two clients contend; expected named writer, explicit conflict, owner can pause and acquire ownership.

## CHECKPOINT SE-02

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73815db620eb541ab93435?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/72


## WORK PACKAGE SE-03 · Authenticated remote Streamable HTTP MCP adapter

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 1 · Live Save vertical slice**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-02; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **SE-02**.
Resource lock(s): `stable/mcp; stable/auth-resource`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–4 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: service/app.py, service/mcp_http.py, service/auth.py, service/requirements.lock, tests/test_remote_mcp.py. READ ONLY: agent/bmb_mcp.py::SCHEMAS, Server.handle, _validate_args; agentguide/controller.py::MCPClient.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Use official Python MCP SDK mcp==2.3.0 as inspected baseline, ASGI deployment process, exact dependency lock. Verify SDK supports the researched 2026-07-28 HTTP profile before adapter implementation; failing compatibility probe blocks to REVIEW/PLAN, no handwritten protocol replacement. Implement project-scoped resource endpoint POST /mcp; current per-request metadata and request-scoped response streams, plus explicitly tested 2025-11-25 compatibility only if actual client requires it. Tools read_project, inspect_module, apply_operation, operation_status, acquire_writer, release_writer and validate_draft call actor directly, not CLI/subprocess stdin. No MCP save/export tool. OAuth protected-resource metadata, external managed authorization server, PKCE S256, audience/issuer/signature/expiry validation, subject/tenant+project grants; clientInfo is display data only.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION tests/test_remote_mcp.py: real SDK client over TLS staging transport executes typed write, validation/read and stale retry. Assert both negotiated protocol versions only when supported; unsupported version explicit error. Missing/expired/wrong-audience token 401, missing project capability 403. Existing stdio tests unchanged.

Negative assertion: **Never pass through provider credentials, treat MCP session ID as auth, open localhost tunnelling as product architecture, or use current MCP GET stream/session assumptions from older revisions.**

## Manual gate — owner / expected result

Owner/developer: real Claude Code and Codex connect to nonproduction remote URL after OAuth and project grant; expected discovery + authorized scoped read/write, versions recorded.

## CHECKPOINT SE-03

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381049e91cd47e4924c37?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/73


## WORK PACKAGE SE-04 · MCP Extension onboarding, pairing and agent management

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 1 · Live Save vertical slice**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-00; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-editor`. Dependencies (AND): **SE-00**.
Resource lock(s): `stable/editor-onboarding; stable/auth-ui`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–3 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST MODIFY: apps/editor/src/routes/+page.svelte::EditorMode, requestTransition, executeTransition, unload, onDestroy; apps/editor/src/lib/ui/editor-workspace.css. MUST NEW: apps/editor/src/lib/mcp/McpPanel.svelte, connection.ts, tests/mcp-onboarding.spec.ts. MUST NEW Builder side paired endpoints remain owned by SE-03 auth owner; coordinate API through frozen schema, no simultaneous edits. MUST NEW: apps/editor/src/lib/server/mcp-bff.ts; routes/api/mcp/{login,callback,logout,session,ticket,grants,pause}/+server.ts. BFF routes belong to this task; service auth endpoints SE-03. MUST NEW: apps/editor/src/lib/server/mcp-bff.ts; routes/api/mcp/{login,callback,logout,session,ticket,grants,pause}/+server.ts. BFF routes belong to this task; service auth endpoints SE-03.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Add in-app Extensions → MCP Extension, not an OS/browser addon dependency. States disconnected→signing-in→project-selected→pairing→awaiting-owner-grant→connected/read-only→writer-active, plus paused/reconnecting/expired/error. Owner login via same-origin BFF HttpOnly Secure SameSite=Lax cookie, CSRF token on mutations; no access token in localStorage. Remote agent OAuth obtains pending grant; owner approves exact agent subject/client/project/scopes in Editor. Pair code is human comparison only (8 chars, 5min, 5 attempts); OAuth + explicit grant required. Display actual capabilities, current writer, seen/rendered revision and pause/revoke/remove. Show client-specific setup instructions from official docs; never put credentials in command text, URLs or telemetry.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

BROWSER tests/mcp-onboarding.spec.ts: keyboard-only path, denied consent, expired pairing, fake agent name with different subject, revoke, reopen panel retains current draft; 320/768/1440 widths no inaccessible actions. Wrong code and missing grant never enable writes.

Negative assertion: **Do not promote every old Editor On Hold task or copy private Editor code into public Builder.**

## Manual gate — owner / expected result

Owner: fresh onboarding in actual supported agent clients; expected identity, project and permission choices understandable, pause/revoke visible.

## CHECKPOINT SE-04

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73813e9ae3e4172ec00e55?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-editor/issues/15


## WORK PACKAGE SE-05 · Live draft WebSocket synchronization and lifecycle

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 1 · Live Save vertical slice**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-03, SE-04; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-editor`. Dependencies (AND): **SE-03, SE-04**.
Resource lock(s): `stable/editor-sync`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–3 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: apps/editor/src/lib/mcp/draft-client.ts, draft-protocol.ts, draft-store.ts, tests/draft-sync.spec.ts. MODIFY +page.svelte::snapshotLoadedState, restoreLoadedState, requestTransition, unload/onDestroy. Builder NEW service/draft_ws.py owned by this cross-repo task, isolated from SE-03 files.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Browser-only WebSocket /draft attaches after same-origin BFF produces a single-use 30s ticket via authenticated POST; send ticket in first message within 5s, never query string. Check Origin allowlist and tenant/project grant on upgrade/attachment. HELLO(epoch,lastAppliedRevision,lastRenderedRevision) → bounded snapshot or contiguous events. Event envelope and ordered handling fixed in master. Parse/validate off main thread; stage canonical module replacements; apply only contiguous revision; stale duplicate ignore by hash, hash mismatch pause. Gap triggers resync; retain last good visible draft until complete replacement validated. Heartbeat every5s with 15s TTL. Generation token fences stale socket callbacks; closing page closes socket and revokes presence, not saved file.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

BROWSER tests/draft-sync.spec.ts: drop after accepted operation before response; reconnect uses same operationId and no duplicate; reordered/missing/corrupt event freezes then resyncs; late old-project response cannot replace new project; failed reconnect preserves last good model. No IndexedDB/localStorage/network durable draft.

Negative assertion: **No full BOMC download/import per edit, unbounded replay, token in WebSocket URL, or event from old epoch accepted.**

## Manual gate — owner / expected result

Developer: disconnect browser network then restore; expected visible paused state, reconciled revision, no duplicate walls.

## CHECKPOINT SE-05

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381e29bd5d6be758b2303?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-editor/issues/16


## WORK PACKAGE SE-06 · Render every acknowledged construction operation live

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 1 · Live Save vertical slice**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-01, SE-05; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-editor`. Dependencies (AND): **SE-01, SE-05**.
Resource lock(s): `stable/editor-render`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–4 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: apps/editor/src/lib/mcp/draft-scene.ts, draft-projection.worker.ts, tests/draft-render.spec.ts. MUST MODIFY: packages/viewport/src/prepared-scene-viewport.ts::PreparedSceneViewport (new setExternalDraftProjection/clearExternalDraftProjection methods, dispose cleanup); +page.svelte projection selection. READ ONLY existing authoring/scene.ts, BomcDocument writer and imported E4 decoder.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Dedicated builder-draft mode owns external disposable Group and moduleId→GPU-resource map. Add the two named external-draft methods as wrappers over setDomainOverlay with dedicated builder/module/<moduleId> keys, plus external source-face picking/observation records. Viewport owns attached Group geometry/material disposal; wrappers must never dispose a Group a second time. Unchanged groups stay attached; imported scene picking remains unchanged. Stage changed modules offscreen and swap affected groups atomically; delete old resources once, retain unchanged module objects/material cache references. Map canonical +Z to Three +Y by one root rotation -PI/2 about X; no per-module double conversion. Preserve camera/selection for surviving IDs; never auto-fit on each operation. Render a frame then send renderAck(projectRevision,digest); server permits next write only after ACK. Invalid projection keeps previous frame and pauses further writes.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

BROWSER tests/draft-render.spec.ts: floor→wall→opening→window revision each produces distinct completed frame with exact revision/hash, source-face pick survives unrelated replacement. Holes are visibly empty, shared walls single-owned, mirrored transforms correct. After 200 replacements resource counts return within baseline+5 after disposal/GC, unchanged modules retain object identity.

Negative assertion: **No GPU data used as canonical state, preview boxes as final solids, bypass of importer admission for saved files, or resetting camera each event.**

## Manual gate — owner / expected result

Owner: observe sequential construction and request a window revision while orbiting; expected visible incremental operations and stable navigation. Subjective fidelity recorded in SE-11.

## CHECKPOINT SE-06

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738141b140f7f4f4750290?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-editor/issues/17


## WORK PACKAGE SE-07 · Explicit Save, frozen revision compile and original Editor reopen

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 1 · Live Save vertical slice**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-06; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-editor`. Dependencies (AND): **SE-06**.
Resource lock(s): `stable/save; shared/compiler`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–4 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST MODIFY: +page.svelte Save handler (existing saveBomc/write acknowledgment path remains unchanged for local authoring), transition dirty guard. MUST NEW: lib/mcp/draft-save.ts, tests/draft-save-reopen.spec.ts; Builder service/save.py and tests/test_draft_save.py. READ ONLY bomc/compiler/graph_to_bomc.py::compile_document and original E4 import path.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Only owner browser Save click issues CSRF-protected POST /projects/{id}/save-intents with epoch+expectedProjectRevision+digest. Atomically freeze draft at r, pause agent writer; compile same canonical IR with Builder compiler in RAM, independently validate exact bytes, return one-use owner-only binary response with sha256 and revision. Agents cannot mint intents or export. Browser verifies bytes/hash, downloads filename project-r.bomc (File System Access optional only with user choice); acknowledge save dispatch only after successful browser dispatch or file writer close. Set savedRevision=r only; any later draft revision stays dirty. Failure/cancel leaves dirty and lease resumable; Blob URLs revoked. Discard confirms unsaved loss. Reopen via existing file picker/admitE4File/loadE4InWorker, not a new parser. Reopened output is valid inspectable BOMC; arbitrary imported BOMC→typed Module IR editing is not claimed.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION tests/test_draft_save.py + BROWSER tests/draft-save-reopen.spec.ts: no file or durable model before click; concurrent op versus Save frozen at one exact r; Save failure/cancel keeps dirty; token/agent cannot Save; download captured then original Editor reopens same SHA with geometry/opening/material/transforms numerically equal draft projection. At least two saves separated by localized revision.

Negative assertion: **No autosave on tool completion/reconnect/close, forced section241 round-trip through private authoring subset, lost unsupported geometry, or claim that browser dispatch proves user disk fsync.**

## Manual gate — owner / expected result

Owner: click Save, retain downloaded BOMC, close/reopen in Editor, compare model and changed window; expected valid file and correct revision. Owner confirms actual retained file.

## CHECKPOINT SE-07

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73817897a4c6751980037a?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-editor/issues/18


## WORK PACKAGE SE-08 · Reconnect, actor recovery and multi-agent error semantics

Classification: **Stable Editor + Remote MCP** · Priority **P1** · Milestone **Stable 2 · Reliability & acceptance**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-02, SE-05, SE-07; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **SE-02, SE-05, SE-07**.
Resource lock(s): `stable/project-actor; stable/recovery`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–3 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST MODIFY: core/project/actor.py, service/draft_ws.py, service/mcp_http.py. NEW tests/test_draft_recovery.py; Editor draft-client.ts changes coordinated under same claim.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. No owner presence→stop new writes; in-flight operation already swapped remains accepted but renderPending, queried by operationId. Cancellation before swap rejects, after swap is outcome-known, client disconnect never implies rollback. Keep 128 events or8MiB in RAM, whichever first; 30min disconnected TTL then purge actor and grants, no draft content in logs/swap/core dumps/backups. Server restart creates new epoch; writes blocked until owner explicitly restores last browser-held canonical snapshot after reauth+validation (clear unsaved/recovery notice). If browser is also gone, recover only last user-saved BOMC for inspection; unsaved draft loss disclosed. One writer lease30s, refreshed10s, fence increments on pause/revoke/transfer; second agent BUSY, no auto-steal. Owner operation wins boundary, invalidates prior lease.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION tests/test_draft_recovery.py: process termination before/after swap, server epoch replacement, event-ring expiry, browser restore consent, two agents plus owner conflict, revoked ticket and stale lease; count failed operations, preserve all accepted IDs. Memory purge tested; no disk draft.

Negative assertion: **Do not automatically replay unknown writes under a new key, accept server stale epoch, or promise restart durability without explicit Save.**

## Manual gate — owner / expected result

Owner/developer: restart staging service with browser open, approve recovery; expected snapshot restored without duplicate operation and old agent lease invalid.

## CHECKPOINT SE-08

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738147ac4dfe112b3f7523?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/74


## WORK PACKAGE SE-09 · Cross-application security and bounded remote execution

Classification: **Stable Editor + Remote MCP** · Priority **P1** · Milestone **Stable 2 · Reliability & acceptance**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-03, SE-04, SE-05, SE-07; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **SE-03, SE-04, SE-05, SE-07**.
Resource lock(s): `stable/auth-resource; stable/security`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 2–4 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: tests/test_remote_security.py, docs/two-phase/THREAT-TESTS.md. MODIFY service auth/HTTP/WebSocket/save validation only where failing cases prove contract violation; Editor auth tests in tests/mcp-onboarding.spec.ts.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Threat matrix tenant isolation, CSRF, malicious Origin, token audience, OAuth redirect/PKCE state, grant revocation, replay, pairing brute-force, malicious geometry, memory/CPU peaks and leaked logging. Auth metadata/refresh tokens may use encrypted managed storage; model payloads never do before Save. Use managed OIDC/OAuth authorization service contract rather than home-built password storage. Server runtime single actor per project, sticky route; 20 active projects per worker, admission rejects at cap. Geometry worker isolated process with30s CPU/wall deadline and512MiB RSS, input2MiB maximum and existing stricter operation/module/face/compiler caps. No arbitrary outbound URLs; credentials and geometry scrubbed from logs. No experimental credential can access Stable service.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION tests/test_remote_security.py with two tenants: cross-project every read/write/save/socket attempt denied, revoke effective before next mutation, hostile payload rejected under budgets, deadline kills computation without partial swap; scan error/log captures for secrets/geometry. Record managed authorization server conformance and residual provider policy separately.

Negative assertion: **No cloud-only test called native Windows security certification; no token passthrough or hidden authorization fallback.**

## Manual gate — owner / expected result

Developer security owner: test actual staging IdP/client redirect flows and revocation across both clients; expected fail-closed behavior.

## CHECKPOINT SE-09

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381ea8d73eb2e09de33ea?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/75


## WORK PACKAGE SE-10 · Measured live rendering performance and onboarding usability

Classification: **Stable Editor + Remote MCP** · Priority **P1** · Milestone **Stable 2 · Reliability & acceptance**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-06, SE-08, SE-09; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-editor`. Dependencies (AND): **SE-06, SE-08, SE-09**.
Resource lock(s): `stable/editor-performance; stable/ux-evidence`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 1–3 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: tooling/testing/run-remote-draft-performance.ts, apps/editor/tests/draft-performance.spec.ts, docs/two-phase/PERFORMANCE-RECEIPT.md. Production changes only for measured regression within existing mechanisms, otherwise STOP→PLAN.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Pinned four-room/five-module scene within current compiler caps, plus 100 repeated valid revisions and failed stress inputs retained. Record browser/device/network/compiler/agent SHAs; emulate100ms RTT+10Mbps and separate real-network timing. Measure actor accepted→browser render ACK P95≤500ms, all accepted operations rendered≤2s; post-render camera input P95 frame≤33ms; no main-thread task>100ms from geometry decode; Save≤5s for bounded fixture. Histograms include failures/timeouts. 320/768/1440 layout keyboard/screen reader status checks; owner usability separate. These are targets, not current measurements. Above supported caps reject visibly; do not expand limits to pass.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

PERFORMANCE 20 fresh-session trials with100 revisions each; per-stage timestamps and operation IDs prove order, no skipped frame. BROWSER slow device, hidden tab pauses writer, reconnect recovery and resource disposal. Threshold failure blocks Stable acceptance without redefining workload.

Negative assertion: **No synthetic three-trial P95 advertised as product SLA, no replacing hard fixture with a rectangle, no frame coalescing that hides operations.**

## Manual gate — owner / expected result

Owner: complete fresh setup/pause/revise/Save task without developer assistance; report friction and expected understandable connection/draft/save state.

## CHECKPOINT SE-10

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73812c8805eeb230180589?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-editor/issues/19


## WORK PACKAGE SE-11 · Real remote AI construction → live owner view → Save → reopen gate

Classification: **Stable Editor + Remote MCP** · Priority **P0** · Milestone **Stable 2 · Reliability & acceptance**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: SE-07, SE-08, SE-09, SE-10; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-editor`. Dependencies (AND): **SE-07, SE-08, SE-09, SE-10**.
Resource lock(s): `stable/product-acceptance`. Claim is unassigned; no lock is held by this plan. Execution: Cloud + Owner. Estimate: 1–2 engineer-days plus owner live session (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: apps/editor/tests/remote-agent-acceptance.spec.ts, docs/two-phase/LIVE-AGENT-ACCEPTANCE.md, evidence manifest references (synthetic-only public). No product changes in acceptance task unless bounded failing-contract fix separately recorded.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Run actual authenticated external Claude Code first, Codex second, recorded version/model/endpoint with credentials redacted. Agent receives four-room 8×6m brief, creates floor/walls/shared seams/door/window incrementally through remote typed tools, owner observes each frame; owner pauses, requests private window1.0→1.2m, resumes; stale second agent conflicts; disconnect/reconnect once. Owner clicks Save twice at named revisions; real downloaded bytes open through original Editor file path. Automated replay client is supporting proof only; a real AI agent must select and invoke geometry tools. Require receipts for agent calls, actor revisions, frame ACKs, save hashes, original importer semantic comparison and owner observation. Public repo gets sanitized synthetic records; no API keys/client data.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

LIVE/BROWSER/MANUAL: both actual client runs pass all mandatory steps, all operation IDs mapped to visible frames, geometry/semantics equal after reopening, no persisted BOMC before Save, owner explicitly accepts flow. Failed/live-unavailable results remain FAIL/NOT_RUN and block Stable product readiness; no release/deployment implied.

Negative assertion: **No scripted controller, green SDK smoke, BMB-026 binary or preview seam alone closes this gate.**

## Manual gate — owner / expected result

Owner: personally observe live construction, intervention, Save and reopened file and return explicit acceptance; developer records exact identities. No SketchUp gate needed for this product flow.

## CHECKPOINT SE-11

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73810885c3cfe999051754?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-editor/issues/20


## WORK PACKAGE XB-00 · EXPERIMENTAL charter, future repository split and evaluation protocol

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 0 · Evidence & onboarding**.
State: **NOT STARTED / Blocked**. Owner gate: approve research capacity/budget and future repository naming/visibility decision; do not delay Stable
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **Owner gate only**.
Resource lock(s): `experimental/charter`. Claim is unassigned; no lock is held by this plan. Execution: Owner Gate. Estimate: 0.5–1 research-day (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST: docs/two-phase/EXPERIMENTAL-CHARTER.md and experiments/protocol/manifest.json; future repository brand/name explicitly TBD. No application scaffold yet.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Owner approves independent research budget/capacity and later repository creation; Stable has first call on shared owners/locks. New app will own UI, client brief, research, providers and native orchestration in a future separate repository. Builder retains core/IR/compiler; consume version-pinned public Python package via direct in-process API, not MCP internally. Until split, code experiments isolated under experiments/ with separate lock and no production imports. Publish dataset/participant consent, source licensing, frozen evaluation split and research questions before trials.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

STATIC: charter names ownership/stop decisions, task DAG acyclic, immutable held-out fixtures and metrics committed. Owner decision recorded; no brand/domain invented.

Negative assertion: **No new monolith, copy of geometry core, release claim, or Experimental dependency in Stable.**

## Manual gate — owner / expected result

Owner: approve research-only budget and later repo split gate; expected bounded experiment authority.

## CHECKPOINT XB-00

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381e39599f0e898f751f6?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/76


## WORK PACKAGE XB-01 · Exact-location map and evidence provenance experiment

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 0 · Evidence & onboarding**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-00; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-00**.
Resource lock(s): `experimental/site`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 2–4 research-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW: experiments/site/{schema.json,normalize.py,fixtures/README.md}, tests/test_experimental_site.py. Future UI site map belongs to separate app, not Editor.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. SiteBrief v1 stores WGS84 lon/lat, user-confirmed site polygon, source CRS, uncertainty metres, source/retrievedAt/license, true north and local ENU metre transform. Use MapLibre map UI prototype with licensed tiles; initial online context candidates OSM roads/buildings and Open-Meteo reanalysis, user-provided survey/terrain authoritative only when documented. Separate point precision from survey accuracy. Every road/access/terrain/climate/setback statement has evidence status verified-source/user-stated/inferred/unverified/missing and resolution/time. Missing or contradictory critical site boundary/setback blocks feasible layout claims; mark assumptions, never invent code requirements.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT/integration: antimeridian+hemisphere coordinate tests, CRS round-trip error<1cm arithmetic (not survey accuracy), 12 curated sites including slope/coast/no-data; evidence completeness100%, no silent default terrain/road. External fetch opt-in, timeout/retry≤2, SSRF allowlist, cache licensed data only.

Negative assertion: **No geocoded pin called cadastral boundary, elevation pixel called precise survey, unknown road access called legal access, or climate grid used as site sensor.**

## Manual gate — owner / expected result

Architect/site owner: verify one actual site boundary, access and uncertainties; expected corrections retained as evidence.

## CHECKPOINT XB-01

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381fca0dad8c04661ffa6?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/77


## WORK PACKAGE XB-02 · Room-program onboarding and constraint interpretation

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 0 · Evidence & onboarding**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-00; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-00**.
Resource lock(s): `experimental/room-program`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 2–3 research-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/brief/program.schema.json, normalize_program.py, tests/test_experimental_program.py; future app room selection prototype only after repository split.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Program rooms have stable IDs/type/count/floor, min/target/max area m², optional width/depth m, occupancy/accessibility needs, priority must/should/could and adjacency/privacy edges require/prefer/avoid. User confirms inferred values with per-field source. Multi-floor request may be captured now but solver reports unsupported until XB-07 extension gate. Calculate area budget and circulation reserve explicitly; contradictions (min>max, summed minimum>usable area, impossible adjacency) produce actionable conflict list and require owner choice. Use Drafted room-list usability as reference only, original interaction design and no proprietary asset copy.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT:30 briefs including duplicate names/IDs, mixed units, impossible area, ambiguous floors; deterministic normalization and100% hard contradiction detection on seeded cases. Browser prototype later preserves edits/back navigation and shows quantities/floors/relationships.

Negative assertion: **No model silently deleting rooms or turning hard constraints into preferences.**

## Manual gate — owner / expected result

Client+architect: confirm interpreted room program matches intended quantities, areas and relationships.

## CHECKPOINT XB-02

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381169331f7daa2480932?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/78


## WORK PACKAGE XB-03 · Client interview and desired-feeling research

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 0 · Evidence & onboarding**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-00; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-00**.
Resource lock(s): `experimental/client-interview`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 3–5 research-days plus recruitment (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/interview/{question-bank.md,preference.schema.json,study-protocol.md}, tests/test_experimental_preferences.py.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Interview daily routines, household changes, work/guests/privacy, sensory light/noise/temperature, movement/accessibility, social/secluded choices, materials and desired atmosphere with examples/tradeoffs. Optional skip/unknown and private household answers; no diagnosis/personality/mental-health inference or psychometric score. Each design implication links user quotation/answer→interpreted need→proposed spatial constraint→user confirmation. Literature-backed constructs guide questions, not clinical validity. Pilot5–8 consenting clients and≥2 architects, separate recruitment/demographics/limitations; deidentify research, raw answers private and deletable.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT prevents unsupported diagnostic fields; study checks ≥90% participant-confirmed requirement paraphrases, reports denominator/disagreement and interviews causing changes. Failure revises questions then repeats bounded pilot before use for autonomous constraints.

Negative assertion: **No inferred disability, family conflict or emotional trait used as a fact; no forced sensitive questions.**

## Manual gate — owner / expected result

Consenting participants+architect: review brief paraphrase and mapped design implications; expected corrections and consent captured.

## CHECKPOINT XB-03

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73811aa82fee4b328daf02?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/79


## WORK PACKAGE XB-04 · BYOK provider abstraction, credential safety and 27B Colab benchmark

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 0 · Evidence & onboarding**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-00; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-00**.
Resource lock(s): `experimental/providers`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 2–4 research-days plus compute availability (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/providers/{base.py,anthropic_adapter.py,openai_compatible.py}, experiments/colab/27b-eval.ipynb, tests/test_experimental_providers.py.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Provider request accepts messages/schema/model/limits/cancellation; response normalized validated JSON, usage input/output/cache tokens nullable, cost metadata/date/currency, latency/finish/error and raw response digest. Claude API candidate primary only after comparative gate; Qwen3.5-27B pinned model revision+license+quantization candidate on interactive Colab notebook. No free Colab capacity promise or always-on public tunnel. 27B theoretical weights54GB BF16 or13.5GB 4-bit before KV/runtime; inspect allocated VRAM and actual peak, skip as OOM rather than pretending it ran. User keys kept in per-run process memory by default, never browser storage/log/URL/repo; explicitly authorized vault retention later is separate design. Server proxy accepts only supported provider endpoints to prevent SSRF. No silent provider fallback (possible cost/data transfer).
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION: fake provider determinism and real opt-in20 structured prompts×3 repeats/provider; record schema-valid first pass/after≤2 repairs, groundedness, completed loop %, native token usage/null, retries, TTFT/total time, measured cost and OOM. Key scan on traces and cancellation tests; model trials require owner keys/budget.

Negative assertion: **No estimated bytes/4 called native token usage; Colab hardware/model not actually available remains NOT_RUN.**

## Manual gate — owner / expected result

Owner: supply credentials privately in future prototype, set spend cap, revoke afterward; expected no credential retained unless chosen.

## CHECKPOINT XB-04

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf7381d1864fdb8ba81750e0?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/80


## WORK PACKAGE XB-05 · Native internal agent state machine and research synthesis

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 1 · Native design loop**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-01, XB-02, XB-03, XB-04; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-01, XB-02, XB-03, XB-04**.
Resource lock(s): `experimental/orchestrator`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 3–5 research-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/orchestrator/{state.py,runner.py,tools.py}, tests/test_experimental_loop.py. Reuse core/project API via direct Python calls on pinned version.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Fixed state machine brief-confirmed→research→constraints→zoning→layout→geometry→validate→evaluate→human-review, with bounded repair transitions. One coordinator calls role-specific functions, not autonomous agent swarm; native typed calls, no MCP subprocess/client for internal work. Per iteration immutable state+constraint revision+candidate provenance; max3 candidates and2 repair rounds per stage, max60 model calls/run, max30min and user spend cap defaultUSD2 test-run. Stop on budget, infeasible hard constraints, missing critical evidence, stale brief or provider failure; return best valid candidate only with explicit incomplete label. Model output is untrusted; deterministic validators decide geometry feasibility, never model self-score.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT: deterministic fake-model run + injected provider timeout, research prompt injection and stale brief; completed stages replayable with native calls and no MCP/network without explicit provider/research adapter. Real benchmark reports all failure paths and cost, no indefinite retries.

Negative assertion: **No hidden retry beyond cap, unbounded free-text tool execution, or research text treated as system instructions.**

## Manual gate — owner / expected result

Architect: inspect evidence-to-constraint synthesis and approve unknown assumptions before candidate generation.

## CHECKPOINT XB-05

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738189ad16cc1bd6f7b8a1?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/81


## WORK PACKAGE XB-06 · Zoning and floor-plan algorithm comparison experiment

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 1 · Native design loop**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-05; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-05**.
Resource lock(s): `experimental/spatial-planning`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 4–8 research-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/planning/{baseline.py,solver.py,metrics.py,fixtures/manifest.json}, tests/test_experimental_layout.py.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. First deterministic baseline: single-storey orthogonal room rectangles on100mm grid, fixed footprint, enumerated adjacency and corridor graph; positive dimensions, no overlaps, exterior envelope, single owned seams, doors/connectivity. Compare CP-SAT discrete candidate placement against LLM zoning+same deterministic solver; pin OR-Tools only for experiment. Lexicographic objectives: hard feasibility→required adjacency/access→area deviation→circulation fraction→orientation/preference soft score. Stable seed and tie-break by ordered room IDs/placement tuples. Time limit30s/candidate; infeasible/time-limit distinguished. Nonrectangular/sloped/multi-storey are explicit later research branches with contract freeze, no guessed fallback.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

PERFORMANCE/research:30 training/dev briefs+20 held-out feasible/infeasible briefs×3 seeds, feasible hard-constraint violations0, false feasible0, report success/circulation/area error/diversity/runtime and failures. Target≥80% held-out feasible solved within30s; if below, keep EXPERIMENTAL and investigate, never relax constraints.

Negative assertion: **No bounding-box adjacency substituted for usable doors, GAN image called vector plan, or architect-quality claim from overlap tests.**

## Manual gate — owner / expected result

≥2 architects blind-rank held-out layouts against deterministic baseline with rubric; report disagreement.

## CHECKPOINT XB-06

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738191a799cec5d517abb4?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/82


## WORK PACKAGE XB-07 · Verified floor plan → Module IR → 3D/BOMC geometry

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 1 · Native design loop**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-06, SE-01; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-06, SE-01**.
Resource lock(s): `experimental/geometry-lowering`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 3–5 research-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/geometry/lower_plan.py, tests/test_experimental_lowering.py. READ ONLY core/geometry and bomc/compiler; no separate renderer/compiler.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Lower verified plan using one shared wall per room boundary owner=min lexical roomId, canonical metre/+Z transforms, explicit floor slab/wall/opening ops, exact port adjacency and labels. Use shared projection/compiler. Start single-floor flat-roof supported subset; windows require documented constraints and real wall cutouts. Preserve plan-room/face/module mapping, localized revision changes only affected private modules and invalidated seam dependents. Unsupported materials/string/face/output budgets return compiler typed errors, no geometry deletion. Multi-storey/stairs/sloped terrain await separate evidence contracts after one-floor gate.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION: all accepted held-out plans either compile valid BOMC and independent original Editor reopen or explicit unsupported; openings traversable in geometry, no duplicate seam faces, numeric triangle/material/transform parity.1mm geometric mapping tolerance, source IR remains full precision.

Negative assertion: **No reuse of BMB-032 single-row lowering as claim of full planning, or hidden compiler cap increase.**

## Manual gate — owner / expected result

Architect: inspect3D/plan overlay on5 diverse plans and verify door/window topology, circulation and labels.

## CHECKPOINT XB-07

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73819dac80fb8a7e4705d5?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/83


## WORK PACKAGE XB-08 · Independent evaluation, environmental constraints and uncertainty

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 2 · Research prototype**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-07; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-07**.
Resource lock(s): `experimental/evaluation`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 3–5 research-days plus assessors (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW experiments/evaluation/{rubric.md,score.py,report.py}, tests/test_experimental_evaluation.py.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Separate deterministic hard constraints (boundary/overlap/area/room count/connectivity) from preference satisfaction and environmental approximations. Orientation/sun-path computations have reproducible inputs; daylight/thermal/wind are heuristic unless validated simulator/test evidence exists. Local regulations require jurisdiction/source/version and architect confirmation; absent evidence means unknown, no permit-ready claim. Use held-out briefs and≥2 independent architect assessors, randomized blind order and original client-confirmed rubric; record agreement, revisions, errors, cost, diversity and all invalid outputs. Model evaluator may propose critique but cannot accept its own design.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

UNIT seeded invalid plans always fail; research report gives denominator/confidence intervals and limitations; zero accepted hard violations. Environmental claims trace to source or marked uncertain100%. Target preference score improvements must outperform baseline with paired comparisons, otherwise inconclusive.

Negative assertion: **No human fidelity/architectural validity inferred from compiler success or LLM score.**

## Manual gate — owner / expected result

Architect/client: assess privacy, routines, comfort, functional relationships and tradeoffs, expected documented agreement/disagreement.

## CHECKPOINT XB-08

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738163a7e9e6029e8a7f06?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/84


## WORK PACKAGE XB-09 · Separate application split and three-stage onboarding prototype

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 2 · Research prototype**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-01, XB-02, XB-03, XB-04, XB-08; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-01, XB-02, XB-03, XB-04, XB-08**.
Resource lock(s): `experimental/app-split`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 3–6 engineer-days after research gates (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST NEW docs/two-phase/FUTURE-REPO-HANDOFF.md with exact package/version hashes and migration inventory; actual future app paths app/site, app/program, app/interview, app/review only after owner selects repository name/visibility. No source scaffold in stable Editor.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Create standalone app after explicit future repo approval; brand remains TBD. Three stages map→room program→lifestyle/feeling, back/forward retains explicit draft, per-field evidence badges and conflict review, keyboard/mobile accessible. Native backend job loop calls shared Builder API directly. Shared compiler/IR stays published from Builder, version locked; research code transferred with attribution/history references, no private Editor package copy. App shows EXPERIMENTAL throughout onboarding/review/export and supports configurable provider with per-run spend/usage.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

STATIC handoff complete and BROWSER future separate-app tests: all3 stages editable; site accuracy caveat/evidence visible; quantity/floor/area/relations preserved; optional sensitive answers skip/delete; job cancel/review functional. No Stable dependency changed.

Negative assertion: **No finalized brand or public repository created without the bounded naming/visibility decision.**

## Manual gate — owner / expected result

Owner/client: use all3 stages then correct assumptions before design; expected understandable Experimental status and feedback controls.

## CHECKPOINT XB-09

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73812696bedb0e1892424e?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/85


## WORK PACKAGE XB-10 · Human feedback, localized revision and valid BOMC export

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 2 · Research prototype**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-09; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-09**.
Resource lock(s): `experimental/feedback`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 2–4 engineer-days (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST future app app/review and backend/feedback; current planning handoff docs only. Tests future feedback.spec.ts and shared experiments/test_experimental_feedback.py.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Feedback typed constraints reference room/module IDs and brief revision; preserve accepted layout regions unless explicitly unlocked. Re-run affected planning subproblem then shared geometry validation, compare candidate diff, user accepts/rejects proposed revision before replacing prior accepted candidate. Pause/cancel prevents subsequent state transition; checkpoint at stage boundaries to explicit user project save only under future app retention policy. Export valid BOMC through same compiler after user Save; no duplicate writer. User can reopen in Editor for inspection; reopening into experimental editable plan requires separate plan project artifact, never reverse-engineer arbitrary BOMC silently.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

INTEGRATION/BROWSER: move one room/window and preserve unrelated IDs/geometry; stale feedback rejected; rejected candidate leaves previous; canceled run costs stop; saved BOMC passes independent reader and original Editor. Preserve failed generation records sanitized.

Negative assertion: **No human rejection overwritten by autonomous loop, or impossible constraints silently weakened.**

## Manual gate — owner / expected result

Client+architect:2 revision cycles with clear diff and explicit acceptance; expected valid chosen outcome and intact prior revision.

## CHECKPOINT XB-10

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf738168b5b5da251a0dfa61?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/86


## WORK PACKAGE XB-11 · EXPERIMENTAL end-to-end pilot and provider go/no-go

Classification: **EXPERIMENTAL Builder — future brand TBD** · Priority **P2** · Milestone **Experimental 2 · Research prototype**.
State: **NOT STARTED / Blocked**. Await accepted AND prerequisites: XB-10; then claim exact base and locks under separate execution authority.
Repository owner: `KaisAbiyyi/sibambo-bomc-builder`. Dependencies (AND): **XB-10**.
Resource lock(s): `experimental/pilot`. Claim is unassigned; no lock is held by this plan. Execution: Research + Human. Estimate: 3–5 research-days plus participants (planning range, no spending authority).
Eligible implementer: any approved primary implementer that follows the frozen contract; delegates only with explicit later authorization, GPT-6 Luna maximum supported reasoning and disjoint ownership. Sol/eligible primary REVIEW optional unless stop rule triggers; direct exact-SHA self-review mandatory.

## Change surface / code anchors

MUST docs/two-phase/EXPERIMENTAL-PILOT-RECEIPT.md and future app pilot evidence manifest; research results never Stable blockers.

## Ordered patch contract

1. Read governing master SIB-TWO-PHASE-001 v1.0 and live prerequisite evidence; verify exact baseline, ownership and scope authority. If incomplete, stop dependent edits.
2. Run10 consented briefs (including difficult/infeasible sites) through3-stage onboarding, research, native loop, plan,3D, human feedback, Save and Editor reopen; compare Qwen27B Colab experiments with configured Claude API where available and same prompt/schema caps. Promotion target≥80% feasible briefs yield valid owner-reviewed candidate within budget;0 accepted hard violations;100% saved BOMC reopen;≥90% explicit provenance coverage; all client requirements user-confirmed. Publish actual cost/usage/latency/retries/structured-output reliability, failed denominators and uncertainty. Decide continue/revise/stop each intelligence track; app remains EXPERIMENTAL even if pilot passes.
3. Add the prescribed regression/proof, inspect final diff versus named surface, run affected existing checks on exact source. Preserve old fixture thresholds/claims. Record failures and NOT_RUN honestly.
4. Publish task-owned branch/draft PR and exact-source receipt; sync this Notion task and matching GitHub issue. Do not merge/deploy/release under planning authorization.

## Acceptance and test contract

LIVE/RESEARCH/MANUAL full pipeline with real provider (not scripted only), costs and raw evaluation links privately retained; public reports deidentified. No paid tests without budget/credential approval. Provider chosen only on measured quality/cost/privacy tradeoffs.

Negative assertion: **No pilot called architectural certification, construction documentation, or automatic Stable dependency.**

## Manual gate — owner / expected result

Owner+≥2 architects+clients: approve limited pilot result and remaining limitations; expected explicit go/no-go, not product release.

## CHECKPOINT XB-11

The listed artifact/mechanism and acceptance evidence must exist on the recorded SHA; dependent product claims must not appear before the named manual/live gate. Diff must remain in the named boundary. A missing symbol, changed baseline/lock, failing invariant, unsupported real input, missing credential/consent/budget, or architecture contradiction means **STOP dependent work → record evidence → REVIEW/PLAN**. Independent authorized work can continue. Do not weaken acceptance or select a substitute architecture. Return source/base SHAs, changed paths, test links/verdicts/limits, all failures, owner evidence and next action.

Notion source of task state: https://app.notion.com/p/412c4a6aaf73814d8ea8f55f69de1363?pvs=204

GitHub implementation/evidence: https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/87
