# BMB-004 — MCP / agent security threat model (design contract v0)

**Status:** P0 design specification only; not an implemented MCP server or verified sandbox. **Scope lock:** `research/agent`. **Downstream:** BMB-008 identity, BMB-022 CLI, BMB-023 MCP, BMB-024 context, BMB-030 adversarial QA.

## 1. Protocol and deployment boundary

- Target the MCP **2026-07-28** contract for future stdio server work: stateless per-request protocol metadata and capability discovery, with no assumption of the previous `initialize` handshake or a protocol-maintained session. Legacy 2025 clients require a **separately tested compatibility adapter**, not opportunistic mixed parsing.
- The Builder is a **local, single-project subprocess** launched by a trusted host over stdio. Stdout is reserved for MCP frames; diagnostics go to stderr. No HTTP listener, subprocess tool, shell command, remote fetch, plugin execution, or dynamically loaded script in MVP.
- The server runs under a dedicated low-privilege identity, with a process/container-level mount or filesystem ACL restricted to one explicitly granted project root. MCP Roots are *hints*, not an access-control primitive (deprecated in 2026-07-28).
- Host approval determines the launch root and allowed mutating tools. Tool descriptions, model-generated arguments, module content, project metadata and file contents are **untrusted**. The host may prompt for sensitive writes, but **server enforcement is mandatory even when the host approves**.
- Project/workspace ID is bound server-side to launch configuration and authenticated caller, not supplied as a bypass-capable absolute path. Random operation handles and idempotency keys are not authentication credentials.

