# Remote tool error catalogue (draft-errors-v1)

Every failed tool call and owner REST call returns one `error` object (schema: `schemas/draft-errors-v1.schema.json`):
`code`, `message`, `retryable`, `nextAction`, and for retryable waits `retryAfterMs`. **A failed call never changes the draft** (typed IR, revisions, digest, idempotency cache and tombstones are unchanged; `tests/test_remote_mcp.py` asserts this for every reachable code).

The v1.3 / SE-02 codes keep their names. The actor's own `PAUSED`, `QUEUE_FULL` and `OWNER_ABSENT` are reported to agents as `PAUSED_BY_OWNER`, `BUSY` and `NO_ACTIVE_VIEWER`; both spellings stay in this table.

| Code | Retryable | HTTP (owner REST) | Next action |
| --- | --- | --- | --- |
| `REVISION_CONFLICT` | yes | 409 | Call read_project, rebuild the change on the new projectRevision, resend with a new idempotencyKey. |
| `DEPENDENCY_STALE` | yes | 409 | Call read_project, raise the dependency minRevision or rebuild against current revisions. |
| `IDEMPOTENCY_CONFLICT` | no | 409 | Use a new idempotencyKey for a different request; resend the identical request only to replay. |
| `FENCE_STALE` | yes | 409 | Call acquire_writer to get a current fence, then resend. |
| `LEASE_HELD` | yes | 409 | Another writer holds the lease; wait retryAfterMs, then call acquire_writer again. |
| `LEASE_EXPIRED` | yes | 409 | Call acquire_writer again, then resend. |
| `GRANT_DENIED` | no | 403 | Ask the project owner for the needed read/write grant. |
| `OWNER_ABSENT` | yes | 409 | Ask the owner to open the project in the Editor; retry after it is open. |
| `PAUSED` | yes | 409 | The owner paused the project; wait for the owner to resume. |
| `QUEUE_FULL` | yes | 429 | Too many calls are pending; wait retryAfterMs and send writes one at a time. |
| `TOMBSTONED` | no | 409 | That moduleId was removed in this epoch; choose a new moduleId. |
| `INVALID_REQUEST` | no | 400 | Fix the request shape against the tool schema and resend. |
| `INVALID_OPERATION` | no | 422 | Fix the geometry/seam problem named in message and resend; nothing was changed. |
| `BUDGET_EXCEEDED` | no | 422 | Use fewer or smaller modules; one room per module, at most 8 modules per transaction. |
| `EPOCH_CLOSED` | no | 410 | Ask the owner to open the new epoch and reconnect. |
| `NOT_FOUND` | no | 404 | Check projectId; the same answer is returned for unknown and not-yours. |
| `TENANT_MISMATCH` | no | 403 | The grant belongs to another tenant/project; use the correct project URL. |
| `INTERNAL_ERROR` | yes | 500 | State is unchanged. Call read_project, then retry once; report if it repeats. |
| `UNAUTHENTICATED` (new in SE-03) | no | 401 | Authenticate with OAuth (PKCE S256) for this resource and retry. |
| `FORBIDDEN` (new in SE-03) | no | 403 | Ask the project owner to grant this principal access to the project. |
| `BUSY` (new in SE-03) | yes | 429 | A write is already in flight for this project; wait retryAfterMs and send writes one at a time. |
| `RENDER_ACK_TIMEOUT` (new in SE-03) | yes | 504 | The Editor did not confirm the render in time; call read_project, then retry once. |
| `NO_ACTIVE_VIEWER` (new in SE-03) | yes | 409 | Writes need an active viewer. Ask the owner to open the project in the Editor, then retry. |
| `PAUSED_BY_OWNER` (new in SE-03) | yes | 409 | The owner paused agent writes; wait, then call read_project to see if paused is false. |

## Decisions

SE-05 adds `RENDER_PENDING` (retryable, HTTP 409): wait for the primary Editor viewer's render ACK, query `operation_status` before retrying. It does not roll back or reapply an accepted transaction. The historical SE-03 receipt retains its 24-code projection; current schema/catalogue and SE-05 tests include this additional code.

- `NO_ACTIVE_VIEWER`: writes are rejected while no viewer has the project open (owner heartbeat alive). Reads and `acquire_writer` for an absent viewer are rejected the same way.
- `RENDER_ACK_TIMEOUT`: raised **before** a write is submitted, when the viewer channel does not acknowledge in time, so nothing is committed. The real channel arrives with SE-05; until then the viewer check is the owner heartbeat.
- `PAUSED_BY_OWNER`: the owner's pause wins at the next operation boundary; `nextAction` says to wait and re-read `paused`.
- `BUSY` carries `retryAfterMs`; resend the **same** request (same `idempotencyKey`) so a retry can never apply twice.
- `UNAUTHENTICATED` / `FORBIDDEN` are also HTTP 401 / 403 on `/mcp` and the owner REST surface. Unknown projects and other tenants' projects both answer `NOT_FOUND` (404).

Reproduce the table: `python -c "from service import errors; print(sorted(errors.CATALOG))"`.
