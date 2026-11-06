# BMB-030 — Fuzz, limits and adversarial QA

Lock `qa/security`. Code: [`tests/qa/harness.py`](../tests/qa/harness.py), tests: [`tests/test_bmb030_adversarial.py`](../tests/test_bmb030_adversarial.py), CI: `.github/workflows/bmb030-adversarial.yml` (Ubuntu + Windows, exact-head checkout with SHA assertion, actions pinned to commit SHAs). Cloud-only, synthetic data, stdlib plus the already pinned `jsonschema`.

## Method

Everything is **seeded and deterministic** (`BMB_FUZZ_ITERS`, default 400 per target; the workflow can raise it). A structure-aware mutator edits a valid document at a random path (junk values including 10^400, NaN, surrogates, 100 kB strings, non-JSON types, nesting 50–5000 deep, deleted/duplicated/swapped/extended members). A target passes when every hostile input either succeeds or raises **its documented typed error** (a `ValueError` subclass; `StorageError` / `SessionError` for the file layers; `Rejected` / `InvalidBomc` for the BOMC readers), inside a wall-clock budget, and, in the explicit resource tests, a tracemalloc peak budget. `TypeError`, `KeyError`, `AttributeError`, `OverflowError`, `RecursionError`, `MemoryError`, a hang or a generic `INTERNAL_ERROR` all count as defects.

## Coverage against the acceptance list

| Requirement | What is exercised |
|---|---|
| **Bad indices** | boundary values (0, 1, 0x7F…0xFF, 0x100, 0xFFFF, 0x10000, 0x7FFFFFFF, 0xFFFFFFFF) written over every fixed-width field of sections 5, 6, 8, 11, 12, 13 with CRCs repaired, plus 3 × N random edits; the Builder reader and the container inspector must reject or yield a different valid model, never crash |
| **CRC** | byte damage inside every section without CRC repair, at ~40 offsets per section; random byte, directory-field and header damage |
| **Compression bombs** | deflate sections of 1, 64 and 512 MiB of zeros with honest, understated and 0xFFFFFFFF declared sizes; truncated, corrupt, trailing and garbage zlib streams; rejected without inflating (peak allocation ≤ 8 MiB, ≤ 3 s) |
| **Path traversal** | 36 hostile identifiers (`../`, backslash, absolute and UNC, drive letters, NUL, trailing newline/dot/space, ADS `:`, full-width slash, bidi override, lone surrogate, `%2e%2e`, 5 000 characters, Windows device names…) against journal module/key/block ids, rollback, snapshot, context provider ids and cursors, session ids, graph and assembly ids, CLI arguments and MCP tool arguments; nothing may be created outside the project root |
| **Deep DAG** | a dependency chain as deep as the 1 024-module cap in both traversal orders, a cycle at the end of it, parent chains of 31/32/33/1 024 in both orders, a 256-deep definition chain, a 65 536-instance fan-out (typed budget error, bounded time and memory), every cycle shape in the definition graph |
| **Resource limits** | per-case time budgets on every fuzz loop; size/entry/line limits of journals; MCP frame and response caps (oversize frame closes the stream, 100 kB-deep JSON, garbage bytes, a near-limit echoed version string); CLI never answers `INTERNAL_ERROR` |

Targets fuzzed with the generic mutator: `assemble`, `validate_assembly`, `compile_document`, face-semantics validation and byte decoding, floor, wall, opening, roof, ceiling, stair and triangulation builders, the writer graph encoder, the definition-graph API, journal and session files (byte damage, truncation, re-chained structural edits, deep nesting), the BOMC readers, the MCP stdio loop (tool execution stubbed so every frame is exercised) and the CLI.

## Defects found and fixed (each reproduced red before the fix)

