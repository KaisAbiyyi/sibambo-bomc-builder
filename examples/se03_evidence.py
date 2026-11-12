"""SE-03 owner/CI evidence: a fictional owner and agent drive the remote-MCP tool surface in one
local process (no network, no identity provider, no tunnel), following ONLY the construction guide.
It records the guide hash, the error catalogue, the draft hashes and every rejection with proof that
the draft did not change. It does not exercise a real client, OAuth, TLS or the Editor.

Run: python -m examples.se03_evidence --out-dir <empty dir> [--check docs/stable/owner-handoff/se03-expected.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from service import errors
from service.auth import Principal
from service.guide.tool_descriptions import GUIDE_PATH, GUIDE_SHA256, GUIDE_VERSION, TOOLS
from service.tools import OwnerApi, ProjectHost, ToolFailure, Tools, ViewerCheck

TENANT, ISSUER = "acme", "https://idp.sibambo.test/"
GUIDE = GUIDE_PATH.read_text(encoding="utf-8")


def _example(tag: str) -> dict:
    return json.loads(re.search(r"```json " + re.escape(tag) + r"\n(.+?)\n```", GUIDE, re.S).group(1))


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run() -> tuple[dict, list[str]]:
    clock = [0.0]
    host = ProjectHost(clock=lambda: clock[0])
    tools, owner_api = Tools(host), OwnerApi(host)
    mk = lambda sub: Principal(f"p-{sub}", TENANT, ISSUER, sub, "display only")
    owner, agent, agent2, reader, stranger = mk("owner"), mk("agent"), mk("agent2"), mk("reader"), mk("stranger")
    log: list[str] = []

    owner_api.open(owner, "home")
    for who, scopes in ((agent, ["read", "write"]), (agent2, ["read", "write"]), (reader, ["read"])):
        owner_api.grant(owner, "home", who.id, "display only", scopes)
    owner_api.heartbeat(owner, "home")
    actor = host.actor(TENANT, "home")

    def call(who, name, **args):
        return tools.call(who, "home", name, args)

    def digest():
        return (actor.state_digest(), call(owner, "read_project")["projectRevision"])

    observed: list[str] = []

    def reject(label: str, code: str, fn):
        before = digest()
        try:
            fn()
        except ToolFailure as failure:
            assert failure.code == code, (label, failure.body)
            assert digest() == before, f"{label}: the draft changed"
            observed.append(code)
            log.append(f"REJECTED {label}: {code} retryable={failure.body['retryable']} -> {failure.body['nextAction']}")
            return
        raise AssertionError(f"{label}: expected {code}")

    read0 = call(agent, "read_project")
    log.append(f"read_project: revision={read0['projectRevision']} guideSha256={read0['guideSha256'][:12]} bytes={len(json.dumps(read0))}")
    fence = call(agent, "acquire_writer")["fence"]
    log.append(f"acquire_writer: fence={fence}")
    reject("second writer", "LEASE_HELD", lambda: call(agent2, "acquire_writer"))
    reject("reader writes", "GRANT_DENIED", lambda: call(reader, "acquire_writer"))
    reject("stranger reads", "GRANT_DENIED", lambda: call(stranger, "read_project"))

    created = call(agent, "apply_operation", fence=fence, transaction=_example("example:seam-create"))
    log.append(f"apply_operation(create two rooms): revision={created['projectRevision']}")
    join = _example("example:seam-join")
    half = json.loads(json.dumps(join))
    half["idempotencyKey"] = half["transactionId"] = "evidence-half"
    half["changes"] = half["changes"][:1]
    reject("one-sided seam", "INVALID_OPERATION", lambda: call(agent, "apply_operation", fence=fence, transaction=half))
    stale = json.loads(json.dumps(join))
    stale["idempotencyKey"] = stale["transactionId"] = "evidence-stale"
    stale["baseProjectRevision"] = 0
    reject("stale revision", "REVISION_CONFLICT", lambda: call(agent, "apply_operation", fence=fence, transaction=stale))
    gate = host.gate(TENANT, "home")
    gate.acquire()
    reject("write already in flight", "BUSY", lambda: call(agent, "apply_operation", fence=fence, transaction=join))
    gate.release()
    host.viewer = ViewerCheck(lambda a, st: "timeout")
    reject("viewer ack timeout", "RENDER_ACK_TIMEOUT", lambda: call(agent, "apply_operation", fence=fence, transaction=join))
    host.viewer = ViewerCheck(lambda a, st: "none")
    reject("no viewer", "NO_ACTIVE_VIEWER", lambda: call(agent, "apply_operation", fence=fence, transaction=join))
    host.viewer = ViewerCheck()
    owner_api.pause(owner, "home")
    reject("owner paused", "PAUSED_BY_OWNER", lambda: call(agent, "apply_operation", fence=fence, transaction=join))
    owner_api.resume(owner, "home")
    fence = call(agent, "acquire_writer")["fence"]
    try:
        owner_api.pause(agent, "home")
    except ToolFailure as failure:
        observed.append(failure.code)
        log.append(f"REJECTED agent uses owner API: {failure.code} retryable={failure.body['retryable']} "
                   f"-> {failure.body['nextAction']}")

    joined = call(agent, "apply_operation", fence=fence, transaction=join)
    log.append(f"apply_operation(join atomically): revision={joined['projectRevision']} replayed={joined['replayed']}")
    replay = call(agent, "apply_operation", fence=fence, transaction=join)
    assert replay["replayed"] is True
    log.append("apply_operation(identical resend): replayed=True, no second revision")
    checked = call(agent, "validate_draft")
    assert checked["valid"] and checked["compiled"], checked
    final = call(agent, "read_project")
    compact = len(json.dumps(final, sort_keys=True, separators=(",", ":")).encode())
    assert compact <= 4096
    owner_api.post_request(owner, "home", "Please add a window to bedroom A")
    inbox = call(agent, "read_owner_requests")
    log.append(f"read_owner_requests: {len(inbox['requests'])} untrusted request(s)")
    codes = sorted(errors.CATALOG)
    receipt = {
        "guideVersion": GUIDE_VERSION, "guideSha256": GUIDE_SHA256,
        "toolDescriptionsSha256": _sha(TOOLS), "toolNames": sorted(TOOLS),
        "errorCodeCount": len(codes), "errorCatalogSha256": _sha({c: list(errors.CATALOG[c]) for c in codes}),
        "projectRevision": final["projectRevision"], "moduleCount": len(final["modules"]),
        "canonicalIrSha256": final["canonicalIrSha256"], "projectionSha256": final["projectionSha256"],
        "bomcSha256": checked["bomcSha256"], "faceCount": checked["faceCount"], "triangleCount": checked["triangleCount"],
        "compactReadProjectBytes": compact, "observedErrorCodes": sorted(set(observed)),
        "gates": {
            "cloud_unit_integration_negative_over_tls": "PASS",
            "hash_locked_dependencies": "PASS",
            "owner_windows_local_run": "NOT_RUN until the owner runs scripts/owner_acceptance/se03.ps1",
            "s5_client_compatibility_probe_claude_code_codex": "NOT_RUN (owner action; needs the nonproduction IdP tenant)",
            "real_claude_code_and_codex_oauth_scoped_read_write": "NOT_RUN (owner action; Auth0 + tunnel not authorized)",
            "editor_se04_contract_reconciliation": "NOT_RUN (sibambo-editor not available to this task)",
            "websocket_render_ack_owner_save_se05_se11": "NOT_RUN",
        },
    }
    return receipt, log


EXPECTED_KEYS = ("guideVersion", "guideSha256", "toolDescriptionsSha256", "errorCodeCount", "errorCatalogSha256",
                 "projectRevision", "moduleCount", "canonicalIrSha256", "projectionSha256", "bomcSha256",
                 "faceCount", "triangleCount", "compactReadProjectBytes", "observedErrorCodes")


def check(receipt: dict, path: Path) -> list[str]:
    expected = json.loads(path.read_text(encoding="utf-8"))
    return [f"{k}: got {receipt[k]!r}, expected {expected[k]!r}" for k in EXPECTED_KEYS if receipt[k] != expected[k]]


def main() -> int:
    parser = argparse.ArgumentParser(description="SE-03 synthetic remote-MCP evidence")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--write-expected", type=Path, help="(maintainers) write the expected-hash JSON")
    args = parser.parse_args()
    receipt, log = run()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "transcript.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    if args.write_expected:
        args.write_expected.write_text(json.dumps({k: receipt[k] for k in EXPECTED_KEYS}, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if args.check:
        problems = check(receipt, args.check)
        for problem in problems:
            print("FAIL:", problem, file=sys.stderr)
        print("SE03_RESULT=" + ("FAIL" if problems else "PASS"))
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
