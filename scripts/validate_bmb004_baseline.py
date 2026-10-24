#!/usr/bin/env python3
"""Validate the BMB-004 *design fixture*, not the future MCP implementation.

Public synthetic input only. Stdlib-only; no project/host filesystem mutations.
"""
import json
import math
import re
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks" / "agent-baseline-v0.json"
TOOLS = {
    "project_info", "project_create", "module_create", "module_inspect",
    "assembly_validate", "module_patch", "bomc_compile", "bomc_inspect",
    "consumer_readback",  # conceptual external test adapter, NOT an exposed MCP tool
}
EFFECTS = {"read", "write", "replay", "negative-write", "derived-write", "external-check"}
GATES = {"security", "geometry", "revision_locality", "determinism", "editor_import", "model_eval_import"}
ID_RE = re.compile(r"^house/f1/[a-z0-9-]+$")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def finite_positive(value: object, name: str) -> float:
    require(type(value) in (float, int) and math.isfinite(value) and value > 0,
            f"{name}: must be positive finite number")
    return float(value)


def validate(data: dict) -> None:
    require(isinstance(data, dict), "fixture must be an object")
    require(data.get("schema_version") == "bmb-agent-baseline/0.1", "unexpected schema version")
    require(data.get("fixture_id") == "bmb004-agent-baseline-v0", "unexpected fixture ID")
    require(data.get("kind") == "design-only-synthetic", "no private/real fixture allowed")
    require(data.get("format_target") == "bomc/1.2-declared-subset", "unsupported target")
    coords = data.get("coordinate_system", {})
    require(coords == {"units": "metres", "handedness": "right", "up": "+Z", "north": "+Y"},
            "coordinate system drift")
    prompt = data.get("prompt")
    require(isinstance(prompt, str) and len(prompt) >= 300 and
            "NOT_RUN" in prompt and "0.95 m" in prompt,
            "required fixed baseline prompt incomplete")
    site = data.get("site", {})
    require(finite_positive(site.get("width_m"), "site width") == 10 and
            finite_positive(site.get("depth_m"), "site depth") == 14 and
            finite_positive(site.get("max_footprint_m2"), "footprint") == 85 and
            site.get("storeys") == 1, "baseline site contract drift")
    rooms = data.get("rooms")
    require(isinstance(rooms, list) and len(rooms) == 4, "expected exactly four rooms")
    ids = [r.get("id") for r in rooms]
    require(all(isinstance(x, str) and ID_RE.fullmatch(x) for x in ids),
            "invalid room ID")
    require(len(set(ids)) == 4 and
            sorted(r.get("type") for r in rooms) ==
            ["bathroom", "bedroom", "bedroom", "living"], "room cardinality drift")
    for room in rooms:
        finite_positive(room.get("min_area_m2"), "room area")
    require(sorted(r["min_area_m2"] for r in rooms) == [4, 9, 9, 16],
            "room minimums drift")
    walls = data.get("walls", {})
    require(finite_positive(walls.get("thickness_m"), "wall thickness") == 0.15 and
            finite_positive(walls.get("height_m"), "wall height") == 2.8 and
            walls.get("unique_shared_wall_owner") is True, "wall contract drift")
    door = data.get("door", {})
    require(door.get("module_id") == "house/f1/living" and
            finite_positive(door.get("initial_clear_width_m"), "initial door") == 0.9 and
            finite_positive(door.get("final_clear_width_m"), "final door") == 0.95 and
            finite_positive(door.get("minimum_clear_width_m"), "min door") == 0.8 and
            door.get("requires_real_cutout") is True, "door contract drift")
    policy = data.get("trial_policy", {})
    require(policy.get("cold_trials") == 3 and
            policy.get("same_input_twice_compiled") is True and
            policy.get("require_independent_editor_and_model_eval") is True and
            policy.get("native_visual_gate") == "NOT_RUN", "trial policy drift")
    script = data.get("script")
    require(isinstance(script, list) and len(script) >= 12, "incomplete scripted trace")
    require([step.get("step") for step in script] == list(range(1, len(script) + 1)),
            "steps must have consecutive unique IDs")
    seen = {}
    for step in script:
        tool, effect, expected = step.get("tool"), step.get("effect"), step.get("expected")
        require(tool in TOOLS and effect in EFFECTS and
                expected in ("PASS", "REVISION_CONFLICT"),
                "unknown/unbounded script operation")
        require(isinstance(step.get("assert"), str) and step["assert"].strip(),
                "missing operation assertion")
        require((expected == "REVISION_CONFLICT") == (effect == "negative-write"),
                "negative-write must explicitly expect conflict")
        require((tool == "consumer_readback") == (effect == "external-check"),
                "independent consumer must be a distinct external check")
        key = step.get("key")
        if effect in {"write", "replay", "negative-write", "derived-write"}:
            require(isinstance(key, str) and re.fullmatch(r"[a-z0-9-]{4,64}", key),
                    "mutation missing constrained idempotency key")
            if key in seen:
                require(effect == "replay" and seen[key] == tool,
                        "idempotency key cannot be reused for a different operation")
            else:
                require(effect != "replay", "replay without original request")
                seen[key] = tool
        else:
            require(key is None, "read-only operation must not advertise mutation key")
    require(any(s["expected"] == "REVISION_CONFLICT" for s in script),
            "missing stale-revision negative test")
    require(sum(s["effect"] == "replay" for s in script) >= 2,
            "missing two retry/idempotency replays")
    require({s["tool"] for s in script} >=
            {"project_create", "module_create", "module_patch", "assembly_validate",
             "bomc_compile", "consumer_readback"}, "required scenario actions missing")
    require(set(data.get("required_gates", [])) == GATES, "missing mandatory gates")
    ev = data.get("initial_evidence", {})
    require(isinstance(ev, dict) and ev.get("status") == "NOT_RUN", "fabricated result status")
    for key in ("recorded_tool_calls", "elapsed_ms", "token_count", "rss_peak_bytes", "bomc_sha256"):
        require(key in ev and ev[key] is None, f"fabricated measurement: {key}")


def _reject_nonjson_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


def main() -> int:
    try:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"),
                          parse_constant=_reject_nonjson_constant)
        validate(data)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        print(f"BMB-004 fixture FAIL: {exc}", file=sys.stderr)
        return 1
    print("BMB-004 design fixture PASS (not a live MCP or BOMC test)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
