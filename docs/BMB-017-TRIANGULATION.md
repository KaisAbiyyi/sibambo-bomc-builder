# BMB-017 — Polygon triangulation with holes and normals

Implementation: core/geometry/triangulation.py
Tests: tests/test_bmb017_triangulation.py
Resource lock: geometry/triangulation. Execution: strict cloud-only.

## API contract

Call triangulate_face(vertices, *, holes=(), normal=(0,0,1)), with each vertex as [x,y,z] in local metres. The holes argument is an optional sequence of strictly interior, disjoint, non-nested planar rings. Return type: immutable tuple of Triangle(vertices, normal), consisting of 3D triangle vertices and an outward unit normal. Each output triangle has positive oriented area toward the caller-supplied normal. Both clockwise and counter-clockwise ring input orders are accepted.

Existing floor.py and wall.py emit planar face loops and outward normals; integrate by passing each face's vertices and normal. There is no change to their interfaces. Important: the current Module IR floor-slab footprint has no holes field. This triangle API supports explicit hole loops, but authoring/compiler/consumer readback for holes remains downstream and NOT_RUN until specified and implemented.

## Algorithm and limitations

- Dependency-free pure-Python vertical-slab polygon decomposition using exact rational arithmetic over the input floats for intersection, orientation and area accounting. At every unique projected vertex coordinate, subdivide the plane into vertical strips; sort boundary intersections at each strip midpoint; use even-odd parity to select interior intervals; triangulate each trapezoid. This supports concave polygons and disjoint holes without bridge heuristics.
- Projection uses the dominant axis of the requested normal, supporting XY floors, vertical walls, downward faces and oblique planar faces. Generated triangle vertices are interpolated in exact rational 3D coordinates, then converted to finite floats.
- Fail-closed validation: finite bounded coordinates, positive unit-normal length, plane membership, positive ring and net area, minimum edge length, no self-intersection/spikes/touching, strict hole containment, and nonoverlap.
- Limits: 1024 total vertices, 64 holes, 20000 triangles; coordinates up to absolute 10000 metres, projected edges at least 1e-6 metres and projected ring/net areas at least 1e-6 square metres. Runtime complexity is quadratic or worse in adversarial polygon complexity; budgets are deliberate. The conforming edge pass may increase triangle count and fails closed at the same limit.
- Output is an **unindexed, conforming triangle soup**. All vertices at each sweep-strip boundary are used to split incident vertical triangle edges, preventing T-junctions along strip seams (synthetic acceptance tested). Interior coverage and hole exclusion are exact in projected rational arithmetic. A complete *indexed solid/manifold* and native BOMC consumer interoperability are NOT PROVEN and remain downstream gates.
- The function cannot infer whether a normal is outward from a complete solid: the calling floor/wall face supplies that semantic direction.

## Verification and boundary

Hosted GitHub Actions on Ubuntu and Windows, Python 3.12:
- Focused: python -m unittest discover -s tests -p test_bmb017_triangulation.py -v
- Regression: python -m unittest discover -s tests -p test_*.py -v

Synthetic acceptance includes concave and collinear rings, one/two holes, clockwise/counter-clockwise input, positive/negative outward normals, vertical/oblique plane faces, face integration with BMB-013/014, repeatability, and malformed input rejection. Do not claim BOMC binary or native consumer parity without separate evidence.
