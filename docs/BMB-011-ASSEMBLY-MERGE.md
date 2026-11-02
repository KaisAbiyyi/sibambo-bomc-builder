# BMB-011 — Assembly merge and shared-wall seam ownership

Implementation: [`core/assembly/merge.py`](../core/assembly/merge.py). Tests: [`tests/test_bmb011_assembly.py`](../tests/test_bmb011_assembly.py). Lock: `core/assembly`. Input is [Module IR](MODULE-IR-V1.md) modules; transforms use the [BMB-009](BMB-009-DEFINITION-INSTANCE-GRAPH.md) helpers.

## API

- `assemble(modules) -> Assembly`: merges a list of module objects into one graph or raises `AssemblyError`. Nothing is returned on error and inputs are never mutated (modules are deep-copied as plain JSON).
- `merge_assemblies(*assemblies)`: union of assemblies with disjoint module ids, re-validated as a whole.
- `Assembly`: `modules` (sorted), `order` (dependencies first), `world_transforms`, `seams`, plus `neighbours()`, `seams_of()`, `owned_by()`. The result is identical for any input order.

## What the merge checks (fail closed)

- **Identity:** schemaVersion `1.0.0`, unique valid module ids, integer revisions, bounded counts (operations ≤ 10 000, ports, seams and dependencies ≤ 256 each, modules ≤ 1024: the same limits as the Module IR schema).
- **Links:** `parentId` chains are acyclic and at most 32 deep; a parent that is not itself a module is treated as a group (identity transform), a parent that is a module composes its transform. Dependencies must exist, may not be self, duplicate or cyclic, and `minRevision` must be satisfied by the module's revision.
- **Ports:** each port with a peer needs a `seamId` (and the reverse); the peer must exist in another module and point back; both name the same seam.
- **Shared wall agreement in world space:** port normals (transformed by the inverse transpose, so mirrors, rotations and shear are handled) must be opposite within 1e-6; port frame origins must coincide within 1 mm; and the **world-space opening extents** must match within 1 mm: width and height are scaled by the length of the placed frame +Y / +Z axis (so scale and shear of the module chain and of the port frame count), then compared. A local `width: 0.9` under a `scale(1, 2, 1)` frame is 1.8 m in the assembly.
- **Port frame orientation:** the Module IR does not name the axes of a port's `localTransform`, so this merge assumes (and rejects violations of) a convention: frame **+Y is the width direction and +Z the height direction, both tangent to the port normal**. In world space (axes move with the forward matrix, normals with the inverse transpose) each axis must be perpendicular to the port normal within 1e-6, and the two peers' width lines and height lines must be parallel (sign ignored, so a 180° turn is fine while a 90° turn about the normal, which swaps width and height, is rejected). **Status: provisional, awaiting owner approval.** The convention is not yet normative in `MODULE-IR-V1.md` (this PR does not change the IR contract or schema); until the owner approves and records it there, treat port-frame interoperability as unguaranteed.
- **Type-safe:** malformed nested input (unhashable ids, junk numbers, huge integers) raises `AssemblyError`, never a raw `TypeError`/`OverflowError`; a composed parent chain that becomes singular or out of range is rejected even when each transform is valid alone.
- **Seam ownership:** every reciprocal port pair must be covered by exactly one `ownedSeams` entry declared by one of its two modules. Both claiming it raises `DuplicateOwnershipError`; neither claiming it, an owner that is not a participant or not the declarer, participants that differ from the connected modules, a `surfaceOpId` that is not an operation of the owner, a duplicate seam id, and a seam no port pair references are all rejected.

## Test evidence

`python -m unittest discover -s tests -p test_bmb011_assembly.py -v` (Ubuntu + Windows CI, `.github/workflows/bmb011-assembly.yml`): the IR example, a three-module chain, order independence, nested parents, mirrored / rotated / sheared frames, disjoint union, and rejection cases for ownership, ports, dependencies and parents, peer frames rotated about the normal, and a fuzz-style test that replaces every leaf of a valid assembly with junk values and requires only `AssemblyError`. Mutation checks: removing the duplicate-owner check or using the wrong normal transform makes the matching tests fail.

## Not covered (NOT_RUN)

Geometry validity, bounds overlap and collisions, opening-versus-wall fit and typed diagnostics (BMB-012); compiling the assembly to BOMC (BMB-020); replacing a module with a newer revision inside an existing assembly (rebuild with `assemble`); persistence (BMB-010); Module IR JSON Schema validation (use the BMB-006 schema separately).
