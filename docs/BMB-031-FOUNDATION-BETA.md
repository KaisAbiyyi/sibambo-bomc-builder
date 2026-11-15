# BMB-031 — Foundation Beta source candidate (provisional)

**State:** packaging preparation only. Not an approved release, tag or production deployment. **Lock:** release/checklist. **Issue:** #31. **Exact baseline main:** 7cd6ca7771e7ad64418cb1808edf9460e9f6cc19. Current candidate source SHA is generated from the exact checked-out HEAD at build time; it is not hardcoded into a tracked artifact.

## Version, compatibility, trust

- **Candidate label:** `0.1.0-beta.0` (planning label only; owner must approve final version and API/feature exclusions).
- **Runtime:** Python **3.12**; required `jsonschema==4.23.0`. Validation of the MCP SDK integration additionally uses `mcp==2.3.0`; stdio MCP server runtime itself uses stdlib.
- **Output:** BOMC **1.2** *Builder-supported semantic solid-color subset*, not general BOMC Exact/Visual, editable section 241, textures, arbitrary holed faces, roofs, or all producer features. See [BMB-020](BMB-020-COMPILER.md).
- **License:** GNU **GPL-3.0-only**; preserve root LICENSE and [BMB-003 decision](LICENSE-IP-FIXTURE-POLICY.md). This does not certify all third-party IP/attribution.
- **Source boundary:** separately authored Builder only; no Editor, Ruby producer, private client models, SKP exports, live AI keys, screenshots or original consumer code bundled.

The package script selects only committed paths declared in `release/foundation-beta.json`, takes **canonical Git blob bytes** (not Windows-autocrlf worktree bytes), rejects symlinks, large files and high-confidence embedded credentials/private paths, and writes a deterministic ZIP using fixed metadata and stored compression. This is bounded screening, **not historical git/secret provenance certification**. The archive deliberately excludes the PR #62 four-room implementation because it is not on main. Source SHA, tree SHA, every member SHA-256, ZIP SHA-256 and runtime dependencies are in `dist/release-manifest.json`. The ZIP is an ephemeral *candidate*, not a published distribution.

## Clean build on Linux (from an exact checked-out Git commit)

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install jsonschema==4.23.0 mcp==2.3.0
git rev-parse HEAD
python scripts/build_foundation_beta.py --out dist
python scripts/bmb031_smoke.py --report dist/smoke.json
python -m unittest discover -s tests -p 'test_bmb031_release.py' -v
python scripts/release_readiness.py --gate packaging --report-dir dist/readiness
python scripts/release_readiness.py --gate release --report-dir dist/readiness
```

The last command **must exit 4** while owner and integration gates are unresolved. An exit 0 there without actual owner approval requires investigation. Do not interpret a packaging exit 0 as release approval.

## Clean build on Windows 10/11, PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install jsonschema==4.23.0 mcp==2.3.0
git rev-parse HEAD
.\.venv\Scripts\python.exe scripts\build_foundation_beta.py --out dist
.\.venv\Scripts\python.exe scripts\bmb031_smoke.py --report dist\smoke.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_bmb031_release.py -v
.\.venv\Scripts\python.exe scripts\release_readiness.py --gate packaging
.\.venv\Scripts\python.exe scripts\release_readiness.py --gate release
Get-FileHash dist\*.zip -Algorithm SHA256
```

Hosted Windows CI tests the code on GitHub-runner Windows. It is **not** owner-native ACL, Job Object, host-specific, SketchUp or visual qualification.

## Direct CLI and stdio MCP startup

A trusted operator chooses an **absolute** writable journal/project directory. On Linux, use a private owner-only directory for the MCP server, for example `mkdir -m 700 /tmp/bmb-private-project`. Do not expose stdio MCP to an untrusted host without OS isolation.

```sh
python -m cli.bmb --root /tmp/bmb-journal create --module-id release/synthetic
python -m cli.bmb --root /tmp/bmb-journal inspect --module-id release/synthetic
python -m cli.bmb --root /tmp/bmb-journal validate
python -m agent.bmb_mcp --root /tmp/bmb-private-project
python -m agent.bmb_mcp --root /tmp/bmb-private-project --allow-writes
```

The second MCP form intentionally grants mutation to the trusted launcher. On Windows replace the project root with an approved absolute private Windows directory and independently verify restricted DACL/host Job Object before considering native security PASS. This modern MCP server uses **2026-07-28** `server/discover`, not legacy `initialize`. See [BMB-023](BMB-023-STDIO-MCP.md).

## Synthetic create → validate → compile → inspect

```sh
# Journal lifecycle: create, inspect and validate persisted synthetic module.
python -m cli.bmb --root /tmp/bmb-demo create --module-id release/synthetic
python -m cli.bmb --root /tmp/bmb-demo inspect --module-id release/synthetic
python -m cli.bmb --root /tmp/bmb-demo validate

# Separate typed synthetic Module IR input; it is NOT reconstructed from that journal.
python -m bomc.compiler.graph_to_bomc --input examples/bmb020-semantic-floor.json --output /tmp/bmb-floor.bomc

# One automated command additionally independently parses the generated BOMC and
# checks decoded nonzero geometry and the real file hash.
python scripts/bmb031_smoke.py --report dist/smoke.json
python -m tests.interop.goldens --check
```

**Expected:** journal inspect revision 0, journal validation with one module, BOMC v1.2 semantic solid-color 3D file (nonzero faces/triangles and geometry sections 5–9), real SHA256 equals compiler receipt, independent Builder reader accepts. A generated binary is **not** an original Editor/Model-Eval consumer PASS. The `bmb031_smoke.py` fixture is deliberately separate from journal assembly: journal block → typed Module IR adapter is not claimed. The goldens command is available in a full repository checkout, not the source ZIP.

## Manifest and readiness results

`release/foundation-beta.json` is the versioned **plan**. At exact HEAD:

- `dist/bomc-builder-foundation-beta-<version>-<sha12>.zip` — unapproved reproducible source-only candidate.
- `dist/release-manifest.json` — exact source/tree SHA, ZIP filename/size/SHA256, per-file source hashes, BOMC profile, dependency and license declarations.
- `dist/provenance-report.json` — declared IP/fixture and dependency status with unresolved audits.
- `dist/readiness/readiness.json` + `.md` — **separate** `packagingReady` and `releaseApproved` verdicts with errors/blockers.

`scripts/release_readiness.py --gate packaging` exits 0 only if required documents, licensing declarations, ledger shape, exact checkout source SHA, archive hash and inventory match. `--gate release` exits 0 only if every mandatory gate has accountable PASS (or owner-authorized exclusion), licensing provenance has been accepted and every owner decision has been recorded. All PASS references must contain an exact SHA, PR URL, workflow run and qualified scope. Existing historical references do not become exact-current-HEAD evidence by being listed: historical SHA PASS remains a release blocker until requalified on current HEAD. Even if all owner approval flags are set, a source-SHA-specific owner Issue #31 comment reference is also required; its authorship must be independently checked on GitHub. The validator cannot authenticate commenters without network access.

The CI workflow uses SHA-pinned actions, checks out the PR **head** exactly, runs the script, verifier, smoke and Builder regressions on Ubuntu and Windows. Only JSON/Markdown reports are retained as CI artifacts; the source ZIP is **not published or uploaded**. Repeating the package build must give the same archive hash.

See [provenance](BMB-031-PROVENANCE.md), [acceptance ledger](../release/acceptance-ledger.json) and [owner handoff](BMB-031-OWNER-HANDOFF.md).
