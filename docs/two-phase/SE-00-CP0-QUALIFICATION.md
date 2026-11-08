# SE-00 CP0 — exact-source qualification and owner handoff

Date: 2026-11-08 (Asia/Jakarta). Executor: Claude Code managed cloud, single writer, no delegates.
Governing plan: SIB-TWO-PHASE-001 v1.5 including D10/D11. D11 is authoritative for the initial demonstration. Manifest revision 2 pins the D11 master: Editor commit `cc75bd1b0ec9b8800f588d0b907ac31c0d7e5e05`, blob `3479da07f7d7471a4229a09367db17002bd40c2d`, SHA-256 `67105d23f3576f2a3d78b2aa8d11c38014d9f4e0b9043fdab7e2e4a6d5fb3965` (the earlier `d744f779…` pin is kept as superseded history).

**Verdict: CP0 source-level qualification PASS. SE-00 moves to Review / Owner Acceptance, not Done.**
Nothing was merged, released or deployed. No credentials, tunnel, Auth0 tenant or Render service were used or created.
Remote product mechanisms (actor, auth, BFF, WebSocket, remote Save, Streamable HTTP/OAuth) are still absent and remain downstream SE work; they are not CP0 prerequisites under D11.

## Final qualified candidates

| Repository | Candidate | PR | Composition |
| --- | --- | --- | --- |
| Builder | `f1503748216b8778d2e11e6e73674bd64e295450` | [#90](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/90) | main `7cd6ca7…` + exactly four added files, blob-identical to #62 `8fc6ebb…`. No other path differs from main; compiler/core inventory digest unchanged (`5c067aae…`). |
| Editor | `98b01dc16ae11f6712dd86de38541a1b889f699d` | [#13](https://github.com/KaisAbiyyi/sibambo-editor/pull/13) | main `04e4c1d…` → #12 `b5f46a7…` (exact ancestor) → #13 content → #14 squash. No commits created, nothing duplicated. `bomc-loader.ts` is byte-identical to #12; original E4 security and semantic validation preserved. |

Designated branch `claude/blissful-lamport-6w9bm1` in both repositories points at these exact SHAs and was used only to dispatch hosted workflows on them.

## Results

| Gate | Result | Evidence |
| --- | --- | --- |
| Builder full suite, hosted Ubuntu | PASS: 634 run, 634 passed, 0 skipped (620 inherited + 14 house) | [run 42462743933](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462743933) |
| Builder full suite, hosted Windows | PASS: 634 run, **629 passed, 5 skipped**, 0 failures/errors. Skips: POSIX private-root ×1 and permission/ACL/symlink ×3 (Windows ACLs not validated), child peak memory ×1. Skips are not passes. | same run |
| Builder full suite, local cloud Linux (Py 3.13) | PASS: 634 run, 634 passed, 0 skipped | log sha256 `8c574eeb…` |
| BMB-026 four-room house, Ubuntu+Windows | PASS; artifacts byte-equal to Editor pinned fixtures | [run 42462751551](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462751551) |
| Journal / replay / identity / assembly | PASS (journal 48 local; BMB-022/023 workflows) | [42462749810](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462749810), [42462758945](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462758945) |
| Negative / adversarial | PASS (BMB-030: 42 local; hosted) | [42462753296](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462753296) |
| Other Builder workflows | PASS: [BMB-020](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462746033), [021](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462748012), [024](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462756801), [025](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462755049), [028](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462760598), [029](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462762462), [032](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42462764288) | exact candidate |
| Editor original E4 consumer + material/count regressions, Ubuntu+Windows | PASS 80 pass / 0 fail per OS, provenance, check, shared types, build | [run 42462771023](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42462771023) |
| Editor BMB-021 original acceptance, Ubuntu+Windows | PASS | [run 42462773070](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42462773070) |
| Editor BMB-005/007 | PASS, exact-SHA PR-event run (not re-dispatchable) | [run 42417192641](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42417192641) |
| Editor local: consumer 80/80, svelte-check 0/0, `tsc` exit 0, production build | PASS | log sha256 `9209b5e1…` |
| Editor Builder-preview Chromium | PASS 2/2 (local Linux) | hosted BMB-027 at `98b01dc`: NOT_RUN |
| Cross-repo Builder → original Editor BOMC import (fail-closed checker v2) | PASS | below |
| Checker negative tests (24) | PASS | `docs/two-phase/test_se00_cross_repo_check.py`; log sha256 `c0887c21…` |
| Windows-native local, Auth0, tunnel, Render, WebSocket, live agents, remote Save, owner acceptance | NOT_RUN | not authorized / not implemented |

### Cross-repository import (checker v2, fail-closed)

`docs/two-phase/se00_cross_repo_check.py` uses explicit validation only (no `assert`, so `python -O`/`-OO` cannot disable it) and exits non-zero on any failure or unexpected error; `PASS` is printed only after every step. Both `--expected-builder-sha` and `--expected-editor-sha` are mandatory 40-hex values. Each checkout must be the repository top level, `HEAD` must equal its expected SHA and the tree must be clean. Pinned inputs are read from the expected commit objects, the Builder is exported with `git archive` (ignored or untracked files cannot influence output), and the generator runs twice under different `PYTHONHASHSEED` values and must be byte-identical. Output must equal the Editor's pinned fixtures, the fixture manifest, and independent pins compiled into the script, so a consistently tampered fixture+manifest pair is also rejected.

Run on Builder `f1503748…` and Editor `98b01dc…`: PASS (receipt sha256 `4e78f007…`). The generated bytes were also loaded through the unmodified production `BomcLoader.load` (11/11): five modules / four rooms, 278 source faces vs 66 analytical surfaces, 556 front triangles, nine materials. Hosted Ubuntu and Windows Builder artifacts are byte-equal to the same fixtures.

Negative tests (24, 0 failures, kept outside `tests/` so the inherited Builder count stays 620/634) cover: wrong, malformed or moved expected SHA; dirty or untracked tree; non-top-level path; tampered fixture; tampered fixture plus manifest; missing, invalid or malformed manifest; differing, non-deterministic, failing or incomplete generator output; receipt gate not PASS; ignored-file injection; absence of `assert`; CLI exit codes under `-O`/`-OO`; unexpected internal error. Mutation check: removing the HEAD, clean-tree, manifest-pin or determinism checks makes tests fail. (The final generated-vs-pin comparison is intentionally redundant defense in depth.) Writing these tests exposed one real defect in the first draft of the checker: under `-OO` the stripped docstring crashed argument parsing before any verdict; fixed.

| File | SHA-256 | Bytes |
| --- | --- | --- |
| `baseline.bomc` | `071ebe152b44d2bae387818094ad67a6f461645d45d1ad33c195848dbb0b49aa` | 32,660 |
| `revised.bomc` | `e56924fead241df9a1a76c9de9e0e647b13caf2785cf14bc4c679a8979192233` | 32,660 |

Other contract hashes (IR schema `3ca89523…`, loader `9dbb8fe8…`, compiler/core inventory `5c067aae…`) are in `BASELINE-CONTRACT-MANIFEST.json`.

## Defects found and fixes

Candidates: none; all gates passed on the first exact-SHA run and no production, test, workflow or fixture byte was changed. Documentation: the first receipt wrongly reported the hosted Windows Builder run as 634/634; the log shows 634 run, 629 passed, 5 skipped (corrected here, in manifest rev 2, and by erratum on issue #70). Checker: the `-OO` crash described above (docs-side tool only). Historical evidence (#62 run 42036423066, #12/#13 receipts, the earlier audit and validation JSON) is untouched.

## Remaining risks (see manifest for full list)

- Candidates are unmerged drafts. A different merge order or a moved base requires re-qualification.
- Windows-native execution is not validated and Windows ACL/private-root semantics are untested (4 of the 5 hosted Windows skips are POSIX-permission/ACL tests); this matters for the D11 Windows-laptop actor.
- stdio MCP uses spawn-per-call workers and filesystem journals; it cannot share an in-memory draft with a separate server. The canonical single actor (stdio bridge plus Editor WebSocket plus owner Save) is future SE-01/SE-03 scope.
- No hosted cross-repo workflow exists (the private Editor cannot be checked out from Builder CI without a token); cross-repo evidence is local plus a hosted byte-identity chain.
- Viewing is not strict editability; no native SketchUp certification; full historical Editor suite remains partial.

## Owner handoff — recommended merge sequence (nothing merged)

1. Builder [#90](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/90) onto main.
2. Builder [#89](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/89) (this documentation and manifest) after #90.
3. Editor [#12](https://github.com/KaisAbiyyi/sibambo-editor/pull/12) onto main.
4. Editor [#13](https://github.com/KaisAbiyyi/sibambo-editor/pull/13) after #12 (already contains #12 and the #14 squash; never merge #14 separately).
5. Re-pin the resulting main SHAs and re-run the cross-repo checker (with the new expected SHAs) before authorizing SE-01 and SE-04.

Owner gates: approve the merge order above; later supply nonproduction Auth0/tunnel inputs (no secrets in text); separately authorize SE-01 and SE-04 IMPLEMENT.
SE-01 (`shared/ir; shared/compiler`) and SE-04 (`stable/editor-onboarding; stable/auth-ui`) have disjoint locks and are ready for parallel authorization once the owner accepts CP0; each must re-check heads and claims, and SE-04 must not edit SE-03-owned Builder auth endpoints.

Direct implementor self-review only; not independent review.
