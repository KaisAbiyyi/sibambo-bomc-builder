# BMB-032 — silabs-generator integration handoff contract

**Lock:** `integration/generator`. **Code:** [`integration/generator/`](../integration/generator/), [`schemas/generator-handoff-v1.schema.json`](../schemas/generator-handoff-v1.schema.json), [`examples/generator/`](../examples/generator/), tests [`tests/test_bmb032_generator.py`](../tests/test_bmb032_generator.py), CI `.github/workflows/bmb032-generator.yml`. Cloud-only, synthetic data, standard library plus the Builder's own packages.

## What this is, and what it is not

A **survey**, a **form** or a **room-brief** produced by the generator reaches the Builder through **the same agent builder API** every other agent uses: the stdio MCP tools of [BMB-023](BMB-023-STDIO-MCP.md) (`bmb_create_module`, `bmb_inspect_module`, `bmb_edit_module`, `bmb_validate_journals`, `bmb_validate_assembly`). There is no second entry point, no private back door and no model in the loop: the initial proof is a deterministic function plus those tools. **No paid LLM, no network call and no credential is required**, and the test suite enforces it (the package imports no network or model library and never reads the environment).

This is a **contract and an executable proof of the path**, not a design engine. In particular:

- The three input shapes below are **proposed** by this contract. They were not taken from the generator's own code, so whether the generator emits them as-is or through a thin adapter is for the generator side to confirm (**NOT_RUN** here).
- v1 lays rooms out in **one row along +X** and emits floors and party walls only (details under *Scope of v1*). It demonstrates the API path and the invariants (ownership, revision locality, idempotency), not architectural quality.

## Flow

```
survey-v1 ─┐
form-v1   ─┼─► validate + normalize ─► room-brief-v1 ─┬─► lower ─► Module IR 1.0.0 ─┐
room-brief ┘   (BriefError on reject)                 └─► journal blocks            │
                                                                                   ▼
host-owned private root ◄── stdio MCP: discover → list → create/inspect/edit (CAS) → validate_assembly
```

The host launches `python -m agent.bmb_mcp --root <private dir> --allow-writes`. The generator **never supplies a path**: the root is the host's, exactly as in BMB-023. A brief that fails validation never reaches the server (a test asserts that nothing is created for a rejected brief).

## Input shapes

| Kind | `schemaVersion` | Carries | Becomes |
|---|---|---|---|
| room-brief | `room-brief-v1` | `briefId`, `project`, `floorId`, `depthM`, optional `wallHeightM`, `rooms[]` (`id`, `name`, `kind`, `widthM`), optional `doors[]` (`between`, `widthM`, optional `heightM`, `offsetM`) | canonical form |
| form | `form-v1` | `formId`, `depthM`, optional `project`, `floorId`, `doorWidthM`, `wallHeightM`, `rooms[]` (`name`, `type`, `widthM`) | room-brief via name-derived ids, a door between every neighbouring pair |
| survey | `survey-v1` | `surveyId`, `answers` {`bedrooms` 0–6, `bathrooms` 0–4, `size` `compact`\|`standard`} | room-brief via the fixed table below |

Machine-readable form: [`generator-handoff-v1.schema.json`](../schemas/generator-handoff-v1.schema.json) (Draft 2020-12). The Python validator is authoritative: it adds the rules a schema cannot express (neighbour doors, one door per wall, door fit) and the test suite checks that the schema rejects everything it can express.

**Survey table.** Order is living room, `bedroom-1…n`, `bath-1…m`; every neighbouring pair gets a 0.90 m door.

| `size` | depth | living | bedroom | bath |
|---|---|---|---|---|
| `compact` | 3.0 m | 4.0 m | 3.0 m | 2.0 m |
| `standard` | 3.5 m | 5.0 m | 3.5 m | 2.4 m |

**Form ids.** A room id is the ASCII slug of its name (lower case, runs of other characters become `-`); a name with no ASCII letters falls back to its type, an id that would start with a digit gets a `room-` prefix, and a repeat gets `-2`, `-3`… Names are free text (1–80 printable characters) and are only ever stored as data, never used as an identifier.

