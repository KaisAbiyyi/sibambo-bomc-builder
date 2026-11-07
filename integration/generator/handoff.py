"""Submit a normalized brief through the SAME stdio MCP tools any agent uses (no private back door).

Flow, every step inspected before the next write is built:
  1. discover the server and require the five tools this contract uses;
  2. read which modules exist (`bmb_validate_journals`), refuse a brief that would drop rooms;
  3. per room: create when missing, inspect, then write ONLY the blocks that differ, at the revision
     just observed, with an idempotency key derived from (module, observed revision, desired blocks);
  4. validate the lowered Module IR with `bmb_validate_assembly`.
Resubmitting the same brief therefore performs no write, and a change to one room touches that
room's journal only. The generator never supplies a path: the host owns the project root.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agentctx.budget import canonical, digest
from agentguide.controller import MCPClient, PROTOCOL, ControllerError, _error_code, _ok, _tool
from integration.generator.brief import (
    BriefError, brief_sha256, journal_blocks, lower, module_id, to_brief,
)

# The only journal blocks this contract writes. Anything else in a module (another agent's notes) is
# neither compared, replaced nor removed.
OWNED_BLOCKS = frozenset({"room", "door-east"})

REQUIRED_TOOLS = {"bmb_create_module", "bmb_inspect_module", "bmb_edit_module",
                  "bmb_validate_journals", "bmb_validate_assembly"}


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise ControllerError(why)


def _ops(current: dict, desired: dict) -> list:
    """add / replace / remove operations that turn the OWNED observed blocks into the desired ones."""
    current = {name: value for name, value in current.items() if name in OWNED_BLOCKS}
    ops = [{"op": "remove", "id": name} for name in sorted(current) if name not in desired]
    for name in sorted(desired):
        if name not in current:
            ops.append({"op": "add", "id": name, "data": desired[name]})
        elif current[name] != desired[name]:
            ops.append({"op": "replace", "id": name, "data": desired[name]})
    return ops


def submit(root: Path, source: object, *, writes: bool = True) -> dict:
    """Run one submission on an existing private project root. Raises on anything unexpected.

    `writes=False` models a host that launched the server read-only: the handoff then stops at
    discovery with a clear error instead of attempting a mutation."""
    brief = to_brief(source)
    sha = brief_sha256(brief)
    document = lower(brief)
    wanted = journal_blocks(brief)
    prefix = f"{brief['project']}/{brief['floorId']}/"
    client = MCPClient(Path(root), writes=writes)

    discover = client.batch([("server/discover", {}), ("tools/list", {})])
    _require("error" not in discover[0] and discover[0]["result"]["supportedVersions"] == [PROTOCOL],
             "unsupported MCP protocol")
    _require("error" not in discover[1], "MCP tool discovery failed")
    names = {t["name"] for t in discover[1]["result"]["tools"]}
    _require(REQUIRED_TOOLS <= names, "the server does not expose the tools this handoff uses "
                                      "(was it started without --allow-writes?)")

    existing = _ok(client.batch([_tool("bmb_validate_journals")])[0], "journal listing")
    present = set(existing["moduleIds"])
    dropped = sorted(m for m in present if m.startswith(prefix) and m not in wanted)
    if dropped:
        raise BriefError(f"the brief no longer contains {dropped}; handoff v1 never deletes modules")

    created, updated, unchanged = [], [], []
    for mid, blocks in wanted.items():
        if mid in present:
            seen = _ok(client.batch([_tool("bmb_inspect_module", {"moduleId": mid, "includeBlocks": True})])[0],
                       "inspect " + mid)
            revision, current = seen["revision"], seen["blocks"]
        else:
            _ok(client.batch([_tool("bmb_create_module", {"moduleId": mid})])[0], "create " + mid)
            revision, current = 0, {}
            created.append(mid)
        ops = _ops(current, blocks)
        if not ops:
            if mid not in created:
                unchanged.append(mid)
            continue
        key = "gen-" + digest({"module": mid, "from": revision, "blocks": blocks}, 32)
        wrote = _ok(client.batch([_tool("bmb_edit_module", {
            "moduleId": mid, "expectedRevision": revision, "idempotencyKey": key, "ops": ops})])[0],
            "edit " + mid)
        _require(wrote["revision"] == revision + 1, "unexpected revision after the edit")
        if mid not in created:
            updated.append(mid)

    graph = _ok(client.batch([_tool("bmb_validate_assembly", {"document": document})])[0],
                "assembly validation")
    _require(graph["moduleCount"] == len(wanted), "assembly module count mismatch")
    final = _ok(client.batch([_tool("bmb_validate_journals")])[0], "final journal validation")
    document_sha = hashlib.sha256(canonical(document).encode("utf-8")).hexdigest()
    return {
        "contract": "bmb032-generator-handoff-v1", "briefId": brief["briefId"], "briefSha256": sha,
        "moduleIrSha256": document_sha, "rooms": len(wanted),
        "created": created, "updated": updated, "unchanged": unchanged,
        "revisions": {m: r for m, r in final["revisions"].items() if m in wanted},
        "assemblyModules": graph["moduleCount"],
        "mcpToolCalls": sum(t["method"] == "tools/call" for t in client.trace),
        "llmRequired": False, "networkRequired": False, "transport": "stdio-mcp", "protocol": PROTOCOL,
    }


def prepare_root(path: Path) -> Path:
    """Create a NEW owner-only project root, or accept an existing directory (the launcher checks it)."""
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
        if os.name == "posix":
            os.chmod(path, 0o700)
    return path


def dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2)
