# BMB-024 — Scoped context retrieval and resumable sessions

Lock `agent/context`. Code: [`agentctx/`](../agentctx/) (`budget.py`, `retrieval.py`, `session.py`, `evidence.py`; stdlib only). Tests: [`tests/test_bmb024_context.py`](../tests/test_bmb024_context.py). CI: `.github/workflows/bmb024-context.yml` (Ubuntu + Windows). It is a library over the existing core (BMB-008 identity, BMB-010 journal, BMB-011 assembly, BMB-012 validator); it changes none of them and adds no CLI command or MCP tool (BMB-022/023 own those and can wrap it).

## Scoped reads (`ContextProvider`)

Built on a `JournalStore` and, optionally, a BMB-011 `Assembly` of the same module ids. Every response is deterministic, read-only, hash-stamped and cut to a hard token budget.

- **`manifest(cursor, page_size, max_tokens)`** — a page of `{id, rev, blocks, hash}` rows, a project digest and totals. Never block contents. `page.next` continues, `page.omitted` counts what the page left out.
- **`module(id, depth, blocks, max_tokens)`** — the focus module's revision, hash, block index and (only when asked, at most 16 ids, ≤ 2 KiB each) block data; dependency edges with `satisfied` against the live revision; dependents; BMB-012 diagnostics scoped to this module (as subject or related); and neighbours up to `depth` ≤ 2 through shared seams, each with revision, world-space AABB, seam owner and ports. Unrelated modules never appear. Without an assembly only journal facts are returned and the response says so.
- **Budget:** `max_tokens` is 200–8000 (default 1500). Sections are filled in priority order — dependencies, dependents, diagnostics, neighbours, block index, block data — each in stable order until the next item does not fit; whatever is dropped is counted in `omitted`, and a final pass trims the least important items until the stamped size fits. A budget too small for even the header is `BUDGET_TOO_SMALL`, never an overrun.
- **Estimator:** `ceil(len(canonical-json-utf8) / 4)`. This is a documented estimate, **not a provider-native token count**; provider usage is `null` in all evidence.

### Evidence (estimator; synthetic scenes; `python -m agentctx.evidence`)

| modules in scene | dump everything | manifest page | one module + neighbours | dump ÷ scoped |
|---|---|---|---|---|
| 3 | 972 | 121 | 321 | 3.0× |
| 30 | 6 635 | 488 | 321 | 20.7× |
| 300 | 63 267 | 489 | 321 | 197× |

The scoped cost is constant in the size of the scene; a dump grows linearly. The test asserts the constant and a > 50× reduction at 120 modules. CI repeats the measurement on both OSes and writes it to the job summary.

## Sessions (`SessionStore`, `Session`)

One append-only JSON-lines file per session, `<root>/sessions/<id>.jsonl` (outside `modules/`, so the journal loader ignores it), hash-chained, no timestamps, entries ≤ 128 KiB, file ≤ 4 MiB, ≤ 10 000 entries, ids `[a-z][a-z0-9-]{0,63}`. A torn final line is dropped on open; any other damage (flipped byte, dropped or reordered line, duplicate keys, NaN, bad sequence) raises `SessionError`. A second writer, or a write whose outcome is unknown (failed fsync), puts the handle into a broken state that refuses further writes until reopened.

- **Reads** go through `session.manifest(provider, …)` / `session.module(provider, id, …)`. The session has a cumulative token cap (default 50 000): each request is shrunk to what is left, and when less than the minimum remains `SessionBudgetExceeded` is raised **before** a response is delivered. Each read is recorded as tool, request, response digest and token cost.
- **Writes** go through `session.create_module / apply / rollback(store, …)`, which call the journal and then record the full request and the resulting revision and journal hash. Failed calls and idempotent retries change nothing and are not logged. Requests over 96 KiB are refused before the journal is touched.
- **`checkpoint(provider, label)`** stores every module's `(revision, journal hash)` and the project digest.
- **`resume(provider)`** compares the last checkpoint with the live journal. An unchanged project returns a tiny `current` report. Otherwise: `advanced` (newer revision and the checkpointed hash is still in its history), `diverged` (a different history at the checkpointed revision, or an older one), `missing`, `new`, an `unchanged` count, and `changed`, the ids worth re-reading with `module(...)`. Lists are capped at 50 with explicit omitted counts.
- **`replay_into(store)`** re-runs the recorded writes in order against another store and requires each result's revision and journal hash to match the recording (`ReplayDivergence` otherwise). Into an empty root it reproduces the journal files byte for byte; into the original it is a verified no-op. A forged recording with valid hashes is caught because the replayed journal hash differs.

## Trust and limits

Sessions are bookkeeping, not authentication: the hash chain detects accidental damage and edits that were not re-chained, not a writer with file access. The project root and session binding are chosen by the trusted host (BMB-023), never by the model. Neighbour geometry is the module bounds box (as in BMB-012), not mesh geometry. `ContextProvider` reads the journal store's block counts and its verified journal files directly (`store._blocks`, `modules/<id>/journal.jsonl`); it never writes them.

## Test evidence

`python -m unittest discover -s tests -p test_bmb024_context.py -v` — 37 tests: manifest paging and tight budgets, module context (neighbours, depth, dependencies, scoped diagnostics, block data bounds, no-assembly mode, determinism, read-only), every budget from 8000 to 200 respected with prefix-preserving cuts, token evidence, session file integrity and failure modes, cumulative cap, checkpoint and resume (current, advanced, new, rolled back, diverged, longer-but-different history, missing, cold process), recorded writes and replay (byte-identical, no-op, forged). Removing the cap check, the replay comparisons or the history-hash check makes tests fail.

## Not covered (NOT_RUN)

Provider-native token measurements and a live agent run (BMB-025/028); exposure as CLI commands or MCP tools (BMB-022/023 own the transports, path containment and rate limits); session authentication and multi-process locking; mesh-level neighbour geometry; a typed mapping from journal blocks to Module IR (still the gap noted in BMB-022); Notion sync.
