# BMB32 product gap audit — SIB-TWO-PHASE-001 v1.0



Inspected actual source, repository instructions, dependency manifests, tests, issues, PR metadata and Notion task schemas/rows. Main source pins at inspection:

| Surface | Verified state | Consequence |
|---|---|---|
| Builder main | `7cd6ca7771e7ad64418cb1808edf9460e9f6cc19` | Python headless core, Module IR, geometry, compiler, stdio MCP, context sessions and deterministic experiments exist. No remote product service. |
| Editor main | `04e4c1d1656e7c65b093d1667f556c3fdb4b5130` | SvelteKit/Three/Bun workspace; browser import and bounded local authoring. No hosted project/auth/collaboration APIs. |
| Builder BMB-026 #62 | Draft, open, `8fc6ebbeb1996889983bd6fff0958d1f9a7aaf00` | Accepted bounded house evidence does not mean its code is integrated in main. Preserve localized-window revision and compiler-budget workaround evidence. |
| Editor #12 / #13 | Open/unmerged predecessors; #12 `b5f46a761d1763241b60375cbb5f7110d62d99d2`; current #13 branch `98b01dc16ae11f6712dd86de38541a1b889f699d` | Original consumer fixes/proof are distinct from main readiness. |
| Editor BMB-027 #14 | Merged **into #13 feature branch**, merge `98b01dc...`; original head `7d03a40e19df3a8ee19ced02d0fcac8bec3a2944` | File picker read-only preview disables Save BOMC and Move; no live MCP bridge. Not merged into main. |
| Builder BMB-031 #69 | Draft open `253725b8143f08aa6e5fc0718e10235392e861f5` | Packaging Ready cloud PASS; Release Approved BLOCKED. Release is not a prerequisite for building the Stable slice from an authorized source pin. |
| Notion BMB registry | 31 Done, 031 Review; historical Last Done 027/028/029/030/032 | Preserve task-specific acceptance. Remove 96.9% as product-readiness proxy. |
| BMB-025/028 | `agentguide/controller.py::MCPClient.batch` uses scripted subprocess stdio batches; benchmark native provider tokens null | Real tools/compiler are used, but no autonomous real-model remote-live browser proof. |
| BMB-032 | `integration/generator/brief.py::lower`, `handoff.py::submit` | Deterministic single-row room proof; journal and IR produced separately; no site intelligence/native autonomous planning system. |

BMB-021 native synthetic Exact/visual acceptance was accepted by the owner on its recorded source/consumer pins. Keep that bounded receipt; do not request the same visual check again or generalize it to remote Save, arbitrary authoring, release, or complex round-trip. The local `BMB021-NATIVE-LOCAL-ACCEPTANCE.md` was re-read. Source/branch installation identities may since have changed; no new native check occurred here.

### Why the 32-task plan missed the product

1. It measured component completion, not a top-level end-to-end remote product invariant. A valid file compiler and a read-only file-picker preview could both be Done while the intended experience did not exist.
2. Journal generic JSON blocks, typed Module IR, and compiled geometry are separate sources. Current MCP exposes journal operations and supplied-IR validation, not an authoritative typed geometry-authoring transaction or compiler tool. A bridge cannot infer their equivalence.
3. Stdio launcher identity/private filesystem assumptions do not establish internet OAuth, pairing, tenant isolation, revocation or reconnect semantics.
4. File preview reload is not a live operation feed. There is no revision/frame acknowledgment path, draft owner, or explicit owner-only remote Save boundary.
5. Scripted controller/estimated tokens and a one-row deterministic survey adapter do not prove an autonomous architectural planner, a live model's reliability, or a client interview's validity.
6. Stacked merges and accepted evidence can leave default branches missing essential code. Baseline integration must precede new features; green component CI cannot fill that gap.

The remedy is **new product gates**, not reopening every accepted component task. Remote gates and Experimental research are a new ledger, SE-00…11 and XB-00…11. All inherited gates remain scoped.

