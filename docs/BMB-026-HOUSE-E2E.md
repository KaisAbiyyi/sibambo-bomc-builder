# BMB-026 — Four-room synthetic house and localized BOMC revision

**Claim:** Issue #26 · owner KaisAbiyyi / ChatGPT GPT-6 cloud session · lock e2e/house · branch work/bmb-026/cloud-house-20261105. Scope is Builder cloud-only. No main merge or native consumer acceptance is authorized by this work.

## Physical and data model

The wholly invented 8 m × 6 m plan has four independently revisioned modules in a 2×2 grid:

| Location | Room | Local rectangle | World translation |
| --- | --- | --- | --- |
| Southwest | living | 4 m × 3 m | (0,0,0) |
| Southeast | bedroom-a | 4 m × 3 m | (4,0,0) |
| Northwest | bedroom-b | 4 m × 3 m | (0,3,0) |
| Northeast | bath | 4 m × 3 m | (4,3,0) |

A fifth non-room module carries a flat-roof slab over the 8×6 footprint at elevation 2.85 m. This is the **supported flat-slab BOMC profile**, not BMB-016's unsupported gable-roof/stairs operation.

The modules author 4 floor slabs, external perimeter walls, four singly owned internal wall seams, three **real wall-cut** doors (living↔bedroom-a, living↔bedroom-b, bedroom-a↔bath), one intact boundary (bedroom-b↔bath) with a \`shared-boundary\` port rather than a fake door, and one exterior bedroom-a window with real cut topology. Ports are reciprocal and checked in world coordinates by BMB-011; straight wall cuts use BMB-015, and BOMC 1.2 geometry/face/coverage uses BMB-017/018/020. This is synthetic architectural geometry, not construction-code-certified design.

## Localized revision

\`build_house()\` yields baseline revision 1 for every module. \`build_house(revised=True)\` increments **only bedroom-a** to revision 2 and widens its *private exterior window* from 1.0 m to 1.2 m. It does not alter any shared doorway, seam, dependency minimum, room transform, roof, or other module. Per-module canonical JSON SHA256 values prove that **living, bedroom-b, bath and roof remain byte-identical as serialized modules**. The BMB-010 journal test additionally seeds and reopens five real per-module hash-chained journals, rejects a stale CAS edit, commits *only* the Bedroom A replacement, and verifies the other four journal files' exact bytes and modification timestamps are unchanged after reopening. The revised assembly rebuilt from persisted journal blocks compiles to the same BOMC SHA256 as the revised fixture; idempotent replay does not rewrite a journal. The BOMC document necessarily changes because the overall compiled artifact contains the changed window; this is a full derived recompile, not a claim of binary patch/delta.

A door width revision across a shared seam would require coordination and is deliberately not misrepresented as isolated. Bedroom-a revision 2 continues satisfying a bath dependency with minRevision=1.

## BOMC 1.2 bounded label profile

The existing compiler enforces a **254-entry string table** because this strict BOMC 1.2 subset uses one-byte string indices. Four rooms with three actual door cuts exceed that cap if every simple wall/slab face receives an automatically generated unique path label. The fixture uses the already approved BMB-018 face-annotation schema to reuse meaningful `wall solid surface`, `floor solid surface` and `roof solid surface` labels on **uncut** simple walls/slabs. Cut walls retain their mandatory unique face labels and true topology. Every face record, material binding, mesh, normal and coverage count remains present; this is not a compiler-limit bypass. **Labels are not unique face identifiers** and should not be used as a future edit-selection key.

## Reproduction

    python -m pip install jsonschema==4.23.0
    python -m unittest discover -s tests -p test_bmb026_house.py -v
    python -m examples.bmb026_house --out-dir bmb026-evidence

Outputs are baseline/revised source JSON, **real** baseline/revised BOMC 1.2 binary, and a receipt with SHA256, geometry counts, revision diff, preserved-module hashes and explicitly classified gates. The independent Builder strict reader from BMB-021 validates all section/CRC/geometry semantics; that does **not** imply the original Editor E4 reader was run.

The exact-commit Ubuntu + Windows workflow \`.github/workflows/bmb026-house.yml\` also runs predecessor geometry, compiler, interoperability and scripted-agent regressions, uploads synthetic evidence and records the exact SHA. A green cloud result proves only what those jobs actually ran. Never promote a pending/failed/skipped check as PASS.

## Negative and scope checks

Regression tests reject duplicate seam ownership, reciprocal port span mismatches, unsatisfied revision dependencies, and unsupported oversize openings. They check multiple cold compiler processes for identical bytes, shuffled source operation/module ordering for stable output, real cutout topology and door clearance, and that the original Editor/visual gate stays NOT_RUN in receipts.

**NOT_RUN / separately controlled:** Original Editor E4 import and visual A/B for both binaries (Editor PR #12 remains draft/unmerged), native SketchUp/Windows gates, live LLM controller, provider-native token benchmarking, real roof-gable/stair topology, arbitrary architectural geometry, hostile-process security, release and product certification.

**No self-merge.** After exact-HEAD cloud CI, request independent acceptance and owner merge authorization; separately arrange an original Editor consumer workflow on exact source/fixture hashes. Follow BMB-021 consumer source pinning and do not rewrite Editor main on this Builder task.
