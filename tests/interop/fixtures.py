"""BMB-021 synthetic source models for the semantic golden suite. Wholly invented data."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from bomc.compiler.graph_to_bomc import compile_definition_graph, compile_document
from core.graph import dag

ROOT = Path(__file__).resolve().parents[2]


def module(mid, parent="house/level", transform=None, bounds=((0, 0, 0), (6, 4, 3))):
    return {
        "schemaVersion": "1.0.0", "moduleId": mid, "parentId": parent, "revision": 1,
        "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z", "forwardAxis": "+Y",
                       "transform": list(transform or dag.IDENTITY)},
        "bounds": {"min": list(bounds[0]), "max": list(bounds[1])},
        "operations": [], "materials": [], "ports": [], "ownedSeams": [], "dependencies": [],
        "provenance": {"origin": "synthetic", "generator": "bmb021-interop"},
    }


def floor_module(mid, footprint, transform=None, parent="house/level"):
    m = module(mid, parent=parent, transform=transform)
    m["operations"] = [{"kind": "floor-slab", "opId": "slab", "role": "floor", "materialId": "base",
                        "footprint": footprint, "thickness": 0.2, "elevation": 0}]
    m["materials"] = [
        {"materialId": "base", "rgba": [140, 135, 130, 255], "opacity": 1, "semanticRole": "floor"},
        {"materialId": "paint", "rgba": [200, 50, 35, 240], "opacity": 0.8, "semanticRole": "floor"}]
    m["faceAnnotations"] = [{"opId": "slab", "faceKey": "top", "role": "floor", "frontMaterialId": "paint",
                             "backMaterialId": "base", "label": "Floor top: independent front/back"}]
    return m


def envelope(*modules):
    return {"schemaVersion": "1.0.0", "modules": list(modules)}


def _example(name):
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def minimal_root():
    return compile_document(envelope(module("house/level/a", bounds=((0, 0, 0), (0, 0, 0)))))


def floor_front_back():
    return compile_document(_example("bmb020-semantic-floor.json"))


def concave_l_floor():
    l_shape = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 3], [0, 3]]
    return compile_document(envelope(floor_module("house/level/l", l_shape)))


def mirrored_sheared_floors():
    parent = module("house/level", parent=None, transform=dag.mirror("x"), bounds=((0, 0, 0), (0, 0, 0)))
    child = floor_module("house/level/a", [[0, 0], [2, 0], [2, 1], [0, 1]],
                         transform=dag.compose(dag.translation(3, 0, 0), dag.shear_xy(0.25)))
    return compile_document(envelope(parent, child))


def two_room_door_seam():
    return compile_document(_example("module-ir-two-rooms.json"))


def nested_shared_definitions():
    graph = dag.DefinitionGraph()
    for name in ("house", "wing", "room"):
        graph.add_definition(name)
    graph.add_instance("wing", "room-a", "room", dag.translation(0, 4, 0))
    graph.add_instance("wing", "room-b", "room", dag.compose(dag.translation(3, 0, 0), dag.mirror("x")))
    graph.add_instance("house", "wing-west", "wing", dag.translation(-6, 0, 0))
    graph.add_instance("house", "wing-east", "wing", dag.compose(dag.translation(6, 0, 0), dag.shear_xy(0.25)))
    graph.add_instance("house", "annex", "room", dag.translation(0, -4, 0))
    return compile_definition_graph(graph, "house")


# name -> (builder, one-line intent)
FIXTURES = {
    "minimal-root": (minimal_root, "one empty module under the root: no geometry sections"),
    "floor-front-back": (floor_front_back, "flat slab with independent front/back solid materials"),
    "concave-l-floor": (concave_l_floor, "concave L-shaped slab face, triangulated"),
    "mirrored-sheared-floors": (mirrored_sheared_floors, "mirror parent and sheared child transforms"),
    "two-room-door-seam": (two_room_door_seam, "two rooms, real door cutout, single-owned shared seam"),
    "nested-shared-definitions": (nested_shared_definitions, "nested shared empty-group definitions with mirror and shear"),
}


def unsupported_sources():
    """Inputs the Builder profile must refuse (fail closed). name -> (document, reason)."""
    holed = floor_module("house/level/h", [[0, 0], [4, 0], [4, 4], [0, 4]])
    holed["operations"][0]["holes"] = [[[1, 1], [2, 1], [2, 2], [1, 2]]]
    roofed = module("house/level/r")
    roofed["operations"] = [{"kind": "roof-gable", "opId": "roof", "footprint": [[0, 0], [4, 0], [4, 4], [0, 4]]}]
    textured = floor_module("house/level/t", [[0, 0], [2, 0], [2, 1], [0, 1]])
    textured["materials"][0]["texture"] = "wood.png"
    return {
        "holed-face": (envelope(holed), "Module IR v1 has no hole-authoring field"),
        "roof-operation": (envelope(roofed), "roof operations are not in the Module IR v1 schema"),
        "textured-material": (envelope(textured), "textures and UVs are not part of the profile"),
    }


def copy_of(value):
    return copy.deepcopy(value)
