# BMB-009 — Definition-instance DAG and nested transforms

Implementation: [`core/graph/dag.py`](../core/graph/dag.py). Tests: [`tests/test_bmb009_graph.py`](../tests/test_bmb009_graph.py). Lock: `core/graph`.

## Model

A *definition* holds named *instances*; each instance places another definition with a local transform. Definitions may be instanced many times, so one definition yields several world placements, addressed by slash-joined instance path (`wing-a/room-2`). The reference relation must be acyclic.

Matrices use the [Module IR convention](MODULE-IR-V1.md): flat row-major 4×4, translation at indices 3/7/11, last row `[0,0,0,1]`, metres. World = parent world × local. Mirrors (negative determinant), shear and non-uniform scale are allowed; `is_mirrored` reports handedness flips.

## Guarantees

- `add_instance` rejects a cycle (including self-reference) with `CycleError` carrying the loop path; every rejected edit leaves the graph unchanged.
- `find_cycle` / `topological_order` / `world_transforms` also fail closed on a corrupted graph that already contains a cycle.
- Transforms must be finite, within ±1e6, affine and invertible (|det| > 1e-9).
- `world_transforms` is deterministic and independent of insertion order (sorted traversal).
- Budgets: 256 definitions, 256 instances per definition, depth 32, 10 000 expanded instances (blocks exponential fan-out).

## Test evidence

`python -m unittest discover -s tests -p test_bmb009_graph.py -v` covers nested, mirrored (single and double), sheared and deep-chain composition against closed-form points, inverse round-trips, cycle rejection without mutation, pre-existing cycle detection, bad-transform rejection, budgets and insertion-order stability.

## Not covered (NOT_RUN)

Persistence/journal (BMB-010), assembly merge and seam ownership (BMB-011), validator diagnostics (BMB-012), and loading from Module IR JSON are out of scope. Cross-consumer BOMC proof belongs to BMB-021.
