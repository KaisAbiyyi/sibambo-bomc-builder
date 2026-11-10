# Stable remote MCP — D16 hardening proposals (public edition)

> **Status: DRAFT planning proposal, 2026-11-10. Not owner-accepted.** Additive to SIB-TWO-PHASE-001 v1.5. No task status, claim, merge, deploy or IMPLEMENT authority changes. Nothing here is implemented or tested. This public edition covers **Stable and shared-core only**; the complete planning note lives in the private Editor repository and in Notion.

The proposals below came from re-reading the SE-02 … SE-11 contracts against the MCP 2026-07-28 specification and the current source. Each item names the task that would own it if the owner accepts it. IDs match the private D16 note.

## Why now

Two findings change the order of work rather than its content:

1. **Real-client compatibility is only exercised at the final manual gates.** Which registration method Claude Code and Codex use against the chosen identity provider, whether they send the `resource` parameter, and whether the provider advertises `code_challenge_methods_supported` decide the shape of `service/auth.py`. The specification requires clients to refuse when PKCE support is not advertised. Probe first (S5).
2. **Render acknowledgement gates every write**, yet the contracts do not say what an agent sees when no viewer is attached or the tab is hidden. That policy has to exist before SE-05 and SE-06 are written (S8).

## Security

| ID | Gap | Proposal | Owner task |
| --- | --- | --- | --- |
| S2 | The D11 stdio → actor bridge is described as a thin loopback client with no authentication requirement. Any local process could call it | Named pipe / Unix socket with an owner-only ACL, or loopback plus a per-launch random secret read from an owner-only file. Bind 127.0.0.1. Negative test: a second local process without the secret is refused | SE-02 |
| S3 | SE-03 does not enumerate transport-conformance tests | Invalid `Origin` → 403. `MCP-Protocol-Version`, `Mcp-Method` or `Mcp-Name` disagreeing with the body → 400 `HeaderMismatch` (−32020). GET / DELETE on the endpoint → 405. `Mcp-Session-Id` ignored, never minted. No `Last-Event-ID` resumption. Send `X-Accel-Buffering: no` and keep-alive comments on long streams | SE-03 |
| S4 | Writer leases, operation IDs, idempotency keys and WebSocket tickets are state handles. Possession must never authenticate | Explicit rows: a handle minted for principal A presented by principal B (including one with a read grant on the same project) is rejected; a lease released by a non-holder is rejected | SE-09 |
| S5 | No early proof that real clients can register and obtain a correctly audience-bound token from the chosen provider | **SE-03.0 compatibility probe** before adapter code: record protocol version, registration method and `resource` behaviour of the installed Claude Code and Codex versions against the nonproduction tenant. Requires separate owner approval | SE-03 |
| S6 | A Tailscale Funnel hostname is public internet exposure, limited to ports 443 / 8443 / 10000, with non-configurable bandwidth limits | Path allowlist in the service (MCP endpoint, draft socket, owner API, OAuth metadata, health); everything else 404. Health reveals nothing. Rate-limit unauthenticated requests. The stop script closes the tunnel first | SE-09, D11 scripts |
| S8 | Browser render ACK gates the next write. An early or forged ACK, or an absent viewer, is unspecified | The server compares the ACK digest with the digest it computed for that revision, accepts it only from the owner-ticketed socket, once per revision. ACK deadline → project state `awaiting_viewer`. Typed errors `RENDER_ACK_TIMEOUT` (retryable) and `NO_ACTIVE_VIEWER`. An ACK is never skipped automatically | SE-05 service side, SE-03.B |
| S9 | Stored injection across agents: text authored by one agent is read by another through `read_project` / `inspect_module` | The construction guide marks every string in a tool result as untrusted data. Add two rows to the threat tests: hostile label read by a second agent; hostile label echoed to the owner view | SE-09 |
| S10 | Two owner tabs mean two viewers; whose ACK counts is undefined | One primary viewer per project (latest attached); others are read-only followers and do not gate | SE-05 service side |
| S11 | `service/requirements.lock` is not required to carry hashes | Install with `--require-hashes`; CI fails on an unhashed lock | SE-03 |

## Performance

| ID | Gap | Proposal | Owner task |
| --- | --- | --- | --- |
| P1 | `replace_module` carries the whole module body. Checked-in examples are 0.9–1.4 KiB per room module; the cap is 64 KiB. Large modules make every small revision expensive for the agent | The guide fixes a granularity budget (one room per module, target ≤ 8 KiB). SE-10 records bytes per operation and the gap between operations. If the measured median crosses a recorded threshold, open a plan for parametric patch operations | SE-03.A, SE-10 |
| P2 | A 256 KiB tool response can cost an agent tens of thousands of tokens | `read_project` is compact by default (IDs, revisions, hashes, bounds; target ≤ 4 KiB); detail only through `inspect_module`. Report total tool-result bytes per build | SE-03, SE-11 |
| P3 | An isolated geometry process with a 30 s deadline versus a P95 ≤ 500 ms accepted-to-ACK target: spawning Python per operation is costly on Windows | Warm isolated worker (pool of one, recycled after N operations or on RSS growth). Measure cold and warm | SE-09, SE-10 |
| P5 | "20 active projects per worker" combined with 10,000 modules × 64 KiB does not fit a 512 MiB instance | Per-project live-draft caps (starting proposal ≤ 200 modules, ≤ 8 MiB canonical IR, snapshot chunks ≤ 2 MiB) and RAM-based admission. Numbers are to be measured, not promised | SE-02 |
| P6 | "No unbounded replay" has no number; a slow viewer can grow a server queue | Per-connection queue bound (starting proposal 64 events / 4 MiB) then forced snapshot resync. Slow-consumer test | SE-05 service side |
| P7 | Agents may issue parallel tool calls; with a single fenced writer the result is a run of `REVISION_CONFLICT` | Guide: write sequentially. Server: `BUSY` with `retryAfterMs`. SE-11 reports the conflict rate per client | SE-03.A, SE-11 |

## Agent-facing behaviour

| ID | Gap | Proposal | Owner task |
| --- | --- | --- | --- |
| X2 | When the owner pauses, the agent is not told what to do and may retry in a loop | Typed `PAUSED_BY_OWNER` with `nextAction`: read the owner request inbox, wait, back off | SE-03.B |
| G3 | Module IR v1 admits `floor-slab`, `wall-run` and `opening-cut` only. Pitched roofs and stairs exist as internal geometry primitives (BMB-016) but cannot be persisted or compiled | State this as a Stable product limit in the SE-11 record and demo material. Adopting an IR v1.1 remains a separate plan decision | SE-11 |

New error codes are additive; the v1.3 codes are unchanged.

## What does not change

The SE-11 phase gate, atomic 1–8 module transactions, the single fenced writer, the 64 KiB / 256 KiB caps, the absence of any MCP save or export tool, owner-only Save, no draft persistence before Save, and the rule that tests are never weakened to pass.

## References

MCP 2026-07-28: [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http), [Authorization — Security Considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations), [Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices). [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel). Existing design contract: [MCP-THREAT-MODEL.md](../MCP-THREAT-MODEL.md).
