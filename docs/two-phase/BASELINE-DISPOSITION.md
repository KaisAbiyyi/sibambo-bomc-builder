# SE-00 baseline disposition — proposed owner decision

Observed 2026-11-08 (Asia/Jakarta). **SE-00 remains Blocked / Owner Gate.**
This is an audit recommendation, not integration, implementation, deployment or release authority.
Read with [cloud audit](SE-00-CLOUD-AUDIT.md), [machine manifest](BASELINE-CONTRACT-MANIFEST.json)
and [validation receipt](SE-00-VALIDATION.json).

## Recommended reproducible source set

| Role | Exact source | Disposition |
| --- | --- | --- |
| Builder execution source | `7cd6ca7771e7ad64418cb1808edf9460e9f6cc19` (`main` at observation) | Retain current hardening and already merged components. Do not reset to #62. |
| Editor execution source | `98b01dc16ae11f6712dd86de38541a1b889f699d` (current #13 head) | Approve the existing predecessor stack as the proposed working source; it includes #12 and the squash of #14. It is NOT Editor main. |
| Four-room corpus generator | Builder `8fc6ebbeb1996889983bd6fff0958d1f9a7aaf00` (#62) | Retain as a separate, immutable read-only corpus source until approved integration. |
| Original BMB-021 fixture producer | Builder `0e3ec262e98762969da66088d412f8beebb63523` | Keep this historical producer pin for unchanged consumer regressions. |

Editor main is still `04e4c1d1656e7c65b093d1667f556c3fdb4b5130`.
The recommendation deliberately names existing commits, so it can be reproduced without an unapproved merge.
No future combined commit is invented: `futureIntegratedSha` is null in the manifest.
The source pair is a proposed implementation starting point, not a finished Stable product.
Owner approval must say whether work may branch from the Editor feature pin or must wait for main integration.
Recommended default: finish the predecessor integration gate first and re-pin its resulting exact commits before SE-01/SE-04.

Current Builder main compiles the immutable four-room IR to the original byte-identical files;
the original Editor at the proposed consumer pin imports those same bytes and passes the retained negative suite.
This is cross-repository compatibility evidence for the bounded corpus only.

## Dependency state and integration order

The `base reported` column preserves the provider PR snapshot; `live target` identifies the independently fetched branch tip.
For #62, the reported base is its historical fork point, not current main. Open-PR synthetic merge SHAs are not accepted baselines.

| Dependency | HEAD | Base reported / live target | State and required action |
| --- | --- | --- | --- |
| Builder #62 / BMB-026 | `8fc6ebbeb1996889983bd6fff0958d1f9a7aaf00` | `0878cbaa63abcfd16571a4d7475ee208f80c808b` / `7cd6ca7771e7ad64418cb1808edf9460e9f6cc19` | Open draft. Four additive files absent from main. Required corpus, not a replacement core. |
| Builder #69 / BMB-031 | `253725b8143f08aa6e5fc0718e10235392e861f5` | `7cd6ca7771e7ad64418cb1808edf9460e9f6cc19` / same | Open draft. Defer packaging/release work; optional for Stable source-based development. |
| Builder #66 / BMB-032 | `437277e549da0fbaef89214803d0ded5a2cd5ea7` | `960750cd31eb1e3c86f37f3a408fd011156648ad` / main now `7cd6ca7…` | Merged as `ab4d86973396592cd0e7361055439120359e9c3d`; ancestor of current main. Retain; no second integration. Not a Stable prerequisite. |
| Editor #12 | `b5f46a761d1763241b60375cbb5f7110d62d99d2` | `04e4c1d1656e7c65b093d1667f556c3fdb4b5130` / same | Open draft. Mandatory original-consumer material/count behavior and regressions. Exact ancestor of #13. |
| Editor #13 | `98b01dc16ae11f6712dd86de38541a1b889f699d` | `04e4c1d1656e7c65b093d1667f556c3fdb4b5130` / same | Open draft. Mandatory corpus proof and narrow browser typecheck repair; retains #12 and #14. |
| Editor #14 / BMB-027 | `7d03a40e19df3a8ee19ced02d0fcac8bec3a2944` | `9570d8d57cd95be3d95e4785d7b1f8a45b83ae73` / current #13 `98b01dc…` | Closed, squash-merged into #13 as `98b01dc…`; head and squash have identical trees. Original head need not be a git ancestor. Never merge it again. Preview feature is optional; retain it in the selected stack. |

Recommended owner-approved integration sequence, **not performed here**:

1. Builder: selectively integrate exactly #62's four additions onto current main, preserving attribution and original receipts:
   `.github/workflows/bmb026-house.yml`, `docs/BMB-026-HOUSE-E2E.md`,
   `examples/bmb026_house.py`, `tests/test_bmb026_house.py`.
   All four paths are currently absent, so no same-path conflict was found. Later main changes in assembly,
   identity/journals, geometry and compiler make fresh combined-source tests mandatory.
   The full #62 delta from its fork is only those four files; an approved integration of that exact delta is also acceptable.
2. Editor: accept/integrate #12 first, then #13 with its retained #14 content; alternatively explicitly approve
   integrating #13's aggregate tree once, since #12 is already its ancestor. Do not duplicate patches.
   Default is #12 then #13, preserving each acceptance record. Requalify and pin the resulting heads after any base change.
3. Re-run Builder full regressions, four-room generator/journal/cold compilation, original Editor material/count/house
   suites, preview boundaries, check/types/build and baseline compatibility on the **actual integrated SHAs**.
   Their future integration checks are NOT_RUN even though the current source set passes bounded checks.
4. Keep #69 under its separate `release/checklist` owner gate. Packaging Ready is not Release Approved.
   Existing disposable #65 and alternate #58 are unrelated candidates, not Stable prerequisites.
5. Review planning docs separately. Builder #88 and Editor #21 are draft docs at v1.3;
   newer v1.5 documents exist on the separately pinned planning branches. Do not merge a stale planning PR as authority
   for v1.3-only behavior or import private planning/Editor implementation into public Builder.

Builder and Editor predecessor integrations can proceed independently after owner authorization,
but a cross-repository receipt joins them before CP0 closes. No predecessor branch was modified here.

## Contract and corpus freeze

Canonical Module IR remains `1.0.0`, metres/right-handed +Z, row-major module-to-parent transforms.
Schema file SHA-256: `3ca89523ff3239e1cb52e716ca3aebc8a30a9bbddbb512d4c3111188b57a66a5`.
Compiler entry point is `bomc.compiler.graph_to_bomc.compile_document` at Builder `7cd6ca7…`.
The manifest pins every tracked `core/**/*.py` and `bomc/**/*.py` blob and SHA-256, with deterministic inventory digest
`5c067aae01a4f34b3179df3411f7f47678e481f541bf7dea0f56134f2c595053`.
Consumer loader SHA-256 is `9dbb8fe8e2f898da669e985c9c6ad70eeb1845f1c7e01efced0a2641bc98cc01` at Editor `98b01dc…`.
No draft operation/view/error schema exists yet; their hashes remain null, to be frozen by their owning SE tasks.

The synthetic corpus is four rooms (living, bedrooms A/B, bath) in an 8 × 6 m two-by-two layout,
plus a fifth flat-roof module, four single-owned reciprocal seams, three real doors and one exterior window.
Revision 1→2 widens only Bedroom A's private window from 1.0 to 1.2 m; the other four module hashes stay unchanged.
Both binaries contain 278 source faces, 556 front triangles, five meshes and nine materials, and are 32,660 bytes.
The maximum canonical module is 5,329 UTF-8 bytes, below the unchanged 65,536-byte block cap.

| File | Exact SHA-256 |
| --- | --- |
| `baseline.bomc` | `071ebe152b44d2bae387818094ad67a6f461645d45d1ad33c195848dbb0b49aa` |
| `revised.bomc` | `e56924fead241df9a1a76c9de9e0e647b13caf2785cf14bc4c679a8979192233` |

Original fixture/source/receipt and archive digests are retained in the machine manifest.
The original archive bytes were not downloaded again in this audit; tracked fixture digests and exact generator reproduction were checked.
The original Editor fixtures are consumed in its private checkout; no private source or binary was copied into this public documentation PR.

Keep existing ceilings: 1–8 modules per future transaction, 256 KiB request, 64 KiB canonical-module block,
2 MiB project envelope, and every stricter compiler/core limit. Current compiler JSON input cap is **1,000,000 bytes**,
output cap **2,000,000 bytes**, strings/materials 254 each, faces 4,096, vertices 8,192,
triangles 20,000, source operations 128 per module and nodes 128.
The looser project envelope never overrides those stricter caps. Preserve semantic face-label reuse without treating labels as unique face IDs.

## Acceptance and risks retained

- [BMB-026 issue #26](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/26)
  records owner acceptance of five visual A/B pairs on 2026-11-07 and release of `e2e/house`.
  The bounded independent Builder review is linked there. Older PR bodies saying visual acceptance is pending are historical.
  Do not reopen that accepted visual gate merely because its code is unmerged; new live Save/reopen is a separate gate.
- Original Editor acceptance report is pinned to `9570d8d…`, with current consumer checks also run on `98b01dc…`.
  E4 viewing does not prove private section-241 editability, arbitrary round-trip or native SketchUp certification.
- #62's initial string-table failures were repaired without increasing limits. Main includes later BMB-030 hardening;
  taking #62 as the execution core would omit it. BMB-032 is a bounded deterministic single-row adapter,
  not canonical typed actor ownership or general planning; its compile ceiling is 1–5 rooms, with 6+ hitting the string budget.
- Editor full historical unit qualification remains partial in the existing receipt because exact historical inputs were unavailable.
  This audit did not replace them or claim a full Editor suite pass. Existing bundle/dynamic-import warnings remain non-blocking.
- Existing local authoring Save serializes the private canonical graph; Builder preview disables Save.
  Future remote drafts need a distinct mode and owner Save route. Do not force Builder files through local editable restoration.
- No actor, remote auth service, BFF sessions, WebSocket render ACK or real-client staging acceptance exists in the inspected application sources.

## Minimal owner decision checklist

- [ ] Approve the exact source set above and #62 four-file integration; default retain current main hardening.
- [ ] Approve Editor #12→#13 predecessor disposition (including #14), integration route and re-pin requirement.
- [ ] Supply/approve nonproduction Auth0 tenant, issuer/audience, owner BFF client, separate Claude Code/Codex client principals,
  callback allowlist, service/Editor TLS origins and secret-store bindings. Enter secret values in environment settings, never task text.
- [ ] Authorize a nonproduction long-lived single-actor service with TLS streaming/WebSocket proxy and no unsaved-model
  logs, backups, swap or core dumps; name the infrastructure owner and available capacity. No production release follows.
- [ ] After CP0 source/environment evidence exists, issue a separate Stable IMPLEMENT scope, starting SE-01 and SE-04;
  retain v1.5 selected inbox/timeline/opt-in receipt and deferred camera. No SE implementation is authorized by this audit alone.

Do not ask again for v1.5 D2 feature selections or accepted BMB-026 visual checks.
Auth0 readiness and actual remote TLS/client compatibility are still unverified inputs, not proof of account absence.

## Resource boundaries and next execution

This audit owns only `stable/baseline` documentation on `docs/se-00-cloud-audit-20261108`.
The canonical ledger showed no other Stable claimant when checked. The claim is serialized coordination, not an atomic lock.
Release audit write ownership at handoff; keep Status=Blocked, Execution=Owner Gate, Now=SE-00,
Up Next=SE-01 and SE-04; all later Stable tasks remain blocked by their AND dependencies.

After owner approval, predecessor qualification and fresh claim checks, SE-01 (`shared/ir; shared/compiler`)
and SE-04 (`stable/editor-onboarding; stable/auth-ui`) can proceed in parallel on disjoint owned files.
Freeze their shared protocol first; SE-04 must coordinate SE-03-owned Builder auth endpoints, not edit them concurrently.
Serialize SE-01/SE-07 compiler work, SE-03/SE-09 auth work and overlapping SE-05/SE-08 synchronization work.
Every later task still checks all AND prerequisites, exact heads, claim generations and logical locks.
No future-phase implementation, trials or experiments are part of this disposition.
