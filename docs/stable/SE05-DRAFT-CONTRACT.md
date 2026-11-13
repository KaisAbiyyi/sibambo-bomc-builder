# SE-05 public draft integration contract

Status: implementation contract for the full SE-05 continuation authorized by the owner on 13 November 2026. The owner's instruction to fix every blocker and implement FULL supersedes the earlier source stop. No historical actor/compiler fixture or expected hash is replaced. This document records the exact compatibility mapping rather than silently changing the accepted SE-01/02/03 internals.

## Identity and owner API

The verified credential identity is `(issuer, subject, signed azp/client_id)` within the exact tenant/project lookup. MCP `clientInfo` is display data. A different OAuth application with the same human subject is a different principal and needs its own explicit grant; it cannot act as the owner's BFF. Missing signed application identity fails authentication. Two processes using the same credential principal share that grant.

`/v1/projects/{project}/owner/mcp` implements `se04-owner-mcp-v1` for the Editor BFF. Only authenticated POST `/open` opens a project; GET does not create one. Its `/grants`, `/pause`, `/requests` and `/ticket` actions use the exact owner actor. Pairing is bound to the signed subject/client, requested read/write scopes, five-minute pending entry and eight-character comparison code; approval has five attempts. The owner status omits the comparison code. Read/write grants never add a Save/export MCP tool. Legacy `/owner/v1/projects/*` routes remain available to authenticated owners; their grant/revoke/pause/resume changes also invalidate outstanding new tickets.

Ticket POST returns `ticket`, `ticketExpiresAt` (UTC with millisecond precision) and `ttlSeconds:30`. RAM holds only its SHA-256 and exact actor/authority binding. It is consumed once, including failed attachment. Grant/revoke/pause, explicit new epoch, logout or expiry prevents reuse. Authenticated `/owner/v1/logout` pauses/fences the owner's channels and disconnects their viewers, retaining canonical state until the normal idle expiry.

## Preserved actor, explicit wire mapping

The accepted actor retains integer internal epochs, the `draft-operation-v1` transaction envelope, uint32/core limits, canonical-module ledger, reciprocal-seam validation, tombstones and 1024-entry outcome cache. Existing legacy operations are unchanged. Project IDs retain the accepted service's validated IDs. The application channel exposes a random UUID per actor instance; this UUID never changes the actor's integer identity. A new actor gets a different UUID and the browser refuses to silently replace retained state across epochs. Explicit restoration belongs to SE-08.

Numeric `DraftOperationV1` is accepted alongside legacy operations:

| Public field | Accepted actor representation |
| --- | --- |
| `operationId` UUID | unchanged `transactionId` and `idempotencyKey` |
| `expectedProjectRevision` | `baseProjectRevision`, subject to the stricter accepted core bound |
| `expectedModuleRevisions[id]` | each target's `expectedModuleRevision`; mandatory current CAS for existing referenced dependencies/parents/seam peers outside the transaction |
| `leaseFence` | must match the authenticated tool's live fenced lease |
| UUID `epoch` | must equal this actor instance's channel UUID |
| `action.changes` | 1–8 unique targets, sorted by ASCII module ID, staged in one existing actor transaction |

The complete normalized numeric request has a separate RAM digest, bounded by the actor's retained outcomes. Changing any wire field under an accepted operation ID is an idempotency conflict. Exact accepted retries return the known outcome even after a lost response/disconnection, without another write/event. Dependency checks occur after exact replay recognition. No accepted mutation is rolled back because its HTTP response or viewer disappeared. Optional `requestId` associates the first accepted operation with an inbox item; changing it on a retry cannot create another completion receipt.

## Channel, presence and bounds

`wss://<configured service>/draft` permits only the exact allowlisted Editor Origin and Host, with no query. The first message must be HELLO with the ticket within five seconds. The browser requests the ticket through same-origin BFF/CSRF; no bearer or ticket goes in a WebSocket URL, subprotocol, storage or log. HELLO always receives a bounded current snapshot; reconnect never requires unlimited replay.

Snapshot/event module records carry exact canonical JSON and shared projection JSON strings with separate UTF-8 SHA-256 hashes. A sorted active/tombstone manifest produces `draftSha256`. Snapshot caching is keyed by the immutable actor-state reference; ACK/heartbeat does not recompile geometry. Events contain the entire accepted transaction and one project revision. The event ring is at most 128 events / 8 MiB; each peer queue is at most 64 events / 4 MiB. Overflow drops the queue, sends `resync_required` and blocks ACK until a replacement snapshot. A snapshot above the bounded channel budget is rejected, never truncated.

The last attached tab is the primary viewer; previous tabs become read-only followers. Closing a primary does not promote a stale follower. Only a visible, current, primary socket with the exact current digest/revision can ACK. The actual browser implementation ACKs after worker schema/hash validation, atomic projection swap, successful render and next animation frame. Heartbeats are five seconds, presence expires in fifteen, and pending ACK beyond two seconds yields `RENDER_ACK_TIMEOUT`; before that writes get `RENDER_PENDING`. No active viewer gives `NO_ACTIVE_VIEWER`. REST owner heartbeat cannot substitute for render presence. Production host defaults are owner heartbeat 15 seconds, writer lease 30 seconds and eight pending actor requests; explicit legacy test doubles retain their frozen test settings.

All unsaved content stays in RAM. After thirty minutes without a connected peer, sweep closes the actor and purges channel/tickets/requests/registry entries. No draft journal, browser persistence, automatic Save, producer package or external deployment is introduced.

## Requests and acceptance boundary

Owner request text stays in the existing bounded volatile inbox (50 × 4 KiB, 30 minutes). Typed numeric parameters and up to eight canonical module IDs remain attached to that request. Withdrawn items are excluded from the agent inbox. `owner_request_status` contains only item IDs/statuses, never request text, and never advances the project revision. An item becomes `addressed` only after its associated accepted revision receives the render ACK; withdrawal cannot be overwritten by a late ACK.

`tests/test_draft_ws.py` exercises actual TLS HTTP, SDK MCP and application WebSocket traffic, signed pairing/identity, expiry/reuse/origin/project negatives, primary/follower ACK, lost accepted response/retry, numeric CAS, tombstones, bounded queues, logout and idle purge. The private Editor integration CI checks out this public Builder at a pinned commit and runs the actual production BFF → WSS → worker → shared viewport → frame ACK. Public Builder does not fetch private Editor source.

Automated synthetic TLS evidence is separate from real managed IdP, real Claude Code/Codex registrations, public tunnel and owner acceptance. Those live gates remain explicit. Full rendering UX/performance qualification, Save/reopen and restore remain their own later milestones; no Stable final acceptance follows from this source change alone.
