# BMB-015 — Real door/window topology cutouts

## Scope, interface, and limitations

`core.geometry.openings.build_wall_with_openings(wall_op, opening_ops, minimum_door_clearance=0.70)` consumes an independently validated BMB-014 `wall-run` operation and a list of existing Module IR v1 `opening-cut` operations. All values use **metres**, local right-handed axes, and +Z up. Only **one straight (or collinearly normalized) wall run** is supported. Non-collinear bends, T/X wall intersections, shared-wall seam ownership, arbitrary boolean unions, polygon triangulation and BOMC/consumer integration **fail closed or remain out of scope**; this is not a claim of arbitrary cutout parity.

The returned object has:

- `wall`: preserved BMB-014 `wall-solid` metadata, but `faces` replaced with a conforming oriented quad shell; `volume` is reduced by actual rectangular void volumes. The `openings` array contains validated derived local bounds; `topology` is `conforming-quad-voids`.
- `inserts`: separately identified `door-insert` or `window-insert` objects, each with closed frame-part solids and either a fully open 90-degree door leaf outside the wall-depth passage, or a glazing pane inside the genuine window opening. These have their own face meshes and bounds, not visual overlays.
- `doorwayClearance`: a clear contiguous rectangular through-wall passage per door, with metres-based width, headroom and local bounds. Defaults to a tested 0.70 m minimum width and 1.90 m headroom, which are **implementation guards, not building-code certification**. The door leaf is represented open, not as a closed blockage.

To preserve a true solid cutout, wall faces are generated from an X/Z partition of occupied cells, with all exposed jamb, sill and lintel surfaces and no internal faces. Each quad and shared edge is consistently oriented; tests verify watertight edge pairing and outward face normals. Frame/glazing/door-leaf geometry is intentionally stored **separately** from wall-shell volume. No wall material is left within the cutout; a window's **glazing** is deliberate separate geometry.

## Example

```python
from core.geometry.openings import build_wall_with_openings

wall = {
    "kind": "wall-run", "opId": "wall-a",
    "path": [[0, 0], [4, 0]],
    "thickness": 0.2, "height": 2.8, "baseElevation": 0,
}
door = {
    "kind": "opening-cut", "opId": "door-a",
    "targetWallOpId": "wall-a", "offset": 1, "width": 0.9,
    "height": 2.1, "sillHeight": 0, "openingType": "door",
}
result = build_wall_with_openings(wall, [door])
assert result["wall"]["volume"] < 4 * 0.2 * 2.8
assert result["doorwayClearance"][0]["width"] >= 0.7
```

The engine rejects invalid dimensions, NaN/Infinity/booleans, wrong target references, duplicate IDs, openings crossing wall boundaries, openings without head/side piers, windows without positive sills, doors with blocking sills, overlapping or touching openings, non-straight walls, and excessively large input (max 16 openings, 2048 X/Z partition cells). No clipping, silent snapping, or gap-filling guesses.

## Synthetic acceptance and verification

GitHub-hosted `.github/workflows/bmb015-openings.yml` runs Ubuntu/Windows Python 3.12:

```shell
python -m pip install 'jsonschema==4.23.0'
python -m unittest discover -s tests -p 'test_bmb015_openings.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
```

The tests check true volume subtraction, no front/back faces spanning the void, surface orientation, watertight manifold edge pairing, separate solid inserts, open door clearance, window glazing, multi-opening geometry, reversed/diagonal walls, repeatable serialization, schema-fixture compatibility, and negative error cases.

**Evidence policy:** Only an actual GitHub Actions run at the exact source HEAD can be marked hosted PASS. Module IR output is **not** automatically compiled, triangulated, rendered, or proven in native Editor/Model-Eval. BMB-017, BMB-020 and BMB-021 own those later verification contracts. Track PASS/FAIL/NOT_RUN distinctly in issue, PR and Notion.
