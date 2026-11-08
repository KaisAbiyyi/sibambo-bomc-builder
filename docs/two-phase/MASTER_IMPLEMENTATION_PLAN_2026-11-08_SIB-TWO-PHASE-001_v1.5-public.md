# MASTER IMPLEMENTATION PLAN v1.5 — public edition (Stable + shared core)

ID: **SIB-TWO-PHASE-001** · Version: **1.5 — CURRENT** · Date: **2026-11-08, Asia/Jakarta**

The owner accepted v1.4 and recorded decisions D1–D9 on 2026-11-08. The full v1.5 text is kept in the private project workspace because, under owner decision D7, the Experimental (Batch 2) application is proprietary and specified privately. This public edition carries only what concerns the Stable remote MCP workstream and the shared Builder core. Nothing in v1.3 or v1.4 is withdrawn by this edition; it adds the decisions below.

## Decisions relevant to this repository

- **D1 · v1.4 accepted.** v1.4 is normative together with v1.3 (see `MASTER_IMPLEMENTATION_PLAN_2026-11-08_SIB-TWO-PHASE-001_v1.4.md` on this branch).
- **D2 · Stable (Batch 1) scope.** In scope: Required SE-03.A (remote construction guide + agent-grade tool descriptions), SE-03.B (typed error catalogue), SE-11.A (owner acceptance checklist), and the selected SE-03.C/SE-04.A/SE-05.A owner → agent request inbox (TP-020), SE-06.A activity timeline + changed-module highlight, and SE-07.A opt-in Save receipt. SE-06.B follow-agent camera is deferred to the SE-12 parking lot. SE-11's window-revision step is performed by the agent reading the inbox; the v1.3 owner typed-parameter revision remains in scope and tested. Critical path and SE-11 dependencies are unchanged. These are acceptance checklists inside their parent SE tasks, not separate DAG nodes.
- **D4 · Board rule.** Now = every task that can be worked on right now (many cards are fine when parallel). Up Next = every task whose blocker is in Now. Last Done = at most 5. Current projection: Now SE-00; Up Next SE-01, SE-04.
- **D7 · Licensing.** The Stable remote MCP service stays open source in this repository (GPL-3.0) where possible; a later client decision could change that only through a new plan version. The Experimental application is proprietary and lives in a separate private repository. This repository receives only generic shared-core changes (for example a future Module IR v1.1 schema proposal for stairs/roofs/ceilings and public projection schemas). No Experimental code, prompts, fixtures or client data is added here.

The Experimental phase gate is unchanged: no Experimental work runs before Stable SE-11 is accepted by the owner.
