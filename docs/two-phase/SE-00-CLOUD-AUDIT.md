# SE-00 cloud audit — evidence and limitations

Date: 2026-11-08, Asia/Jakarta. Executor: Codex, managed cloud, single writer; no delegates.
**Audit documentation prepared; SE-00 remains Blocked / Owner Gate. Product implementation NOT_STARTED.**
No merge, cherry-pick, rebase, deployment, release or production source modification occurred.

## Authority and current-source reconciliation

Sources actually retrieved:

- [Current master v1.5](https://app.notion.com/p/412c4a6aaf738117ac36c5101c01fae2), including accepted v1.4 additions and preserved v1.3 contracts.
- [SE-00 task](https://app.notion.com/p/412c4a6aaf73817a95c4f924aeb464ab) and its current schema/claim/status.
- [Stable roadmap](https://app.notion.com/p/412c4a6aaf7381c5b063dc52002c89b9) and complete 12-task Stable ledger.
- [Builder issue #70](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/70), #26/#27/#32,
  current PR metadata and named CI runs for Builder #62/#69/#66 and Editor #12/#13/#14.
- [Builder planning PR #88](https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/88), head `482e9338becf05a07032592909fecebda7d2fe9d`,
  base `7cd6ca7771e7ad64418cb1808edf9460e9f6cc19`, open draft, unmerged.
- [Editor planning PR #21](https://github.com/KaisAbiyyi/sibambo-editor/pull/21), head `e0522bf4ddba45fdd72a9213ca0d50319dabd52a`,
  base `04e4c1d1656e7c65b093d1667f556c3fdb4b5130`, open draft, unmerged.
- Actual fetched git refs, both root `AGENTS.md` files, Editor orchestration/README/architecture/data/verification,
  Builder IR, producer/compiler, assembly, identity/journal, stdio MCP and component receipts/workflows.

The complete private v1.5 master was read from Editor planning branch head
`d744f779befaa028dc84ed0d1c9241c7b4900f2d`, blob `3f68c1485455bd9f1a2b107cc42e8ef7e17f9521`.
The current public Stable edition is at Builder `ed61b3e55cbab306e1756e3c95e6bfae54cf6699`,
blob `8c4a2c211d0208237cc0d980885ba5962b09a8f9`.
The Notion page's older Editor SHA `9092c84…` is a historical pointer; the actual current document identity is recorded in the manifest.
GitHub #70 and planning PR bodies still reference v1.3; current v1.5 owner decisions prevail additively.
The newer planning branch is a document reference, not the selected runtime baseline: it does not contain the #13 consumer stack.
Do not run its app and infer #12's directory-count behavior is present.

The published public artifacts contain only Stable/shared-core audit material, source hashes and synthetic evidence.
The private consolidated plan and private Editor implementation were not copied here.

## Dependency findings and CI evidence

Full SHA/base/merge disposition is in [BASELINE-DISPOSITION.md](BASELINE-DISPOSITION.md).
Git ancestry independently confirms #12 is in #13 and Builder #66's merge is in main.
Editor #14 head and #13 squash commit have identical trees; the squash is not proof of main integration.
No #62 paths are present in Builder main. #69 adds release machinery, not required geometry/remote functionality.

| Exact component source | Provider evidence re-read | Audit interpretation |
| --- | --- | --- |
| Builder #62 `8fc6ebb…` | [42036423066](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42036423066), Ubuntu/Windows jobs and exact-source assertion steps successful | PASS bounded house compiler/journal/readback evidence; independently re-ran its 14 focused tests in cloud. |
| Builder #69 `253725b…` | [42438706764](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42438706764), all three jobs successful, including cross-OS archive comparison and expected release block | Preserve Packaging Ready PASS / Release Approved BLOCKED. No release/archive publication performed. |
| Builder #66 `437277e…` | Merged as `ab4d869…`; original [42380405750](https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/42380405750) receipt records 44 tests per OS | Historical component evidence retained; current main full regression rerun includes this adapter. |
| Editor #12 `b5f46a7…` | [41948209524](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/41948209524), [41948209540](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/41948209540) reported success | Its regressions are re-run at selected #13 head, not assumed from old CI. |
| Editor #13 `98b01dc…` | [42417192657](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42417192657), Ubuntu/Windows jobs, source reproduction, consumer tests, check/types/build steps successful; retained BMB-021 [42417192633](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42417192633) and BMB-005/007 [42417192641](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42417192641) successful | Current head has evidence beyond the stale #13 body, which names `9570d8d…`. Fresh cloud consumer/build/browser checks below use `98b01dc…`. |
| Editor #14 `7d03a40…` | [42360761963](https://github.com/KaisAbiyyi/sibambo-editor/actions/runs/42360761963) successful | File preview only. Fresh browser rerun on #13 retains read-only boundaries. |

Provider workflow lookup is PR-triggered/first-page only; an empty result for Builder main does not prove absence of push CI.
Job metadata and workflow commands were inspected; historic test counts are attributed to the existing receipts rather than claimed as newly executed Windows tests.
All new execution in this audit used cloud Linux. No Windows-native test or new subjective/native acceptance is claimed.

## Architecture readiness against v1.5

These are source findings, not new implementations. Future acceptance suites remain NOT_RUN.

| Required contract | Existing source and gap | Owning work |
| --- | --- | --- |
| Canonical typed Module IR | `schemas/module-ir-v1.schema.json`, `compile_document`, assembly/validator exist. MCP writes generic journal blocks, while supplied IR is validated separately. No canonical typed project transaction owner. | SE-01 defines operations/helpers; SE-02 owns canonical map. Never infer IR from generic journal contents. |
| Atomic 1–8 modules | Existing `ModuleStore.apply` is module-local; assembly requires reciprocal ports and one seam owner. New operation envelope, staged clone, project CAS and atomic swap are absent. | SE-01/02; both seam participants staged before validation; partial transactions reject. |
| Fenced single writer/revisions | Existing module CAS/idempotency/journal recovery are useful but do not provide tenant/project/epoch/fence ownership. | SE-02/08; one mutex, one writer, tombstones, deterministic request digest and explicit new-epoch restore. |
| Shared compiler/live geometry | `semantic_v12._shape_faces`, `_mesh`, `encode_semantic` implement real geometry. No public pure live projection/schema exists. | SE-01 extracts common intermediate, keeps golden bytes; SE-06 applies `R * M_world` exactly once to local Float64 positions. |
| Volatile drafts | Existing journals persist; current Editor holds local model state in page memory. No remote volatile actor exists. | SE-02/05/08; do not use disk JournalStore or browser durable storage for unsaved drafts. |
| Independent render ACK | Current stdio response and file-loader completion are not a WebSocket revision receipt. No draft socket or `DraftEventV1` handler. | SE-05/06; hash exact canonical strings before parsing, atomic multi-module scene swap, one ACK after render, rollback/disposal on render failure. |
| Owner-only Save/reopen | `+page.svelte::saveBomc` writes local authoring graph and acknowledges download dispatch. Builder preview intentionally disables Save. | SE-07 freezes exact epoch/revision/digest, compiles in RAM via Builder, owner BFF/CSRF only, original `BomcLoader.load` reopen. Agents cannot Save/export. |
| Owner→agent request inbox | Absent; v1.5 selected it. | SE-03.C/04.A/05.A: RAM requests, read-only agent tool, status channel separate from revisions. Requests never grant write capability. |
| Timeline/highlight | Absent; v1.5 selected it. | SE-06.A; separate temporary overlay material/disposal; SE-10 measures highlight on and off. |
| Optional Save receipt | Absent; selected for implementation, user opt-in at Save. | SE-07.A: unchecked one file, checked sidecar with exact BOMC hash; no IR/credentials and never required for reopen. |
| Camera policy | Existing file import can frame a model; that is not permission to auto-fit each live revision. | No Batch-1 follow-agent camera. SE-06.B deferred; preserve user camera across live revisions. |
| Agent guide/errors/owner checklist | Existing stdio guide is insufficient for remote typed tools. | Mandatory SE-03.A, SE-03.B and SE-11.A; do not omit them when interpreting old task bodies. |

Preserve 65,536-byte canonical-module data, 256 KiB requests and all stricter compiler caps.
Empty/all-deleted actor state needs its own representation because the existing nonempty IR/compiler contract must not be weakened.
Save of such a draft returns EMPTY_PROJECT. New schemas need actual hashes later; null is not a compatibility certification.

## Environment and authentication audit

Managed cloud environment was observed running/connected with current observations and enforced unrestricted HTTP policy.
Status metadata listed **no configured secret bindings, runtime variables or outbound identities**.
That observation describes this executor only, not the owner's Auth0 or hosting accounts.
Authenticated GitHub/Notion source access worked. Python 3.12.14, pinned jsonschema 4.23.0 and MCP SDK 2.3.0
were installed in an isolated audit venv; Bun 1.3.0 was installed in a task-local directory.
The preinstalled MCP SDK was 1.29.0 and was not mistaken for the selected 2.3.0 dependency.

| Surface | Verified now | Independently preparable | Owner input / actual blocker |
| --- | --- | --- | --- |
| Auth0 / PKCE S256 | Architecture and source absence checked; no tenant discovery or login tested | Registration inventory, redirect/issuer/audience/claim mapping checklist | Actual tenant, audience, client registrations, allowed callbacks and secret-store binding absent from audit inputs. Auth qualification NOT_RUN; blocks CP0/service onboarding readiness. |
| Remote Streamable HTTP/TLS | SDK 2.3.0 installs; existing real stdio SDK test negotiates `2026-07-28` in Builder suite | Exact dependency lock, protocol/client compatibility matrix after authorization | No staging resource URL, TLS/streaming endpoint or real-client receipt. Remote SDK/TLS/OAuth compatibility NOT_RUN, not inferred from stdio. |
| Tenant/project/agent authorization | Launcher-scoped stdio grants only; no remote subject/client/project grant/revocation source | Principal/scope mapping and negative test matrix | Must implement SE-02/03/09 and qualify wrong audience/tenant, revocation, stale fence and distinct client principals. Pairing code or clientInfo is never auth. |
| Editor BFF/cookies | Route tree has page/build endpoint, no MCP BFF/login/session service | Allowlisted service-origin and CSRF/session contract | Owner BFF OAuth registration and allowed origins; SE-04 implementation. Require opaque HttpOnly Secure SameSite=Lax cookies, no bearer localStorage. |
| WebSocket live delivery | No application draft socket/render-ACK path | Proxy capability inventory and event-schema review | Long-lived service, TLS WS proxy, Origin allowlist and single-use first-message ticket; SE-05/06 still absent. No ticket in URL. |
| Nonproduction hosting | Existing Editor preview CI/deployment links are historical evidence only | Container resource/retention/proxy checklist | Named staging origins/infrastructure owner/capacity, 30 s CPU/wall and 512 MiB worker bounds, one actor owner; no model logs/backups/swap/core dumps. Current hosting controls NOT_RUN. |
| Real Claude Code/Codex | No live external agent was run | Client version/identity/receipt template; synthetic input already pinned | Owner accounts/client registrations/consent and authorized staging needed. SE-11 remains NOT_RUN for both clients. |

The selected architecture remains Auth0/managed OAuth, same-origin Editor BFF, independent WebSocket feed
and long-lived Builder ASGI process. Existing Vercel page preview does not establish durable actor hosting.
No IdP/vendor purchase, credential provisioning, deployment or production changes were performed.
No credential values were read into audit output or committed.

## Verification record and reproducibility

Machine outcomes, source identities, commands and log digests are in [SE-00-VALIDATION.json](SE-00-VALIDATION.json).
The core bounded result is PASS: current main compiles original house IR to identical original binaries,
the independent Builder reader decodes both, original E4 material/count/house suite passes 80/80,
and retained preview browser suite passes 2/2 in actual cloud Chromium.
Editor check/shared types/production build pass; no complete Editor historical suite or new native gate is claimed.

Reproduce without integrating any patch (paths are examples for separate cloud checkouts):

```sh
git clone https://github.com/KaisAbiyyi/sibambo-bomc-builder.git builder
git -C builder checkout --detach 7cd6ca7771e7ad64418cb1808edf9460e9f6cc19
git -C builder worktree add --detach ../house 8fc6ebbeb1996889983bd6fff0958d1f9a7aaf00
git -C builder worktree add --detach ../interop 0e3ec262e98762969da66088d412f8beebb63523
git clone https://github.com/KaisAbiyyi/sibambo-editor.git editor
git -C editor checkout --detach 98b01dc16ae11f6712dd86de38541a1b889f699d
python -m venv audit-venv
audit-venv/bin/pip install jsonschema==4.23.0 mcp==2.3.0
```

Run `python -m unittest discover -s tests -v` in Builder with that venv,
the 14-test `test_bmb026_house.py` suite in `house`, and
`python editor/scripts/bmb026-verify-provenance.py house` (use absolute checkout paths).
For the current-main compiler proof, run from Builder with its modules on Python's path:

```python
import json
from pathlib import Path
from bomc.compiler.graph_to_bomc import compile_document
from tests.interop.reader import read
fixture = Path('../editor/packages/e4-import/src/bmb026-fixtures')
for name in ('baseline', 'revised'):
    compiled = compile_document(json.loads((fixture / (name + '.json')).read_text()))
    assert compiled.payload == (fixture / (name + '.bomc')).read_bytes()
    assert read(compiled.payload)['counts']['faces'] == 278
```

In Editor, `bun install --frozen-lockfile` with Bun 1.3.0, then set `BMB021_BUILDER_DIR`
to the absolute `interop` checkout and `BMB021_RUBY_FIXTURE_DIR` to its tracked synthetic fixture directory.
Run the **unchanged** eight-file command from `.github/workflows/bmb026-original-editor.yml`,
then `bun run check`, `bun x tsc --project packages/tsconfig.json`, and `bun run build`.
The audit used a temporary Playwright config outside repositories to run existing
`apps/editor/tests/bmb027-builder-preview.spec.ts` against the Node build with system `/usr/bin/chromium`.
It changed only runtime executable/baseURL configuration, not assertions or app source.

## Failures, limitations and approval boundary

- Existing #62 string-table failure and #69 shallow-history/Windows-line-ending archive failures remain in history;
  final component runs supersede them for their exact scope. Limits were not raised here.
- Historical full Editor missing-fixture failures remain unclosed; targeted 80/80 does not erase them.
- Remote architecture requirements fail a current-product-readiness assessment because their source does not exist yet;
  this is expected future SE work, not a claim that a live security test failed. Live/auth/performance/Save gates are NOT_RUN.
- Future integrated-SHA CI is NOT_RUN. Public schemas for remote draft operations/view/errors and a service dependency lock are missing.
- No paid provider call, real client run, performance threshold measurement, owner action or Windows-native execution occurred.
- Deployment endpoint policy, IdP tenant availability/cost and external accounts were not independently verified.

Audit completion does not set CP0/SE-00 Done. Owner disposition, exact integrated pins/qualification,
IdP/service inputs and separate Stable IMPLEMENT authority remain required.
See the actionable checklist and lock schedule in [baseline disposition](BASELINE-DISPOSITION.md).
Next eligible implementation tasks after that gate are SE-01 and SE-04, with every later AND dependency preserved.
