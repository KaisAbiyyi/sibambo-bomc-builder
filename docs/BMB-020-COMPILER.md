# BMB-020 — Graph-to-BOMC compiler: bounded metadata subset

Implementation: [graph_to_bomc.py](../bomc/compiler/graph_to_bomc.py); tests: [test_bmb020_compiler.py](../tests/test_bmb020_compiler.py). Cloud-only; no owner/local files or assets; GPL-3.0 clean-room Python stdlib.

## Supported behavior

- BMB-006 strict document -> BMB-011 assembled graph -> canonical sorted node tree -> BMB-019 BOMC 1.2 writer.
- BMB-009 in-memory definition-instance DAG -> deterministic expanded empty-group placements; repeats of a definition are represented as distinct group instances, **not** reusable geometric definitions.
- BMB-011 parent hierarchy uses each module's **local** row-major 4×4 transform converted to the BMB-019 writer's column-major form; mirrors and shears are preserved, not double-composed. Nonmodule parents are deduplicated once as identity groups.
- Stable SHA-derived internal IDs, canonical order, sorted/deduplicated string table from BMB-019, bounded 128 total nodes, 1 MiB JSON and 2 MiB output. The emitted sections are 1, 2, 11, 12, 13, 17, 20. Six coverage counters are **zero** only because there is **no geometry**.
- Any nonempty module operations, materials, ports, seams or face annotations, or nonzero geometry bounds, are rejected rather than silently producing an empty house. Source IR revision/dependencies/provenance are not a BOMC authoring journal; dependencies and provenance are validated upstream but are not serialized.
- Inputs are not mutated. CLI writes atomically and prints a JSON receipt with SHA256, section IDs and zero coverage.

## Reproduction

The CLI input is a BMB-006 envelope with geometry-free modules (not the realistic two-room example; that must be rejected until geometry writer support exists):

    python -m bomc.compiler.graph_to_bomc --input empty-modules.json --output output.bomc
    python -m unittest discover -s tests -p test_bmb020_compiler.py -v

CI executes two **separate cold Python processes** and asserts full byte and SHA256 identity; independent structural harness checks the output. Matrix: Ubuntu and Windows Python 3.12.

## Acceptance classification

**PASS only after exact HEAD GitHub Actions succeeds:** deterministic metadata-only graph, canonical grouping and sorting, no lossy fallbacks, valid binary container and zero geometry coverage.

**NOT_RUN / unfinished BMB-020 requirement:** real nonempty face/vertex/triangle/material BOMC 1.2 authoring, geometry coverage, positive original Editor/Model-Eval semantic readback, BMB-021 interoperability/corruption, owner/native visual gates.

This is useful compiler integration infrastructure **but is not full BMB-020 acceptance** and must not be closed or merged as a complete real-house compiler. A future geometry adapter needs independently documented byte schema and genuinely positive semantic consumer evidence.
