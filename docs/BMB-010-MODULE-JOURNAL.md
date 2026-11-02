# BMB-010 — Module journal with reopen and rollback

Implementation: [`core/storage/journal.py`](../core/storage/journal.py). Tests: [`tests/test_bmb010_journal.py`](../tests/test_bmb010_journal.py). Lock: `core/storage`. Builds on [BMB-008](BMB-008-IDENTITY-REVISIONS.md) (`JournalStore` extends `ModuleStore`, so IDs, revision checks and idempotency behave identically).

## Layout and entries

`<root>/modules/<module-id with "/" as "__">/journal.jsonl`: one small append-only file per module. Module ids already match `[a-z0-9-]` slugs, so names are reversible and cannot traverse paths. Each line is canonical JSON: `create` (revision 0), `commit` (ops, idempotency key, request fingerprint, dependency minimums) or `rollback` (as `commit` plus `rollbackTo`). Every entry carries `prev` and `hash` (SHA-256 chain), no timestamps, so identical operations produce **byte-identical** files.

## Guarantees

- **Atomic commit:** the in-memory edit is validated by `ModuleStore`, then one newline-terminated line is written and fsynced. A revision exists once that line is complete. If the write fails, the module is reloaded from disk, so memory never keeps an uncommitted revision and the idempotency key is not consumed.
- **Torn tail recovery:** a trailing line without a newline (crash mid-write) is dropped and the file truncated on open; an incomplete `create` removes the empty module. Complete lines are never guessed at.
- **Fail-closed integrity:** hash chain, contiguous revisions, exact field sets, matching module id, strict JSON (no NaN/Infinity) and replay through `ModuleStore` validation. Recorded request metadata is verified, not trusted: `mins` must be a valid `{moduleId: minRevision}` object, the request fingerprint is **recomputed** from the module, revision, ops and minimums and must equal the stored one, and a `rollback` entry's `rollbackTo` must be an earlier revision, carry no minimums and its ops must actually restore the blocks of that revision. A hash-consistent but self-contradictory entry raises `CorruptJournalError`. Any violation raises `CorruptJournalError`; the module is not loaded.
- **Independent reload:** `JournalStore.open(root, modules=[...])` reads only the named modules, so one corrupt module does not block others. Idempotency keys and replay survive reopen.
- **Deterministic rollback:** `rollback(module, expected_revision, key, to_revision)` commits a new revision whose ops restore the blocks of `to_revision` (sorted diff). History is kept and revisions only grow; rolling back a rollback works. A repeated key replays, a different request with the same key raises `IdempotencyConflictError`, and rolling back to an identical state is rejected.
- **Second-writer detection:** each append checks that the file size is what this store last saw; otherwise `ConcurrentWriteError` and the module is reloaded. Budgets: 10 000 revisions per module, 64 MiB per entry, 256 MiB per file. The file budget is enforced **before writing** (create included), so a commit that would make the journal larger than `open()` accepts fails with `StorageError` and leaves the file untouched.

## Test evidence

`python -m unittest discover -s tests -p test_bmb010_journal.py -v` (Ubuntu + Windows CI, `.github/workflows/bmb010-journal.yml`): reopen and replay, byte determinism, rejected edits leave bytes unchanged, torn tails at several cut points, injected write failures and partial writes, second writer, tampered/reordered/removed/duplicated/garbage entries, module independence, unsafe ids, rollback (including idempotency, determinism, failures). Review-driven tests re-chain tampered entries so every hash is valid (malformed or mismatched `mins`, foreign fingerprints, bad `rollbackTo`, rollback ops that do not restore the target) and patch the file budget to land exactly on it. The tests were checked to fail when the hash check, concurrent-writer check, failure reload, fingerprint verification or pre-write size check is removed.

## Not covered (NOT_RUN)

- The commit point is `fsync` of the file; durability of the containing directory is best-effort (skipped where unsupported) and power-loss behaviour was not tested.
- The size check is not a lock: two processes can still race inside a single append; the hash chain then detects the damage on the next load. No multi-process locking.
- Journal compaction/snapshots, loading from Module IR JSON, assembly merge (BMB-011), CLI exposure (BMB-022).
