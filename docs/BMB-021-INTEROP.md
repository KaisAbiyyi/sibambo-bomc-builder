# BMB-021 — Semantic BOMC certification (Builder side) and consumer hand-off

Lock `tests/interop`. Code: [`tests/interop/`](../tests/interop/) (reader, fixtures, mutation helpers, goldens). Tests: [`tests/test_bmb021_interop.py`](../tests/test_bmb021_interop.py). CI: `.github/workflows/bmb021-interop.yml` (Ubuntu + Windows).

## What this delivers, and what it does not

**Delivered (Builder side only, cloud CI):** a committed suite of seven valid semantic synthetic BOMC 1.2 files compiled by this repository, a pinned manifest (SHA-256, sizes, counters), an independent strict reader, deterministic cold-process recompile, and a large corruption and robustness matrix run against that reader.

**NOT delivered, still `NOT_RUN`:** every check that needs the original Editor E4 viewer, Editor strict editable reader, or Model-Eval loader (positive reads, parity, malformed section 241, consumer-specific corruption and limits), and Ruby-producer pairings. Those repositories are private and cannot be checked out by this session or the Builder Actions token. The Builder-side reader is **not** an original consumer; passing it promotes no pairing in `compatibility/bomc-1.2-matrix.json` `cases`. The result is recorded separately as `builderSideCertification` (`PASS_BUILDER_SIDE_ONLY`). Issue #21 therefore stays open for the consumer gates.

## Golden suite (`tests/interop/goldens/`)

| Fixture | Covers | Faces / triangles |
|---|---|---|
| `minimal-root` | empty module under the root, no geometry sections | 0 / 0 |
| `floor-front-back` | slab with independent front and back solid materials, label | 6 / 12 |
| `concave-l-floor` | concave L-shaped face, triangulated | 8 / 22 |
| `mirrored-sheared-floors` | mirrored parent, sheared child, offset | 6 / 12 |
| `two-room-door-seam` | two rooms, true door cutout, single-owned shared seam | 58 / 116 |
| `wall-window-cutout` | 4 m wall with a real 1.2 m × 1.2 m window cutout (0.9 m sill), reveals, frame and translucent glazing inserts, two materials | 62 / 124 |
| `nested-shared-definitions` | nested **empty-group** hierarchy with mirror and shear | 0 / 0 |

**Window fixture assertions:** the cut removes exactly the window area from both wall faces (2 × 1.44 m²), adds the two jamb reveals and the sill and head (2 × 0.24 m² each), and adds 30 window-insert faces (surface 8) bound to the translucent glass material (RGBA 150/200/230/120, opacity 0.47); the uncut wall of the same size is compiled alongside as the control.

**Shared geometry is not demonstrated.** `nested-shared-definitions` shares only *empty* group definitions; no fixture instances one mesh more than once, because Module IR v1 has no shared geometry-definition reference. Reusable shared mesh geometry therefore stays `NOT_DEMONSTRATED` (manifest `sharedMeshGeometry`) and is not a basis for any consumer claim.

`manifest.json` pins each file's SHA-256 and the reader's decoded summary (sections, counts, triangles, bounds, materials and opacity, nodes, transforms, geometry and face digests). Regenerate with `python -m tests.interop.goldens --write tests/interop/goldens`; `--check` fails if a fresh compile differs by a single byte. The compiler source hashes in the manifest are informational (the byte comparison is the gate). Two cold processes with different `PYTHONHASHSEED` reproduce every binary.

**Unsupported by the Builder source (fail closed, tested):** holed faces (Module IR v1 has no hole field), roof operations, textured materials. A concave+holed fixture therefore does not exist yet; this stays open until the IR gains hole authoring.

## Strict reader policy (Builder profile only)

`tests/interop/reader.py` decodes every byte it accepts and rejects the rest: exact header and flags (`0x11`), strictly ascending sections, **only sections 1, 2, 3, 5–9, 11, 12, 13, 17, 20** (anything else, including 240 and Editor section 241, is rejected, not skipped), codec 0 only (compression is rejected), **canonical varuints only** (see below), valid CRC, no overlap, aligned in-bounds payloads, **no trailing bytes**, exact item counts, strict string table, fully decoded materials, definitions, instances and encoding contract, per-face loop/triangle/normal/winding/area checks, coverage derived from the face table, and **model bounds recomputed from the transformed geometry**. This is the Builder profile's own policy; it says nothing about what another consumer does with unknown sections or 241, which must be tested there.

### Varuint policy

The repository's contract documents name the codec ("delta-varint") but contain no passage saying whether non-minimal encodings are legal, so none can be cited. The decision is therefore a **Builder-profile policy, not a wire-contract claim**: the Builder writers only emit minimal forms and the reader rejects overlong encodings (a redundant trailing zero group), values that overflow 32 bits, unterminated encodings and encodings longer than five bytes, in the topology loop and triangle columns and in the face loop-count, triangle-count and loop-length columns. Crafted CRC-repaired files prove each column; how the original consumers treat non-minimal forms is `NOT_RUN`.

## Corruption and robustness evidence

Against the reader: header fields (magic, versions 1.1/1.3/2.0, endian, flags, counts, directory offset); every directory entry (codec, compression, flags, sizes, item counts, CRC, offsets, alignment, overlap, duplicates, order); a CRC failure in every section; truncation at **every** length and trailing bytes; unknown sections, section 241 well-formed-looking and malformed; each required section missing; a 64 MiB deflate bomb (rejected, peak allocation < 8 MiB); the byte budget; about 60 semantic corruptions with CRCs repaired (counts, bounds, strings, materials, meshes, faces, positions, topology, normals, definitions, instances, transforms, coverage, contract); crafted overlong, overflowing and unterminated varuints in every encoded column; and a byte-flip sweep over the fixtures asserting that every flip is either rejected or changes the decoded model, except in alignment padding.

## Hosted CI evidence

`.github/workflows/bmb021-interop.yml` checks out the exact commit under test (`github.event.pull_request.head.sha || github.sha`), asserts `git rev-parse HEAD` equals it, pins `actions/checkout` (v4.2.2, `11bd7190…`) and `actions/setup-python` (v5.6.0, `a26af69b…`) to immutable commit SHAs, and runs on Ubuntu and Windows with Python 3.12: `goldens --check`, this suite, and the BMB-019 writer, BMB-020 compiler and semantic, BMB-009 graph, BMB-011 assembly, BMB-007 fixture harness and compatibility-matrix tests. Each job writes the commit, runner, Python version, run URL and gate list to its job summary. It is triggered by changes to `core/`, `bomc/`, `examples/`, `schemas/`, `fixtures/`, `tools/`, `compatibility/`, `tests/interop/` and the listed tests.

A commit cannot contain its own run URL, so the run for each head is recorded in the PR #57 conversation and the Issue #21 comment. Earlier evidence for `2ce575c39531834e2b27c744ad5b9b7db9e6c93f` (24 BMB-021 tests per OS, merge-ref checkout): [run 41629550190](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/41629550190) and [matrix run 41629550106](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/41629550106), both SUCCESS. A local full-suite count is not hosted evidence and is reported separately.

## Hand-off to the consumer repositories (NOT_RUN)

For each golden file, a test in the Editor and Model-Eval repositories should: load the file at a recorded source SHA; assert the counts, triangle count, bounds, material colors and opacity, transform set and face labels in `manifest.json`; and record file SHA, consumer SHA, command, exit code and counters. The same repositories own the section-241 and consumer-specific corruption cases. Until those runs exist and are recorded, every Builder → consumer pairing stays `NOT_RUN`.
