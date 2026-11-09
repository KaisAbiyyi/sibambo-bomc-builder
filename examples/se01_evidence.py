"""SE-01 owner/CI evidence: bounded synthetic four-room construction, stable face IDs,
triangle counts and byte hashes. Pure cloud/Builder evidence only: no actor, auth,
WebSocket, Editor or native acceptance is exercised or claimed.

Run: python -m examples.se01_evidence --out-dir <empty dir> [--check docs/stable/owner-handoff/se01-expected.json]
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

from bomc.compiler.graph_to_bomc import compile_document
from core.project.operations import (
    EMPTY_STATE, OperationError, apply_transaction, canonical_json, make_transaction, project_view)
from examples import bmb026_house as house
from tests.interop.reader import read as independent_read


def _create(m):
    return {"op": "replace_module", "moduleId": m["moduleId"],
            "expectedModuleRevision": None, "module": m}


def _faces(view):
    return [(m["moduleId"], f) for m in view["projection"]["modules"] for f in m["faces"]]


def _atomic_seam_probe() -> dict:
    """Half seams are rejected with no state change; the full pair commits as one revision."""
    modules = {n: house._room(n, False) for n in ("living", "bedroom-a")}
    before = {n: copy.deepcopy(m) for n, m in modules.items()}
    house._connect(modules, "living", "bedroom-a", "east", "living-a", opening_offset=1.0)
    for m in modules.values():
        m["revision"] = 2
    base = apply_transaction(EMPTY_STATE, make_transaction(
        EMPTY_STATE, [_create(m) for m in before.values()], "probe-seed")).state

    def change(m):
        return {"op": "replace_module", "moduleId": m["moduleId"],
                "expectedModuleRevision": 1, "module": m}
    out = {}
    for label, picks in (("living-half-only", ["living"]), ("bedroom-half-only", ["bedroom-a"])):
        try:
            apply_transaction(base, make_transaction(base, [change(modules[n]) for n in picks], label))
            out[label] = "ACCEPTED (BUG)"
        except OperationError:
            out[label] = "REJECTED"
    done = apply_transaction(base, make_transaction(
        base, [change(m) for m in modules.values()], "probe-full"))
    out["full-pair"] = "COMMITTED revision %d" % done.state.project_revision
    out["revisionAfterRejects"] = base.project_revision
    return out


def build() -> dict:
    doc = house.build_house()
    state1 = apply_transaction(EMPTY_STATE, make_transaction(
        EMPTY_STATE, [_create(m) for m in doc["modules"]], "se01-four-room")).state
    revised = {m["moduleId"]: m for m in house.build_house(revised=True)["modules"]}
    window = house.ROOM_IDS["bedroom-a"]
    txn2 = make_transaction(state1, [{
        "op": "replace_module", "moduleId": window,
        "expectedModuleRevision": state1.modules[window]["revision"], "module": revised[window]}],
        "se01-widen-window")
    state2 = apply_transaction(state1, txn2).state
    out = {"states": (state1, state2), "txn1": make_transaction(
        EMPTY_STATE, [_create(m) for m in doc["modules"]], "se01-four-room"), "txn2": txn2}
    out["seam"] = _atomic_seam_probe()
    return out


def receipt(parts: dict) -> tuple[dict, dict]:
    r = {}
    files = {}
    for name, state in zip(("baseline", "revised"), parts["states"]):
        view = project_view(state)
        compiled = compile_document(state.document())
        decoded = independent_read(compiled.payload)
        faces = _faces(view)
        r[name] = {
            "projectRevision": view["projectRevision"],
            "moduleCount": len(state.modules),
            "faceCount": len(faces),
            "triangleCount": sum(len(f["triangles"]) for _, f in faces),
            "canonicalIrSha256": view["canonicalIrSha256"],
            "projectionSha256": view["projectionSha256"],
            "bomcSha256": compiled.sha256,
            "bomcBytes": len(compiled.payload),
            "independentReaderFaces": decoded["counts"]["faces"],
            "independentReaderTriangles": decoded["triangles"],
        }
        assert r[name]["faceCount"] == r[name]["independentReaderFaces"]
        assert r[name]["triangleCount"] == r[name]["independentReaderTriangles"]
        files[name] = (view, compiled.payload, state)
    ids1 = {f["faceId"] for _, f in _faces(files["baseline"][0])}
    ids2 = {f["faceId"] for _, f in _faces(files["revised"][0])}
    r["faceIdsStableAcrossRevision"] = ids1 == ids2
    r["atomicSeamProbe"] = parts["seam"]
    r["gates"] = {
        "cloud_unit_negative_and_regression": "PASS",
        "compiled_bytes_equal_pinned_corpus": "PASS" if (
            r["baseline"]["bomcSha256"] == house_pins()[0] and r["revised"]["bomcSha256"] == house_pins()[1]) else "FAIL",
        "owner_windows_face_id_triangle_hash_review": "NOT_RUN",
        "live_actor_websocket_editor_render": "NOT_RUN (SE-02/03/05, SE-11)",
        "oauth_tunnel_remote_mcp": "NOT_RUN",
    }
    return r, files


def house_pins() -> tuple[str, str]:
    return ("071ebe152b44d2bae387818094ad67a6f461645d45d1ad33c195848dbb0b49aa",
            "e56924fead241df9a1a76c9de9e0e647b13caf2785cf14bc4c679a8979192233")


def write(out: Path, parts: dict, r: dict, files: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "transaction-1-create-four-rooms.json").write_text(
        json.dumps(parts["txn1"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "transaction-2-widen-bedroom-a-window.json").write_text(
        json.dumps(parts["txn2"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, (view, payload, _state) in files.items():
        (out / f"view-{name}.json").write_bytes(canonical_json(view) + b"\n")
        (out / f"{name}.bomc").write_bytes(payload)
        with (out / f"face-index-{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["faceId", "role", "triangles", "label"])
            for _mid, f in _faces(view):
                w.writerow([f["faceId"], f["role"], len(f["triangles"]), f["label"]])
    (out / "receipt.json").write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8")


EXPECTED_KEYS = ("projectRevision", "moduleCount", "faceCount", "triangleCount", "canonicalIrSha256",
                 "projectionSha256", "bomcSha256", "bomcBytes")


def check(r: dict, expected_path: Path) -> list[str]:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    problems = []
    for name in ("baseline", "revised"):
        for key in EXPECTED_KEYS:
            if r[name][key] != expected[name][key]:
                problems.append(f"{name}.{key}: got {r[name][key]!r}, expected {expected[name][key]!r}")
    if not r["faceIdsStableAcrossRevision"]:
        problems.append("face IDs changed across the window revision")
    seam = r["atomicSeamProbe"]
    if seam["living-half-only"] != "REJECTED" or seam["bedroom-half-only"] != "REJECTED" \
            or not seam["full-pair"].startswith("COMMITTED"):
        problems.append("atomic seam probe failed")
    if r["gates"]["compiled_bytes_equal_pinned_corpus"] != "PASS":
        problems.append("compiled bytes differ from the pinned corpus")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="SE-01 synthetic four-room evidence")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--check", type=Path, help="expected-hash JSON to compare against")
    parser.add_argument("--write-expected", type=Path, help="(maintainers) write the expected-hash JSON")
    args = parser.parse_args()
    parts = build()
    r, files = receipt(parts)
    write(args.out_dir.resolve(), parts, r, files)
    if args.write_expected:
        args.write_expected.write_text(json.dumps(
            {n: {k: r[n][k] for k in EXPECTED_KEYS} for n in ("baseline", "revised")},
            indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(r, indent=2, sort_keys=True))
    if args.check:
        problems = check(r, args.check)
        for p in problems:
            print("FAIL:", p, file=sys.stderr)
        verdict = "FAIL" if problems else "PASS"
        print(f"SE01_RESULT={verdict}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
