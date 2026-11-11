"""SE-03.B: the typed error catalogue. v1.3 / SE-02 codes are unchanged; every entry adds
``retryable`` and ``nextAction``. The wire layer maps by code only (no free-text parsing).
"""
from __future__ import annotations

from core.project import state as S

# code -> (retryable, nextAction, httpStatus for the owner REST surface)
CATALOG: dict[str, tuple[bool, str, int]] = {
    # --- v1.3 / SE-02 codes, unchanged names -------------------------------------------
    S.REVISION_CONFLICT: (True, "Call read_project, rebuild the change on the new projectRevision, resend with a new idempotencyKey.", 409),
    S.DEPENDENCY_STALE: (True, "Call read_project, raise the dependency minRevision or rebuild against current revisions.", 409),
    S.IDEMPOTENCY_CONFLICT: (False, "Use a new idempotencyKey for a different request; resend the identical request only to replay.", 409),
    S.FENCE_STALE: (True, "Call acquire_writer to get a current fence, then resend.", 409),
    S.LEASE_HELD: (True, "Another writer holds the lease; wait retryAfterMs, then call acquire_writer again.", 409),
    S.LEASE_EXPIRED: (True, "Call acquire_writer again, then resend.", 409),
    S.GRANT_DENIED: (False, "Ask the project owner for the needed read/write grant.", 403),
    S.OWNER_ABSENT: (True, "Ask the owner to open the project in the Editor; retry after it is open.", 409),
    S.PAUSED: (True, "The owner paused the project; wait for the owner to resume.", 409),
    S.QUEUE_FULL: (True, "Too many calls are pending; wait retryAfterMs and send writes one at a time.", 429),
    S.TOMBSTONED: (False, "That moduleId was removed in this epoch; choose a new moduleId.", 409),
    S.INVALID_REQUEST: (False, "Fix the request shape against the tool schema and resend.", 400),
    S.INVALID_OPERATION: (False, "Fix the geometry/seam problem named in message and resend; nothing was changed.", 422),
    S.BUDGET_EXCEEDED: (False, "Use fewer or smaller modules; one room per module, at most 8 modules per transaction.", 422),
    S.EPOCH_CLOSED: (False, "Ask the owner to open the new epoch and reconnect.", 410),
    S.NOT_FOUND: (False, "Check projectId; the same answer is returned for unknown and not-yours.", 404),
    S.TENANT_MISMATCH: (False, "The grant belongs to another tenant/project; use the correct project URL.", 403),
    S.INTERNAL_ERROR: (True, "State is unchanged. Call read_project, then retry once; report if it repeats.", 500),
    # --- SE-03 additions (additive) ----------------------------------------------------
    "UNAUTHENTICATED": (False, "Authenticate with OAuth (PKCE S256) for this resource and retry.", 401),
    "FORBIDDEN": (False, "Ask the project owner to grant this principal access to the project.", 403),
    "BUSY": (True, "A write is already in flight for this project; wait retryAfterMs and send writes one at a time.", 429),
    "RENDER_ACK_TIMEOUT": (True, "The Editor did not confirm the render in time; call read_project, then retry once.", 504),
    "NO_ACTIVE_VIEWER": (True, "Writes need an active viewer. Ask the owner to open the project in the Editor, then retry.", 409),
    "PAUSED_BY_OWNER": (True, "The owner paused agent writes; wait, then call read_project to see if paused is false.", 409),
}

NEW_IN_SE03 = ("UNAUTHENTICATED", "FORBIDDEN", "BUSY", "RENDER_ACK_TIMEOUT", "NO_ACTIVE_VIEWER", "PAUSED_BY_OWNER")
RETRY_AFTER_MS = {"BUSY": 250, S.QUEUE_FULL: 500, S.LEASE_HELD: 1000, "NO_ACTIVE_VIEWER": 2000,
                  "RENDER_ACK_TIMEOUT": 1000, "PAUSED_BY_OWNER": 5000, S.PAUSED: 5000}
# The actor's own code is translated to the agent-facing code (additive; both stay in the catalogue).
SERVICE_NAME = {S.PAUSED: "PAUSED_BY_OWNER", S.QUEUE_FULL: "BUSY", S.OWNER_ABSENT: "NO_ACTIVE_VIEWER"}


def error_body(code: str, message: str, **details) -> dict:
    """The one error shape every tool/REST failure uses."""
    code = SERVICE_NAME.get(code, code)
    retryable, next_action, _status = CATALOG[code]
    body = {"code": code, "message": str(message)[:500], "retryable": retryable, "nextAction": next_action}
    if code in RETRY_AFTER_MS and retryable:
        body["retryAfterMs"] = RETRY_AFTER_MS[code]
    clean = {k: v for k, v in details.items() if isinstance(v, (str, int, bool, type(None)))}
    if clean:
        body["details"] = clean
    return body


def http_status(code: str) -> int:
    return CATALOG[SERVICE_NAME.get(code, code)][2]