1. `core/geometry/semantics.py`: `_check_finite` recursed on untrusted nesting, so `compile_document` / `validate_module_faces` raised `RecursionError`; `decode_authored_module` let `json.loads` recursion escape. Now iterative with a depth (64) and size (2 000 000 nodes) budget and a typed `SemanticFaceError`.
2. `core/geometry/wall.py` (shared by openings): `_number` called `math.isfinite` on a huge integer → `OverflowError`. Magnitude is now compared first.
3. `core/storage/journal.py`: a deeply nested journal line made `JournalStore.open` raise `RecursionError`; it is now a `CorruptJournalError`.
4. `agentctx/session.py`: the same for `SessionStore.open` (→ `SessionError`); and session ids that are Windows device names (`con`, `nul`, `aux`, `prn`, `com1`–`com9`, `lpt1`–`lpt9`) were accepted although `con.jsonl` opens the console on Windows. They are refused.
5. `core/graph/dag.py`: unhashable arguments (list, dict) to `add_instance` / `set_transform` / `remove_instance` / `instances` / `world_transforms` raised `TypeError`; they are now `GraphError`.
6. `core/assembly/merge.py`: the dependency topological sort recursed, so a dependency chain of 1 024 modules (the cap) in the unlucky order raised `RecursionError` from `assemble` and `validate_assembly`. Now an iterative post-order DFS with the same order and cycle message.
7. `core/assembly/merge.py`: acceptance of deeply nested junk in fields the merge does not read depended on the interpreter's recursion limit (1 500 levels were accepted, 30 000 rejected). `assemble` now enforces an explicit, iterative nesting budget (64 levels; the real schema needs about 6).
8. `bomc/compiler/graph_to_bomc.py`: the bounds check called `math.isfinite` before the magnitude test, so a huge integer bound raised `OverflowError` from `compile_document`. Magnitude is compared first.
9. **Rejection messages built from hostile values** (found by the first hosted Windows run, not by the Linux runs): `f"invalid id {value!r}"` is evaluated *before* the check it reports on, so a deeply nested value made `repr`/`str` itself raise `RecursionError`, at a depth that depends on the platform's C stack (5 000-deep fuzz values passed on Linux CI and failed on Windows CI in `build_floor_slab`; 20 000 fail on a local Python 3.13). About 50 sites in `core/geometry/floor.py`, `core/graph/dag.py`, `core/identity/store.py`, `core/storage/journal.py`, `core/assembly/merge.py`, `agentctx/retrieval.py`, `agentctx/session.py`, `bomc/compiler/graph_to_bomc.py` and `cli/bmb.py` now render the value through `core.textsafe.show`: scalars exactly as `repr` (strings cut at 64 characters), everything else as its type name. Messages for ordinary short ids are unchanged.
10. `core/identity/store.py`, `core/storage/journal.py`: an unhashable `module_id` (list, dict) reached `module_id in self._rev` (`revision`, `snapshot`, `rollback`, `apply`, `recover`) and the `{module_id} | deps` set in `_refuse_uncertain`, raising `TypeError`. A `_known()` helper accepts only strings; the others are an `IdentityError`.

`ErrorMessageTests` pins 9 and 10 independently of the platform with 200 000-level values (red before the fix: `RecursionError` at four entry points, then the two `TypeError` points; green after).

Reverting any one of these files makes its regression tests fail again (24 + 1 + 1, 13, 1, 11, 1, 12, 1 failing tests for semantics, wall, journal, session, graph, assembly and compiler respectively). No other behaviour was changed. The reviewed BOMC readers, the MCP adapter, the CLI and the context layer produced no defect under the fuzzers other than the items above. Item 9 is a reminder that a green Linux run is not Windows evidence: the platform-dependent depth was only exposed by hosted Windows CI.

## Not covered (NOT_RUN)

Native Windows ACL/DACL and Job Object enforcement; hostile co-tenant and symlink/junction/TOCTOU races (only static symlink rejection is exercised); power loss and physical crash/cancel recovery; the original Editor E4 / Model-Eval consumers and section 241 behaviour there; external MCP hosts beyond the pinned SDK smoke in BMB-023; coverage-guided fuzzing (the mutator is seeded and structure-aware, not instrumented); provider-native resource accounting; Notion sync. The Windows POSIX-only tests are skipped, which is not Windows evidence.