**Normalization.** Every number becomes a float, rooms keep row order, a missing door offset is centred, a missing door height is 2.1 m. Equal briefs therefore hash equally (`3` and `3.0` are the same brief). `briefId` is the **stable identity of the design**: resubmit the same `briefId` to revise it.

### Limits (all rejected with `BriefError` before anything else happens)

| Item | Limit |
|---|---|
| Input size | 64 KiB |
| Rooms | 1–12 |
| Identifiers (`briefId`, `project`, `floorId`, room `id`) | `[a-z][a-z0-9-]{0,35}`, whole string, matched with `\Z` in the validator and `(?![\s\S])` in the schema (a trailing newline is not accepted by either) |
| Room width and `depthM` | 1.5–12 m |
| `wallHeightM` | 2.4–4.0 m (default 2.8) |
| Door width / height | 0.81–2.0 m / 1.95 m up to 0.1 m below the wall height |
| Door position | 0.1 m of wall clear at both ends; one door per shared wall; only between neighbours |
| Numbers | finite, not boolean, not strings; a 200 000-level nested value in any field is a typed rejection |

The door minimums are not arbitrary: they are the smallest values the real geometry builder accepts for the 0.15 m wall the lowering emits (0.70 m clear width and 1.90 m clear height after frame and open leaf). The tests probe 0.80 m (refused) and 0.81 m (accepted) against `core.geometry.openings` so the limit cannot drift silently. A "doorway" here is the opening cut in the wall, not the clear width.

## Mapping onto the builder API

For a normalized brief, module ids are `<project>/<floorId>/<roomId>`.

1. **Typed geometry.** `lower(brief)` returns the Module IR 1.0.0 envelope: per room a floor slab, for every room that has a right-hand neighbour a party wall (`east-wall`) owned by the **left** room, a doorway opening cut where a door is declared, reciprocal ports and one owned seam `"<left>-to-<right>"`, and a dependency of each room on its left neighbour. A pair without a door gets a `shared-boundary` port instead of a doorway. The lowering is deterministic and pure; it carries no digest of the whole brief, so a door change alters only the two rooms it joins (tested).
2. **Journal intent.** Each module's journal receives two kinds of block, and only these (the *owned* blocks): `room` (`briefId`, `roomId`, `kind`, `name`, `widthM`, `depthM`, `order`) and, for the room that owns the party wall, `door-east`. Blocks written by anyone else are never compared, replaced or removed (tested).
3. **Calls**, in this order, inspecting every result before building the next request:

| Step | Tool | Notes |
|---|---|---|
| discover | `server/discover`, `tools/list` | requires protocol `2026-07-28` and the five tools; a read-only server is a clear refusal, not a write attempt |
| list | `bmb_validate_journals` | which modules exist |
| observe (reads only) | `bmb_inspect_module` with `includeBlocks` for every existing module of the brief's `project/floor` | **before any write**: if an existing `room` block carries a different `briefId`, the submission is refused as a collision (`BriefCollision`); a module the brief no longer contains is refused (v1 never deletes). A module with no `room` block is adopted and its other blocks are kept |
| per room | `bmb_create_module` (if missing) | writes start only after the observation above passed |
| per room, only if blocks differ | `bmb_edit_module` | `expectedRevision` = the revision just observed, ops = `add`/`replace`/`remove` of owned blocks, `idempotencyKey = "gen-" + digest(module, observed revision, desired blocks)[:32]` |
| validate | `bmb_validate_assembly` | the lowered Module IR as `document` |
| confirm | `bmb_validate_journals`, then `bmb_inspect_module` of every module of the brief | **last step**: the owned blocks read back must equal the brief, otherwise `HandoffConflict` (another writer changed them after our write); the reported revisions are the ones just read back |

