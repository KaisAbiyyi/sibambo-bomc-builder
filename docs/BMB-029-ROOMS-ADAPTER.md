# BMB-029 — Optional Rooms evidence adapter

**Lock:** `integration/rooms`. **Code:** [`integration/rooms/`](../integration/rooms/), schema [`schemas/rooms-evidence-v1.schema.json`](../schemas/rooms-evidence-v1.schema.json), examples [`examples/rooms/`](../examples/rooms/), tests [`tests/test_bmb029_rooms.py`](../tests/test_bmb029_rooms.py), CI `.github/workflows/bmb029-rooms.yml`. Cloud-only, synthetic data, standard library plus the Builder's own packages.

## What it is

A room detector (an external component) looks at a model and says which rooms it sees. This adapter compares that **evidence** with the rooms the Module IR **intends** (its floor slabs) and reports disagreements as typed diagnostics: a room the model has but nobody detected, a detection that is not in the model, two rooms merged into one open space, one room cut in two, a room in the wrong place or of the wrong size.

It is an **enhancement of validation, entirely optional**:

| Property | How it is held |
|---|---|
| **Off by default** | `BMB_ROOMS_ADAPTER` must be set to `1`, `true`, `yes` or `on`; anything else (empty, `0`, a typo) is off. A host can also pass `enabled=True`; only the real boolean `True` turns it on, never a truthy string |
| **Off means no effect** | `validate_with_rooms(...)` returns exactly what `core.validator.validate_assembly` returns, and the evidence is never read, parsed or validated (a test hands it garbage and a 200 000-level nested value, and asserts the evidence validator is not even called). The CLI does not open the evidence file |
| **No core dependency** | no module of `core`, `agent` (the MCP server), `agentctx`, `agentguide`, `bomc`, `cli`, `evaluation`, `tools` or `integration/generator` imports this package (an AST test), and importing all of them in a fresh interpreter never loads it (a subprocess test). The package imports the core, never the other way round |
| **Adds, never rewrites** | when on, the core report is computed first and returned unchanged inside an `EnhancedReport`; room findings sit beside it, never merged into it |
| **No network, no model, no third-party library** | enforced by a test; the environment is read in one place only, `flag.py`, for the one variable above |

## The evidence interface (`rooms-evidence-v1`, **proposed**)

The shape is **defined by this task**, not taken from any real detector; whether a real detector emits it, or needs a thin translator, is for its maintainers (**NOT_RUN**).

```json
{"schemaVersion": "rooms-evidence-v1", "evidenceId": "demo", "detector": {"name": "…", "version": "…"},
 "elevationM": 0.0,
 "rooms": [{"id": "living", "label": "Living room", "polygon": [[0,0],[4,0],[4,3],[0,3]], "confidence": 0.98}]}
```

Coordinates are metres in the **assembly frame** (the same frame the validator uses), polygons are simple and may be concave, winding does not matter. Machine-readable form: the JSON Schema above; the Python validator is authoritative (it also requires every polygon to be simple, by running the core triangulator on it).

| Limit | Value |
|---|---|
| Evidence size | 256 KiB |
| Rooms / vertices per polygon / vertices in total | 64 / 256 / 4 096 |
| Identifiers (`evidenceId`, room `id`) | `[a-z][a-z0-9-]{0,35}`, whole string (`\Z` in the validator, `(?![\s\S])` in the schema: a trailing newline is accepted by neither) |
| Coordinates | finite, within ±10 000 m; booleans and strings are refused |
| Polygon area | at least 0.01 m² |
| `confidence` | 0–1, default 1 |
| `elevationM` | ±1 000 m, default 0 |
| Nesting | a value nested 200 000 levels deep in any field is a typed `EvidenceError`, never a crash |

Every problem is an `EvidenceError` (a `ValueError`). Rooms are normalized to floats and sorted by id, so equal evidence hashes equally and the report does not depend on the order the detector listed rooms.

## Intended rooms

