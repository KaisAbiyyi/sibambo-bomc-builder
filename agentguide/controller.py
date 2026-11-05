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


def _project_observed_two_room_ir(assembly: dict, living_id: str, hall_id: str,
                                  *, old_width: float, observed_width: float, revision: int) -> dict:
    """BMB-025 fixture-only projection of an inspected door into typed IR, not a general journal-to-IR adapter.

    Refuse unexpected fixture topology/widths, then update the one opening, reciprocal ports,
    revision and dependent minimum. The result must pass the real BMB-023 graph validator.
    """
    _require(type(observed_width) in (float, int) and 0.8 <= observed_width <= 2.0,
             "invalid observed doorway width")
    _require(type(revision) is int and revision >= 1, "invalid observed revision")
    document = copy.deepcopy(assembly)
    _require(document.get("schemaVersion") == "1.0.0"
             and isinstance(document.get("modules"), list) and len(document["modules"]) == 2,
             "unexpected synthetic IR envelope")
    indexed = {module.get("moduleId"): module for module in document["modules"]}
    _require(len(indexed) == 2 and set(indexed) == {living_id, hall_id},
             "synthetic IR module identity mismatch")
    living, hall = indexed[living_id], indexed[hall_id]
    _require(living.get("revision") == 1, "expected the original synthetic living IR revision")
    cuts = [o for o in living["operations"] if o.get("kind") == "opening-cut"
            and o.get("openingType") == "door"]
    liv_ports = [p for p in living["ports"] if p.get("kind") == "doorway"
                 and p.get("peer", {}).get("moduleId") == hall_id]
    hall_ports = [p for p in hall["ports"] if p.get("kind") == "doorway"
                  and p.get("peer", {}).get("moduleId") == living_id]
    deps = [d for d in hall["dependencies"] if d.get("moduleId") == living_id]
    _require(all(len(items) == 1 for items in (cuts, liv_ports, hall_ports, deps)),
             "unexpected synthetic door/port/dependency topology")
    cut, liv_port, hall_port, dep = cuts[0], liv_ports[0], hall_ports[0], deps[0]
    _require(all(type(w) in (float, int) and w == old_width for w in
                 (cut["width"], liv_port["width"], hall_port["width"]))
             and dep["minRevision"] == 1, "baseline synthetic door and dependency mismatch")
    _require(liv_port["seamId"] == hall_port["seamId"] and
             liv_port["peer"]["portId"] == hall_port["portId"] and
             hall_port["peer"]["portId"] == liv_port["portId"],
             "synthetic port peer/seam identity mismatch")
    cut["width"] = liv_port["width"] = hall_port["width"] = observed_width
    living["revision"] = revision
    dep["minRevision"] = revision
    return document


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
    # Phase gates: no dependent mutation is sent until the previous result is inspected.
    discover = client.batch([("server/discover", {}), ("tools/list", {})])
    _require("error" not in discover[0] and
             discover[0]["result"]["supportedVersions"] == [PROTOCOL],
             "unsupported MCP protocol")
    _require("error" not in discover[1] and isinstance(discover[1].get("result", {}).get("tools"), list),
             "MCP tool discovery failed")
    names = {tool["name"] for tool in discover[1]["result"]["tools"]}
    _require({"bmb_create_module", "bmb_inspect_module", "bmb_edit_module",
              "bmb_validate_journals", "bmb_validate_assembly"} <= names, "missing required MCP tools")

    for module in (living, hall):
        created = client.batch([_tool("bmb_create_module", {"moduleId": module["id"]})])[0]
        _ok(created, "create " + module["id"])
    for module, key in ((living, "bmb025-seed-living"), (hall, "bmb025-seed-hall")):
        seeded = client.batch([_tool("bmb_edit_module",
                                    {"moduleId": module["id"], "expectedRevision": 0,
                                     "idempotencyKey": key,
                                     "ops": [{"op": "add", "id": module["block"],
                                              "data": module["value"]}]})])[0]
        _require(_ok(seeded, "seed " + module["id"])["revision"] == 1,
                 "synthetic module seed revision mismatch")

    first = client.batch([
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True}),
        _tool("bmb_inspect_module", {"moduleId": hall["id"], "includeBlocks": True}),
        _tool("bmb_validate_journals"),
    ])
    before_living = _ok(first[0], "initial living inspection")
    before_hall = _ok(first[1], "initial hall inspection")
    initial_integrity = _ok(first[2], "initial journal validation")
    _require(initial_integrity["revisions"] == {living["id"]: 1, hall["id"]: 1},
             "initial journal revisions unexpected")
    _require(before_living["revision"] == before_hall["revision"] == 1, "unexpected seed revisions")
    _require(before_living["blocks"][living["block"]]["clearWidthM"] == change["fromWidthM"],
             "seed doorway differs from the prompt")
    _require(before_hall["blocks"][hall["block"]] == hall["value"], "seed hall differs from prompt")
    hall_hash = before_hall["journalHash"]
    living_hash = before_living["journalHash"]

    # The expected rejection MUST be observed before ANY recovery write is constructed or queued.
    stale = {"moduleId": living["id"], "expectedRevision": 0,
             "idempotencyKey": "bmb025-stale",
             "ops": [{"op": "replace", "id": living["block"],
                      "data": {**living["value"], "clearWidthM": change["toWidthM"]}}]}
    rejected = client.batch([_tool("bmb_edit_module", stale)])[0]
    _require(_error_code(rejected, "stale edit") == "REVISION_CONFLICT",
             "stale edit not rejected with the frozen error code")
    after_stale = _ok(client.batch([
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True})
    ])[0], "post-stale inspection")
    _require(after_stale["revision"] == before_living["revision"] and
             after_stale["journalHash"] == living_hash and
             after_stale["blocks"] == before_living["blocks"],
             "rejected stale edit unexpectedly changed journal or inspection state")

    # Use the revision observed *after* rejection, and require proof of the repair before replay.
    repair = {"moduleId": living["id"], "expectedRevision": after_stale["revision"],
              "idempotencyKey": "bmb025-door-095",
              "ops": [{"op": "replace", "id": living["block"], "data":
                       {**living["value"], "clearWidthM": change["toWidthM"]}}]}
    write = _ok(client.batch([_tool("bmb_edit_module", repair)])[0], "doorway revision")
    _require(write["revision"] == after_stale["revision"] + 1 and
             write["replayed"] is False, "unexpected repair result; replay refused")
    verified = _ok(client.batch([
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True})
    ])[0], "verify repaired living")
    _require(verified["revision"] == write["revision"] and
             verified["journalHash"] != living_hash and
             verified["blocks"][living["block"]]["clearWidthM"] == change["toWidthM"],
             "repair not observed and verified; replay refused")
    replay = _ok(client.batch([_tool("bmb_edit_module", repair)])[0], "idempotency replay")
    _require(replay["replayed"] is True and replay["revision"] == verified["revision"],
             "idempotent replay not verified")

    final_reads = client.batch([
        _tool("bmb_inspect_module", {"moduleId": living["id"], "includeBlocks": True}),
        _tool("bmb_inspect_module", {"moduleId": hall["id"], "includeBlocks": True}),
        _tool("bmb_validate_journals"),
    ])
    after_living = _ok(final_reads[0], "post-repair living")
    after_hall = _ok(final_reads[1], "post-repair hall")
    integrity = _ok(final_reads[2], "journal validation")
    _require(after_living == verified and after_hall == before_hall,
             "replay changed state or unrelated hall module was rewritten")
    _require(integrity["revisions"] == {living["id"]: 2, hall["id"]: 1},
             "journal revision summary mismatch")

    # Narrow synthetic projection from OBSERVED journal value into the typed IR fixture.
    # No general journal->IR mapping, geometry build or binary BOMC compilation is implied.
    observed_width = after_living["blocks"][living["block"]]["clearWidthM"]
    revised_ir = _project_observed_two_room_ir(
        assembly, living["id"], hall["id"], old_width=change["fromWidthM"],
        observed_width=observed_width, revision=after_living["revision"])
    projected_living = next(m for m in revised_ir["modules"] if m["moduleId"] == living["id"])
    _require(projected_living["revision"] == 2 and observed_width == change["toWidthM"],
             "projection not derived from accepted repair")
    graph = _ok(client.batch([_tool("bmb_validate_assembly",
                                    {"document": revised_ir})])[0],
                "observed synthetic graph validation")
    _require(graph["moduleCount"] == 2, "assembly graph module count mismatch")
    projected_sha = hashlib.sha256(json.dumps(
        revised_ir, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

    broken_assembly = copy.deepcopy(revised_ir)
    broken_assembly["schemaVersion"] = "invalid"
    invalid_assembly = client.batch([_tool("bmb_validate_assembly",
                                            {"document": broken_assembly})])[0]
    _require(_error_code(invalid_assembly, "invalid assembly") == "INVALID_ARGUMENT",
             "invalid assembly input accepted")
    unsafe = client.batch([_tool("bmb_create_module", {"moduleId": "../../escape"})])[0]
    _require(_error_code(unsafe, "unsafe module ID") == "INVALID_ARGUMENT",
             "unsafe module ID accepted")
    ro = MCPClient(root, writes=False).batch([
        _tool("bmb_create_module", {"moduleId": "house/forbidden"})
    ])
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
        "revised_synthetic_ir_projection": "PASS", "recovery_stage_gates": "PASS",
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
                         "validatedDoorWidthM": observed_width, "validatedGraphSha256": projected_sha,
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
            "A fixture-specific graph projection copies the observed journal door width into opening, reciprocal ports and dependent revision; this is NOT a general journal-to-IR adapter.",
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
