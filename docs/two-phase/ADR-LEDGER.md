# Two-product ADR ledger — SIB-TWO-PHASE-001 v1.3

Date:2026-11-08 Asia/Jakarta. Decisions preserved from v1.0; v1.3 locks cross-runtime byte hashing and credential-principal identity. Implementation NOT_STARTED.



| ADR | Decision and alternatives rejected | Consequence / owner |
|---|---|---|
| TP-001 | Two products in strict sequence: Phase1 Stable accepted through SE-11, then Phase2 Experimental; future Experimental repo/brand TBD. Reject embedding an autonomous planner in Editor. | Separate budgets/backlogs/processes; Builder shared core owner. XB-00 depends on accepted SE-11; no Experimental execution/claim before that gate. |
| TP-002 | Remote MCP Streamable HTTP over TLS; fixed researched protocol 2026-07-28, compatibility probe for actual clients. Reject stdio tunnelling/localhost listener/browser extension as primary product transport. | MCP clients do not need access to owner filesystem. No deploy occurs in this planning session. |
| TP-003 | Browser live feed is application WebSocket, independent of MCP notifications/sessions. Reject full BOMC reload each edit and assuming MCP GET/SSE session semantics persist in 2026. | Browser sees exact ordered revisions even when agent client has no subscription support. |
| TP-004 | Volatile drafts only before Save. Reject default automatic journal/IndexedDB/server model persistence. | Unsaved draft lost if both service and page disappear. RAM state/revisions/replay retained within TTL; recovery is explicit. |
| TP-005 | Typed canonical Module IR plus in-memory ModuleStore CAS, one fenced project writer at a time with bounded multi-module atomic transactions. Reject CRDT/OT and simultaneous independent per-module writers for v1. | Simpler deterministic seam/revision correctness; multiple agents read and take turns; disjoint parallel writers require a future plan. |
| TP-006 | Auth0 Auth for MCP + Universal Login is the managed authorization server recommendation, OAuth PKCE S256; Editor BFF opaque cookie, grant bound to tenant/project/subject/client. Reject self-built passwords, bearer URLs or pairing-code-as-auth. | SE-00 needs actual tenant/audience/client registration/environment receipt; missing configuration blocks dependent implementation, not architecture improvisation. Auth0 access/cost not assumed purchased. |
| TP-007 | One shared Python face/mesh projection and compiler, Editor consumes public typed view schema. Reject separate TS geometry generation and GPU-as-document. | No duplicate geometry math, loss of fidelity or private source transfer. |
| TP-008 | Owner-only Save freezes r, compiles/validates in RAM, downloads exact BOMC. Reject agent export/save capability or auto-export on operations. | Browser dispatch is acknowledged, actual file retention is owner evidence. Cloud saved-project storage is out of initial Stable scope. |
| TP-009 | Native Experimental coordinator/state machine calls direct Builder API. Reject reusing BMB-032 MCP orchestration as internal architecture or a swarm framework. | Existing legacy handoff remains a compatibility adapter; new app can optionally expose an external MCP adapter later only by new plan. |
| TP-010 | Constraint solver+deterministic geometry, with LLM reasoning restricted to typed briefs/zoning/critique. Reject unconstrained mesh/code generation as foundation. | CP-SAT experiment versus deterministic baseline; learned layouts only candidates, not accepted geometry. |
| TP-011 | Evidence provenance and user-confirmed needs, no psychological diagnosis/personality score. Reject false precision from map pin/weather grids and unsupported psychometrics. | Site/needs/interview research independently qualified. Architecture outputs remain schematic EXPERIMENTAL. |
| TP-012 | Configurable BYOK providers; Qwen ~27B notebook experiments, Claude API candidate after measured comparison. Reject hard-coded provider/hidden fallback or Colab production service. | Per-run spend/usage/cancellation and credential retention boundaries mandatory. |



Normative detailed protocol, invariants and patch contracts: [MASTER_IMPLEMENTATION_PLAN_2026-11-08_SIB-TWO-PHASE-001_v1.3.md](MASTER_IMPLEMENTATION_PLAN_2026-11-08_SIB-TWO-PHASE-001_v1.3.md).
