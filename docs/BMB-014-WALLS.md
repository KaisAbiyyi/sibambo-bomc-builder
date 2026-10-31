# BMB-014 — Parametric wall runs and end-to-end junctions

## Purpose and boundaries

Independent headless Python implementation of Module IR v1 `wall-run`. Input dimensions are **metres**, in the module's local right-handed +Z frame. No binary BOMC writer or proprietary Editor geometry code is used. All fixtures are synthetic.

The public API is `build_wall_run(op)` and `join_wall_runs([op, ...], op_id="joined-wall")` in `core.geometry.wall`; only Python 3.12 standard library is required at runtime.

## Geometric contract

- A wall path is an **open centreline polyline**, 2–1024 finite coordinate pairs. Validated positive finite thickness and height, finite base elevation, a stable slug operation ID and bounded coordinates are required.
- Left/right half-thickness rails are offset from segment directions. At every interior corner their offset lines intersect, forming a **miter**. This avoids double-faced caps at ordinary L corners.
- Same-direction collinear waypoints are simplified deterministically. Backtracks, duplicate points, self-crossing centrelines, excessive miter spans, intersecting footprint boundary, and unsupported degenerate geometry fail closed.
- The footprint is counter-clockwise and extruded between the specified base and top heights. The output includes ordered top/bottom and individual side polygons, explicit outward unit normals, bounds, centreline length, area, volume, and miter junction coordinates.
- `join_wall_runs` accepts a connected, open **end-to-end** chain of matching operations. Endpoint equality is exact: no silent snapping. Input order/direction does not affect mesh result. The merger removes internal caps by constructing one solid, while enforcing equal thickness/height/base elevation/material/role and unique source operation IDs.
- Multi-branch T/X junction unions, crossing seams, multi-owner graph assignment and closed rings **fail closed**. BMB-011 owns graph seam ownership, BMB-015 actual door/window cutouts, BMB-017 triangulation; these are not falsely considered implemented. A later junction-boolean operation is required for branching walls.

## Example

```python
from core.geometry.wall import join_wall_runs

west = {"kind": "wall-run", "opId": "west", "path": [[0, 0], [3, 0]],
        "thickness": 0.15, "height": 2.8, "baseElevation": 0}
north = {"kind": "wall-run", "opId": "north", "path": [[3, 0], [3, 2]],
         "thickness": 0.15, "height": 2.8, "baseElevation": 0}
solid = join_wall_runs([north, west])
assert solid["sourceOpIds"] == ["west", "north"]
assert solid["junctions"][0]["kind"] == "miter"
```

The returned faces are **polygon surfaces**, not triangulated BOMC payloads; no module-to-world transforms are applied. BOMC semantic writer/consumer conformance and native Editor/Model-Eval positive import remain **NOT_RUN** for BMB-019/020/021.

## Cloud CI

`.github/workflows/bmb014-wall.yml` runs GitHub-hosted Ubuntu and Windows with Python 3.12 on PR changes, using these commands:

```shell
python -m pip install 'jsonschema==4.23.0'
python -m unittest discover -s tests -p 'test_bmb014_wall.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
```

Acceptance cases exercise dimensions, volume, outside/inside miter joins, winding/normals, closed-manifold edge pairing, deterministic serialization and direction/order-independent seam merges, with malformed-path/number/ID/branch rejection. Record exact-head GitHub Actions evidence separately; source code alone is not a PASS.
