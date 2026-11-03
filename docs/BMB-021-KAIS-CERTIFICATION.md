# BMB-021 — Kais independent semantic BOMC certification

**Candidate:** KaisAbiyyi. **Lock:** tests/interop:kais. **Reserved branch:** work/bmb-021/kais-interop-20261103. **Pinned baseline:** cc01e0a02aafe519d2fe3d3136d2f28fb6b0011e. **Execution:** STRICT CLOUD-ONLY. **Merge:** prohibited until owner compares against Nazar's independent full-scope candidate.

This is an independently authored Builder-side semantic verifier, **NOT** evidence of original Editor E4 or Model-Eval acceptance. The baseline includes merged BMB-019/020 semantic geometry. The candidate uses the public BMB-001/005/007/019/020 contracts, not code from the competing implementation. The separate [candidate verdict matrix](../compatibility/bmb021-kais-candidate.json) retains all unproven gates as NOT_RUN.

## Architecture

- The dedicated independent decoder in tests/interop/kais_reader.py never calls the production writer or BMB-020's test reader. It checks the actual BOMC header, directory, checksum, section budgets, string table, material names and colors, definition-instance hierarchy, transform matrices, mesh topology, normals, triangle-to-ring area equivalence, positive winding, per-face labels, front/back materials, world bounds and actual face-derived coverage. Unknown extensions are rejected in this intentionally strict Builder profile; that policy does not represent every original consumer.
- tests/interop/kais_cases.py supplies real synthetic geometry: minimal slab, concave slab, two-room door opening, window cutout and nested mirrored + sheared + nonuniform modules. New dimensions are invented; the two existing Builder examples are public synthetic seed documents, not real user/client geometry.
- tests/test_bmb021_kais.py performs positive semantic readback and negative corruption tests with independently rebuilt valid CRCs. Cases include unsupported version/flags/endianness/codec, CRC, directory truncation/misalignment/overlap, bounds and sizes, inconsistent face/topology/coverage, invalid indices, cyclic hierarchy, nonfinite transforms, malformed section 241 and unknown sections. Its 241 rejection tests only the new strict Builder decoder.
- tests/interop/kais_receipt.py compiles each fixture in two separate cold Python processes and checks full binary byte equality, not only receipts. It records exact source commit, input JSON SHA256, BOMC SHA256, version/profile, section counts and hashes, triangles, faces, vertices, meshes, materials, AABB and coverage.
- The isolated cloud workflow bmb021-kais-certification.yml runs on Linux and Windows using pinned Actions commits, Python 3.12 and the existing jsonschema 4.23.0 dependency. It runs BMB-019/020 and BMB-009/011 regressions plus BMB-007 container checks. Candidate-only artifact names include bmb021-kais, runner OS and exact commit SHA.

The full output hashes and section manifests are published in each exact-head hosted CI artifact, rather than inventing fixed hashes in advance.

## Synthetic fixture expectations

| Fixture | Mandatory expected semantic behavior |
| --- | --- |
| minimal-solid | One real slab mesh, six faces, twelve triangles, two independently identified materials; top front finish/back concrete; nonzero coverage; bounds (0,0,0) to (2,1,0.2) |
| concave-solid | One real six-corner concave L mesh with eight faces; triangle area equals polygon area; bounds (0,0,0) to (3,3,0.2) |
| door-and-two-room | Real wall cutout and door inserts; exactly two owned meshes, 58 faces, 116 triangles, three material identities |
| window-cutout | Real cut wall, window/frame insert role and valid nonempty face/triangle topology |
| nested-mirror-shear-nonuniform | Parent mirror, child nonuniform/sheared local matrix, true global geometry bounds (-5.25,2,0) to (-3,3.5,0.15) |

**Limitations:** Source Module IR has no hole-authoring field and no arbitrary shared reusable mesh definitions. BMB-009 can reuse empty group definitions, not authored geometry. Unsupported holes, roof/stair operations, UV/textures, and Editor 241 authoring records are never silently downgraded to fake valid geometry. The independently tested strict reader's 2 MiB allocation budget and version/codec rejection policy do not prove original-consumer security.

## Real original-consumer acceptance ledger

| Producer | Consumer | Result |
| --- | --- | --- |
| BOMC Builder | Original Editor E4 viewer | **NOT_RUN** |
| BOMC Builder | Original Model-Eval | **NOT_RUN** |
| Original Ruby producer | Original Editor E4 viewer | **NOT_RUN** |
| Original Ruby producer | Original Model-Eval | **NOT_RUN** |
| Original Editor writer | Original Model-Eval | **NOT_RUN** |

Builder-versus-independent-Kais-reader PASS, if certified by exact-HEAD cloud CI, is *not* original-consumer interoperability PASS. Strict Editor editable restoration is separate from E4 viewing: Ruby and Builder do not produce the private Editor BWEB section 241; malformed 241 at the actual Editor reader remains NOT_RUN. The same is true for all other original-consumer corruption, codec and budget behavior.

## Minimal safe consumer-owned cloud handoff

1. On the final Kais candidate SHA, download the bmb021-kais Ubuntu/Windows GitHub Actions artifact and verify all BOMC SHA256 values against kais-manifest.json. Use public synthetic bytes only.
2. Run an approved private Editor workflow at its exact pinned source SHA. Execute the **actual E4 viewer loader** on Builder bytes and independently verify face/triangle/loop/hole (where representable), hierarchy, world/local transform, materials, labels, bounds and coverage. Separately invoke the strict editable reader against an Editor-owned legal 241 binary and a malformed 241 binary.
3. Run approved private Model-Eval CI at its pinned SHA. Feed it the same Builder bytes and separately synthetic original Ruby-produced and Editor-writer binaries. Record actual parser, return code, semantic values, fixture SHA, consumer commit, workflow URL and all unsupported fields.
4. Run malformed header, CRC, version, codec, overlap, truncation, expansion/budget and 241 vectors at the real consumer entrypoints. Mark FAIL or PASS only on observed behavior, preserving NOT_RUN for anything missing.

GitHub connector repository-read access is not equivalent to permission for Builder's default Actions token to clone private producer, Editor and Model-Eval repositories. Never request broad credentials or vendor private implementation sources into this public repository.

## Provenance, security, review and acceptance

All new files are original Python test tooling and docs using GPL-3.0 project's published contract. No copying from the competing Nazar implementation or private original consumer code. No private owner model, SKP, client data, new credentials, network runtime fetch or embedded assets. This is a bounded self-review, not a third-party license, legal-clean-room or full security certification. An original consumer gate may be promoted only when actual original consumer code ran and passed exact binary/semantic assertions.

The candidate PR must remain unmerged. Exact final HEAD and Linux/Windows run links must be reported in the PR and Issue #21. The owner selects the winner after comparing both independent candidates against identical original acceptance criteria.
