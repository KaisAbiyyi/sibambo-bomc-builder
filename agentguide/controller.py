"""BMB-025: scriptable, synthetic Codex-like controller against the real BMB-023 stdio MCP.

This is an intentionally bounded demonstration, not an LLM, OS security sandbox,
typed journal-to-Module-IR converter, BOMC compiler, or independent consumer.
The host owns the private project root; MCP commands never include a root path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from agentctx import ContextProvider, SessionStore
from core.storage.journal import JournalStore

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "bmb025-prompts.json"
PROTOCOL = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "bmb025-script-controller", "version": "1.0"},
}


class ControllerError(RuntimeError):
    """An unexpected response or invariant violation: never relabel as a PASS."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ControllerError(message)


def _request(method: str, params: dict, request_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method,
            "params": {"_meta": META, **params}}


def _tool(name: str, arguments: dict | None = None) -> tuple:
    return ("tools/call", {"name": name, "arguments": {} if arguments is None else arguments})


class MCPClient:
    """Short-lived sequential stdio batches; inspect outcomes before deciding later steps."""

    def __init__(self, root: Path, *, writes: bool = True):
        self.root = root
        self.writes = writes
        self.next_id = 1
        self.trace: list[dict] = []

    def batch(self, actions: list[tuple]) -> list[dict]:
        requests = [_request(method, params, self.next_id + i) for i, (method, params) in enumerate(actions)]
        self.next_id += len(requests)
        payload = b"".join(json.dumps(p, separators=(",", ":"), allow_nan=False).encode() + b"\n"
                           for p in requests)
        command = [sys.executable, "-m", "agent.bmb_mcp", "--root", str(self.root)]
        if self.writes:
            command.append("--allow-writes")
        try:
            process = subprocess.run(command, cwd=REPO, input=payload, capture_output=True,
                                     timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ControllerError("MCP process timed out; durability of any in-flight write is unknown") from exc
        _require(process.returncode == 0,
                 "MCP launcher refused or exited abnormally (root grant/OS gate requires investigation)")
        _require(not process.stderr, "MCP process emitted an unexpected stderr error")
        try:
            responses = [json.loads(line) for line in process.stdout.splitlines()]
        except (UnicodeDecodeError, ValueError) as exc:
            raise ControllerError("invalid stdio JSON-RPC response") from exc
        _require(len(responses) == len(requests), "missing/extra MCP response")
        for request, response in zip(requests, responses):
            _require(response.get("jsonrpc") == "2.0" and response.get("id") == request["id"],
                     "MCP response ID or protocol mismatch")
            row = {"method": request["method"]}
            if request["method"] == "tools/call":
                row["tool"] = request["params"]["name"]
            result = response.get("result")
            row["code"] = (response.get("error") or {}).get("code") if result is None else (
                (result.get("structuredContent") or {}).get("error") or {}).get("code")
            row["ok"] = bool(result and not result.get("isError", False))
            self.trace.append(row)
        return responses


def _ok(response: dict, label: str) -> dict:
    _require("error" not in response, label + ": unexpected JSON-RPC protocol error")
    result = response["result"]
    data = result.get("structuredContent")
    _require(result.get("isError") is False and isinstance(data, dict) and data.get("ok") is True,
             label + ": unexpected tool failure")
    return data.get("data", {})


def _error_code(response: dict, label: str) -> str:
    _require("error" not in response, label + ": protocol error instead of typed tool error")
    result = response["result"]
    _require(result.get("isError") is True, label + ": unexpectedly accepted")
    code = result["structuredContent"]["error"]["code"]
    _require(isinstance(code, str), label + ": missing error code")
    return code


def run_scenario(root: Path, scenario: dict, assembly: dict) -> dict:
    """Execute on a NEW private root. Returns evidence, raising on any unexpected failure."""
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == "posix":
        os.chmod(root, 0o700)
    _require(scenario.get("schemaVersion") == "1.0.0" and len(scenario["modules"]) == 2,
             "unsupported fixture shape")
    living, hall = scenario["modules"]
    _require(living["id"] != hall["id"], "module IDs must be distinct")
    change = scenario["revision"]
    _require(change["module"] == living["id"] and change["block"] == living["block"],
             "scenario revision target mismatch")
    client = MCPClient(root)
    phase1 = [
        ("server/discover", {}),
        ("tools/list", {}),
        _tool("bmb_create_module", {"moduleId": living["id"]}),
        _tool("bmb_create_module", {"moduleId": hall["id"]}),
        _tool("bmb_edit_module", {"moduleId": living["id"], "expectedRevision": 0,
                                 "idempotencyKey": "bmb025-seed-living",
                                 "ops": [{"op": "add", "id": living["block"], "data": living["value"]}]}),
        _tool("bmb_edit_module", {"moduleId": hall["id"], "expectedRevision": 0,
                                 "idempotencyKey": "bmb025-seed-hall",
                                 "ops": [{"op": "add", "id": hall["block"], "data": hall["value"]}]}),
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True}),
        _tool("bmb_inspect_module", {"moduleId": hall["id"], "includeBlocks": True}),
        _tool("bmb_validate_journals"),
    ]
    first = client.batch(phase1)
    _require(first[0]["result"]["supportedVersions"] == [PROTOCOL], "unsupported MCP protocol")
    names = {tool["name"] for tool in first[1]["result"]["tools"]}
    _require({"bmb_create_module", "bmb_inspect_module", "bmb_edit_module",
              "bmb_validate_journals", "bmb_validate_assembly"} <= names, "missing required MCP tools")
    for i in (2, 3, 4, 5, 8):
        _ok(first[i], "initial action " + str(i))
    before_living = _ok(first[6], "initial living inspection")
    before_hall = _ok(first[7], "initial hall inspection")
    _require(before_living["revision"] == before_hall["revision"] == 1, "unexpected seed revisions")
    _require(before_living["blocks"][living["block"]]["clearWidthM"] == change["fromWidthM"],
             "seed doorway differs from the prompt")
    _require(before_hall["blocks"][hall["block"]] == hall["value"], "seed hall differs from prompt")
    hall_hash = before_hall["journalHash"]
    living_hash = before_living["journalHash"]
    repair = {"moduleId": living["id"], "expectedRevision": before_living["revision"],
              "idempotencyKey": "bmb025-door-095",
              "ops": [{"op": "replace", "id": living["block"], "data":
                       {**living["value"], "clearWidthM": change["toWidthM"]}}]}
    stale = {**repair, "expectedRevision": 0, "idempotencyKey": "bmb025-stale"}
    broken_assembly = copy.deepcopy(assembly)
    broken_assembly["schemaVersion"] = "invalid"
    phase2 = [
        _tool("bmb_edit_module", stale),
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True}),
        _tool("bmb_edit_module", repair),
        _tool("bmb_edit_module", repair),  # byte-stable idempotency replay
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True}),
        _tool("bmb_inspect_module", {"moduleId": hall["id"], "includeBlocks": True}),
        _tool("bmb_validate_journals"),
        _tool("bmb_validate_assembly", {"document": assembly}),
        _tool("bmb_validate_assembly", {"document": broken_assembly}),
        _tool("bmb_create_module", {"moduleId": "../../escape"}),
    ]
    second = client.batch(phase2)
    _require(_error_code(second[0], "stale edit") == "REVISION_CONFLICT",
             "stale edit not rejected with the frozen error code")
    after_stale = _ok(second[1], "post-stale inspection")
    _require(after_stale["revision"] == 1 and after_stale["journalHash"] == living_hash,
             "rejected stale edit mutated the journal")
    write = _ok(second[2], "doorway revision")
    replay = _ok(second[3], "idempotency replay")
    _require(write["revision"] == 2 and replay["replayed"] is True
             and replay["revision"] == 2, "repair or idempotency was not durable")
    after_living = _ok(second[4], "post-repair living")
    after_hall = _ok(second[5], "post-repair hall")
    _require(after_living["revision"] == 2 and
             after_living["blocks"][living["block"]]["clearWidthM"] == change["toWidthM"],
             "doorway revision not visible")
    _require(after_hall == before_hall, "unrelated hall module was rewritten")
    _require(after_living["journalHash"] != living_hash, "living journal hash did not advance")
    integrity = _ok(second[6], "journal validation")
    _require(integrity["revisions"] == {living["id"]: 2, hall["id"]: 1},
             "journal revision summary mismatch")
    graph = _ok(second[7], "synthetic graph assembly validation")
    _require(graph["moduleCount"] == 2, "assembly graph module count mismatch")
    _require(_error_code(second[8], "invalid assembly") == "INVALID_ARGUMENT",
             "invalid assembly input accepted")
    _require(_error_code(second[9], "unsafe module ID") == "INVALID_ARGUMENT",
             "unsafe module ID accepted")
    ro = MCPClient(root, writes=False).batch([_tool("bmb_create_module", {"moduleId": "house/forbidden"})])
    _require(_error_code(ro[0], "read-only grant") == "PERMISSION_DENIED",
             "write tool ran without host authorization")
    _require(not (root / "modules" / "house__forbidden").exists(),
             "read-only grant created a module")
    # The MCP process has ended. BMB-024 is library-only: reads/checkpoints below
    # are NOT presented as an MCP tool or proof that MCP journals map to typed IR.
    store = JournalStore.open(root)
    provider = ContextProvider(store)
    sessions = SessionStore(root)
    brief_hash = hashlib.sha256(scenario["prompt"].encode("utf-8")).hexdigest()
    session = sessions.create("bmb025-demo", brief_hash=brief_hash, token_cap=5000)
    manifest = session.manifest(provider, max_tokens=800)
    focused = session.module(provider, living["id"], depth=0, blocks=[living["block"]], max_tokens=1000)
    _require(manifest["totals"]["modules"] == 2 and len(manifest["modules"]) == 2,
             "scoped context manifest mismatch")
    _require(focused["focus"]["rev"] == 2 and focused["focus"]["id"] == living["id"],
             "scoped context lost the revised module")
    _require(focused["budget"]["usedTokens"] <= 1000, "scoped response over budget")
    checkpoint = session.checkpoint(provider, "after-revision")
    resumed = sessions.open("bmb025-demo").resume(provider)
    _require(resumed["status"] == "current" and resumed["changed"] == [],
             "checkpoint/resume did not agree with journal state")
    gates = {
        "mcp_discovery": "PASS", "create_inspect": "PASS", "stale_edit_rejected": "PASS",
        "local_repair": "PASS", "idempotent_replay": "PASS", "unrelated_module_unchanged": "PASS",
        "journal_integrity": "PASS", "synthetic_ir_graph_validation": "PASS",
        "unsafe_input_rejected": "PASS", "readonly_write_denied": "PASS",
        "scoped_context": "PASS", "checkpoint_resume": "PASS",
        "journal_ir_mapping": "NOT_RUN", "typed_geometry_or_bomc_compile": "NOT_RUN",
        "independent_consumer_readback": "NOT_RUN", "live_llm_agent": "NOT_RUN",
        "native_windows_security": "NOT_RUN", "provider_native_token_usage": "NOT_RUN",
    }
    return {
        "scenarioId": scenario["scenarioId"], "controller": "deterministic-scripted-no-llm",
        "fixtureSha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "protocol": PROTOCOL, "transport": "stdio-mcp", "gates": gates,
        "bmb025TargetVerdict": "PASS", "fullProductE2E": "INCOMPLETE",
        "observations": {"revisions": integrity["revisions"], "hallHashUnchanged": True,
                         "livingHashAdvanced": True, "graphModules": graph["moduleCount"],
                         "contextTokensEstimated": focused["budget"]["usedTokens"],
                         "checkpointSeq": checkpoint["seq"], "resume": resumed["status"],
                         "mcpToolCalls": sum(t["method"] == "tools/call" for t in client.trace) + 1},
        "expectedNegativeTests": [
            {"case": "stale-edit", "code": "REVISION_CONFLICT", "journalUnchanged": True},
            {"case": "invalid-assembly-version", "code": "INVALID_ARGUMENT"},
            {"case": "unsafe-module-id", "code": "INVALID_ARGUMENT"},
            {"case": "read-only-write", "code": "PERMISSION_DENIED"},
        ],
        "unexpectedFailures": [], "mcpTranscript": client.trace + [
            {"method": "tools/call", "tool": "bmb_create_module",
             "ok": False, "code": "PERMISSION_DENIED", "hostGrant": "read-only"}],
        "limitations": [
            "The bundled Module IR graph is validated independently; it is NOT reconstructed from journal blocks.",
            "The assembly validation is not BOMC binary compilation, geometry inspection or independent import.",
            "BMB-024 session reads/checkpoint are called from the Python library after MCP exits, not through MCP tools.",
            "All tokens are estimator values; no live model was used.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BMB-025 scripted synthetic cloud-hosted acceptance")
    parser.add_argument("--pretty", action="store_true", help="human-readable evidence JSON")
    args = parser.parse_args(argv)
    scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assembly = json.loads((REPO / scenario["assemblySource"]).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="bmb025-") as temp:
        evidence = run_scenario(Path(temp) / "private-project", scenario, assembly)
    print(json.dumps(evidence, sort_keys=True, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ControllerError as exc:
        print(json.dumps({"bmb025TargetVerdict": "FAIL", "error": str(exc)}))
        raise SystemExit(1)
