# BMB-028 — Measured agent workflow benchmarks

**Lock:** `evaluation/metrics`. **Code:** [`evaluation/`](../evaluation/) (`metrics.py`, `probe.py`, `trial.py`, `run.py`), schema [`schemas/benchmark-result-v1.schema.json`](../schemas/benchmark-result-v1.schema.json), tests [`tests/test_bmb028_benchmarks.py`](../tests/test_bmb028_benchmarks.py), CI `.github/workflows/bmb028-benchmarks.yml`. Cloud-only, synthetic data, standard library only (no `psutil`, no network, no model).

It implements the measurement protocol that [BMB-004](AGENT-BASELINE-BENCHMARK.md) defined and left `NOT_RUN`: token count, calls, retries, elapsed time, memory, model size and geometric acceptance, for a workflow that runs against the **real** stdio MCP server and the **real** BOMC compiler.

## What is measured

The scenario is the BMB-025 scripted workflow (`examples/bmb025-prompts.json`: two modules, a stale edit that must be rejected, a localized doorway revision, an idempotent replay, unsafe-input and read-only denials, scoped context and checkpoint/resume) followed by compiling the bundled two-room Module IR (`examples/module-ir-two-rooms.json`) to BOMC 1.2 in two cold processes. **It is not the BMB-004 four-room baseline**: that needs the BMB-026 house, whose code is not on `main`, so `baselineStatus` is `NOT_RUN` and says why.

| Metric | Source | Kind |
|---|---|---|
| `requests`, `toolCalls`, `rejectedToolCalls`, `rejectionCodes` | an observer on the real MCP transport (see below) | deterministic |
| `retries` | a call repeated for the same tool and module after a *recoverable* rejection (`REVISION_CONFLICT`) that then succeeded; denied or invalid requests are never "retries" | deterministic |
| `estimatedInputTokens` / `estimatedOutputTokens` | what the model would **read** (responses) / **write** (requests), by the documented provider-independent estimator `ceil(len(canonical-json-utf8)/4)` | deterministic |
| `providerTokens` | **null**: no live model was used, so provider-native usage does not exist | — |
| `requestBytes`, `responseBytes`, `mcpBatches` | the wire | deterministic |
| `elapsedMs`, `mcpProcessMs`, `slowestBatchMs` | monotonic clock; one MCP process runs per batch, so latency is measured per batch, not guessed per request | descriptive |
| `driverPeakPythonBytes` | `tracemalloc` peak of the driving process | descriptive |
| `childPeakRssBytes` | largest MCP server or tool worker, POSIX `RUSAGE_CHILDREN`; **null on Windows** because the standard library has no such API, and the note says so | descriptive |
| `model.bomcBytes`, `sha256`, `sections`, `faceCount`, `triangleCount`, `vertexCount`, `meshCount`, `nodeCount`, `floorAreaM2` | the compiled file and its receipt | deterministic |
| `model.coldCompiles[].peakRssBytes`, `wallMs`, `compileMs` | each cold compile process measures itself (`resource` on POSIX, `GetProcessMemoryInfo` on Windows) | descriptive |

**The observer only watches.** It wraps `subprocess.run` for the duration of the run, passes the command, input and result through untouched, records the JSON-RPC exchanges of `agent.bmb_mcp` and restores the original even when the run raises (tested). The observer's tool-call count is **cross-checked at run time against the controller's own count**; if they disagree the trial fails, because then one of them is wrong and no metric from the run can be trusted.

### Geometric acceptance

Every check is `PASS`, `FAIL` or `NOT_RUN`:

| Check | What it compares |
|---|---|
| `assembly_validator` | the BMB-012 validator accepts the assembly |
| `floor_area_two_calculations_agree` | `build_floor_slab(...).area` from the real geometry core vs an independent shoelace sum of the footprints (18.0 m² here) |
| `independent_readback` | the Builder's strict reader (`tests/interop/reader.py`, written independently of the compiler) accepts the bytes: CRC, directory, geometry |
| `faces_`, `triangles_`, `nodes_`, `meshes_`, `vertices_`, `materials_`, `strings_`, `sections_match_receipt`, `size_matches_receipt` | every count and the size the result reports about the model, decoded by the reader and compared with what the compiler claims (none is merely copied from the receipt) |
| `world_bounds` | the decoded bounds vs the union of the IR's module bounds under their translations (6 x 3 x 2.8 m) |
| `geometry_semantics_valid_per_compiler` | the compiler's own semantic receipt |
| `revision_locality_and_replay` | stale edit rejected, the untouched module's journal hash unchanged, replay idempotent |

