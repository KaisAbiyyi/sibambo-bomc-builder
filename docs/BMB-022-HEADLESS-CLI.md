# BMB-022 — Headless CLI

Implementation: cli/bmb.py. Tests: tests/test_bmb022_cli.py. CI: .github/workflows/bmb022-cli.yml. Exclusive resource lock: agent/cli. Stdlib Python 3.12 only.

## Commands

Run at the repository root. For persistent commands, pass an absolute project root explicitly; never implicitly write into the current directory. Output: one machine-readable JSON line per invocation, with ok, command, and result or error. Keys in the error object are code and message. Exit 0 means success, 2 invalid input or semantic validation, 3 revision/dependency/idempotency conflict, 4 journal/storage/I/O, 1 internal failure.

For example, on Linux:

    python -m cli.bmb --root /tmp/demo create --module-id house/living
    python -m cli.bmb --root /tmp/demo inspect --module-id house/living
    printf '{"ops":[{"op":"add","id":"wall-a","data":{"height":2.5}}]}' | python -m cli.bmb --root /tmp/demo edit --module-id house/living --expected-revision 0 --key request-1
    python -m cli.bmb --root /tmp/demo inspect --module-id house/living --blocks
    python -m cli.bmb --root /tmp/demo validate
    python -m cli.bmb --root /tmp/demo rollback --module-id house/living --expected-revision 1 --key undo-1 --to-revision 0
    python -m cli.bmb validate --assembly-stdin < examples/module-ir-two-rooms.json

Use an absolute Windows project path in place of /tmp/demo when running on Windows.

- create: creates an empty durable module via JournalStore.create_module; rejects duplicate and unsafe IDs.
- inspect: loads only the chosen journal via JournalStore.open(modules=[id]); returns revision, journal hash, block count and IDs. Add --blocks for a full bounded payload.
- edit: reads a single JSON object from stdin. Required key ops is a list of {op,id,data} changes; optional minRevisions maps dependency module IDs to required revisions. Only the existing JournalStore.apply mutates state, with CAS, atomic batch and idempotency.
- rollback: invokes JournalStore.rollback with the target historical revision; commits a compensating new revision and preserves history.
- validate: defaults to loading all journals, with --module-id optionally scoping validation to a single journal. With --assembly-stdin and no root it validates an envelope containing {"modules":[...]} plus optional {"schemaVersion":"1.0.0"} (the published BMB-006 example uses the versioned form) via core.assembly.assemble, returning module IDs, topological order and seam ownership.
- All commands have stable JSON error codes. Input/output limits are 1 MiB; error messages are additionally truncated to 512 characters so oversized arguments cannot amplify JSON output. Invalid UTF-8, duplicate JSON fields and non-finite constants are rejected.

## Stable error codes

INVALID_ARGUMENT, INVALID_OPERATION, INVALID_ASSEMBLY, STALE_REVISION, STALE_DEPENDENCY, IDEMPOTENCY_CONFLICT, CORRUPT_JOURNAL, CONCURRENT_WRITE, DURABILITY_UNCERTAIN, STORAGE_ERROR, IO_ERROR and INTERNAL_ERROR. Programmatic clients should use code rather than parsing human message strings.

The persistent journal stores stable block dictionaries. A Module IR envelope has separately typed operations, ports and seams. This CLI does NOT fabricate a mapping between arbitrary journal blocks and typed Module IR. Assembly validation is intentionally a distinct input mode using the existing shared assembly core. Reconciliation/typed persistence belongs to a later core adapter.

## Scope boundaries

Journal integrity and assembly graph validation are real BMB-010/011 core checks, not independent CLI reimplementations. Assembly validation does not check geometry intersections/collisions, legal construction, compiled BOMC bytes, real consumer import or visual rendering (BMB-012/020/021). The BMB-011 port-frame convention remains provisional. BMB-023 separately owns untrusted agent root containment, MCP tools and request budgets. The direct CLI runs on an owner-selected root and should not be exposed to arbitrary remote traffic without a trusted sandbox. The journal is not a multi-process lock; use one writer per module. The durability-uncertain state requires trusted recovery and must never be retried as if committed.

## Test and evidence expectations

    python -m unittest discover -s tests -p test_bmb022_cli.py -v

The GitHub Actions matrix runs Linux and Windows subprocess tests plus BMB-008 identity, BMB-010 journal and BMB-011 assembly regressions. Tests cover persistence, replay, stale revision/dependency, rollback, bounded inputs, corrupt journal refusal and real assembly graph acceptance from a synthetic example. Record exact PR HEAD and actual CI run before claiming PASS. Sudden power loss, simultaneous independent writers, real BOMC compilation/consumer ingestion and physical owner Windows tests remain NOT_RUN.
