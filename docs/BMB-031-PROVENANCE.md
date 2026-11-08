# BMB-031 — GPL, IP and provenance qualification

This is an inspectable **bounded provenance declaration**, not legal advice, an independent chain-of-title audit or authority to publish.

## Binding decision and inspected source boundary

- Owner's [BMB-003 policy](LICENSE-IP-FIXTURE-POLICY.md): **GNU GPL-3.0-only**, originally authored and independently developed Builder; do not copy, port or vendor private Editor/producer/Model-Eval implementation. The owner's authorship assertion is an **attestation**, not verified historic contribution or contract evidence.
- Root `LICENSE` must remain the full GNU GPL **Version 3**; `scripts/release_readiness.py` checks this and the policy text. Reopen license scope only through owner decision.
- Archive inventory is the Git-tracked, selected Builder packages and explicitly named synthetic examples plus public documentation and one independently written Builder reader. Member bytes are retrieved from exact-HEAD Git blobs to prevent checkout line-ending changes from altering the release SHA across operating systems. `dist/release-manifest.json` hashes every included byte. No Editor package, Ruby producer, native binary or client model is intentionally included.
- `examples/bmb020-semantic-floor.json` and `examples/module-ir-two-rooms.json` are repo-authored synthetic inputs documented under BMB-020/BMB-007. No real house, private SKP, customer site or personal data is authorized. These particular human-authored fixture inputs do not carry a universal generator seed; per-fixture seed/authorship chain remains **unverified**, not invented.
- Archive checks detect known token prefixes, Windows private home/project paths, symlinks and member/path/hash anomalies. They **cannot** prove clean history, absent unknown secrets, third-party copyright title or sole ownership.

## Dependency and redistribution inventory

| Item | Pin / origin | License / status |
|---|---|---|
| Builder source | exact source SHA in generated manifest | Owner-selected GPL-3.0-only; independent historical IP proof **NOT_RUN** |
| Python runtime | Python 3.12 | CPython redistribution and all platform obligations not independently audited for any binary redistribution; source package includes no Python binary |
| `jsonschema` | PyPI `jsonschema==4.23.0` | MIT declared; complete direct/transitive notices/source inventory **NOT_RUN** |
| MCP SDK (test only) | PyPI `mcp==2.3.0` | Declared MIT; full dependency tree and redistribution review **NOT_RUN**; no SDK vendored into archive |
| Vendored MCP reference schema | `tests/fixtures/mcp-2026-07-28-schema.json` from upstream pinned commit under BMB-023 | Upstream MIT/Apache-2.0 reference notice tracked as `tests/fixtures/mcp-upstream-LICENSE.txt`; **both excluded** from the source-only candidate archive. Repository/test distribution still requires preserving notice; third-party audit incomplete |
| BOMC synthetic examples | source paths listed in plan | Human-authored synthetic intent; rights/seed attestations not independently verified |
| BMB-021 synthetic BOMC goldens | Builder test assets | Excluded from source archive; test/CI provenance is not proof of production input provenance |
| Editor, Model-Eval, Ruby producer, Rooms detector, silabs-generator | separate repositories/consumers | **Not vendored**, integration/redistribution authority not inferred from public metadata |

Pinning runtime versions does **not** pin the full transitive wheel hashes; dependency supply-chain audit and SBOM generation are separate release actions. Any actual redistribution of third-party wheels/assets requires original licenses/attributions and source obligations to be checked with owner approval. No license unknowns are silently converted to PASS.

## Unresolved release qualifications

1. Independent author/contributor, employer/client contractual ownership, and full repository-history asset/secret review.
2. Transitive runtime/SDK dependency license, notices and wheel hash/SBOM review.
3. Per-example creator/seed provenance and any permissions required for public reuse.
4. Original Editor/Model-Eval consumer integration and native Windows acceptance; these are **not** license conclusions.
5. Owner acceptance of exact archive/version/feature exclusions; no approved tag or publication.

See `dist/provenance-report.json` for source-SHA-specific file inventory counts, observed installed `jsonschema`/optional `mcp` distribution version and license metadata, their declared dependency requirements and unresolved exceptions. These are package metadata observations, not a transitive license audit. A reviewer must inspect the actual archive and independent source/third-party evidence before setting provenance gates to PASS.
