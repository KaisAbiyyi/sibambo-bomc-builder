# BMB-004 — Scripted agent baseline benchmark v0

**Artifact:** [synthetic test vector](../benchmarks/agent-baseline-v0.json). **Scope:** define repeatable benchmark inputs, prescribed recovery, evidence schema and comparison method. **Not a measured run:** MCP/CLI/Core/BOMC implementation is pending BMB-006/008/022/023/025/026/028.

## 1. Baseline prompt (fixed text)

> Design a simple one-storey house within a 10 m × 14 m site, with a total enclosed footprint no greater than 85 m². Include one living room at least 16 m², two bedrooms each at least 9 m², and one bathroom at least 4 m². The main entry faces south; each bedroom is connected to the living room through an accessible circulation path and every specified doorway must be an actual wall cutout at least 0.80 m clear width. Use one floor slab, 0.15 m nominal wall thickness, 2.8 m nominal wall height, and one simple roof. The coordinate system is metres, right-handed, +Z up, north at +Y. Give shared walls exactly one owning module. Build from named modules, validate, revise the living-room doorway from 0.90 m to 0.95 m without rewriting unrelated modules, then compile one deterministic BOMC 1.2 file. Return manifest/revisions, validation failures and recoveries, compiled SHA256, independent Editor and Model-Eval import results, and per-run token/tool/time/memory statistics. If a tool or evidence is unavailable, report NOT_RUN; do not invent success.

This prompt is a **synthetic design request**, not proof of engineering, code compliance, consumer compatibility or geometric feasibility until validated by implemented code. Never publish user/customer floor plans as public benchmark fixtures.

## 2. Reproducible scenario

The JSON script is the normative sequence of **logical phases**, NOT a claim that one \`module_create\` call creates every room. Repeat the named typed operation per module under separate mutation receipts; real tool-call counts must be measured. A real agent may add bounded inspection/retry calls but must preserve the invariants. Suggested phases:

1. Discover supported versions/capabilities and read project metadata/budget (no assumption that MCP's 2026 protocol has session initialization).
2. Create project with fixed brief hash and `idempotency_key`. Repeat same request with same key: state must not duplicate.
3. Create four rooms and necessary wall/floor/roof modules with stable IDs; share wall ownership rather than copying overlapping walls.
4. Inspect living module and neighbors via small scoped responses, checking bounds, ports, revision, not full-site mesh dumps.
5. Validate graph and physical geometry. Inject one **intentional** stale-revision patch; reject it without changing geometry. Retry with exact current revision and new idempotency key.
6. Revise living room door clearance from 0.90 m to 0.95 m, preserving the IDs and content hashes of unrelated modules. Replay identical patch key and confirm no second write.
7. Revalidate, compile canonical BOMC output twice from **cold independent processes** with identical compiler/fixture hashes; compare byte SHA and CRC/section bounds.
8. Import/read the generated file in pinned Editor and Model-Eval consumers. Never substitute self-parser results for independent consumer proof.

Schema fixture stores `expected`/intent, not actual results. Intentional expected conflicts are **success cases for rejection**, not system failures. All operations are conceptual until BMB-022+023 freeze method names and payload schemas.

## 3. Measurement protocol

- Pin fixture SHA256, exact Builder/CLI/MCP/consumer commit SHAs, BOMC format/version and supported feature profile, OS/CPU/RAM, invocation transport, model/controller build, temperature/seed if controllable, network policy, timeout, permitted retries and token counting method.
- Run **three independent cold trials** per agent/controller configuration with fresh project directories. A cold trial resets durable journal/output and restarts the server; do not reuse a hot process/cache unless separately labeled.
- Capture monotonic elapsed time from first tool request to final verified consumer result; per-tool latency/argument and response bytes; input/output tokens (native provider usage if available; otherwise count as `null` and record estimator); retry count; invalid/stale requests; recovery rate; peak RSS, disk high-water, generated BOMC bytes and SHA256.
- Record geometry acceptance separately: room counts and floor areas in m², openings and connectivity, shared-wall ownership, bounding-box overlaps (m³/m), revision locality (unchanged module IDs/content hashes), reference integrity, BOMC CRC and binary readback parity.
- For **success**, all mandatory design constraints, mutation locality, two cold same-SHA compiles and both consumer readbacks must pass; `NOT_RUN` for any mandatory check makes the overall result `INCOMPLETE`, never PASS.
- Summarize per-trial raw values and median/P95 of numeric metrics across trials; with three runs, P95 is descriptive only, not a statistical performance guarantee. Failed or timed-out trials must remain in the denominator. Record timeouts separately from validation rejections.
- Include explicit `PASS`, `FAIL`, `NOT_RUN` per gate, raw evidence links/log hash, and a short cause for any failure. No prefabricated fake metrics.

Suggested result envelope (values are intentionally null before a run):

```json
{
  "fixture_id": "bmb004-agent-baseline-v0",
  "implementation_sha": null,
  "controller": null,
  "trial_id": null,
  "metrics": {"wall_time_ms": null, "tool_calls": null, "input_tokens": null, "output_tokens": null, "peak_rss_bytes": null, "bomc_bytes": null},
  "gates": {"security": "NOT_RUN", "geometry": "NOT_RUN", "revision_locality": "NOT_RUN", "determinism": "NOT_RUN", "editor_import": "NOT_RUN", "model_eval_import": "NOT_RUN"},
  "overall": "INCOMPLETE"
}
```

## 4. Acceptance test map and implementation handoff

| Gate | Measurement / invariant | Owned by |
|---|---|---|
| G-01 | Fixture parses, all scripted step IDs unique, no raw shell/path requests, valid expected outcomes | BMB-004 (design lint) |
| G-02 | Frame/schema/permissions/path containment/limits and replay negatives rejected without side effects | BMB-023, BMB-030 |
| G-03 | 4 named rooms, area/footprint bounds, real doorway cuts and traversable circulation | BMB-012–018, BMB-026 |
| G-04 | Revision CAS and idempotent replay; non-target hashes unchanged | BMB-008, BMB-010, BMB-026 |
| G-05 | Two isolated cold compiles byte-identical, BOMC 1.2 subset/CRC valid | BMB-019–021 |
| G-06 | Independent Editor and Model-Eval import and semantically matching structure | BMB-021 |
| G-07 | Measured time, token, call, retry, RSS, disk and sizes for 3 cold runs with reproducible logs | BMB-025, BMB-028 |

**P0 exit criterion:** freeze a reviewable security contract + reproducible synthetic scripted vector and validator. Runtime tests and measurements are `NOT_RUN`. Do not conflate future target limits with observed performance.

Related: [MCP threat model](MCP-THREAT-MODEL.md), [conceptual agent guide](AGENT-CONSTRUCTION-GUIDE.md), [project WBS](TASK-INDEX.md).
