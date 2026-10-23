# BMB-003 — License/IP and public fixture decision

**Owner decision:** 2026-10-23 (Asia/Jakarta). **Status:** owner-approved scope and documentation-only audit, not a legal opinion or release certification. [Tracking issue](https://github.com/KaisAbiyyi/sibambo-bomc-builder/issues/3).

## Owner's binding decisions

1. **License:** keep GNU **GPL-3.0** for the public `sibambo-bomc-builder`. Do not migrate to MIT/Apache, add “or later” rights, change `LICENSE`, or dual license without further explicit owner approval.
2. **Authorship:** owner attests original Sibambo source is entirely owned by the owner. This is an **owner declaration**, not independently verified chain-of-title evidence; third-party dependencies, employer/client contributions, textures, assets and datasets are not covered by the attestation.
3. **Clean-room:** independently author new builder code from a written format specification and observable public interface contract. **Do not copy, port, vendor, mechanically translate or import** producer/Editor/Model-Eval implementation code, even if owner-authored. Specifically do not import private `@sibambo/bomc-document` as a runtime/code dependency. Compatibility test consumers separately; never assume importing a private package is allowed merely because a repository has a GPL license. Strict legal clean-room isolation requires separately documented spec reviewers and implementors; this documentation audit does **not** certify that.
4. **Public fixtures:** **synthetic-only**. Generate wholly invented dimensions, synthetic geometry, generated fake metadata and textures with verified publishing rights. Public code, golden `.bomc`, screenshots, sample manifests, benchmarks, logs and CI artifacts must not contain real houses, imported SKP/BOMC exports, client/site information, private personal data or proprietary artwork. “Anonymizing” a real house is **not** the same as synthetic. Exceptions require a new explicit owner decision and evidence.

## Evidence and source inventory (bounded, 2026-10-23)

| Item | Checked evidence | Policy |
| --- | --- | --- |
| [Builder LICENSE](https://github.com/KaisAbiyyi/sibambo-bomc-builder/blob/main/LICENSE) | GNU GPL version 3 text committed; current Builder contains planning docs, not an executable writer. | Keep existing license unchanged. |
| [Editor root LICENSE](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/LICENSE) / [workspace package](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/package.json) | GPL v3 text; package declares `GPL-3.0-only` and `private:true`. | No implementation copying; interfaces only as compatibility constraints. |
| [Editor bomc-document](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/packages/bomc-document/package.json) / [README](https://github.com/KaisAbiyyi/sibambo-editor/blob/main/packages/bomc-document/README.md) | `@sibambo/bomc-document@0.1.0`, `private:true`, `fflate ~0.8.2`, restricted `web-core-v1` authoring subset. | Do **not** import/vendor/translate its code; verify with independently written consumer tests. `private:true` is package-publication metadata, **not** a legal license by itself. |
| [BOM Engine LICENSE](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/main/LICENSE) / [format spec](https://github.com/KaisAbiyyi/sibambo-bom-engine-plugin/blob/main/BOM_COMPILED_FORMAT.md) | GPL v3; written BOMC binary specification. | Use documented wire behavior for independent interoperability; no copied source. |
| [Model-Eval LICENSE](https://github.com/KaisAbiyyi/sibambo-model-eval/blob/main/LICENSE) / [consumer docs](https://github.com/KaisAbiyyi/sibambo-model-eval/blob/main/docs/BOMC_MODEL_EVAL.md) | GPL v3; consumer doc mentions 1.0/1.1 (1.2 not proven here). | Consumer-only evidence; must version-pin actual tests for 1.2 claims. |
| Third-party packages and fixture inputs | Builder new runtime dependencies/fixtures: **none in this change**; full transitive audit not performed. | Assess licenses, attributions, source obligations, asset permissions **before** future addition. |

Owner's attestation does not substitute for historical contributor/contract/license review. No full git-author, employer-IP, media-provenance, or dependency-tree audit was performed; record those limits honestly.

## Release and PR guardrails

- For every new source file, dependency and asset: record source, author, license, version, provenance, redistribution rights and required NOTICE/source obligations. Unknown origin = **BLOCKED**, never “implicitly permitted”.
- For each synthetic fixture: keep generator path/version, seed, invented parameters, test intent, generated artifact SHA256 and assertion coverage. Never create public fixtures by editing/anonymizing real SKP/BOMC.
- Reference format documentation and independent expected behavior; keep Builder source originally authored. Do not paste private source, translated snippets, copied test datasets, client data, embedded meshes or textures into code/fixtures/PR text/CI artifact.
- Ahead of publication: review git diff and public history for unlicensed source, real geometry, personal information, third-party attribution and credentials; independently validate consumer acceptance. A clean diff does not prove historical cleanliness.
- Link this policy from BMB-002 (writer compatibility), BMB-005 (consumer matrix), BMB-007 (fixtures), BMB-031 (release).
- Reopening GPL choice, code reuse or real fixtures requires a new owner authorization and recorded rationale.

## BMB-003 audit qualification

- **PASS:** explicit four-item owner decision captured; current source license/package evidence inspected.
- **NOT_RUN:** independent proof of historical sole ownership/third-party chain of title; all dependency and asset licensing; builder clean-room implementation; synthetic golden generation; executable tests; Editor/Model-Eval readback; native/Windows validation.
- **CI:** report check and workflow state on the exact PR SHA; missing checks or workflows are **NOT_RUN**, not PASS.
- Completing this documentation/policy task is not proof that a future Builder binary is licensed, compatible, or release-ready.