The reader is a **Builder-side** decoder, not an original consumer; `editor_import` and `model_eval_import` stay `NOT_RUN`. Mutation testing of the file is part of the evidence: flipping **every single byte** of the compiled two-room file is refused by the reader everywhere except the 49 bytes of alignment padding between sections, which no CRC covers (so the SHA-256 over the whole file, not a section CRC, is what the determinism gate relies on).

## Protocol (from BMB-004)

- **Cold trials.** Each trial is a fresh interpreter (`python -m evaluation.trial`) with a new private project directory; the compile runs in two further fresh interpreters. Nothing is reused. Default **three** trials.
- **Deterministic vs descriptive.** Deterministic quantities must be **identical in every trial**, and so must the pins (fixture, assembly, compiler sources, golden, commit, fixture id, controller): trials that ran different inputs are not repeats even if their numbers coincide; `deterministic.identical` in the summary records whether they were, and a difference fails the run. Descriptive quantities (time, memory) are summarized as min / median / nearest-rank P95 / max. With three trials a P95 is the maximum and is **descriptive, not a guarantee**.
- **Failed trials stay in the denominator.** A crashed or failing trial counts as failed and fails the run.
- **Gates.** Each gate is `PASS`, `FAIL` or `NOT_RUN`. `overall` is `INCOMPLETE` while a mandatory consumer gate is `NOT_RUN`, and can never read `PASS` then.

| Gate | Here |
|---|---|
| `geometry`, `revision_locality`, `determinism`, `metrics_recorded` | measured (`PASS` when the checks above hold) |
| `security` | `NOT_RUN` here (owned by BMB-023/030) |
| `editor_import`, `model_eval_import` | `NOT_RUN` (original consumers) |
| `baseline_four_room_fixture` | `NOT_RUN` (needs BMB-026 on `main`) |
| `live_llm_tokens` | `NOT_RUN` (no live model) |

The measured scenario's `overall` is therefore **`INCOMPLETE`** by construction, which is the honest outcome.

## Reproduce

```sh
python -m evaluation.run --trials 3 --out result.json     # prints the summary, writes trials + summary
python -m evaluation.trial --trial 1                       # one cold trial, as JSON
python -m evaluation.probe compile --input examples/module-ir-two-rooms.json --output out.bomc
python -m unittest discover -s tests -p test_bmb028_benchmarks.py -v
```

A result pins what produced it: SHA-256 of the prompt fixture, the assembly and the three compiler sources (**text files are hashed with CRLF folded to LF**: the first hosted Windows run showed that a Windows checkout converts line endings, so raw hashes of the same commit differed per OS and two runs could not be compared; the binary golden is hashed raw), the checked-in golden hash, the commit (`EXPECTED_SHA`/`GITHUB_SHA` or `git rev-parse HEAD`), the OS, Python version and CPU count. Exit status is 0 for `PASS`/`INCOMPLETE` and 1 for `FAIL`.

## Local sample (orientation only)

One run of `--trials 3` on a Linux sandbox, Python 3.13. Timings depend on the machine; the hosted Ubuntu and Windows runs are recorded in the PR and the issue, and **nothing here is a performance claim**.

| Deterministic | Value |
|---|---|
| requests / tool calls / rejected / retries | 21 / 19 / 4 / 1 (`INVALID_ARGUMENT`, `PERMISSION_DENIED`, `REVISION_CONFLICT`) |
| MCP processes (batches) | 16 |
| estimated tokens read / written | 3 770 / 3 106 |
| request / response bytes | 12 405 / 15 067 |
| BOMC | 8 364 bytes, 58 faces, 116 triangles, 60 vertices, SHA-256 `a21109c1…`, identical to the checked-in BMB-021 golden |

| Descriptive (3 trials) | min | median | max |
|---|---|---|---|
| workflow elapsed | 1.95 s | 2.15 s | 2.22 s |
| slowest MCP batch | 246 ms | 250 ms | 274 ms |
| cold compile (wall, 6 processes) | 125 ms | 147 ms | 166 ms |
| cold compile peak RSS | 26.3 MB | 26.4 MB | 26.5 MB |
| MCP child peak RSS (POSIX) | 21.7 MB | 21.8 MB | 21.9 MB |

## Not covered (NOT_RUN)

The BMB-004 four-room baseline (needs BMB-026's house on `main`); provider-native token usage and any live agent (the controller is scripted, so the "model" is a deterministic script and token counts are estimator values); original Editor and Model-Eval import; the security gates (BMB-030); child-process peak memory on Windows; disk high-water; instrumented coverage. Nothing here asserts a speed or memory target: no threshold on timing or memory exists, because they vary with the machine and would only produce flaky failures. Reproducibility is asserted where it is real: the deterministic quantities.
