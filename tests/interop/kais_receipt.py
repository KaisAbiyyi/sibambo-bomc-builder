"""Emit exact-SHA, cross-OS-comparable synthetic evidence from hosted runner.

All outputs are created afresh; writes outside --out are prohibited by caller.
Original consumer statuses must be supplied only by genuine external CI, never
promoted from this Builder-local decoder receipt.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from kais_cases import (REFERENCE, UNSUPPORTED, canonical_bytes,
                        make_fixtures, source_digest, GENERATOR_VERSION)
from kais_reader import semantic_read


PAIRINGS = [
    ("Builder", "Original Editor E4"),
    ("Builder", "Original Model-Eval"),
    ("Original Ruby producer", "Original Editor E4"),
    ("Original Ruby producer", "Original Model-Eval"),
    ("Original Editor writer", "Original Model-Eval"),
]


def git_sha():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                   text=True).strip()


def compile_cold(source, target):
    run = subprocess.run([sys.executable, "-m", "bomc.compiler.graph_to_bomc",
                          "--input", str(source), "--output", str(target)],
                         cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(run.stdout), target.read_bytes()


def emit(destination):
    destination.mkdir(parents=True, exist_ok=True)
    sha = git_sha()
    records = []
    for label, doc in make_fixtures().items():
        canonical = canonical_bytes(doc)
        src = destination / (label + ".json")
        src.write_bytes(canonical)
        first, payload = compile_cold(src, destination / (label + ".bomc"))
        second, check = compile_cold(src, destination / (label + ".cold2.bomc"))
        if payload != check or first != second:
            raise RuntimeError("two cold processes differ: " + label)
        decoded = semantic_read(payload)
        expected = REFERENCE[label]
        for key, val in expected.items():
            observed = decoded[key]
            if key == "bounds":
                if any(abs(x-y) > 1e-8 for x,y in zip(val,observed)):
                    raise RuntimeError("bounds mismatch " + label)
            elif observed != val:
                raise RuntimeError("semantic reference mismatch: " + label + "/" + key)
        (destination / (label + ".cold2.bomc")).unlink()
        records.append({
            "fixture": label,
            "sourceInputSHA256": source_digest(doc),
            "producerSourceCommit": sha,
            "fixtureGeneratorVersion": GENERATOR_VERSION,
            "binarySHA256": hashlib.sha256(payload).hexdigest(),
            "binaryBytes": len(payload),
            "format": "BOMC 1.2; compact-directory; production exact solid subset",
            "sectionInventory": decoded["sectionInventory"],
            "meshCount": decoded["meshCount"], "faceCount": decoded["faceCount"],
            "vertexCount": decoded["vertexCount"],
            "triangleCount": decoded["triangleCount"],
            "materialCount": decoded["materialCount"],
            "coverage": decoded["coverage"], "bounds": decoded["bounds"],
            "sourceExpected": expected, "status": "PASS",
        })
    manifest = {
        "schema": "bmb021-kais-evidence-v1",
        "candidate": "KaisAbiyyi",
        "sourceCommit": sha,
        "startingBaseline": "cc01e0a02aafe519d2fe3d3136d2f28fb6b0011e",
        "python": sys.version, "jsonschema": version("jsonschema"),
        "runnerOS": platform.system(),
        "resultScope": "Builder producer vs independent Kais decoder, NOT original consumers",
        "fixtures": records,
        "consumerPairings": [
            {"producer": source, "consumer": consumer, "status": "NOT_RUN",
             "reason": "No actual cross-repository original-consumer semantic invocation in this Builder CI"}
            for source, consumer in PAIRINGS
        ],
        "featureGates": [
            {"feature": key, "status": "NOT_RUN", "reason": reason}
            for key, reason in UNSUPPORTED.items()
        ],
        "originalConsumerCorruption": {"status": "NOT_RUN",
            "reason": "Builder parser adversarial results cannot establish original consumer behavior"},
        "originalConsumerSection241": {"status": "NOT_RUN",
            "reason": "No original Editor reader invoked on malformed section 241"},
        "strictEditorEditable": {"status": "NOT_RUN",
            "reason": "241 absent; generic E4 semantic load is distinct from editable import"},
    }
    (destination / "kais-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    print(json.dumps({"sourceCommit": sha, "os": manifest["runnerOS"],
                      "fixtures": [{"name": v["fixture"],
                                    "binarySHA256": v["binarySHA256"],
                                    "faces": v["faceCount"], "triangles": v["triangleCount"]}
                                   for v in records],
                      "originalConsumerStatus": "NOT_RUN"}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    emit(parser.parse_args().out)
