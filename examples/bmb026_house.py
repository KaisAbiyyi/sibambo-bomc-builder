"""BMB-026: wholly synthetic, four-room house Module IR and cloud BOMC evidence.

Four room modules plus one flat-roof slab. Shared walls have exactly one geometric
owner and a reciprocal typed port. A bedroom's private exterior window is revised
without modifying any other module or shared seam. This is not a native Editor test.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from bomc.compiler.graph_to_bomc import compile_document
from core.assembly import assemble
from core.geometry.openings import build_wall_with_openings
from core.graph import dag
from tests.interop.reader import read as read_builder_bomc

ROOT = "house/level"
H = 2.8
W = 4.0
D = 3.0
DOOR_W = 0.9
DOOR_H = 2.1
ROOMS = ("living", "bedroom-a", "bedroom-b", "bath")
ORIGINS = {"living": (0, 0), "bedroom-a": (4, 0),
           "bedroom-b": (0, 3), "bath": (4, 3)}
ROOM_IDS = {room: f"{ROOT}/{room}" for room in ROOMS}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _material(name: str, color: tuple[int, int, int], role: str) -> dict:
    return {"materialId": name, "rgba": [*color, 255],
            "opacity": 1, "semanticRole": role}


def _wall(side: str) -> dict:
    paths = {"west": [[0, 0], [0, D]], "east": [[W, 0], [W, D]],
             "south": [[0, 0], [W, 0]], "north": [[0, D], [W, D]]}
    return {"kind": "wall-run", "opId": f"wall-{side}", "role": "wall",
            "materialId": "plaster", "path": paths[side],
            "thickness": 0.15, "height": H, "baseElevation": 0}


def _room(name: str, revised: bool) -> dict:
    x, y = ORIGINS[name]
    walls = {
        "living": ("west", "south", "east", "north"),
        "bedroom-a": ("south", "east", "north"),
        "bedroom-b": ("west", "north", "east"),
        "bath": ("north", "east"),
    }[name]
    ops = [{"kind": "floor-slab", "opId": "floor", "role": "floor",
            "materialId": "flooring", "footprint": [[0, 0], [W, 0], [W, D], [0, D]],
            "thickness": 0.15, "elevation": 0}, *(_wall(s) for s in walls)]
    if name == "bedroom-a":
        # Private exterior opening: no adjacent seam/port needs to be rewritten.
        ops.append({"kind": "opening-cut", "opId": "exterior-window", "role": "opening",
                    "targetWallOpId": "wall-east", "offset": 0.85,
                    "width": 1.2 if revised else 1.0, "height": 1.15,
                    "sillHeight": 0.9, "openingType": "window"})
    return {
        "schemaVersion": "1.0.0", "moduleId": ROOM_IDS[name], "parentId": ROOT,
        "revision": 2 if name == "bedroom-a" and revised else 1,
        "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z",
                       "forwardAxis": "+Y", "transform": list(dag.translation(x, y, 0))},
        "bounds": {"min": [0, 0, 0], "max": [W, D, H]},
        "operations": ops,
        "materials": [_material("flooring", (185, 176, 158), "floor"),
                      _material("plaster", (233, 232, 226), "wall")],
        "ports": [], "ownedSeams": [], "dependencies": [],
        "provenance": {"origin": "synthetic", "generator": "bmb026-cloud-house",
                       "note": "Fictitious 8 by 6 metre four-room layout"},
    }


def _roof() -> dict:
    return {
        "schemaVersion": "1.0.0", "moduleId": f"{ROOT}/roof", "parentId": ROOT,
        "revision": 1,
        "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z",
                       "forwardAxis": "+Y", "transform": list(dag.IDENTITY)},
        "bounds": {"min": [0, 0, 0], "max": [8, 6, 3]},
        "operations": [{"kind": "floor-slab", "opId": "flat-roof", "role": "roof",
                        "materialId": "roof-solid", "footprint": [[0, 0], [8, 0], [8, 6], [0, 6]],
                        "thickness": 0.15, "elevation": 2.85}],
        "materials": [_material("roof-solid", (129, 139, 146), "roof")],
        "ports": [], "ownedSeams": [], "dependencies": [],
        "provenance": {"origin": "synthetic", "generator": "bmb026-cloud-house"},
    }


def _port(name: str, other: str, peer_id: str, seam: str,
          normal: tuple[int, int, int], point: tuple[float, float],
          width: float, kind: str) -> dict:
    # Port +Y is the horizontal span direction. North ports rotate 90 degrees.
    turn = 90 if normal[1] else 0
    return {"portId": name, "kind": kind, "normal": list(normal),
            "localTransform": list(dag.compose(dag.translation(point[0], point[1], 0),
                                                dag.rotation_z(turn))),
            "width": width, "height": DOOR_H if kind == "doorway" else H,
            "peer": {"moduleId": ROOM_IDS[other], "portId": peer_id},
            "seamId": seam}


def _connect(modules: dict[str, dict], owner: str, peer: str, side: str,
             seam: str, *, opening_offset: float | None) -> None:
    owning, other = modules[owner], modules[peer]
    normal = (1, 0, 0) if side == "east" else (0, 1, 0)
    if opening_offset is None:
        # A solid shared boundary is not misrepresented as a traversable door.
        span = 2.4
        center = D / 2 if side == "east" else W / 2
        kind = "shared-boundary"
    else:
        span = DOOR_W
        center = opening_offset + span / 2
        kind = "doorway"
        owning["operations"].append(
            {"kind": "opening-cut", "opId": f"door-{peer}", "role": "opening",
             "targetWallOpId": f"wall-{side}", "offset": opening_offset,
             "width": span, "height": DOOR_H, "sillHeight": 0, "openingType": "door"})
    owner_pos = (W, center) if side == "east" else (center, D)
    peer_pos = (0, center) if side == "east" else (center, 0)
    owner_pid = f"to-{peer}"
    peer_pid = f"to-{owner}"
    owning["ports"].append(_port(owner_pid, peer, peer_pid, seam, normal, owner_pos, span, kind))
    other["ports"].append(_port(peer_pid, owner, owner_pid, seam,
                                 tuple(-v for v in normal), peer_pos, span, kind))
    owning["ownedSeams"].append(
        {"seamId": seam, "ownerModuleId": ROOM_IDS[owner],
         "participants": [ROOM_IDS[owner], ROOM_IDS[peer]],
         "surfaceOpId": f"wall-{side}"})


def build_house(*, revised: bool = False) -> dict:
    """Generate Module IR from immutable dimensions, no filesystem writes."""
    if type(revised) is not bool:
        raise TypeError("revised must be bool")
    modules = {name: _room(name, revised) for name in ROOMS}
    _connect(modules, "living", "bedroom-a", "east", "living-a", opening_offset=1.0)
    _connect(modules, "living", "bedroom-b", "north", "living-b", opening_offset=1.35)
    _connect(modules, "bedroom-a", "bath", "north", "a-bath", opening_offset=1.45)
    _connect(modules, "bedroom-b", "bath", "east", "b-bath", opening_offset=None)

    # Revisions are independent: consumers accept a compatible >=1 bedroom
    # dependency, so a non-shared window edit cannot force a bath rewrite.
    modules["bedroom-a"]["dependencies"] = [{"moduleId": ROOM_IDS["living"], "minRevision": 1}]
    modules["bedroom-b"]["dependencies"] = [{"moduleId": ROOM_IDS["living"], "minRevision": 1}]
    modules["bath"]["dependencies"] = [
        {"moduleId": ROOM_IDS["bedroom-a"], "minRevision": 1},
        {"moduleId": ROOM_IDS["bedroom-b"], "minRevision": 1},
    ]
    return {"schemaVersion": "1.0.0", "modules": [*modules.values(), _roof()]}


def evidence() -> tuple[dict, dict, dict]:
    """Compiler + independent Builder reader. Never assert original Editor success."""
    before, after = build_house(), build_house(revised=True)
    a = {m["moduleId"]: canonical_hash(m) for m in before["modules"]}
    b = {m["moduleId"]: canonical_hash(m) for m in after["modules"]}
    changed = sorted(mid for mid in a if a[mid] != b[mid])
    assert changed == [ROOM_IDS["bedroom-a"]], changed
    receipts: dict[str, dict] = {}
    for name, source in (("baseline", before), ("revised", after)):
        assembly = assemble(source["modules"])
        assert len(assembly.seams) == 4
        assert len({s.seam_id for s in assembly.seams}) == 4
        for member in source["modules"]:
            ops = member["operations"]
            for op in ops:
                if op["kind"] == "opening-cut":
                    wall = next(o for o in ops if o["opId"] == op["targetWallOpId"])
                    actual = build_wall_with_openings(wall, [op])
                    assert actual["wall"]["topology"] == "conforming-quad-voids"
                    if op["openingType"] == "door":
                        assert len(actual["doorwayClearance"]) == 1
        compiled = compile_document(source)
        decoded = read_builder_bomc(compiled.payload)
        assert decoded["counts"]["meshes"] >= 5 and decoded["counts"]["faces"] > 0
        assert decoded["triangles"] > 0
        receipts[name] = compiled.receipt()
        receipts[name]["builderReadback"] = {
            "faces": decoded["counts"]["faces"],
            "meshes": decoded["counts"]["meshes"],
            "triangles": decoded["triangles"],
            "bounds": list(decoded["bounds"]),
        }
    assert receipts["baseline"]["sha256"] != receipts["revised"]["sha256"]
    return before, after, {
        "task": "BMB-026", "source": "synthetic", "layout": "2 bedrooms, living, bath + flat roof",
        "roomCount": 4, "moduleCount": 5, "sharedWallOwners": 4,
        "doorOpenings": 3, "exteriorWindows": 1,
        "changedModules": changed, "preservedModuleHashes": {
            mid: sha for mid, sha in a.items() if a[mid] == b[mid]
        },
        "beforeModuleHashes": a, "afterModuleHashes": b,
        "outputs": receipts, "gates": {
            "builder_source_assembly_compiler_reader": "PASS",
            "native_editor_e4_import": "NOT_RUN",
            "owner_visual_acceptance": "NOT_RUN",
            "full_roof_gable_stairs_and_arbitrary_bomc": "NOT_RUN",
            "provider_native_live_agent": "NOT_RUN",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Wholly synthetic four-room BOMC exercise")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    before, after, receipt = evidence()
    directory = args.out_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for label, source in (("baseline", before), ("revised", after)):
        (directory / f"{label}.json").write_text(
            json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (directory / f"{label}.bomc").write_bytes(compile_document(source).payload)
    (directory / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
