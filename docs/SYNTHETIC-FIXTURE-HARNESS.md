# BMB-007 — Synthetic BOMC container fixture harness

An independently authored Python stdlib harness generates **six deterministic BOMC 1.2 compact container vectors**, and a JSON manifest of SHA256, CRC32, per-section counters and sizes. The fictional intents are minimal, floor, holed-wall, concave face, nested affine, and front/back materials. Inputs and labels are entirely synthetic (no imported houses, client models, or proprietary assets).

**Important limitation:** section payloads contain opaque invented markers, *not* valid nested BOMC model/mesh/geometry tables. A sound header, directory, alignment, stored CRC and version do **not** make these files valid renderable BOMC, semantic golden fixtures or Editor/Model-Eval-compatible. The manifest marks `scope: container-only`, `semanticBomcTablesValid: false` and `independentConsumerStatus: NOT_RUN`. The downstream independent writer (BMB-019/020) and consumer test (BMB-021) must replace/augment these fixtures with real synthetic semantic goldens.

## Repeatability

- Deterministic seed 0 and canonical marker construction; no timestamps, OS paths, randomness or external assets in bytes.
- BOMC 1.2, compact 24-byte descriptors, little endian, 8-byte aligned raw sections, production/compact flags 0x11, 32-byte header, CRC32 of stored payload.
- Baseline directory sections: 1,2,11,12,13,17,20; additional synthetic intent sections: 3,5,6,7,8,9.
- Run `python tools/bomc_fixture_harness.py --write DIRECTORY`; manifest includes six fixture SHA256, byte sizes and per-section logical counts.
- Run `python tools/bomc_fixture_harness.py --check DIRECTORY`; byte-for-byte compare against the original recipe.
- GitHub CI performs two cold process runs and checks all generated outputs and hashes, retaining a 14-day **container-only** artifact.

The [committed cloud reference SHA ledger](../fixtures/container-only-reference-sha256.json) fixes the six generated SHA256 and file lengths from successful CI run 40063418837; the unit test fails on unexpected bytes. This ledger still certifies **container integrity only**.

## Negative cases and budgets

Ten independent vectors must fail under the strict structural reader: invalid magic, 1.3 and 2.0 versions, unknown header bit, truncation, CRC mutation, unsupported codec, oversized expanded allocation, payload overlap with directory, and duplicate section. Guards: maximum input and expanded bytes 2 MiB, maximum sections 64. These are harness safety budgets, not normative BOMC maxima. The harness is a strict synthetic test reader, not a replacement for producer or consumer decoders.

The malformed BWEB section 241, actual holed polygon semantics, sheared instance parity and independent front/back material acceptance **remain NOT_RUN** until real semantic payloads and separately pinned consumers are available. Never claim those conditions passed because the manifest mentions their test intents.

## Cloud runner commands

```bash
python tools/bomc_fixture_harness.py --selftest
python -m unittest discover -s tests -p 'test_fixture_harness.py' -v
python tools/bomc_fixture_harness.py --write "$RUNNER_TEMP/goldens-a"
python tools/bomc_fixture_harness.py --write "$RUNNER_TEMP/goldens-b"
diff -r "$RUNNER_TEMP/goldens-a" "$RUNNER_TEMP/goldens-b"
python tools/bomc_fixture_harness.py --check "$RUNNER_TEMP/goldens-a"
```

The generated artifact is an evidence receipt for structural byte integrity and reproducibility only. It is not a consumer release artifact.

## Independent original-consumer admission proof — 24 October 2026

The six `container-*.bomc` vectors from exact generator commit `eafc5270abfab27c7f73d78b5ff7f3274e1180f8` were generated again in the two original private consumer CI environments (no private sources published here). Both runners execute this public harness and independently verify its six pinned hashes and ten corruptions before passing the bytes to native readers.

- [Sibambo Editor CI 40064796823](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/40064796823), [private consumer test PR #10](https://github.com/KaisAbiyyi/sibambo-editor/pull/10): **PASS 38 tests / 0 fail**. `parseDirectory(..., 'source-envelope')` accepted all six container structures; `readWebBomc` rejected every one for missing valid authoring section 241. Its own independently generated semantic 1.2 BOMC from `BomcWriter` loaded through strict `readWebBomc` and the original E4 viewer.
- [Model-Eval CI 40064799201](https://github.com/KaisAbiyyi/sibambo-model-eval/actions/runs/40064799201), [private consumer test PR #3](https://github.com/KaisAbiyyi/sibambo-model-eval/pull/3): **40 pass / 0 fail / 2 skipped**. `BomcContainer` accepted all six valid headers/descriptors and loaded opaque section bytes, while the real `BomcLoader` rejected all six as invalid semantic model tables. Existing tests successfully loaded unrelated valid self-authored semantic BOMC 1.2 data.

**Explicit conclusion:** Independent consumers have now tested the **expected semantic rejection** of these six vectors. This is a positive *negative-boundary* test, not positive semantic geometry acceptance. `semanticBomcTablesValid=false`, `independentConsumerStatus=NOT_RUN` in the fixture manifest remain correct for *valid authored binary semantic roundtrip* because no such goldens are emitted here. Independently authored meaningful BOMC writer/output and cross-consumer roundtrip remain dependent on BMB-019/020/021. No private code or real-house fixtures are copied into this public Builder.
