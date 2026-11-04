# BMB-023 — Typed bounded stdio MCP server

**Scope:** single pre-created, trusted-host-selected project, modern MCP protocol `2026-07-28` only. **Runtime:** Python 3.12 standard library; no third-party MCP SDK, HTTP listener, network fetch, shell execution, arbitrary filesystem path tool or dynamic plugin. **Resource lock:** `agent/mcp`.

## Launch

A trusted host creates a private single-project directory and applies low-privilege OS process/ACL or sandbox boundaries. Only launch the server for a directory entirely controlled by that principal; MCP code cannot replace filesystem isolation.

```sh
python -m agent.bmb_mcp --root /absolute/private/project
python -m agent.bmb_mcp --root /absolute/private/project --allow-writes
```

Without `--allow-writes`, mutating tools are hidden from `tools/list` and rejected from `tools/call` even when manually supplied. The command line root is *never* accepted from a tool argument; the client cannot switch projects. One process holds an exclusive per-root `.bmb-mcp.lock` to serialize mutation. A second server on the same project refuses startup. Do not launch other journal writers concurrently. Stdio stdout is reserved for newline-delimited JSON-RPC replies; stderr is for generic launch failures only.

## Modern per-request protocol

Every JSON-RPC request must include the following in `params._meta`:

```json
{
  "io.modelcontextprotocol/protocolVersion": "2026-07-28",
  "io.modelcontextprotocol/clientCapabilities": {},
  "io.modelcontextprotocol/clientInfo": {"name": "trusted-host", "version": "1.0"}
}
```

Discovery is `server/discover` (required); tools use `tools/list` and `tools/call`. The server deliberately does not negotiate `initialize`/legacy MCP 2025 sessions. Unknown versions return JSON-RPC `-32022` with `supported: ["2026-07-28"]`; absent required metadata returns `-32602`. Business and security errors from valid tools return `resultType: "complete"`, `isError: true`, with stable `structuredContent.error.code`. MCP transport/method parsing problems are JSON-RPC errors. Server capability is `tools`; no resources, subscriptions, prompts or HTTP transport.

## Typed allowlisted tools

| Name | Arguments | Access / core operation |
| --- | --- | --- |
| `bmb_create_module` | `moduleId` | Write, `JournalStore.create_module` |
| `bmb_inspect_module` | `moduleId`, optional boolean `includeBlocks` | Read, scoped journal snapshot |
| `bmb_edit_module` | `moduleId`, `expectedRevision`, `idempotencyKey`, `ops`, optional `minRevisions` | Write, atomic `JournalStore.apply` |
| `bmb_rollback_module` | `moduleId`, `expectedRevision`, `idempotencyKey`, `toRevision` | Write, `JournalStore.rollback` |
| `bmb_validate_journals` | Optional `moduleId` | Read, journal integrity |
| `bmb_validate_assembly` | `document` with `modules` and optional `schemaVersion: "1.0.0"` | Read, `core.assembly.assemble` |

Tool schemas are advertised as JSON Schema with `additionalProperties: false`, and verified again in the server before dispatch. Module/block/operation IDs must conform to shared core patterns. No tool grants arbitrary OS paths, URLs, program execution, or project IDs. The journal owns persisted changes, exact revisions and durable idempotency; the MCP server does not invent a second database or state representation.

## Enforced budgets

| Budget | Ceiling | Enforcement |
| --- | --- | --- |
| Inbound stdio JSON-RPC frame | 256 KiB | Read bounded frame; oversize frame closes stream |
| JSON structure | 32 nesting levels, 100,000 nodes | Verify before dispatch |
| Total serialized JSON-RPC response | 256 KiB | Fail with typed error, never truncate JSON |
| Core result before MCP wrapping | 128 KiB | Fail rather than return unbounded content |
| Project modules | 1,024 | Existing BMB-008 core limit |
| Edit operations | 1–256 per call | Reject before core |
| Dependency minimums | 256 | Reject before core |
| Module IR assembly modules | 1,024 | Verify before core |
| Existing project journal files | 32,768 files and 1 GiB | Pre/post stat scan; must have no symlink/junction/hardlink |
| Per-tool deadline | 30 s | Worker process killed on timeout |
| Worker virtual memory | 512 MiB on POSIX | `RLIMIT_AS`; Windows requires a host Job Object |
| Rate | 60 tools/minute and 600/hour | In-memory bounded sliding windows per server process |
| Concurrency | One request at a time and one server per root | Single reader dispatcher plus root-exclusive file lock |

These caps can be *lowered* in later hardening; do not assume all production resource controls are satisfied. The adapter uses Python `spawn` workers, not `shell=True` or arbitrary command spawn. It applies a POSIX umask of `077`; Windows host must independently provide restricted ACL/DACL and Job Object memory/CPU quotas. Caller self-reported `clientInfo` is not authentication. The launcher and its OS identity are the trusted principal. The project root must be owned by that principal and inaccessible to hostile co-tenants.

## Error and failure semantics

Typed errors include `INVALID_ARGUMENT`, `UNKNOWN_TOOL`, `PERMISSION_DENIED`, `PATH_OUTSIDE_ROOT`, `LIMIT_EXCEEDED`, `DEPTH_LIMIT`, `REVISION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `CORRUPT_INPUT`, `STORAGE_ERROR`, `BUSY`, `TIMEOUT`, `DURABILITY_UNCERTAIN`, `INTERNAL_ERROR`. Exception traces, environment variables and absolute host paths are not sent through MCP. The deadline can terminate a worker during a journal write: `TIMEOUT` means **commit status unknown**, not an automatic rollback guarantee. The existing journal handles torn tails on next open, but owner-level power-loss validation is separate. Retry with the same durable idempotency key only after inspecting project state.

## Scope exclusions and security evidence

This adapter rejects static symlinks/junctions/hardlinked journal paths before core I/O. It is **not** a proof of race-free handle-relative/no-follow I/O on Windows or against a malicious local process that can mutate the project tree during calls. The host must enforce a private root and one principal; BMB-030 owns hardening for symlink/junction TOCTOU, hostile multi-principal access, advanced cancellation, rate-limit persistence across process restarts, crash injection, CPU/Job Object limits and adversarial resource peaks. Stdio `notifications/cancelled` receives no reply but does not currently preempt an already executing synchronous request; a 30s hard deadline applies. Source and tests are synthetic-only under the project GPL/fixture policy.

**NOT_RUN gates:** owner-native Windows ACL/Job Object, multi-process hostile symlink swaps, physical crashes, live external MCP-client compatibility, consumer BOMC readback, geometry validation and full agent benchmark. A green unit-test matrix is not evidence that these gates passed.

## Tests

```sh
python -m unittest discover -s tests -p test_bmb023_mcp.py -v
```

Dedicated GitHub Actions `bmb023-mcp.yml` runs synthetic stdio/subprocess tests on Ubuntu and Windows plus BMB-022 CLI, BMB-010 journal, BMB-008 identity and BMB-011 assembly regression suites. Record exact PR HEAD, actual workflow URLs, truthful PASS/FAIL/NOT_RUN and owner merge gate in the issue and Notion before closure.

References: [MCP 2026-07-28 stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio), [Discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover), [MCP request metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic/index), [BMB-004 threat model](MCP-THREAT-MODEL.md), [BMB-022 CLI](BMB-022-HEADLESS-CLI.md).
