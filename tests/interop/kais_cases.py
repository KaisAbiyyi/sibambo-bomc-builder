"""Independently selected, synthetic BMB-021 fixtures.

Only public Builder examples are used as seed inputs; all additional geometry
and transforms are invented for this certification. No client/owner SKP data.
"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR_VERSION = "bmb021-kais-fixtures-v1"


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def source_digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_seed(name):
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def make_fixtures():
    small = load_seed("bmb020-semantic-floor.json")
    rooms = load_seed("module-ir-two-rooms.json")
    concave = copy.deepcopy(small)
    shape = concave["modules"][0]
    shape["operations"][0]["footprint"] = [
        [0, 0], [3, 0], [3, 1], [1, 1], [1, 3], [0, 3]]
    shape["bounds"] = {"min": [0, 0, 0], "max": [3, 3, 0.2]}
    shape["provenance"]["generator"] = GENERATOR_VERSION
    shape["provenance"]["note"] = "Original invented concave L-shaped slab"
    window = copy.deepcopy(rooms)
    hall = window["modules"][0]
    hall["operations"][2]["openingType"] = "window"
    hall["operations"][2]["height"] = 1.0
    hall["operations"][2]["sillHeight"] = 1.2
    hall["ports"] = []
    hall["ownedSeams"] = []
    hall["dependencies"] = []
    hall["provenance"]["generator"] = GENERATOR_VERSION
    window["modules"] = [hall]
    nested = copy.deepcopy(small)
    child = nested["modules"][0]
    child["moduleId"] = "house/level-1/child"
    child["parentId"] = "house/level-1/root"
    child["localFrame"]["transform"] = [
        1, .25, 0, 3, 0, 1.5, 0, 2, 0, 0, .75, 0, 0, 0, 0, 1]
    child["provenance"]["generator"] = GENERATOR_VERSION
    parent = copy.deepcopy(child)
    parent["moduleId"] = "house/level-1/root"
    parent["parentId"] = None
    parent["bounds"] = {"min": [0, 0, 0], "max": [0, 0, 0]}
    parent["operations"] = []
    parent["materials"] = []
    parent.pop("faceAnnotations", None)
    parent["localFrame"]["transform"] = [
        -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    nested["modules"].insert(0, parent)
    return {
        "minimal-solid": small,
        "concave-solid": concave,
        "door-and-two-room": rooms,
        "window-cutout": window,
        "nested-mirror-shear-nonuniform": nested,
    }


# Explicit source-independent reference expectations. Every case has a real
# nonzero face/vertex/triangle budget. No fake-positive empty geometry.
REFERENCE = {
    "minimal-solid": {
        "meshCount": 1, "faceCount": 6, "triangleCount": 12,
        "materialCount": 2, "bounds": [0, 0, 0, 2, 1, 0.2],
    },
    "concave-solid": {
        "meshCount": 1, "faceCount": 8, "triangleCount": 22,
        "materialCount": 2, "bounds": [0, 0, 0, 3, 3, 0.2],
    },
    "door-and-two-room": {
        "meshCount": 2, "faceCount": 58, "triangleCount": 116,
        "materialCount": 3,
    },
    "window-cutout": {"meshCount": 1, "faceCount": 68, "triangleCount": 136,
                      "materialCount": 2},
    "nested-mirror-shear-nonuniform": {
        "meshCount": 1, "faceCount": 6, "triangleCount": 12,
        "materialCount": 2, "bounds": [-5.25, 2, 0, -3, 3.5, 0.15],
    },
}

# These gaps must not silently become passes just because a different fixture
# has a similar-sounding feature. The producer/consumer can represent more
# than the present Builder Module IR.
UNSUPPORTED = {
    "concave-with-holes": "BMB-006 Module IR lacks hole authoring field",
    "shared-geometry-definition": "Module IR has unique per-module meshes; only empty group reuse supported in BMB-009",
    "Editor-241-authored-metadata": "Builder does not produce the Editor's private BWEB authoring section",
    "Ruby-producer-source-positives": "Requires original producer cloud-controlled synthetic fixture generation",
}
