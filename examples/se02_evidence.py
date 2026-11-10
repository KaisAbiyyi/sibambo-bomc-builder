"""SE-02 owner/CI evidence: two synthetic agents contend for one project actor.

Pure in-process cloud/Builder evidence: no network, no auth service, no WebSocket, no Editor,
no disk write while the scenario runs. It is not native or owner acceptance.

Run: python -m examples.se02_evidence --out-dir <empty dir> [--check docs/stable/owner-handoff/se02-expected.json]
"""
from __future__ import annotations

import argparse
import builtins
import copy
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from core.project import operations as ops
from core.project.actor import ProjectActor
from core.project.state import ActorError, Grant
from examples import bmb026_house as house

OWNER, AGENT_A, AGENT_B = "owner-demo", "agent-a", "agent-b"
LIVING, BEDROOM = house.ROOM_IDS["living"], house.ROOM_IDS["bedroom-a"]


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@contextmanager
def no_disk_writes():
    """Any attempted disk write raises; the count of attempts is reported (expected 0)."""
    attempts = []
    real_open = builtins.open

    def guarded(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+"):
            attempts.append(f"open:{file}")
            raise OSError("disk write blocked by evidence guard")
        return real_open(file, mode, *a, **k)

    def blocked(name):
        def fn(*a, **k):
            attempts.append(name)
            raise OSError("disk write blocked by evidence guard")
        return fn
    patches = [mock.patch("builtins.open", guarded), mock.patch("io.open", guarded)]
    patches += [mock.patch(n, blocked(n)) for n in ("os.fsync", "os.replace", "os.rename", "os.mkdir",
                                                      "os.makedirs", "os.remove", "os.unlink")]
    for p in patches:
        p.start()
    try:
        yield attempts
    finally:
        for p in reversed(patches):
            p.stop()


def txn(base, changes, key):
    return {"schemaVersion": "draft-operation-v1", "transactionId": key, "idempotencyKey": key,
            "baseProjectRevision": base, "changes": changes}


def create(m):
    return {"op": "replace_module", "moduleId": m["moduleId"], "expectedModuleRevision": None, "module": m}


def replace(m, expected):
    return {"op": "replace_module", "moduleId": m["moduleId"], "expectedModuleRevision": expected, "module": m}


def attempt(fn, *args):
    try:
        return "OK", fn(*args)
    except ActorError as exc:
        return exc.code, exc


def grant(subject, client):
    return Grant("tenant-demo", "project-demo", subject, client, frozenset({"read", "write"}))


def scenario() -> dict:
    steps, facts = [], {}

    def record(action, expected, actual):
        steps.append({"n": len(steps) + 1, "action": action, "expected": expected, "actual": actual,
                      "verdict": "PASS" if expected == actual else "FAIL"})

    clock = Clock()
    actor = ProjectActor("tenant-demo", "project-demo", 1, OWNER, clock=clock)
    actor.owner_heartbeat(OWNER)
    actor.grant(OWNER, grant(AGENT_A, "Claude Code"))
    actor.grant(OWNER, grant(AGENT_B, "Codex"))
    record("Owner opens epoch 1, grants agent-a (Claude Code) and agent-b (Codex), sends a heartbeat",
           "epoch=1 projectRevision=0", f"epoch={actor.epoch} projectRevision={actor.status(OWNER)['projectRevision']}")

    code, lease_a = attempt(actor.acquire_lease, AGENT_A)
    record("agent-a asks for the writer lease", "OK fence=1", f"{code} fence={lease_a.fence}")

    house_modules = house.build_house()["modules"]
    code, out = attempt(actor.submit, AGENT_A, lease_a, txn(0, [create(m) for m in house_modules], "demo-seed"))
    record("agent-a creates the synthetic four-room house in ONE atomic transaction (5 modules)",
           "OK COMMITTED projectRevision=1", f"{code} {out['status']} projectRevision={out['projectRevision']}")
    facts["afterSeed"] = {"canonicalIrSha256": out["canonicalIrSha256"], "projectionSha256": out["projectionSha256"],
                          "moduleRevisions": out["moduleRevisions"]}

    code, err = attempt(actor.acquire_lease, AGENT_B)
    record("agent-b asks for the writer lease while agent-a holds it",
           "LEASE_HELD writer=agent-a", f"{code} writer={err.detail.get('writer')}")

    living1 = next(m for m in house_modules if m["moduleId"] == LIVING)
    living2 = ops.update_operation(living1, "floor", thickness=0.16)
    edit = txn(1, [replace(living2, 1)], "demo-edit-1")
    code, out = attempt(actor.submit, AGENT_A, lease_a, edit)
    record("agent-a thickens the living-room floor (project revision 1 to 2)",
           "OK COMMITTED projectRevision=2", f"{code} {out['status']} projectRevision={out['projectRevision']}")

    code, out = attempt(actor.submit, AGENT_A, lease_a, copy.deepcopy(edit))
    record("agent-a sends the exact same request again (network retry)",
           "OK replayed=True projectRevision=2", f"{code} replayed={out['replayed']} projectRevision={out['projectRevision']}")

    actor.release_lease(AGENT_A, lease_a)
    code, lease_b = attempt(actor.acquire_lease, AGENT_B)
    living2b = ops.update_operation(living1, "floor", thickness=0.17)       # agent-b still thinks revision is 1
    code, err = attempt(actor.submit, AGENT_B, lease_b, txn(1, [replace(living2b, 1)], "demo-b-stale"))
    record("agent-b becomes the writer but sends an edit based on stale project revision 1",
           "REVISION_CONFLICT currentProjectRevision=2",
           f"{code} currentProjectRevision={err.detail.get('currentProjectRevision')}")

    living3 = ops.update_operation(living2, "floor", thickness=0.17)
    code, out = attempt(actor.submit, AGENT_B, lease_b, txn(2, [replace(living3, 2)], "demo-b-rebased"))
    record("agent-b rebases on revision 2 and writes again",
           "OK COMMITTED projectRevision=3", f"{code} {out['status']} projectRevision={out['projectRevision']}")
    facts["afterContention"] = {"canonicalIrSha256": out["canonicalIrSha256"],
                                "projectionSha256": out["projectionSha256"]}

    living4 = ops.update_operation(living3, "floor", thickness=0.18)
    paused_edit = txn(3, [replace(living4, 3)], "demo-b-paused")
    actor.pause(OWNER)
    code, err = attempt(actor.submit, AGENT_B, lease_b, paused_edit)
    record("owner pauses the project; agent-b tries to write", "PAUSED", code)

    actor.resume(OWNER)
    code, err = attempt(actor.submit, AGENT_B, lease_b, paused_edit)
    record("owner resumes; agent-b retries with its OLD writer lease", "FENCE_STALE", code)

    mine = actor.owner_acquire(OWNER)
    code, err = attempt(actor.acquire_lease, AGENT_B)
    record("owner takes the writer role; agent-b asks for the lease",
           f"LEASE_HELD writer={OWNER}", f"{code} writer={err.detail.get('writer')}")
    code, out = attempt(actor.submit, OWNER, mine, txn(3, [replace(living4, 3)], "demo-owner-edit"))
    record("owner writes as the named writer", "OK COMMITTED projectRevision=4",
           f"{code} {out['status']} projectRevision={out['projectRevision']}")
    facts["finalStatus"] = {k: v for k, v in actor.status(OWNER).items() if k in ("projectRevision", "writer", "paused")}

    # Atomic reciprocal seam: a second, independent project actor so the story above stays readable.
    seam = ProjectActor("tenant-demo", "project-seam", 1, OWNER, clock=Clock())
    seam.owner_heartbeat(OWNER)
    seam.grant(OWNER, Grant("tenant-demo", "project-seam", AGENT_A, "Claude Code", frozenset({"read", "write"})))
    lease = seam.acquire_lease(AGENT_A)
    rooms = {n: house._room(n, False) for n in ("living", "bedroom-a")}
    seam.submit(AGENT_A, lease, txn(0, [create(m) for m in rooms.values()], "seam-seed"))
    before = seam.state_digest()
    pair = {n: copy.deepcopy(m) for n, m in rooms.items()}
    house._connect(pair, "living", "bedroom-a", "east", "living-a", opening_offset=1.0)
    for m in pair.values():
        m["revision"] = 2
    code, _ = attempt(seam.submit, AGENT_A, lease, txn(1, [replace(pair["living"], 1)], "seam-half-1"))
    code2, _ = attempt(seam.submit, AGENT_A, lease, txn(1, [replace(pair["bedroom-a"], 1)], "seam-half-2"))
    record("two rooms get a shared door: each ONE-SIDED half is sent alone",
           "INVALID_OPERATION INVALID_OPERATION unchanged=True",
           f"{code} {code2} unchanged={seam.state_digest() == before}")
    both = txn(1, [replace(pair["living"], 1), replace(pair["bedroom-a"], 1)], "seam-pair")
    code, out = attempt(seam.submit, AGENT_A, lease, both)
    revs = out["moduleRevisions"]
    record("both halves in ONE atomic transaction",
           "OK COMMITTED projectRevision=2 living=2 bedroom-a=2",
           f"{code} {out['status']} projectRevision={out['projectRevision']} living={revs[LIVING]} bedroom-a={revs[BEDROOM]}")
    code, out = attempt(seam.submit, AGENT_A, lease, copy.deepcopy(both))
    record("the same atomic transaction is retried", "OK replayed=True projectRevision=2",
           f"{code} replayed={out['replayed']} projectRevision={out['projectRevision']}")
    return {"steps": steps, "facts": facts}


def build() -> dict:
    with no_disk_writes() as attempts:
        result = scenario()
    result["steps"].append({"n": len(result["steps"]) + 1, "action": "disk writes attempted by the actor during all steps above",
                            "expected": "0", "actual": str(len(attempts)),
                            "verdict": "PASS" if not attempts else "FAIL"})
    result["verdict"] = "PASS" if all(s["verdict"] == "PASS" for s in result["steps"]) else "FAIL"
    return result


def transcript(result: dict) -> str:
    lines = ["SE-02 synthetic contention transcript (cloud/Builder evidence only)", ""]
    for s in result["steps"]:
        lines.append(f"[{s['verdict']}] step {s['n']}: {s['action']}")
        lines.append(f"        expected: {s['expected']}")
        lines.append(f"        actual:   {s['actual']}")
    lines += ["", f"After the four-room seed: IR sha256 {result['facts']['afterSeed']['canonicalIrSha256']}",
              f"                     projection sha256 {result['facts']['afterSeed']['projectionSha256']}",
              f"VERDICT: {result['verdict']}",
              "NOT_RUN: owner manual review, live actor service, WebSocket, Editor, OAuth, tunnel."]
    return "\n".join(lines) + "\n"


def pinned(result: dict) -> dict:
    return {"steps": [{"n": s["n"], "actual": s["actual"]} for s in result["steps"]], "facts": result["facts"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--check", help="compare with the pinned expected JSON")
    args = ap.parse_args(argv)
    out = Path(args.out_dir)
    if out.exists() and any(out.iterdir()):
        print(f"STOP: {out} is not empty", file=sys.stderr)
        return 2
    result = build()
    out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "transcript.txt").write_text(transcript(result), encoding="utf-8")
    ok = result["verdict"] == "PASS"
    for s in result["steps"]:
        if s["verdict"] != "PASS":
            print(f"FAIL: step {s['n']}: expected {s['expected']!r}, actual {s['actual']!r}")
    if args.check:
        expected = json.loads(Path(args.check).read_text(encoding="utf-8"))
        if pinned(result) != expected:
            ok = False
            print("FAIL: receipt differs from the pinned expected values:")
            exp = {s["n"]: s["actual"] for s in expected["steps"]}
            for s in result["steps"]:
                if exp.get(s["n"]) != s["actual"]:
                    print(f"  step {s['n']}: pinned {exp.get(s['n'])!r} != actual {s['actual']!r}")
            if expected["facts"] != result["facts"]:
                print("  facts (hashes/revisions) differ")
    print(f"SE02_RESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
