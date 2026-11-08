# BMB-031 — Owner acceptance handoff (STOP BEFORE MERGE/RELEASE)

**Decision requested:** determine whether a restricted **Foundation Beta** is acceptable; **do not publish/tag/merge by default**. The planned candidate version `0.1.0-beta.0` is not owner-approved.

## Packaging and evidence

1. Open BMB-031 draft PR, inspect its exact HEAD, Builder workflow jobs/logs, `dist/readiness/readiness.json`, and the scoped diff. Confirm source SHA in the generated manifest equals the tested PR HEAD.
2. Reproduce in a **clean** Linux/Windows checkout at that commit using commands in [release instructions](BMB-031-FOUNDATION-BETA.md). Verify ZIP SHA256 and each manifest-listed file. The CI archive is deliberately **not** uploaded/published.
3. Review [provenance](BMB-031-PROVENANCE.md) and BMB-003 GPL-only/clean-room/synthetic decisions. Obtain actual third-party license/notice, asset ownership, source history and dependency SBOM proof where required.
4. Check the [machine ledger](../release/acceptance-ledger.json): only narrow exact-SHA historical Builder tests are PASS. Issue/PR completion is not equivalent to consumer acceptance. `releaseApproved=false` is expected.

## Original integrations to resolve separately (NO AUTOMATIC MERGE)

- **Builder #62, BMB-026**: draft/unmerged four-room synthetic BOMC house and localized revision; its exact-head hosted Builder tests and artifacts do not mean its source is on Builder `main`. Independent accept, merge by explicit owner instruction, then rerun Builder main/exact-tree.
- **Editor #12**: original E4 semantic reader/CRC count corrections; draft/unmerged into Editor main.
- **Editor #13**: original E4 four-room consumer and matching browser evidence; draft/unmerged into Editor main; stacked on Editor #12 (and earlier Editor #14 merged *into #13*, not Editor main). Review base relationship and merge order with owner authorization. Perform fresh exact-tree checks.
- **Original Model-Eval**: no certified BOMC 1.2 full semantic pairings. Execute real original Model-Eval consumer readback/corruption tests against the **same exact** Builder release binary and record hashes and version.
- **BMB-028 four-room baseline**: synthetic scripted two-room benchmark passed, but four-room scenario and provider-native token measurement are NOT_RUN. Run the four-room baseline after Builder #62 integration if within approved beta scope.
- **Rooms detector**: BMB-029 adapter is optional/synthetic; a real Rooms detector integration and calibration is NOT_RUN.
- **Generator**: BMB-032 proof demonstrates proposed survey/form/brief over the shared MCP surface; real silabs-generator adoption is NOT_RUN.

## Owner/local Codex Windows commands and evidence

Use an owner-controlled checkout at the PR's exact commit and a trusted private project folder; commands below are templates, replace the exact commit only from the PR and use approved OS ACLs. No background cloud session should touch the owner's local machine.

```powershell
git fetch origin
git checkout --detach <BMB031_EXACT_PR_SHA>
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install jsonschema==4.23.0 mcp==2.3.0
.\.venv\Scripts\python.exe scripts\build_foundation_beta.py --out dist
.\.venv\Scripts\python.exe scripts\bmb031_smoke.py --report dist\smoke.json
.\.venv\Scripts\python.exe scripts\release_readiness.py --gate packaging
.\.venv\Scripts\python.exe scripts\release_readiness.py --gate release
Get-FileHash dist\*.zip -Algorithm SHA256
```

The release gate must currently exit **4**; this is expected, not a security waiver. Record exact source SHA, Python version, artifact checksum, test output and host environment. For the MCP native gate, only after configuring a restricted Windows DACL and Job Object, start:

```powershell
.\.venv\Scripts\python.exe -m agent.bmb_mcp --root <ABSOLUTE_PRIVATE_PROJECT_DIR>
.\.venv\Scripts\python.exe -m agent.bmb_mcp --root <ABSOLUTE_PRIVATE_PROJECT_DIR> --allow-writes
```

Use a separately authorized real host client. Document ACL/DACL, process memory/CPU limits, link/reparse and co-tenant tests, crash/restart/recovery, cancellation, and protocol/security outcomes. Hosted `windows-latest` does not substitute for this owner-native evidence.

Perform original Editor E4 import/preview and subjective appearance checks for **both** exact BMB-026 baseline/revised binaries, including fixed camera/display settings and void geometry; additionally original Model-Eval real readback. Attach exact binary SHA256, consumer app version/commit, tests, screenshots and observed counts. Do not copy any private fixture/assets into a public Builder release package.

## Scope decisions required from owner

- Decide whether Foundation Beta excludes original Editor/Model-Eval, provider tokens, Rooms calibration, native security and original generator adoption; explicitly record each exclusion, rationale and version-bound limitation before considering an owner-approved restricted beta.
- Authorize (or deny) individual integration merges of Builder #62 and Editor #12/#13.
- Sign off on native-security and visual acceptance based on actual evidence, not a hosted runner.
- Approve exact release version, tag/contents, dependency/license inventory and publishing location.
- Record the exact HEAD-specific owner authorization as an authenticated GitHub Issue #31 comment, retain its URL and actor in `owner_authorization`, and independently inspect it. Boolean approval flags alone are not sufficient evidence; historical CI SHA values require current-head requalification before release approval.
- Re-run final exact-head acceptance and update the ledger/validator only after these decisions. No fabricated FAIL/NOT_RUN → PASS, and no automatic tag, GitHub Release or publication.

**Foundation Beta packaging readiness** means a reproducible, inspectable, GPL-policy-aligned Builder source candidate with bounded synthetic smoke and exact-SHA cloud checks. **Full integration/production readiness** additionally needs original consumers, real agents/provider accounting, real Rooms/generator integration, native security, security/privacy provenance, operational support and owner authorization. They are **not synonyms**.
