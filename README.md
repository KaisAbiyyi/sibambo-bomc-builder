# sibambo-bomc-builder

> **Product architecture update — 2026-11-08:** the [two-phase MASTER IMPLEMENTATION PLAN](docs/two-phase/MASTER_IMPLEMENTATION_PLAN_2026-11-08_SIB-TWO-PHASE-001_v1.0.md) governs new Stable Editor remote MCP/live draft/owner Save delivery and the separate **EXPERIMENTAL** native agentic application. This older document is retained as foundation/history; its task/component completion is not product readiness. [Gap audit](docs/two-phase/GAP-AUDIT.md) · [ADRs](docs/two-phase/ADR-LEDGER.md) · [task contracts](docs/two-phase/TASK-CONTRACTS.md) · [Notion/GitHub resource map](docs/two-phase/RESOURCE-MAP.md). No product implementation/deployment/release is performed by this documentation update.


Headless, agent-operable modular building construction into a deterministic compiled BOMC 3D document. **Incremental implementation:** a bounded Python journal/assembly CLI is available (BMB-022); MCP, full geometric construction and compiler/consumer proof are separately gated.

## Available headless CLI

The cloud-tested command-line interface uses the existing journal and assembly core to create, inspect, edit, roll back and validate synthetic projects. See [BMB-022 CLI contract](docs/BMB-022-HEADLESS-CLI.md). It does not compile final BOMC files or validate geometric collisions.

## Project planning
- [Technical BOMC research](docs/BOMC-RESEARCH.md)
- [Pinned BOMC 1.2 producer contract (BMB-001)](docs/BOMC-PRODUCER-CONTRACT.md)
- [Forward-compatible BOMC versioning / adapter policy](docs/BOMC-VERSIONING.md)
- [Modular architecture & invariants](docs/ARCHITECTURE.md)
- [Roadmap through December 2026](docs/ROADMAP.md)
- [Agent construction guide (proposed tools)](docs/AGENT-CONSTRUCTION-GUIDE.md)
- [32 small cloud-first tasks / acceptance criteria](docs/TASK-INDEX.md)
- [Standalone Notion Project Hub](https://app.notion.com/p/402c4a6aaf738181adf0eb95320ff947)

BOMC source/consumer implementations are currently maintained in separate repositories, and the publicly licensed portions of those implementations must not be assumed reusable here. **BMB-003 owner decision (2026-10-23):** retain GNU GPL-3.0, owner-attested original-code ownership, independently written clean-room Builder (do not import or copy the private Editor kernel), and **synthetic-only public fixtures**. See the [License/IP/Fixture Policy](docs/LICENSE-IP-FIXTURE-POLICY.md) for scope and unverified provenance gates. No other repository or local files were changed.
