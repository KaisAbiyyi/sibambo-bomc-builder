"""BMB-021 semantic golden suite: committed .bomc fixtures, pinned manifest, reader summaries.

    python -m tests.interop.goldens --write tests/interop/goldens
    python -m tests.interop.goldens --check tests/interop/goldens
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.interop import fixtures  # noqa: E402
from tests.interop.reader import read  # noqa: E402

COMPILER_SOURCES = ("bomc/adapter/writer_v12.py", "bomc/compiler/graph_to_bomc.py", "bomc/compiler/semantic_v12.py")
MANIFEST = "manifest.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def summarize(payload: bytes) -> dict:
    """JSON-safe, deterministic reader summary: what any independent consumer should also observe."""
    s = read(payload)
    surfaces = {}
    for f in s["faces"]:
        surfaces[str(f["surface"])] = surfaces.get(str(f["surface"]), 0) + 1
    return {
        "sections": list(s["sections"]),
        "counts": s["counts"],
        "triangles": s["triangles"],
        "bounds": list(s["bounds"]),
        "stringCount": len(s["strings"]),
        "materialColors": [list(c) for c in s["colors"]],
        "materialOpacity": s.get("opacity", []),
        "nodes": s["nodes"],
        "meshDefinitions": s.get("meshDefinitions", []),
        "geometryDigest": s.get("geometryDigest"),
        "faceDigest": sha256(json.dumps(s["faces"], sort_keys=True, separators=(",", ":")).encode()),
        "transforms": [list(m) for m in s["transforms"]],
        "faceSurfaceCounts": dict(sorted(surfaces.items())),
        "faceLabels": sorted({f["label"] for f in s["faces"] if f["label"]}),
        "frontBackDistinctFaces": sum(1 for f in s["faces"] if f["front"] is not None and f["back"] is not None
                                      and f["front"] != f["back"]),
        "meshVertices": s.get("meshVertices", []),
        "coverage": [s["counts"]["faces"], s["counts"]["faces"], 0, 0, 0, 0],
    }


def build_all() -> dict[str, bytes]:
    return {name: build().payload for name, (build, _) in fixtures.FIXTURES.items()}


def manifest(blobs: dict[str, bytes]) -> dict:
    return {
        "schemaVersion": 1,
        "scope": "Builder-side certification only: bytes compiled by this repository and read by its own strict reader",
        "sharedMeshGeometry": "NOT_DEMONSTRATED: Module IR v1 has no shared geometry-definition reference; nested-shared-definitions is an empty-group hierarchy only",
        "consumerStatus": {"originalEditorE4": "NOT_RUN", "originalModelEval": "NOT_RUN", "section241": "NOT_RUN"},
        "compilerSources": {p: sha256((ROOT / p).read_bytes()) for p in COMPILER_SOURCES},
        "fixtures": [
            {"name": name, "intent": fixtures.FIXTURES[name][1], "file": f"{name}.bomc",
             "sha256": sha256(blob), "byteSize": len(blob), "reader": summarize(blob)}
            for name, blob in sorted(blobs.items())],
        "unsupportedByBuilderSource": [
            {"name": name, "reason": reason} for name, (_, reason) in sorted(fixtures.unsupported_sources().items())],
    }


def write(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    blobs = build_all()
    for name, blob in blobs.items():
        (directory / f"{name}.bomc").write_bytes(blob)
    (directory / MANIFEST).write_text(json.dumps(manifest(blobs), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check(directory: Path) -> None:
    blobs = build_all()
    for name, blob in blobs.items():
        assert (directory / f"{name}.bomc").read_bytes() == blob, f"{name}: committed bytes differ from a fresh compile"
        print(name, sha256(blob), len(blob))
    expected = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    actual = manifest(blobs)
    actual["compilerSources"] = expected["compilerSources"]  # informational; the byte comparison is the gate
    assert actual == expected, "manifest differs from the regenerated one"


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args()
    write(args.write) if args.write else check(args.check)


if __name__ == "__main__":
    main()
