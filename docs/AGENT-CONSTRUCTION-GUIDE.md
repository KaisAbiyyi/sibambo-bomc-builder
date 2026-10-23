# Agent Construction Guide v0 — conceptual specification

**NOT YET IMPLEMENTED.** These tool names are target designs for BMB-022 through BMB-025; do not report the MCP as installed or successful.

## Mission
You are controlling a deterministic BOMC Modular Builder. Produce a building by planning and creating geometric modules at the level needed for efficient reasoning, validate, locally repair, merge the graph, and compile actual BOMC. Do **not** handcraft binary section bytes in model output.

## Loop
1. Read global building brief, approved tools, budgets, supported BOMC subset.
2. Plan floors/rooms/adjacency, shared-wall ownership, door path connectivity, module IDs and global coordinates.
3. Create a module (room, wall, floor etc.) with typed operations and expected revision + idempotency key.
4. Inspect that module, neighbors' bounds/ports, and local validation diagnostics; keep all other geometry out of context.
5. If collision, invalid opening, gap, nonmanifold face or missing requirement, edit only implicated modules, revalidate.
6. After all blocking checks pass, assemble once and compile BOMC; store SHA, compiler version, checks, source brief hash.
7. Read back with independent consumers. Mark any unperformed test NOT_RUN, not PASS.

## Proposed API
Read-only: project_info, manifest_get, module_inspect, assembly_inspect, bomc_inspect.
Mutating: project_create, module_create, module_patch, module_delete, geometry_add_wall, geometry_add_floor, geometry_add_opening, assembly_validate, bomc_compile.
**Actual schemas, auth, resource limits and methods must be frozen only after implementation/testing.**

## Sample structured brief
- Site 10m × 14m, +Z up, north 0 degrees, single storey, max footprint 85 m2.
- Spaces: living 1 at least 16m2; bedrooms 2 at least 9m2 each; bathroom 1 at least 4m2.
- Main entry south, all bedrooms reachable via circulation, living exposed to daylight.
- Construction: simple walls/slabs, real doors in cut walls, simple roof.
- Return: versioned manifest, module IDs, BOMC bytes, validation report and readback evidence.

## Context and geometry budget
Give each tool response small ID lists, AABBs, connection ports, error reports, revision and counts. Provide full mesh arrays only when requested for focused diagnosis, bounded by byte/count quotas. Never reread an entire building when editing one room. Every mutation is validated and atomic. No arbitrary shell command or out-of-workspace path. Shared walls have one writer/owner and are NOT independently duplicated in rooms A and B.

## Acceptance
- Geometry: correct winding, nondegenerate triangle faces, wall thickness > 0, openings truly cut, connected doors passable, overlaps measured.
- Graph: stable ID, no dangling refs/cycles, transforms reproducible including mirror/shear where supported, no stale-write overwrite.
- Output: supported BOMC version/CRC/coverage, same input/engine SHA parity, independent consumers successful.
- Agent quality: exact brief room type/count/area and relationships, localized correction, recorded time/tokens/tool-calls/retries.
- Transparency: performance and visual/native evidence separate; model is design concept, not structural/regulatory proof.
