#!/usr/bin/env python3
"""BMB-031 synthetic no-network create/validate/compile/independent-inspect smoke."""
from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> dict:
    completed = subprocess.run([sys.executable, *args], cwd=ROOT,
                               text=True, capture_output=True, timeout=60, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="bmb031-synthetic-") as temp:
        root = Path(temp)
        project = root / "journal"
        created = run("-m", "cli.bmb", "--root", str(project), "create",
                      "--module-id", "release/synthetic")
        inspected = run("-m", "cli.bmb", "--root", str(project), "inspect",
                        "--module-id", "release/synthetic")
        validated = run("-m", "cli.bmb", "--root", str(project), "validate")
        binary = root / "synthetic.bomc"
        receipt = run("-m", "bomc.compiler.graph_to_bomc",
                      "--input", "examples/bmb020-semantic-floor.json", "--output", str(binary))
        assert created["ok"] and inspected["ok"] and validated["ok"], "journal command failed"
        assert inspected["result"]["revision"] == 0, "unexpected revision"
        assert validated["result"]["moduleCount"] == 1, "journal validation failed"
        assert receipt.get("sha256") == hashlib.sha256(binary.read_bytes()).hexdigest(), "compile hash mismatch"
        independent_read = runpy.run_path(str(ROOT / "tests/interop/reader.py"))["read"]
        parsed = independent_read(binary.read_bytes())
        assert parsed["counts"]["faces"] > 0 and parsed["triangles"] > 0, "empty compiled geometry"
        output = {
            "status": "PASS",
            "scope": "Synthetic journal create/inspect/validate plus separately supplied Module IR compile/Builder-independent-reader inspect",
            "warning": "Journal-to-typed-Module-IR mapping is NOT demonstrated by this smoke; original Editor/Model-Eval remain NOT_RUN",
            "compilerReceipt": receipt,
            "artifactSha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "faceCount": parsed["counts"]["faces"],
            "triangleCount": parsed["triangles"],
        }
        encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(encoded, encoding="utf-8")
        print(encoded.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