One per **floor slab** of the Module IR, placed with the module's world transform from `core.assembly.assemble`. The compared surface is the slab **top** (`elevation + thickness`); only slabs within `level_tolerance` (0.25 m) of the evidence's `elevationM` take part, so other levels are ignored. A module with several slabs at the level yields `moduleId#opId` rooms. Floors are assumed horizontal: a tilted slab is reported (`INTENDED_UNUSABLE`, warning) and skipped, never guessed at. An assembly that cannot be placed at all (it fails the core merge rules) gives one `ASSEMBLY_INVALID` error instead of a comparison.

## The comparison

Pure and deterministic. Intersection areas are computed exactly enough for concave rooms by triangulating both polygons and clipping triangle pairs (Sutherland–Hodgman); no third-party geometry library.

| Code | Severity | Meaning |
|---|---|---|
| `ROOM_MERGED` | error | one detection covers at least 30 % of each of two or more intended rooms (open plan) |
| `ROOM_SPLIT` | error | one intended room has at least 30 % of its area covered by each of two or more detections |
| `SHAPE_MISMATCH` | error | best match, but overlap (IoU) below `accept_iou` (0.95) |
| `AREA_MISMATCH` | error | overlap fine, areas more than `area_tolerance` (3 %) apart |
| `ROOM_MISSING` | error | an intended room less than 30 % covered by any detection |
| `ROOM_UNEXPECTED` | error | a detection less than 30 % overlapping any intended room |
| `ROOM_UNMATCHED` | error | substantial overlap but no one-to-one match (IoU below 0.5) |
| `ASSEMBLY_INVALID` | error | the assembly cannot be placed |
| `LOW_CONFIDENCE` | warning | detection below `min_confidence` (0.5): ignored, and said so |
| `DETECTED_OVERLAP` | warning | two detections overlap by more than 5 % of the smaller: the detector contradicts itself |
| `INTENDED_UNUSABLE` | warning | an intended floor that could not be compared (tilted or unusable) |

Matching is greedy one-to-one by descending IoU. **Invariant (tested over 80 randomized cases):** every intended room and every usable detection ends up either matched or named by at least one error; nothing is silently dropped. The thresholds are a `Policy` with validated bounds; they are heuristics for synthetic evidence, **not calibrated against any real detector**.

## Using it

```python
from integration.rooms.check import validate_with_rooms
report = validate_with_rooms(assembly["modules"], evidence)          # BMB_ROOMS_ADAPTER=1, or enabled=True
```

Off (or no evidence): a `ValidationReport`, byte-for-byte the core's. On: an `EnhancedReport` with `.core`, `.rooms` and `.ok` (both must be ok). Invalid evidence raises `EvidenceError` only when the adapter is on.

```sh
python -m integration.rooms check --assembly examples/module-ir-two-rooms.json --evidence examples/rooms/evidence-two-rooms.json --enable
python -m unittest discover -s tests -p test_bmb029_rooms.py -v
```

CLI exit status: `0` the adapter is off, or the comparison found no error; `1` an error finding (or a failing core report); `2` input that cannot be read or must not be compared (bad JSON, duplicate keys, NaN, oversize, invalid evidence), reported as `{"verdict": "FAIL", ...}`, never a traceback.

## Limits (explicit)

- The evidence format is proposed here; no real detector was run (NOT_RUN). Thresholds are not calibrated.
- 2D only, one level per comparison; horizontal floors only; no walls, doors or openings are compared (the detector would have to report them, and the interface does not ask for them).
- Matching is greedy, not an optimal assignment; it is explained and deterministic, and the accounting invariant holds regardless.
- Intended rooms come from floor slabs only; a room defined by walls without a slab is not an intended room.

## Status per gate

| Gate | Status |
|---|---|
| Off by default, no effect when off, evidence unread | **PASS** (tests, both OS in CI) |
| No core / MCP / CLI dependency on the adapter | **PASS** (AST and subprocess tests) |
| Evidence validated as hostile input | **PASS** (rules, fuzz, 200 000-level nesting, schema agreement) |
| Typed, complete, deterministic findings | **PASS** (scenarios, accounting invariant, order independence) |
| A real room detector's output | **NOT_RUN** |
| Calibration of the thresholds | **NOT_RUN** |
| Editor / Model-Eval, native Windows security, Notion sync | **NOT_RUN** |
