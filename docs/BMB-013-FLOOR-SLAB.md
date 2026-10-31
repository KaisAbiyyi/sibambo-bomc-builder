# BMB-013 — Parametric floor slab primitive

Implementation: [`core/geometry/floor.py`](../core/geometry/floor.py). Tests: [`tests/test_bmb013_floor.py`](../tests/test_bmb013_floor.py). Lock: `geometry/floor`.

## Model

`build_floor_slab(op)` takes a [Module IR](MODULE-IR-V1.md) `floor-slab` operation (`footprint`, `thickness`, `elevation`, optional `materialId` / `role`, default role `floor`) and returns a `FloorSlab`: a closed prism in module-local metres, right-handed, +Z up. **`elevation` is the z of the slab's bottom face**; the slab extends to `elevation + thickness`.

Faces are planar polygon loops (counter-clockwise seen from outside, outward unit `normal` stored): `top`, `bottom`, then `side-i` for footprint edge *i*. They are **not triangulated** (BMB-017) and a footprint has no holes (the IR has no hole field). A clockwise footprint is normalised to counter-clockwise keeping the first vertex first. `bounds`, `area` and `volume` are exact-arithmetic based for the area and fully deterministic.

## Validation (fail closed, nothing returned on error)

- thickness finite, in (0, 100] m; all numbers finite, real (bool/str rejected), |value| ≤ 1e4 m (out-of-range integers are rejected before float conversion, so no OverflowError).
- footprint 3..1024 vertices (stricter than the schema's 4096 because the simplicity check is O(n²)); each edge ≥ 1 µm; area ≥ 1e-6 m².
- footprint must be a simple polygon: no self-intersection, touching, repeated vertex, repeated closing point or edges folding back on themselves. Orientation tests use exact rational arithmetic. Collinear extra vertices are allowed.
- ids follow the IR slug pattern; role is one of the IR roles; unknown fields rejected.

## Test evidence

`python -m unittest discover -s tests -p test_bmb013_floor.py -v` (Ubuntu + Windows CI, `.github/workflows/bmb013-floor.yml`): rectangle and concave L bounds/area/volume, CW normalisation, per-face winding vs normal, closed-manifold edge pairing and Euler count, divergence-theorem volume, IR example floor ops, determinism, and rejection cases.

## Not covered (NOT_RUN)

Triangulation (BMB-017), wall junctions and seams (BMB-014/011), world transforms (BMB-009), BOMC emission (BMB-019/020) and any consumer readback (BMB-021). Slabs with holes would need an IR extension.
