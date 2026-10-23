# sibambo-bomc-builder

Headless, agent-operable modular building construction into a deterministic compiled BOMC 3D document. **Planning phase**; no CLI/MCP or executable geometry builder has shipped yet.

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
