# BMB-008 — Stable IDs, revisions, idempotency and stale-write detection

Implementation: [`core/identity/store.py`](../core/identity/store.py). Tests: [`tests/test_bmb008_identity.py`](../tests/test_bmb008_identity.py). Lock: `core/identity`.

## Model

A `ModuleStore` holds modules (ids follow the [Module IR](MODULE-IR-V1.md) `moduleId` slug namespace, e.g. `house/living`). Each module has an integer `revision` (starts at 0) and blocks keyed by stable slug ids, never by array position. Writes are batches of `add` / `replace` / `remove` ops.

## Guarantees

- **Stale-write detection:** `apply(module, expected_revision, key, ops)` fails with `StaleRevisionError` if the module is no longer at `expected_revision`. Optional `min_revisions` (a dict, or `None` for omitted; any other type, including falsy `[]`, `False`, `0`, `""`, is rejected) mirrors IR `dependencies[].minRevision` and raises `StaleDependencyError`.
- **No partial mutation:** the batch is validated and applied to a staged copy and committed last; any rejection (stale, duplicate/unknown block, bad payload, budget) leaves blocks, revision and idempotency records untouched, and the key is not consumed.
- **Idempotency:** a repeated key with an identical request (SHA-256 over module, expected revision, ops, minimums) returns the original result with `replayed=True` without mutating, even after later writes. The same key with a different request raises `IdempotencyConflictError`. Keys are scoped per module. A successful batch bumps the revision by exactly one.
- Inputs and snapshots are deep-copied; block data must be plain JSON (no NaN/Infinity), ≤ 64 KiB. Budgets: 1024 modules, 4096 blocks and 4096 idempotency keys per module, 256 ops per batch. Keys are never evicted, so the budget fails closed instead of weakening replay protection.

## Test evidence

`python -m unittest discover -s tests -p test_bmb008_identity.py -v` (Ubuntu + Windows CI, `.github/workflows/bmb008-identity.yml`).

## Not covered (NOT_RUN)

Durable persistence, reopen and rollback (BMB-010), loading from Module IR JSON, assembly merge (BMB-011), and cross-process concurrency: the store is single-threaded in-memory and provides no locking.
