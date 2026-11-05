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
- **Writes** go through `session.create_module / apply / rollback(store, …)` and are **write-ahead**: the full request is recorded and fsynced as an `intent` entry *before* the journal is called, with room for its outcome reserved up front (entries and bytes), and the `outcome` (`applied` with revision and journal hash, `noop` for an idempotent retry, `rejected` for validation and stale-write errors) is recorded right after. So a full or broken session refuses the write **before** the journal changes. If the outcome cannot be recorded (I/O error) or the journal call fails in a way that leaves the result unknown (storage or durability error), the intent stays open: `pending()` lists it, writes are refused, and after reopening the session `reconcile(store)` decides from the journal itself — `applied` (the journal holds exactly this request under this key and revision, which then becomes a normal recorded step), `abandoned` (nothing in the journal, never replayed) or `conflict` (a different request under the same key, reported and never replayed). Requests over 96 KiB are refused before anything is recorded.
- **`checkpoint(provider, label)`** stores every module's `(revision, journal hash)` and the project digest.
- **`resume(provider)`** compares the last checkpoint with the live journal. An unchanged project returns a tiny `current` report. Otherwise: `advanced` (newer revision and the checkpointed hash is still in its history), `diverged` (a different history at the checkpointed revision, or an older one), `missing`, `new`, an `unchanged` count, and `changed`, the ids worth re-reading with `module(...)`. Lists are capped at 50 with explicit omitted counts.
- **`replay_into(store, require_final_state=False)`** re-runs the recorded writes in order against another store and **always verifies the history**: each write must end with the recorded revision and the recorded journal hash at that revision (a freshly applied write against the target's newest hash, an already present write against the target's journal entry at that revision; nothing is skipped). A divergence raises `ReplayDivergence`; a forged recording with valid hashes is caught because the replayed hash differs. Replay does **not** by default prove the target's final state equals the recording, because later revisions are legitimate; the report states it (`historyVerified`, `finalStateMatches`, `extraRevisions`) and `require_final_state=True` turns any extra revision into a divergence. Into an empty root it reproduces the journal files byte for byte.

### File permissions

The session directory is created `0o700` and session files `0o600` (also under a permissive umask), because a session holds full write requests including block data. On open and create (POSIX) the directory and file must be plain (no symlinks), owned by the current user, and group/other access is removed if present; appends use `O_NOFOLLOW` so a link swapped in under an open handle is refused. Windows ACLs are **not** validated (inherited from the project root; NOT_RUN). The project root's own permissions remain the host's responsibility (BMB-023).

## Trust and limits

Sessions are bookkeeping, not authentication: the hash chain detects accidental damage and edits that were not re-chained, not a writer with file access. The project root and session binding are chosen by the trusted host (BMB-023), never by the model. Neighbour geometry is the module bounds box (as in BMB-012), not mesh geometry. `ContextProvider` reads the journal store's block counts and its verified journal files directly (`store._blocks`, `modules/<id>/journal.jsonl`); it never writes them.

## Test evidence

`python -m unittest discover -s tests -p test_bmb024_context.py -v` — 50 tests: manifest paging and tight budgets, module context (neighbours, depth, dependencies, scoped diagnostics, block data bounds, no-assembly mode, determinism, read-only), every budget from 8000 to 200 respected with prefix-preserving cuts, token evidence, session file integrity and failure modes, cumulative cap, checkpoint and resume (current, advanced, new, rolled back, diverged, longer-but-different history, missing, cold process), write-ahead recording (full and broken sessions refuse before the journal changes, an unrecorded outcome recovered by `reconcile`, abandoned and conflicting intents, uncertain-durability writes, rejected and idempotent calls), replay (byte-identical, history verified into the original with extra revisions reported, forged), and POSIX permissions (modes, umask 0, tightening, symlinks). Removing the outcome reserve, the abandoned/conflict decision, the replay hash check, the 0o600 mode or `O_NOFOLLOW` makes tests fail.

## Not covered (NOT_RUN)

Provider-native token measurements and a live agent run (BMB-025/028); exposure as CLI commands or MCP tools (BMB-022/023 own the transports, path containment and rate limits); session authentication, multi-process locking and Windows ACL validation; mesh-level neighbour geometry; a typed mapping from journal blocks to Module IR (still the gap noted in BMB-022); Notion sync.
