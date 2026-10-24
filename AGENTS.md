# Agent instructions — BOMC Modular Builder

## Universal execution board — direct successors only (2026-10-24)

This repository follows the universal project board policy on the Notion `Projects` page, covering CoSoS, Mind Place, Sibambo and its children, BOMC Modular Builder, and future projects. This rule supersedes old unrelated blocked-task and arbitrary one-card Up Next examples.

- **02 · Now:** all task(s) currently active or genuinely eligible, including parallel Ready/Claimed/Review/Local Gate/Owner Gate work only where the live AND-prerequisites, ownership, environment, consent and resource locks permit. Focus Lane does not itself alter task Status.
- **03 · Up Next:** **only directly dependent task(s) waiting for the current Now set**. A candidate must have at least one prerequisite in Now and every other prerequisite must be already accepted Done or also in Now. It must be actionable after the relevant Now work completes, subject to rechecking permissions, owners and locks. Do not put unrelated Blocked tasks, tasks blocked by work outside Now, or arbitrary later roadmap tasks here. A direct successor remains actually Blocked/NOT_RUN until gates pass. Multiple descendants can appear, but overlapping locks mean sequential execution. The lane is allowed to be empty when no direct successor exists.
- **01 · Last Done:** at most five recently accepted tasks; full project history stays in the database.
- **On each claim, merge, blocker/gate change and handoff:** recalculate the entire Now set and direct-successor Up Next from the live DAG, sync Notion/GitHub and verify, and remove stale lane selections without changing factual statuses. Task implementors critically self-review exact SHA/diff and CI/security/data/limits; independent reviewer is optional, never a required gate. Cloud CI does not substitute native/owner acceptance. Cloud tasks must not access local files.
