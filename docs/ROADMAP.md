# BOMC Modular Builder — phased roadmap (Oct–Dec 2026)

**Destination:** [new standalone Notion project](https://app.notion.com/p/402c4a6aaf738181adf0eb95320ff947), not part of Sibambo Project Hub. **Goal:** turn an agent-generated spatial plan into independently authored/patchable geometric modules, assembled into one valid real 3D BOMC. **Strategy:** headless, cloud-first, external agent initially; silabs-generator internal loop/UI later.

## Milestones, target dates and real gates

| Phase | Timebox | Milestone | Exit gate |
|---|---|---|---|
| P0 Recon | 23–31 Oct | Pin BOMC v1.2, authoring subset, license + threat model | Compatibility/IP decisions documented; no unverifiable binary promise |
| P1 IR | 28 Oct–7 Nov | Modular manifest, graph DAG, shared-wall seams, revisions | Can merge and inspect disjoint modules deterministically |
| P2 Geometry | 4–17 Nov | Floor, wall, doors/windows, roof, triangulation, semantics | Geometric acceptance fixtures pass: real openings and valid surfaces |
| P3 Writer | 10–22 Nov | Deterministic subset BOMC binary writer and independent readers | Two compiles same SHA; Editor/Model-Eval readback PASS |
| P4 Agent | 13–27 Nov | CLI, MCP, context retrieval and construction guide | Agent loop create → inspect → validate → revise → assemble proven |
| P5 E2E | 20 Nov–5 Dec | 3–4-room real building and Editor integration seam | No duplicate shared wall, working doors, compatible BOMC scene |
| P6 Quality | 28 Nov–14 Dec | Agent benchmarks, fuzz/security, optional Rooms interface | Reproducible metrics + errors and explicit feature limitations |
| P7 Release | 10–20 Dec | Release/checklists + future generator integration contract | Proven CI, provenance, owner/native gates explicitly qualified |

Targets overlap *intentionally* when task dependency locks allow. Dates are indicative, not guaranteed delivery.

## Immediate true parallelism

**Now (4 independent P0 tasks)**: BMB-001 (producer spec), BMB-002 (Editor authoring), BMB-003 (license/IP), BMB-004 (MCP/security+baseline). No code from private repos may be transferred without decision. Each is Ready but unclaimed.

**Up Next (3 P0/P1 tasks)**: BMB-005 (compatibility matrix), BMB-006 (module IR), BMB-007 (synthetic fixtures), AFTER 001/002 evidence. Dependencies must genuinely pass before promotions.

**Subsequent waves**: after IR, ID/revision (008) and transform graph (009) can be parallel. After IR+fixtures, floor (013), wall (014), appearances (018) can run parallel. Doors (015) depend on walls, roof (016) on floor+walls; writer subset adapter (019) can progress in parallel with geometry if 005/007 are satisfied. CLI/MCP/context retrieval (022–024) are not gated on Windows SketchUp; E2E (026) depends on geometric and compiled output. Editor extension is another repo's follow-up, not an invisible dependency of core.

## Critical design decisions
- Module granularity **flexible** (whole building / room / wall / face), but module contract and coordinates fixed.
- Compiled BOMC cannot be assembled with a binary append. Merge IR/scene graph then compile with one deterministic writer.
- Active output is BOMC 1.2 declared **authoring subset** pending pinned source/consumer evidence; do not pretend to support every Exact export feature.
- Validation deterministic, agent reasoning for planning; MCP is an adapter and does not solve geometry itself.
- No wait for Sibambo Rooms data; optional enhancement.
- No forced API key or integrated agent in first milestone.
- Separate projects remain untouched: exporter perf and native acceptance unaffected by this plan.
- Public builder currently GPL-3.0; retain until owner/provenance review explicitly approves a change.

## Core success scenario
A prompt requests 2 bedrooms, 1 bathroom, 1 living room, lot dimensions and a simple roof. External agent plans the building, creates modules with typed tools, edits one room without regenerating the others, validates port/adjacency/walls/area, compiles actual BOMC, and independent Editor/Model-Eval readers load it. Benchmark tool calls, context tokens, elapsed, retries, binary size and deterministic SHA; visualize with a separately tracked owner acceptance gate.

See [research](BOMC-RESEARCH.md), [architecture](ARCHITECTURE.md), [agent guide](AGENT-CONSTRUCTION-GUIDE.md), and [32-task index](TASK-INDEX.md) for detailed constraints/acceptance.
