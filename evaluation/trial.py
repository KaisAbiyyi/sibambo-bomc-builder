"""One cold trial of the measured workflow. Run as `python -m evaluation.trial [--trial N]`.

Per the BMB-004 protocol a trial starts in a fresh interpreter with a new private project directory, so
nothing is reused between trials. It runs, in order:

  1. the scripted BMB-025 workflow against the real stdio MCP server, observed (calls, retries, estimated
     tokens, bytes, latency, memory);
  2. the BOMC compile of the bundled two-room Module IR in TWO cold child processes (model size, hash,
     determinism, per-process peak memory);
  3. independent readback of the compiled bytes and geometry checks against the IR;
and prints one result envelope. PASS / FAIL / NOT_RUN stay distinct and `overall` can never be PASS while a
mandatory consumer gate is NOT_RUN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tracemalloc
from pathlib import Path

from agentguide.controller import FIXTURE, REPO, ControllerError, run_scenario
from core.assembly import assemble
from core.geometry.floor import build_floor_slab
from core.validator import validate_assembly
from evaluation.metrics import (
    McpObserver, _REAL_RUN, environment, peak_rss_children, stopwatch,
)

ASSEMBLY = REPO / "examples" / "module-ir-two-rooms.json"
GOLDEN = REPO / "tests" / "interop" / "goldens" / "two-room-door-seam.bomc"
COMPILER_SOURCES = ("bomc/adapter/writer_v12.py", "bomc/compiler/graph_to_bomc.py", "bomc/compiler/semantic_v12.py")
SCHEMA_VERSION = "bmb028-result-v1"
FIXTURE_ID = "bmb025-two-room-local-revision"
BASELINE_ID = "bmb004-agent-baseline-v0"
EPS = 1e-6


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def implementation_sha() -> str | None:
    value = os.environ.get("EXPECTED_SHA") or os.environ.get("GITHUB_SHA")
    if value:
        return value
    try:
        out = _REAL_RUN(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, timeout=20, check=False)
        text = out.stdout.decode().strip()
        return text if out.returncode == 0 and len(text) == 40 else None
    except (OSError, ValueError):
        return None


def _check(check_id: str, ok: bool | None, detail: str) -> dict:
    return {"id": check_id, "status": "NOT_RUN" if ok is None else ("PASS" if ok else "FAIL"), "detail": detail}


def _shoelace(points: list) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def expected_world_bounds(document: dict) -> tuple | None:
    """Union of module bounds under their translations; None if a module uses more than a translation."""
    lows, highs = [], []
    for module in document["modules"]:
        m = module["localFrame"]["transform"]
        if [m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]] != [1, 0, 0, 0, 1, 0, 0, 0, 1]:
            return None
        t = (m[3], m[7], m[11])
        low, high = module["bounds"]["min"], module["bounds"]["max"]
        lows.append([low[i] + t[i] for i in range(3)])
        highs.append([high[i] + t[i] for i in range(3)])
    return (*[min(c[i] for c in lows) for i in range(3)], *[max(c[i] for c in highs) for i in range(3)])


def measure_workflow() -> dict:
    scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assembly = json.loads(ASSEMBLY.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="bmb028-") as temp:
        observer = McpObserver()
        tracemalloc.start()
        try:
            with stopwatch() as clock, observer:
                evidence = run_scenario(Path(temp) / "private-project", scenario, assembly)
            python_peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    summary = observer.summary()
    # Two independent counts of the same thing: what the observer saw on the wire and what the controller
    # says it sent. If they disagree, one of them is wrong and no metric from this run may be trusted.
    claimed = evidence["observations"]["mcpToolCalls"]
    if summary["toolCalls"] != claimed:
        raise ControllerError(f"observer counted {summary['toolCalls']} tool calls but the controller reports {claimed}")
    child_peak = peak_rss_children()
    summary.update({
        "elapsedMs": round(clock["ms"], 3), "driverPeakPythonBytes": python_peak,
        "childPeakRssBytes": child_peak,
        "childPeakRssNote": ("largest MCP server or tool worker (POSIX RUSAGE_CHILDREN)" if child_peak is not None
                             else "not measured: the standard library has no child-process peak memory on this OS"),
    })
    return {"summary": summary, "evidence": evidence}


def cold_compile(document_path: Path, out_path: Path) -> dict:
    with stopwatch() as clock:
        proc = _REAL_RUN([sys.executable, "-m", "evaluation.probe", "compile", "--input", str(document_path),
                          "--output", str(out_path)], cwd=REPO, capture_output=True, timeout=180, check=False)
    line = proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
    try:
        data = json.loads(line[0])
    except ValueError:
        data = {"ok": False, "error": "unparseable probe output"}
    data["wallMs"] = round(clock["ms"], 3)
    data["exitCode"] = proc.returncode
    return data


def readback_checks(document: dict, payload: bytes, receipt: dict) -> list:
    checks = []
    try:
        from tests.interop.reader import read          # the Builder's own strict, independent decoder
    except ImportError as exc:
        return [_check("independent_readback", None, f"reader unavailable: {exc}")]
    try:
        model = read(payload)
    except Exception as exc:  # noqa: BLE001 - any rejection is a FAIL with its reason
        return [_check("independent_readback", False, f"strict reader rejected the bytes: {type(exc).__name__}")]
    checks.append(_check("independent_readback", True, "strict CRC, directory and geometry decode accepted"))
    checks.append(_check("faces_match_receipt", len(model["faces"]) == receipt["faceCount"],
                         f"reader {len(model['faces'])} vs compiler {receipt['faceCount']}"))
    checks.append(_check("triangles_match_receipt", model["triangles"] == receipt["triangleCount"],
                         f"reader {model['triangles']} vs compiler {receipt['triangleCount']}"))
    checks.append(_check("sections_match_receipt", list(model["sections"]) == receipt["sections"], str(list(model["sections"]))))
    want = expected_world_bounds(document)
    if want is None:
        checks.append(_check("world_bounds", None, "a module uses more than a translation; bounds not derived"))
    else:
        got = model["bounds"]
        checks.append(_check("world_bounds", all(abs(a - b) <= EPS for a, b in zip(got, want)),
                             f"reader {list(got)} vs IR {list(want)}"))
    return checks


def geometry_checks(document: dict) -> tuple[list, float]:
    checks = []
    report = validate_assembly(document["modules"])
    checks.append(_check("assembly_validator", report.ok, f"{len(report.diagnostics)} diagnostics"))
    assemble(document["modules"])
    slabs, area_core, area_independent = 0, 0.0, 0.0
    for module in document["modules"]:
        for op in module["operations"]:
            if op["kind"] == "floor-slab":
                slabs += 1
                area_core += build_floor_slab(op).area
                area_independent += _shoelace([tuple(p) for p in op["footprint"]])
    checks.append(_check("floor_area_two_calculations_agree", abs(area_core - area_independent) <= EPS and slabs > 0,
                         f"{slabs} slabs: core {area_core:.6f} m2 vs shoelace {area_independent:.6f} m2"))
    return checks, area_core


def run_trial(trial_id: int) -> dict:
    document = json.loads(ASSEMBLY.read_text(encoding="utf-8"))
    flow = measure_workflow()
    evidence, workflow = flow["evidence"], flow["summary"]
    gates_in = evidence["gates"]
    locality = (gates_in.get("unrelated_module_unchanged") == "PASS" and evidence["observations"]["hallHashUnchanged"]
                and gates_in.get("stale_edit_rejected") == "PASS" and gates_in.get("idempotent_replay") == "PASS")

    with tempfile.TemporaryDirectory(prefix="bmb028-bomc-") as temp:
        first = cold_compile(ASSEMBLY, Path(temp) / "a.bomc")
        second = cold_compile(ASSEMBLY, Path(temp) / "b.bomc")
        both_ok = first.get("ok") is True and second.get("ok") is True
        payload_a = (Path(temp) / "a.bomc").read_bytes() if both_ok else b""
        payload_b = (Path(temp) / "b.bomc").read_bytes() if both_ok else b""
    golden = GOLDEN.read_bytes() if GOLDEN.exists() else None
    receipt = first.get("receipt", {})
    deterministic = both_ok and payload_a == payload_b and _sha(payload_a) == receipt.get("sha256") == second["receipt"]["sha256"]
    model = {
        "bomcBytes": len(payload_a) if both_ok else None, "sha256": _sha(payload_a) if both_ok else None,
        "sections": receipt.get("sections"), "faceCount": receipt.get("faceCount"),
        "triangleCount": receipt.get("triangleCount"), "vertexCount": receipt.get("vertexCount"),
        "meshCount": receipt.get("meshCount"), "nodeCount": receipt.get("nodeCount"),
        "coldCompiles": [{"wallMs": r.get("wallMs"), "compileMs": r.get("compileMs"), "peakRssBytes": r.get("peakRssBytes")}
                         for r in (first, second)],
        "identicalAcrossColdProcesses": bool(deterministic),
        "matchesCheckedInGolden": None if golden is None or not both_ok else payload_a == golden,
    }

    checks, floor_area = geometry_checks(document)
    checks += readback_checks(document, payload_a, receipt) if both_ok else [_check("independent_readback", False, "compile failed")]
    checks.append(_check("geometry_semantics_valid_per_compiler", bool(receipt.get("geometrySemanticsValid")), "compiler receipt"))
    checks.append(_check("revision_locality_and_replay", bool(locality), "stale edit rejected, hall unchanged, replay idempotent"))
    model["floorAreaM2"] = round(floor_area, 6)

    executed = [c for c in checks if c["status"] != "NOT_RUN"]
    geometry_status = "FAIL" if any(c["status"] == "FAIL" for c in executed) else ("PASS" if executed else "NOT_RUN")
    gates = {
        "security": "NOT_RUN", "geometry": geometry_status,
        "revision_locality": "PASS" if locality else "FAIL",
        "determinism": "PASS" if deterministic and model["matchesCheckedInGolden"] is not False else "FAIL",
        "editor_import": "NOT_RUN", "model_eval_import": "NOT_RUN",
        "baseline_four_room_fixture": "NOT_RUN", "live_llm_tokens": "NOT_RUN",
        "metrics_recorded": "PASS" if both_ok and workflow["toolCalls"] > 0 else "FAIL",
    }
    mandatory = ("geometry", "revision_locality", "determinism", "editor_import", "model_eval_import")
    overall = ("FAIL" if any(gates[g] == "FAIL" for g in mandatory + ("metrics_recorded",))
               else "INCOMPLETE" if any(gates[g] == "NOT_RUN" for g in mandatory) else "PASS")
    return {
        "schemaVersion": SCHEMA_VERSION, "fixtureId": FIXTURE_ID, "baselineFixtureId": BASELINE_ID,
        "baselineStatus": "NOT_RUN", "baselineNote": "the 4-room baseline needs the BMB-026 house, not on main",
        "implementationSha": implementation_sha(), "controller": "deterministic-scripted-no-llm", "trialId": trial_id,
        "environment": environment(),
        "inputs": {"promptFixtureSha256": _sha(FIXTURE.read_bytes()), "assemblySha256": _sha(ASSEMBLY.read_bytes()),
                   "compilerSources": {p: _sha((REPO / p).read_bytes()) for p in COMPILER_SOURCES},
                   "goldenSha256": _sha(golden) if golden else None},
        "metrics": {"workflow": workflow, "model": model},
        "acceptance": {"checks": checks},
        "gates": gates, "overall": overall,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.trial", description="one cold measured trial")
    parser.add_argument("--trial", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_trial(args.trial)
    except (ControllerError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"schemaVersion": SCHEMA_VERSION, "trialId": args.trial, "overall": "FAIL",
                          "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    text = json.dumps(result, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