**Idempotent and local.** Resubmitting the same brief performs **no write** (9 tool calls for three rooms, all reads and the validation; 12 for the first submission); a revision rewrites only the journals whose owned blocks changed. A concurrent writer is handled by the journal's compare-and-swap: a stale revision is rejected by the server and nothing is half-written. Success means the owned blocks matched the brief **when read back at the end**; no later instant can be promised, so a change after that is for the next submission to find. A different design reusing the same `project/floor/room` ids is a collision, never an overwrite: `briefId` is the identity of a design, so give a second design its own `project` or `floorId`. An owned block that drifted (someone edited `room` by hand) is converged back to the brief, which is authoritative for the blocks it owns.

The submission result is a small evidence object (`created`, `updated`, `unchanged`, `revisions`, `assemblyModules`, `mcpToolCalls`, `briefSha256`, `moduleIrSha256`, `llmRequired: false`, `networkRequired: false`). Errors are `BriefError` (rejected input; `BriefCollision` when another design owns the modules), `HandoffConflict` (a post-write mismatch, a `ControllerError`), `ControllerError` (unexpected server behaviour) or the server's own typed codes (`REVISION_CONFLICT`, `PERMISSION_DENIED`, `INVALID_ARGUMENT`); they are never retried silently.

## Scope of v1 (explicit limits)

- One row of rectangular rooms along +X with one shared depth. No exterior walls, roof, stairs, windows, multi-row or non-rectangular plans.
- **Journal ↔ Module IR:** the MCP surface validates a supplied IR document but does not derive IR from journals (the BMB-025 caveat still holds). The IR is produced by the deterministic lowering in the library; the journal records the intent. A general journal-to-IR adapter is out of scope.
- **BOMC output is not an MCP tool.** The lowered IR also compiles through the existing library compiler, observed at this SHA for **1–5 rooms** with doors; 6 or more is rejected by the BMB-020 writer's single-byte string table (the BMB-026 work-around, face-label reuse, is not on `main`). That is a downstream compiler limit, not a handoff rule: assembly and validation accept all 12.
- Revision by removal (dropping rooms) is refused rather than guessed.

## Commands

```sh
python -m integration.generator lower  --input examples/generator/survey-two-bedroom.json
python -m integration.generator submit --input examples/generator/room-brief-three-room.json --root /absolute/private/project
python -m unittest discover -s tests -p test_bmb032_generator.py -v
```

`lower` prints the Module IR; `submit` runs the whole MCP sequence on a project root (created owner-only if missing) and prints the evidence object. Bad input exits 1 with `{"verdict": "FAIL", ...}`, never a traceback.

## Defects the tests found while building this

Two real ones, both fixed before the first green run: identifiers were matched with `$`, which accepts `"a\n"` (now `\Z`), and the door minimums had been guessed at 0.80 m / 1.80 m although the geometry builder refuses them (now 0.81 m / 1.95 m and pinned to the builder by a test).

Independent review of the first version then found three more, all confirmed and fixed (each with a test that fails without the fix, checked by removing the safeguard): a different `briefId` could silently take over existing module ids; success was reported without reading the owned blocks back after the writes; and the JSON Schema still used `$` (its pattern is now `^[a-z][a-z0-9-]{0,35}(?![\s\S])`, which rejects a final line terminator in Python's regex engine as well as in ECMAScript).

## Status per gate

| Gate | Status |
|---|---|
| Three input kinds → one canonical brief → the same MCP tools | **PASS** (tests, both OS in CI) |
| No paid LLM, no network, no credential | **PASS** (static test + the flow runs without them) |
| Idempotent resubmission, localized revision, foreign blocks untouched | **PASS** |
| Hostile input rejected before the server | **PASS** |
| BOMC compile of the lowered output | **PASS for 1–5 rooms**, rejected above by a compiler limit |
| Generator-side adoption of these shapes | **NOT_RUN** (needs the generator's maintainers) |
| Live LLM agent driving the same tools | **NOT_RUN** |
| Editor / Model-Eval import, native Windows security, Notion sync | **NOT_RUN** |
