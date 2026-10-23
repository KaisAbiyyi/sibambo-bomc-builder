# Modular BOMC Construction Architecture

## Headless first, agent as consumer
Manual brief / future silabs-generator forms → external Codex/ChatGPT/local agent → typed CLI/MCP → **headless construction core** → module manifest/graph → validation + seam ownership → deterministic BOMC writer → Sibambo Editor/Model-Eval.

MCP and CLI are adapters. No renderer, SketchUp process, paid LLM API, or Rooms database dependency in core.

## LEGO module IR (proposed, not on-wire BOMC)
Each module has version, stable namespaced module ID, parent ID, revision, local 4x4 transform (metres, right-handed +Z), typed geometry operations, bounds, named ports/adjacency, shared-wall ownership, dependencies, materials/role labels, content hash and provenance. Agent may use a wall, a room, or a full floor as a module. The compiler will normalize to BOMC shared definitions, meshes and instances rather than preserving arbitrary authoring file boundaries as BOMC sections.

Example conceptual module:
- ID: house/floor-1/living
- Parent: house/floor-1; translation: (0,0,0) metres
- Operation: room-shell width=4m depth=3m height=2.8m; wall thickness=0.15m
- East port: one 0.9m door connecting to hall
- North adjacency: kitchen; shared-wall owner recorded once
- Revision: 1; expected parent revision; idempotency key on mutation

This is NOT an implemented schema; BMB-006 must formalize it.

## Processing invariants
1. Missing references, graph cycles, duplicate IDs, NaN/Infinity, invalid transforms, invalid polygons and degenerate triangles are errors.
2. Face winding/normals/holes explicit; door/window openings cut actual wall geometry, not visual markers.
3. Shared walls have one owner; adjoining modules refer to one seam; collisions and gaps checked with unit-labelled tolerances.
4. Parallel agent work requires disjoint module IDs or optimistic revision protection; no silent last-write-wins.
5. Scope inspection to manifest + relevant blocks + neighboring seam summaries, not every mesh vertex.
6. Canonical ordering, stable IDs, deterministic quantization/compression choices; identical input and compiler revision => identical BOMC SHA.
7. All file writes confined to approved workspace; schema-limit lengths, counts, depth, bytes and runtime. No arbitrary shell execution through MCP.
8. A byte-exact unchanged import copy is not evidence of editable arbitrary imported BOMC.

## Planned API (design, not implemented)
Read: project_info, manifest_get, module_inspect, assembly_inspect, bomc_inspect.
Write: project_create, module_create, module_patch, module_delete, geometry_add_floor, geometry_add_wall, geometry_add_opening, assembly_validate, bomc_compile.

Each mutation must include an expected revision + optional idempotency key. Return changed modules, new revision, structured errors, resource stats, and next repair hint. Validation failure points at affected block IDs, not opaque narrative.

## Cross-repo contract
- **bom_engine_plugin**: SketchUp exporter speed/Exact size, independently developed.
- **sibambo-editor**: imports compiled BOMC, later separate optional Builder extension.
- **sibambo-rooms**: future validation signal behind optional adapter.
- **silabs-generator**: future survey/client/room UI and internal agentic orchestrator; consumes stable builder tools.
- **builder**: owns only geometry construction, modular assembly, validation, adapter tools and writer contracts.

## Architecture records
ADR-001: modules are authoring IR; compiled BOMC is derived immutable delivery.
ADR-002: flexible granularity, fixed module contract.
ADR-003: one deterministic graph-level BOMC compiler; do not concatenate binary BOMC.
ADR-004: local geometry guards are deterministic; agent reasoning guides higher-level designs.
ADR-005: cloud-first and Rooms-independent MVP.
ADR-006: GPL/private-to-public gate before sharing existing private kernel implementation.
ADR-007: no claim of arbitrary legacy BOMC edit or true SketchUp Exact acceptance.
