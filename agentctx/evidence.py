"""BMB-024: synthetic scenes and token-cost evidence (estimator based, NOT provider-native token counts).

    python -m agentctx.evidence            # JSON table: scoped reads versus dumping the whole scene
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from agentctx.budget import ESTIMATOR, estimate_tokens
from agentctx.retrieval import ContextProvider
from core.assembly import assemble
from core.graph import dag
from core.storage.journal import JournalStore

LIV, HALL, BATH = "house/f1/living", "house/f1/hall", "house/f1/bath"


def _port(pid, peer, seam, normal, at, turn=0):
    return {"portId": pid, "kind": "doorway", "normal": list(normal), "width": 0.9, "height": 2.1,
            "localTransform": list(dag.compose(dag.translation(*at), dag.rotation_z(turn))),
            "peer": {"moduleId": peer[0], "portId": peer[1]}, "seamId": seam}


def _module(mid, at=(0, 0, 0), ports=(), seams=(), deps=(), size=(2, 3, 2.8), parent="house/f1", walls=True):
    return {"schemaVersion": "1.0.0", "moduleId": mid, "parentId": parent, "revision": 1,
            "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z", "forwardAxis": "+Y",
                           "transform": list(dag.translation(*at))},
            "bounds": {"min": [0, 0, 0], "max": list(size)}, "materials": [],
            "operations": [{"kind": "wall-run", "opId": "east-wall", "path": [[0, 0], [1, 0]], "thickness": 0.15,
                            "height": size[2], "baseElevation": 0}] if walls else [], "ports": list(ports),
            "ownedSeams": list(seams), "dependencies": [{"moduleId": d, "minRevision": r} for d, r in deps],
            "provenance": {"origin": "synthetic"}}


def house_modules(overlap: bool = False) -> list[dict]:
    """living (0..4) - hall (4..6, north of it a bath): two single-owned seams; optional overlapping closet."""
    liv = _module(LIV, size=(4, 3, 2.8), ports=[_port("hall-door", (HALL, "living-door"), "east", (1, 0, 0), (4, 1, 0))],
                  seams=[{"seamId": "east", "ownerModuleId": LIV, "participants": [LIV, HALL], "surfaceOpId": "east-wall"}])
    hall = _module(HALL, at=(4, 0, 0), deps=[(LIV, 1)],
                   ports=[_port("living-door", (LIV, "hall-door"), "east", (-1, 0, 0), (0, 1, 0)),
                          _port("bath-door", (BATH, "hall-door"), "north", (0, 1, 0), (1, 3, 0), turn=90)],
                   seams=[{"seamId": "north", "ownerModuleId": HALL, "participants": [HALL, BATH], "surfaceOpId": "east-wall"}])
    bath = _module(BATH, at=(4, 3, 0), deps=[(HALL, 1)],
                   ports=[_port("hall-door", (HALL, "bath-door"), "north", (0, -1, 0), (1, 0, 0), turn=90)])
    mods = [liv, hall, bath]
    if overlap:
        mods.append(_module("house/f1/closet", at=(1, 1, 0), size=(1, 1, 2.0)))  # sits inside the living room
    return mods


def build_scene(root, filler: int = 0, overlap: bool = False):
    """A journal with the house (each module has blocks and >=1 revision) plus `filler` unrelated modules.

    Returns (store, assembly). Filler modules appear in the journal AND in the typed assembly, far apart.
    """
    store = JournalStore.open(root)
    modules = house_modules(overlap)
    for i in range(filler):
        modules.append(_module(f"site/block-{i:04d}", at=(100 + 10 * (i % 50), 100 + 10 * (i // 50), 0), parent="site/blocks"))
    for m in modules:
        mid = m["moduleId"]
        store.create_module(mid)
        store.apply(mid, 0, "seed-1", [{"op": "add", "id": f"wall-{k}", "data": {"height": 2.8, "thickness": 0.15, "k": k}}
                                       for k in range(6)])
    return store, assemble(modules)


def measure(sizes=(3, 30, 300)) -> list[dict]:
    rows = []
    for total in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            store, assembly = build_scene(tmp, filler=max(0, total - 3))
            provider = ContextProvider(store, assembly)
            full = provider.full_scene_tokens()
            module = estimate_tokens(provider.module(HALL, depth=1))
            page = estimate_tokens(provider.manifest())
            rows.append({"modules": total, "fullSceneTokens": full, "manifestPageTokens": page,
                         "moduleContextTokens": module, "reduction": round(full / module, 1)})
    return rows


if __name__ == "__main__":
    json.dump({"estimator": ESTIMATOR, "providerNativeTokens": None, "rows": measure()}, sys.stdout, indent=2)
    print()
