"""Run N cold trials and summarize: `python -m evaluation.run --trials 3 [--out result.json]`.

Each trial is its own interpreter (`evaluation.trial`), so nothing carries over. The summary separates
- DETERMINISTIC quantities (calls, retries, estimated tokens, bytes, hashes, geometry results, gate
  statuses), which must be identical in every trial and are reported as `deterministic.identical`, from
- DESCRIPTIVE quantities (elapsed time, memory), summarized as min / median / nearest-rank P95 / max.
With three trials a P95 is descriptive only, not a statistical guarantee, and nothing here is a
performance promise. A failed or crashed trial stays in the denominator.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agentguide.controller import REPO
from evaluation.metrics import describe

SCHEMA_VERSION = "bmb028-benchmark-v1"
DETERMINISTIC_WORKFLOW = ("requests", "toolCalls", "rejectedToolCalls", "retries", "rejectionCodes",
                          "estimatedInputTokens", "estimatedOutputTokens", "requestBytes", "responseBytes", "mcpBatches")
DETERMINISTIC_MODEL = ("bomcBytes", "sha256", "sections", "faceCount", "triangleCount", "vertexCount", "meshCount",
                       "nodeCount", "floorAreaM2", "identicalAcrossColdProcesses", "matchesCheckedInGolden")


def run_trial_process(index: int, timeout: int = 600) -> dict:
    proc = subprocess.run([sys.executable, "-m", "evaluation.trial", "--trial", str(index)], cwd=REPO,
                          capture_output=True, timeout=timeout, check=False)
    lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        record = json.loads(lines[-1]) if lines else {}
    except ValueError:
        record = {}
    if not record or proc.returncode != 0:
        record = {"schemaVersion": "bmb028-result-v1", "trialId": index, "overall": "FAIL",
                  "error": record.get("error") or f"trial exited {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[-300:]}"}
    return record


def deterministic_view(trial: dict) -> dict:
    m = trial["metrics"]
    return {"workflow": {k: m["workflow"][k] for k in DETERMINISTIC_WORKFLOW},
            "model": {k: m["model"][k] for k in DETERMINISTIC_MODEL},
            "checks": {c["id"]: c["status"] for c in trial["acceptance"]["checks"]},
            "gates": trial["gates"], "overall": trial["overall"]}


def summarize(trials: list) -> dict:
    good = [t for t in trials if "metrics" in t]
    out = {"schemaVersion": SCHEMA_VERSION, "trialsRequested": len(trials), "trialsCompleted": len(good),
           "trialsFailed": len(trials) - len(good), "failures": [t.get("error") for t in trials if "metrics" not in t]}
    if not good:
        out["overall"] = "FAIL"
        return out
    views = [deterministic_view(t) for t in good]
    identical = all(v == views[0] for v in views[1:])
    differing = sorted({key for v in views[1:] for key in v if v[key] != views[0][key]}) if not identical else []
    out["deterministic"] = {"identical": identical, "differingSections": differing, "values": views[0]}
    col = lambda path: [t["metrics"][path[0]][path[1]] for t in good]  # noqa: E731
    pair = lambda key: [v for t in good for v in (c[key] for c in t["metrics"]["model"]["coldCompiles"]) if v is not None]  # noqa: E731
    child = [t["metrics"]["workflow"]["childPeakRssBytes"] for t in good if t["metrics"]["workflow"]["childPeakRssBytes"] is not None]
    out["descriptive"] = {
        "workflowElapsedMs": describe(col(("workflow", "elapsedMs"))),
        "mcpProcessMs": describe(col(("workflow", "mcpProcessMs"))),
        "slowestBatchMs": describe(col(("workflow", "slowestBatchMs"))),
        "driverPeakPythonBytes": describe(col(("workflow", "driverPeakPythonBytes"))),
        "mcpChildPeakRssBytes": describe(child) if child else None,
        "mcpChildPeakRssNote": good[0]["metrics"]["workflow"]["childPeakRssNote"],
        "coldCompileWallMs": describe(pair("wallMs")),
        "coldCompileMs": describe(pair("compileMs")),
        "coldCompilePeakRssBytes": describe(pair("peakRssBytes")) if pair("peakRssBytes") else None,
        "note": "descriptive only: n is small, timings depend on the machine, none of it is a performance guarantee"}
    gates = {k: sorted({t["gates"][k] for t in good}) for k in good[0]["gates"]}
    out["gates"] = {k: (v[0] if len(v) == 1 else "FAIL") for k, v in gates.items()}
    mandatory_fail = out["trialsFailed"] > 0 or not identical or any(t["overall"] == "FAIL" for t in good)
    mandatory_open = any(out["gates"][g] == "NOT_RUN" for g in ("geometry", "revision_locality", "determinism", "editor_import", "model_eval_import"))
    out["overall"] = "FAIL" if mandatory_fail else ("INCOMPLETE" if mandatory_open else "PASS")
    out["environment"], out["inputs"] = good[0]["environment"], good[0]["inputs"]
    out["implementationSha"] = good[0]["implementationSha"]
    return out


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.run", description="BMB-028 measured benchmark")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", type=Path, help="write the full result (trials + summary) here")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.trials <= 20:
        parser.error("--trials must be 1..20")
    trials = [run_trial_process(i + 1) for i in range(args.trials)]
    result = {"summary": summarize(trials), "trials": trials}
    text = json.dumps(result["summary"] if args.summary_only else result, sort_keys=True, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], sort_keys=True, indent=2))
    return 0 if result["summary"]["overall"] in ("PASS", "INCOMPLETE") else 1


if __name__ == "__main__":
    sys.exit(main())
