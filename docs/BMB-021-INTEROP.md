# BMB-021 — Semantic BOMC certification (Builder side) and consumer hand-off

Lock `tests/interop`. Code: [`tests/interop/`](../tests/interop/) (reader, fixtures, mutation helpers, goldens). Tests: [`tests/test_bmb021_interop.py`](../tests/test_bmb021_interop.py). CI: `.github/workflows/bmb021-interop.yml` (Ubuntu + Windows).

## What this delivers, and what it does not

**Delivered (Builder side only, cloud CI):** a committed suite of six valid semantic synthetic BOMC 1.2 files compiled by this repository, a pinned manifest (SHA-256, sizes, counters), an independent strict reader, deterministic cold-process recompile, and a large corruption and robustness matrix run against that reader.

**NOT delivered, still `NOT_RUN`:** every check that needs the original Editor E4 viewer, Editor strict editable reader, or Model-Eval loader (positive reads, parity, malformed section 241, consumer-specific corruption and limits), and Ruby-producer pairings. Those repositories are private and cannot be checked out by this session or the Builder Actions token. The Builder-side reader is **not** an original consumer; passing it promotes no pairing in `compatibility/bomc-1.2-matrix.json` `cases`. The result is recorded separately as `builderSideCertification` (`PASS_BUILDER_SIDE_ONLY`). Issue #21 therefore stays open for the consumer gates.

## Golden suite (`tests/interop/goldens/`)

| Fixture | Covers | Faces / triangles |
|---|---|---|
| `minimal-root` | empty module under the root, no geometry sections | 0 / 0 |
| `floor-front-back` | slab with independent front and back solid materials, label | 6 / 12 |
| `concave-l-floor` | concave L-shaped face, triangulated | 8 / 22 |
| `mirrored-sheared-floors` | mirrored parent, sheared child, offset | 6 / 12 |
| `two-room-door-seam` | two rooms, true door cutout, single-owned shared seam | 58 / 116 |
| `nested-shared-definitions` | nested shared empty-group definitions with mirror and shear | 0 / 0 |

`manifest.json` pins each file's SHA-256 and the reader's decoded summary (sections, counts, triangles, bounds, materials and opacity, nodes, transforms, geometry and face digests). Regenerate with `python -m tests.interop.goldens --write tests/interop/goldens`; `--check` fails if a fresh compile differs by a single byte. The compiler source hashes in the manifest are informational (the byte comparison is the gate). Two cold processes with different `PYTHONHASHSEED` reproduce every binary.

**Unsupported by the Builder source (fail closed, tested):** holed faces (Module IR v1 has no hole field), roof operations, textured materials. A concave+holed fixture therefore does not exist yet; this stays open until the IR gains hole authoring.

## Strict reader policy (Builder profile only)

`tests/interop/reader.py` decodes every byte it accepts and rejects the rest: exact header and flags (`0x11`), strictly ascending sections, **only sections 1, 2, 3, 5–9, 11, 12, 13, 17, 20** (anything else, including 240 and Editor section 241, is rejected, not skipped), codec 0 only (compression is rejected), valid CRC, no overlap, aligned in-bounds payloads, **no trailing bytes**, exact item counts, strict string table, fully decoded materials, definitions, instances and encoding contract, per-face loop/triangle/normal/winding/area checks, coverage derived from the face table, and **model bounds recomputed from the transformed geometry**. This is the Builder profile's own policy; it says nothing about what another consumer does with unknown sections or 241, which must be tested there.

## Corruption and robustness evidence

Against the reader: header fields (magic, versions 1.1/1.3/2.0, endian, flags, counts, directory offset); every directory entry (codec, compression, flags, sizes, item counts, CRC, offsets, alignment, overlap, duplicates, order); a CRC failure in every section; truncation at **every** length and trailing bytes; unknown sections, section 241 well-formed-looking and malformed; each required section missing; a 64 MiB deflate bomb (rejected, peak allocation < 8 MiB); the byte budget; about 60 semantic corruptions with CRCs repaired (counts, bounds, strings, materials, meshes, faces, positions, topology, normals, definitions, instances, transforms, coverage, contract); and a byte-flip sweep over the fixtures asserting that every flip is either rejected or changes the decoded model, except in alignment padding.

## Hand-off to the consumer repositories (NOT_RUN)

For each golden file, a test in the Editor and Model-Eval repositories should: load the file at a recorded source SHA; assert the counts, triangle count, bounds, material colors and opacity, transform set and face labels in `manifest.json`; and record file SHA, consumer SHA, command, exit code and counters. The same repositories own the section-241 and consumer-specific corruption cases. Until those runs exist and are recorded, every Builder → consumer pairing stays `NOT_RUN`.
