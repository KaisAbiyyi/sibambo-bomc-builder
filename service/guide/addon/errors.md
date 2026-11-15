# Recovery

- SERVICE_OFFLINE: ask the owner to run `node tooling/local-demo/launch.mjs`.
- EDITOR_OFFLINE: open the Editor, create/open an authoring document, press Hubungkan agent.
- EDITOR_TIMEOUT: the Editor may still finish; call describe_scene before retrying a mutation.
- NO_EDITABLE_DOCUMENT: ask the owner to open an editable document.
- PAUSED_BY_OWNER: tell the owner and wait; reads remain available.
- BUSY: send one call at a time and retry after the suggested delay.
- LEASE_HELD: another client has the writer role; wait retryAfterMs.
- STALE_REVISION: inspect the current scene and rebuild the change.
- INVALID_ELEMENT / INVALID_GEOMETRY / INVALID_COMMAND: fix the reported input; rejected changes do not commit.
- MODULE_DETACHED: the owner edited inside a managed group; tell the owner, who may Undo that edit.
- MANAGED_MODULE: use edit_model rather than freeform operations on managed architecture.
- UNDO_NOT_AGENT / NOTHING_TO_UNDO: do not attempt to undo owner work.
- BUDGET_EXCEEDED: reduce call/module size to the documented budgets.