Sources: [official 2026-07-28 overview](https://modelcontextprotocol.io/specification/2026-07-28), [official stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports), [MCP local server isolation](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/local-server-security), [Roots deprecation](https://modelcontextprotocol.io/specification/2026-07-28/client/roots).

## 2. Assets, actors and trust boundaries

**Assets:** project manifest, editable module IR, revision journal, geometry/mesh buffers, generated BOMC, process CPU/RAM/disk quota, audit trail, host filesystem and credentials.

**Adversaries:** malicious prompt/document or imported module; compromised client issuing valid-looking tool calls; accidentally overbroad agent edits; replaying agent; another OS principal; malformed or hostile BOMC input. Owner-authorized ordinary design edits are not treated as malicious, but are still limited.

```text
Untrusted prompt / fixture / imported data
  -> host consent and MCP tool-call boundary
  -> per-request schema + authorization + global budget check
  -> single-project dispatcher / revision & idempotency journal
  -> sandboxed core and temp storage
  -> atomic artifact promotion within project root
  -> bounded structured response and audit metadata
```

All policy checks repeat for **every** request and every mutation; no reliance on agent instructions, a path prefix check, or an earlier approval.

## 3. Threats and required mitigations

| ID | Attack / failure | Required invariant | Negative acceptance test |
|---|---|---|---|
| SEC-01 | `../`, absolute paths, Windows drives/UNC, mixed separators or percent-encoded traversal | Tools accept opaque module/project IDs; if a relative artifact name is allowed, decode once, reject separators/traversal/absolute and normalize against fixed root | Traversal never reads/writes outside root |
| SEC-02 | Symlink/junction/reparse-point redirection or TOCTOU after validation | Root capability + OS isolation; directory-relative no-follow open; reject links for mutations; recheck file identity; atomic rename in same trusted directory | Replaced link cannot redirect write |
| SEC-03 | Hardlinks, casefold or reserved-device filenames | No raw user path selection; create private files exclusively; reject devices/invalid names; sandbox volume private from other tenants | Alias cannot overwrite foreign file |
| SEC-04 | Imported JSON or BOMC with deeply nested graph, oversized count, decompression bomb, invalid transform | Streaming/limited parser; cap input/expanded bytes/depth/ratio; reject nonfinite numerics, cycles, invalid IDs, CRC failure; fail closed | Malformed corpus bounded |
| SEC-05 | Agent prompt injection embedded in manifest/mesh label or tool output | Treat data as data; never parse instructions from artifact fields; escape/sanitize summaries and log data; redact credentials | Hostile label does not change tool access |
| SEC-06 | Shell/command escape via module metadata, filename or tool args | Explicit allowlisted typed tools; never interpolate into shell; no command execution, network fetch or dynamic code loading | `cmd`, URL or script-like payload rejected |
| SEC-07 | Request flooding and unbounded tool output | Fixed time/bytes/count/call/concurrency budgets; bounded pagination; cancellation and process hard limits | Oversize and timeout yield typed errors |
| SEC-08 | Retried mutation duplicates walls or overwrites changed module | Expected revision CAS + persisted scoped idempotency key/argument fingerprint + atomic commit | Same key replays; changed payload conflicts |
| SEC-09 | Cross-project handle guessing and unauthenticated request | Bind principal, project, scope, handle and revision on *each* access; no trust in handle possession | Foreign handle rejected |
| SEC-10 | Partial BOMC or journal overwrite on crash | Stage/checksum/fsync (where supported), atomic rename, crash recovery; journal and artifact publication recover as a unit | Restart cannot expose half-written artifact |
| SEC-11 | Sensitive information in stderr, errors or logs | Structured redacted diagnostics only, no arbitrary file dump, secrets, env, full host paths or raw prompt by default | Audit/log scan does not expose secret |
| SEC-12 | Stale MCP protocol shapes and version mismatch | Explicit protocol version negotiation/support matrix; 2025 handshake compatibility only via audited adapter | Unsupported version rejected safely |

On Windows, canonical path strings and `realpath` checks alone are insufficient against junction/reparse races; permission-restricted root and handle-relative, no-follow behavior (or rejection when unavailable) are mandatory. On Linux, filesystem namespace/permissions supplement openat-style descriptor-relative access. Do not call these invariants implemented until tests prove them.

## 4. Provisional *server-enforced* hard limits

These are **design defaults** to pin in BMB-023 and tune using BMB-028/030 measurements, not benchmark outcomes. Reject before allocation when possible; maintain cumulative limits across nested calls.

| Budget | Initial hard ceiling | Accounting / rejection |
|---|---:|---|
| JSON-RPC frame received | 256 KiB UTF-8 | `REQUEST_TOO_LARGE`; reject prior to JSON materialization |
| Tool response (structured + text) | 256 KiB | Bounded page with continuation, never truncated invalid JSON |
| Project manifest returned | 64 KiB per call | Paginate and return only IDs, summary, cursor |
| Module inspect vertex details | 10,000 vertices / call | Geometry content must be explicitly opted in, paginated |
| Module count | 10,000 / project | Validate before commit; BMB-006 may lower default |
| Graph nesting | 32 levels | `DEPTH_LIMIT` on parse/traverse |
| Source artifact import | 64 MiB stored | Stream/limit + strict format validation |
| Expanded imported payload | 256 MiB or 20:1 ratio, whichever is lower | `EXPANSION_LIMIT` before allocation |
| Compiled BOMC output | 256 MiB | Abort/stage cleanup; not an arbitrary-sized exporter |
| Mutation wall-clock | 30 seconds / request | Cooperative cancellation + worker kill after grace |
| Compiling wall-clock | 120 seconds / request | Separate child isolation, hard timeout |
| Worker memory | 512 MiB RSS / process | OS enforced when available; cannot rely on JS heap check |
| Concurrent mutations | 1 / project | Queue bounded at 8, `BUSY` thereafter |
| In-flight reads | 4 / project | Snapshot consistency; response budget still applies |
| Project disk quota | 1 GiB including temp/journal | Reserve estimated bytes then atomic commit |
| Session rate | 60 calls/min and 600 calls/hour per principal/project | Token-bucket + request accounting; no client-provided bypass |

Configuration may **lower** hard caps; increases require documented owner opt-in, explicit risk review and tests. No implicit unlimited mode. Disk/temp cleanup on cancellation and failed validation is required. Enforce CPU, memory, open files, network and process privileges at OS boundary, not only in app code.

## 5. Mutations, idempotency and crash recovery

Required internal command envelope (illustrative; **not** a frozen MCP `inputSchema`):

```json
{
  "project_id": "synthetic-house",
  "operation": "module_patch",
  "module_id": "house/f1/living",
  "expected_revision": 2,
  "idempotency_key": "step-07-patch-living-v1",
  "patch": {"door_width_m": 0.95}
}
```

1. Reject invalid schema, unknown operation, missing scope or resource-limit excess before mutation.
2. Canonicalize request bytes; fingerprint `principal + project + operation + key + canonical args`. Keys are scoped; no cross-project replay.
3. Atomically check persisted key journal and expected revision under project serialization. Identical key+fingerprint returns original stored result *without reapplying* (including after restart); same key/different fingerprint -> `IDEMPOTENCY_CONFLICT`.
4. New key with stale expected revision -> `REVISION_CONFLICT` with current revision (never last-write-wins). Creation uses expected project or parent revision; no silent upsert.
5. Stage replacement module and journal entry, validate graph and quota, atomically publish revision and receipt. A crash must resolve to the old state or complete committed state. Never mark success while storage is not durable.
6. Failures do not advance revision or produce partial modules. Retry is safe on connection loss; timeouts do not imply rollback until the receipt is queried. Record `request_id`, hashed input and result status; avoid secret-bearing payload logs.
7. Idempotency receipts persist at least for the lifetime of the project journal, including rollback/reopen; subsequent garbage collection must not allow ambiguous replay. Future BMB-008 defines exact retention/migration.

Response template: `{ok, project_id, operation_id, revisions:{before,after}, changed_ids:[], budget:{bytes,elapsed_ms}, diagnostics:[]}`. Typed errors: `INVALID_ARGUMENT`, `PERMISSION_DENIED`, `PATH_OUTSIDE_ROOT`, `LIMIT_EXCEEDED`, `EXPANSION_LIMIT`, `REVISION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `BUSY`, `TIMEOUT`, `CANCELLED`, `CORRUPT_INPUT`, `UNSUPPORTED_VERSION`, `INTERNAL_ERROR`. MCP-level framing/method errors are JSON-RPC errors; valid tool invocations that fail business/security validation return actionable tool results with `isError: true` and a stable typed code.

## 6. Test and ownership gates

- **BMB-023 implementation gate:** enumerate server-exposed tools and validate typed input schemas; stdio framing for pinned 2026 revision; isolation/authorization; quotas; optimistic locking/idempotency; bounded tool outputs; deterministic errors; no shell/network escape. Each failure must not mutate state.
- **BMB-030 security gate:** execute SEC-01..12 adversarial corpus across Linux + Windows where feasible; symlink/junction race, crash at every commit stage, forged project handles, decompress/recursion/resource bombs, reconnect/replay, cancel/timeout cleanup. Record actual resource peaks and gate limits.
- **BMB-025 agent gate:** execute [scripted baseline](AGENT-BASELINE-BENCHMARK.md) with deployed tools. P0 fixture validation alone is **not** live security or geometric acceptance.
- **BMB-021 consumer gate:** independent Editor and Model-Eval BOMC import/readback; compiled file checksum and semantic parity. Owner/native visual gate distinct.
- **Public provenance:** GPL-3.0 Builder, clean-room source only, synthetic-only fixtures per [owner policy](LICENSE-IP-FIXTURE-POLICY.md). Never copy source from private Editor/SketchUp repos into Builder.

### Evidence status on design publication

`DESIGN_REVIEW` is valid when the document/fixture lint tests pass and the exact PR diff is reviewed. All server path isolation, adversarial tests, live agent tool calls, binary output and consumer load tests remain `NOT_RUN` until later implementation. Never upgrade a design-only pass into a server-security PASS.
