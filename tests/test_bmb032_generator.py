"""BMB-032: survey / form / room-brief -> the same agent builder API, with no LLM and no network."""
from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentctx.budget import canonical  # noqa: E402
from agentguide.controller import ControllerError, MCPClient, _ok, _tool  # noqa: E402
from bomc.compiler.graph_to_bomc import compile_document  # noqa: E402
from core.assembly import assemble  # noqa: E402
from core.validator import validate_assembly  # noqa: E402
from integration.generator import (  # noqa: E402
    BriefError, MAX_BYTES, MAX_ROOMS, lower, normalize_form, normalize_survey, to_brief, validate_brief,
)
from integration.generator import __main__ as cli  # noqa: E402
from integration.generator.brief import brief_sha256, journal_blocks  # noqa: E402
from integration.generator.handoff import OWNED_BLOCKS, prepare_root, submit  # noqa: E402
from tests.qa import harness as h  # noqa: E402

EX = ROOT / "examples" / "generator"
BRIEF = json.loads((EX / "room-brief-three-room.json").read_text(encoding="utf-8"))
SURVEY = json.loads((EX / "survey-two-bedroom.json").read_text(encoding="utf-8"))
FORM = json.loads((EX / "form-three-room.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "schemas" / "generator-handoff-v1.schema.json").read_text(encoding="utf-8"))


def row_brief(n: int, *, doors: bool = True, width: float = 3.0, depth: float = 3.0) -> dict:
    rooms = [{"id": f"r{k}", "name": f"Room {k}", "kind": "other", "widthM": width} for k in range(1, n + 1)]
    out = {"schemaVersion": "room-brief-v1", "briefId": "row", "project": "house", "floorId": "floor-1",
           "depthM": depth, "rooms": rooms}
    if doors:
        out["doors"] = [{"between": [f"r{k}", f"r{k + 1}"], "widthM": 0.9} for k in range(1, n)]
    return out


def deep(n: int = 200_000):
    out: list = []
    for _ in range(n):
        out = [out]
    return out


class SchemaTests(unittest.TestCase):
    def setUp(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - CI installs the pinned validator
            self.skipTest("jsonschema is not installed")
        self.validator = jsonschema.Draft202012Validator(SCHEMA)

    def test_examples_satisfy_the_schema_and_the_validator(self):
        for name, doc in (("brief", BRIEF), ("survey", SURVEY), ("form", FORM)):
            with self.subTest(kind=name):
                self.assertEqual(list(self.validator.iter_errors(doc)), [])
                to_brief(doc)

    def test_schema_rejects_what_the_validator_rejects_for_the_shape_rules(self):
        cases = {
            "unknown field": {**BRIEF, "extra": 1},
            "uppercase id": {**BRIEF, "briefId": "Demo"},
            "37-char id": {**BRIEF, "briefId": "a" * 37},
            "path-like project": {**BRIEF, "project": "../x"},
            "13 rooms": row_brief(13),
            "no rooms": {**BRIEF, "rooms": []},
            "room too narrow": {**BRIEF, "rooms": [{**BRIEF["rooms"][0], "widthM": 0.5}]},
            "door too narrow": {**BRIEF, "doors": [{"between": ["living", "bedroom-1"], "widthM": 0.8}]},
            "unknown kind": {**BRIEF, "rooms": [{**BRIEF["rooms"][0], "kind": "garage"}]},
            "bad version": {**BRIEF, "schemaVersion": "room-brief-v2"},
        }
        for label, doc in cases.items():
            with self.subTest(case=label):
                self.assertTrue(list(self.validator.iter_errors(doc)), "the schema accepted it")
                with self.assertRaises(BriefError):
                    to_brief(doc)


class ValidationTests(unittest.TestCase):
    def test_normalization_makes_equal_briefs_equal(self):
        ints = copy.deepcopy(BRIEF)
        ints["depthM"], ints["rooms"][0]["widthM"] = 3, 4.5
        floats = copy.deepcopy(BRIEF)
        self.assertEqual(brief_sha256(ints), brief_sha256(floats))
        self.assertEqual(validate_brief(floats), validate_brief(validate_brief(floats)))

    def test_a_door_is_centred_by_default_and_the_normalized_form_is_complete(self):
        brief = validate_brief(BRIEF)
        self.assertEqual(brief["wallHeightM"], 2.8)
        self.assertEqual(brief["doors"][0]["offsetM"], 1.05)
        self.assertEqual(brief["doors"][0]["heightM"], 2.1)

    def test_each_rule_rejects_with_a_typed_error(self):
        def mutate(fn):
            doc = copy.deepcopy(BRIEF)
            fn(doc)
            return doc
        cases = {
            "duplicate room id": mutate(lambda d: d["rooms"].append(dict(d["rooms"][0]))),
            "door between non-neighbours": mutate(lambda d: d["doors"].append({"between": ["living", "bath-1"], "widthM": 0.9})),
            "two doors on one wall": mutate(lambda d: d["doors"].append({"between": ["bedroom-1", "living"], "widthM": 0.9})),
            "door to unknown room": mutate(lambda d: d["doors"].append({"between": ["living", "nowhere"], "widthM": 0.9})),
            "door wider than wall": mutate(lambda d: (d.update(depthM=1.5), d["doors"][0].update(widthM=1.4))),
            "door too close to a wall end": mutate(lambda d: d["doors"][0].update(offsetM=1.0, widthM=2.0)),
            "door narrower than the geometry builder allows": mutate(lambda d: d["doors"][0].update(widthM=0.8)),
            "door lower than the geometry builder allows": mutate(lambda d: d["doors"][0].update(heightM=1.9)),
            "door height over the wall": mutate(lambda d: d["doors"][0].update(heightM=3.0)),
            "empty name": mutate(lambda d: d["rooms"][0].update(name="")),
            "control character in name": mutate(lambda d: d["rooms"][0].update(name="a\x00b")),
            "name over 80": mutate(lambda d: d["rooms"][0].update(name="x" * 81)),
            "boolean width": mutate(lambda d: d["rooms"][0].update(widthM=True)),
            "string width": mutate(lambda d: d["rooms"][0].update(widthM="4")),
            "NaN width": mutate(lambda d: d["rooms"][0].update(widthM=float("nan"))),
            "infinite depth": mutate(lambda d: d.update(depthM=float("inf"))),
            "huge integer": mutate(lambda d: d["rooms"][0].update(widthM=10 ** 400)),
            "missing rooms": {k: v for k, v in BRIEF.items() if k != "rooms"},
            "rooms not a list": mutate(lambda d: d.update(rooms={"a": 1})),
            "not an object": [BRIEF],
        }
        for label, doc in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(BriefError):
                    validate_brief(doc)

    def test_hostile_identifiers_can_never_become_module_ids(self):
        hostile = ["../x", "a/b", "a\\b", "..", "", "A", "a b", "a\x00", "a\n", "é", "a" * 37, "-a", "1a",
                   "con/..", "%2e%2e", "a:b", "a.b", "‮ab"]
        for value in hostile:
            for field in ("briefId", "project", "floorId"):
                with self.subTest(field=field, value=value[:12]):
                    with self.assertRaises(BriefError):
                        validate_brief({**BRIEF, field: value})
            with self.subTest(room=value[:12]):
                doc = copy.deepcopy(BRIEF)
                doc["rooms"][0]["id"] = value
                doc["doors"] = []
                with self.assertRaises(BriefError):
                    validate_brief(doc)

    def test_a_value_nested_200_000_levels_is_a_typed_rejection_everywhere(self):
        nested = deep()
        for path in (("briefId",), ("project",), ("floorId",), ("depthM",), ("wallHeightM",), ("schemaVersion",),
                     ("rooms", 0, "id"), ("rooms", 0, "name"), ("rooms", 0, "kind"), ("rooms", 0, "widthM"),
                     ("doors", 0, "between"), ("doors", 0, "widthM"), ("doors", 0, "offsetM")):
            doc = copy.deepcopy(BRIEF)
            target = doc
            for step in path[:-1]:
                target = target[step]
            target[path[-1]] = nested
            with self.subTest(path=path):
                with self.assertRaises(BriefError):
                    validate_brief(doc)
                with self.assertRaises(BriefError):
                    to_brief(doc)

    def test_size_and_room_limits(self):
        self.assertEqual(len(lower(validate_brief(row_brief(MAX_ROOMS)))["modules"]), MAX_ROOMS)
        with self.assertRaises(BriefError):
            validate_brief(row_brief(MAX_ROOMS + 1))
        big = copy.deepcopy(BRIEF)
        big["rooms"][0]["name"] = "x" * (MAX_BYTES + 1)
        with self.assertRaises(BriefError):
            to_brief(big)

    def test_seeded_fuzz_only_ever_raises_the_typed_error(self):
        for seed, doc in enumerate((BRIEF, SURVEY, FORM)):
            with self.subTest(kind=doc["schemaVersion"]):
                defects = h.run(to_brief, doc, random.Random(seed), 300, (BriefError,))
                self.assertEqual(defects, [], "\n".join(h.describe(defects, 8)))


class NormalizerTests(unittest.TestCase):
    def test_survey_table(self):
        for beds in range(0, 7):
            for baths in range(0, 5):
                for size in ("compact", "standard"):
                    survey = {"schemaVersion": "survey-v1", "surveyId": "s", "answers": {"bedrooms": beds, "bathrooms": baths, "size": size}}
                    with self.subTest(beds=beds, baths=baths, size=size):
                        brief = normalize_survey(survey)
                        self.assertEqual([r["kind"] for r in brief["rooms"]],
                                         ["living"] + ["bedroom"] * beds + ["bath"] * baths)
                        self.assertEqual(len(brief["doors"]), len(brief["rooms"]) - 1)

    def test_survey_rejects_out_of_range_and_wrong_types(self):
        for answers in ({"bedrooms": 7, "bathrooms": 0, "size": "compact"}, {"bedrooms": -1, "bathrooms": 0, "size": "compact"},
                        {"bedrooms": True, "bathrooms": 0, "size": "compact"}, {"bedrooms": 1.5, "bathrooms": 0, "size": "compact"},
                        {"bedrooms": 1, "bathrooms": 5, "size": "compact"}, {"bedrooms": 1, "bathrooms": 0, "size": "huge"},
                        {"bedrooms": 1, "bathrooms": 0, "size": ["compact"]}, {"bedrooms": 1, "bathrooms": 0},
                        {"bedrooms": 1, "bathrooms": 0, "size": "compact", "extra": 1}):
            with self.subTest(answers=str(answers)[:50]):
                with self.assertRaises(BriefError):
                    normalize_survey({"schemaVersion": "survey-v1", "surveyId": "s", "answers": answers})

    def test_form_room_ids_come_from_names_and_stay_unique(self):
        form = {**FORM, "rooms": [{"name": "Kamar Tidur", "type": "bedroom", "widthM": 3},
                                  {"name": "Kamar Tidur", "type": "bedroom", "widthM": 3},
                                  {"name": "Kamar Tidur", "type": "bedroom", "widthM": 3},
                                  {"name": "日本語", "type": "living", "widthM": 3},
                                  {"name": "2nd floor hall", "type": "hall", "widthM": 3},
                                  {"name": "!!!", "type": "bath", "widthM": 2}]}
        ids = [r["id"] for r in normalize_form(form)["rooms"]]
        self.assertEqual(ids, ["kamar-tidur", "kamar-tidur-2", "kamar-tidur-3", "living", "room-2nd-floor-hall", "bath"])
        self.assertEqual(len(set(ids)), len(ids))

    def test_form_with_twelve_identical_long_names_stays_valid(self):
        form = {**FORM, "rooms": [{"name": "A very long room name indeed " * 2, "type": "other", "widthM": 2}] * 12}
        brief = normalize_form(form)
        self.assertEqual(len({r["id"] for r in brief["rooms"]}), 12)
        assemble(lower(brief)["modules"])

    def test_the_three_kinds_reach_the_same_canonical_brief(self):
        survey = normalize_survey({"schemaVersion": "survey-v1", "surveyId": "same", "answers": {"bedrooms": 1, "bathrooms": 1, "size": "compact"}})
        form = normalize_form({"schemaVersion": "form-v1", "formId": "same", "depthM": 3.0, "doorWidthM": 0.9,
                               "rooms": [{"name": "Living room", "type": "living", "widthM": 4.0},
                                         {"name": "Bedroom 1", "type": "bedroom", "widthM": 3.0},
                                         {"name": "Bathroom 1", "type": "bath", "widthM": 2.0}]})
        # ids come from the names in a form, so align them, then everything else must be equal
        for room, wanted in zip(form["rooms"], survey["rooms"]):
            room["id"] = wanted["id"]
        for door, wanted in zip(form["doors"], survey["doors"]):
            door["between"] = wanted["between"]
        self.assertEqual(validate_brief(form), validate_brief(survey))
        self.assertEqual(lower(form), lower(survey))
        self.assertEqual(to_brief(survey), survey)


class LoweringTests(unittest.TestCase):
    def test_every_example_lowers_to_an_assembly_the_core_accepts(self):
        for name, doc in (("brief", BRIEF), ("survey", SURVEY), ("form", FORM)):
            with self.subTest(kind=name):
                document = lower(to_brief(doc))
                assemble(document["modules"])
                report = validate_assembly(document["modules"])
                self.assertTrue(report.ok, report.diagnostics)

    def test_one_to_twelve_rooms_assemble_and_validate_with_or_without_doors(self):
        for n in range(1, MAX_ROOMS + 1):
            for doors in (True, False):
                with self.subTest(rooms=n, doors=doors):
                    document = lower(validate_brief(row_brief(n, doors=doors)))
                    assemble(document["modules"])
                    self.assertTrue(validate_assembly(document["modules"]).ok)

    def test_up_to_five_rooms_also_compile_to_bomc(self):
        for n in range(1, 6):
            with self.subTest(rooms=n):
                self.assertEqual(compile_document(lower(validate_brief(row_brief(n)))).receipt()["faceCount"] > 0, True)

    def test_the_door_limits_are_exactly_what_the_geometry_builder_accepts(self):
        def compiles(width, height):
            doc = row_brief(2)
            doc["doors"][0].update(widthM=width, heightM=height)
            compile_document(lower(validate_brief(doc)))
        compiles(0.81, 1.95)                                  # the smallest the validator allows must compile
        with self.assertRaises(Exception):
            compiles(0.80, 2.1)                               # one cm below: the builder itself refuses
        with self.assertRaises(Exception):
            compiles(0.9, 1.93)                               # and so does a lower head

    def test_lowering_is_deterministic_and_pure(self):
        brief = validate_brief(BRIEF)
        before = copy.deepcopy(brief)
        first, second = lower(brief), lower(copy.deepcopy(brief))
        self.assertEqual(canonical(first), canonical(second))
        self.assertEqual(brief, before)
        self.assertEqual(compile_document(first).sha256, compile_document(second).sha256)

    def test_a_door_change_alters_only_the_two_rooms_it_joins(self):
        base = lower(validate_brief(row_brief(4)))
        changed_doc = row_brief(4)
        changed_doc["doors"][1]["widthM"] = 1.0                   # between r2 and r3
        changed = lower(validate_brief(changed_doc))
        differing = [a["moduleId"] for a, b in zip(base["modules"], changed["modules"]) if a != b]
        self.assertEqual(differing, ["house/floor-1/r2", "house/floor-1/r3"])
        assemble(changed["modules"])

    def test_a_width_change_keeps_every_other_journal_block_identical(self):
        before = journal_blocks(validate_brief(row_brief(4)))
        edited = row_brief(4)
        edited["rooms"][0]["widthM"] = 5.0
        after = journal_blocks(validate_brief(edited))
        self.assertEqual([m for m in before if before[m] != after[m]], ["house/floor-1/r1"])

    def test_the_lowered_modules_carry_no_digest_of_the_whole_brief(self):
        text = canonical(lower(validate_brief(BRIEF))) + canonical(journal_blocks(validate_brief(BRIEF)))
        self.assertNotIn(brief_sha256(BRIEF), text)
        self.assertNotIn(brief_sha256(BRIEF)[:16], text)


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="bmb032-")
        self.addCleanup(self._tmp.cleanup)
        self.root = prepare_root(Path(self._tmp.name) / "private-project")

    def journals(self) -> dict:
        base = self.root / "modules"
        return {p.parent.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.glob("*/journal.jsonl"))} if base.exists() else {}

    def test_first_submission_creates_every_module_through_the_mcp_tools(self):
        result = submit(self.root, BRIEF)
        self.assertEqual(result["created"], ["house/floor-1/living", "house/floor-1/bedroom-1", "house/floor-1/bath-1"])
        self.assertEqual((result["updated"], result["unchanged"]), ([], []))
        self.assertEqual(set(result["revisions"].values()), {1})
        self.assertEqual(result["assemblyModules"], 3)
        self.assertEqual(result["mcpToolCalls"], 9)
        self.assertEqual((result["llmRequired"], result["networkRequired"], result["transport"]), (False, False, "stdio-mcp"))
        self.assertEqual(len(self.journals()), 3)

    def test_resubmitting_the_same_brief_writes_nothing(self):
        submit(self.root, BRIEF)
        before = self.journals()
        again = submit(self.root, BRIEF)
        self.assertEqual((again["created"], again["updated"]), ([], []))
        self.assertEqual(len(again["unchanged"]), 3)
        self.assertEqual(self.journals(), before, "a journal file changed")
        self.assertEqual(again["mcpToolCalls"], 6)

    def test_a_number_written_as_int_or_float_is_the_same_submission(self):
        submit(self.root, BRIEF)
        before = self.journals()
        ints = copy.deepcopy(BRIEF)
        ints["depthM"], ints["rooms"][0]["widthM"] = 3, 4.5
        self.assertEqual(submit(self.root, ints)["updated"], [])
        self.assertEqual(self.journals(), before)

    def test_a_localized_revision_touches_one_journal_only(self):
        submit(self.root, BRIEF)
        before = self.journals()
        edited = copy.deepcopy(BRIEF)
        edited["doors"][0]["widthM"] = 1.0
        result = submit(self.root, edited)
        self.assertEqual(result["updated"], ["house/floor-1/living"])
        self.assertEqual(len(result["unchanged"]), 2)
        after = self.journals()
        self.assertEqual([m for m in before if before[m] != after[m]], ["house__floor-1__living"])
        self.assertEqual(result["revisions"]["house/floor-1/living"], 2)
        self.assertEqual(result["revisions"]["house/floor-1/bath-1"], 1)

    def test_survey_and_form_use_exactly_the_same_calls_as_a_brief(self):
        for label, doc, rooms in (("survey", SURVEY, 4), ("form", FORM, 3)):
            with self.subTest(kind=label), tempfile.TemporaryDirectory(prefix="bmb032-kind-") as tmp:
                root = prepare_root(Path(tmp) / "p")
                result = submit(root, doc)
                self.assertEqual(result["rooms"], rooms)
                self.assertEqual(result["mcpToolCalls"], 3 + 2 * rooms)
                self.assertEqual(result["assemblyModules"], rooms)

    def test_a_brief_that_drops_a_room_is_refused_and_nothing_changes(self):
        submit(self.root, BRIEF)
        before = self.journals()
        smaller = copy.deepcopy(BRIEF)
        smaller["rooms"].pop()
        smaller["doors"].pop()
        with self.assertRaises(BriefError):
            submit(self.root, smaller)
        self.assertEqual(self.journals(), before)

    def test_blocks_written_by_other_agents_are_never_touched(self):
        submit(self.root, BRIEF)
        client = MCPClient(self.root)
        mid = "house/floor-1/living"
        seen = _ok(client.batch([_tool("bmb_inspect_module", {"moduleId": mid})])[0], "inspect")
        _ok(client.batch([_tool("bmb_edit_module", {"moduleId": mid, "expectedRevision": seen["revision"],
                                                    "idempotencyKey": "other-agent-note",
                                                    "ops": [{"op": "add", "id": "agent-note", "data": {"x": 1}}]})])[0], "note")
        before = self.journals()
        self.assertEqual(submit(self.root, BRIEF)["updated"], [], "a foreign block counted as drift")
        self.assertEqual(self.journals(), before)
        no_door = copy.deepcopy(BRIEF)
        no_door["doors"].pop(0)
        self.assertEqual(submit(self.root, no_door)["updated"], [mid])
        blocks = _ok(client.batch([_tool("bmb_inspect_module", {"moduleId": mid, "includeBlocks": True})])[0], "after")["blocks"]
        self.assertIn("agent-note", blocks)
        self.assertNotIn("door-east", blocks)
        self.assertEqual(sorted(set(blocks) & OWNED_BLOCKS), ["room"])

    def test_a_drifted_owned_block_is_converged_back_to_the_brief(self):
        submit(self.root, BRIEF)
        client = MCPClient(self.root)
        mid = "house/floor-1/bedroom-1"
        seen = _ok(client.batch([_tool("bmb_inspect_module", {"moduleId": mid, "includeBlocks": True})])[0], "inspect")
        drifted = {**seen["blocks"]["room"], "widthM": 9.0}
        _ok(client.batch([_tool("bmb_edit_module", {"moduleId": mid, "expectedRevision": seen["revision"],
                                                    "idempotencyKey": "drift-1",
                                                    "ops": [{"op": "replace", "id": "room", "data": drifted}]})])[0], "drift")
        self.assertEqual(submit(self.root, BRIEF)["updated"], [mid])
        final = _ok(client.batch([_tool("bmb_inspect_module", {"moduleId": mid, "includeBlocks": True})])[0], "final")
        self.assertEqual(final["blocks"]["room"]["widthM"], 3.0)

    def test_a_writer_that_sneaks_in_between_inspect_and_edit_is_rejected_by_the_journal(self):
        from unittest import mock
        import integration.generator.handoff as handoff
        submit(self.root, BRIEF)
        edited = copy.deepcopy(BRIEF)
        edited["doors"][0]["widthM"] = 1.0
        mid, real_ops, fired = "house/floor-1/living", handoff._ops, []

        def racing(current, desired):
            ops = real_ops(current, desired)
            if ops and not fired:                      # another agent commits AFTER our inspection
                fired.append(1)
                other = MCPClient(self.root)
                seen = _ok(other.batch([_tool("bmb_inspect_module", {"moduleId": mid})])[0], "inspect")
                _ok(other.batch([_tool("bmb_edit_module", {"moduleId": mid, "expectedRevision": seen["revision"],
                                                           "idempotencyKey": "race-1",
                                                           "ops": [{"op": "add", "id": "raced", "data": {"x": 1}}]})])[0], "race")
            return ops

        with mock.patch.object(handoff, "_ops", racing):
            with self.assertRaises(ControllerError):
                submit(self.root, edited)
        client = MCPClient(self.root)
        seen = _ok(client.batch([_tool("bmb_inspect_module", {"moduleId": mid, "includeBlocks": True})])[0], "after")
        self.assertEqual(seen["revision"], 2, "only the other writer's commit may exist")
        self.assertIn("raced", seen["blocks"])
        self.assertEqual(seen["blocks"]["door-east"]["widthM"], 0.9, "our stale edit must not have been applied")
        self.assertEqual(submit(self.root, edited)["updated"], [mid], "a fresh submission converges")

    def test_a_read_only_server_is_a_clear_refusal_not_a_write_attempt(self):
        with self.assertRaises(ControllerError) as caught:
            submit(self.root, BRIEF, writes=False)
        self.assertIn("allow-writes", str(caught.exception))
        self.assertEqual(self.journals(), {})

    def test_a_hostile_brief_never_reaches_the_server(self):
        for bad in ({**BRIEF, "project": "../../escape"}, {**BRIEF, "briefId": "A/B"},
                    {**BRIEF, "rooms": [{**BRIEF["rooms"][0], "id": "con/.."}] + BRIEF["rooms"][1:]}):
            with self.subTest(bad=str(bad["project"]) + bad["briefId"]):
                with self.assertRaises(BriefError):
                    submit(self.root, bad)
        self.assertFalse((self.root / "modules").exists(), "something was created for a rejected brief")
        self.assertEqual(sorted(p.name for p in Path(self._tmp.name).iterdir()), ["private-project"])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, json.loads(out.getvalue())

    def test_lower_prints_the_module_ir(self):
        code, doc = self.run_cli(["lower", "--input", str(EX / "room-brief-three-room.json")])
        self.assertEqual(code, 0)
        self.assertEqual(doc, lower(validate_brief(BRIEF)))

    def test_submit_then_verdict(self):
        with tempfile.TemporaryDirectory(prefix="bmb032-cli-") as tmp:
            code, result = self.run_cli(["submit", "--input", str(EX / "survey-two-bedroom.json"), "--root", str(Path(tmp) / "p")])
            self.assertEqual((code, result["rooms"], result["assemblyModules"]), (0, 4, 4))

    def test_bad_input_is_a_fail_verdict_not_a_traceback(self):
        with tempfile.TemporaryDirectory(prefix="bmb032-cli-") as tmp:
            bad = Path(tmp) / "bad.json"
            for content in (b"not json", b"[1,2]", b'{"schemaVersion": "nope"}', b"\xff\xfe", b"x" * (MAX_BYTES + 5)):
                bad.write_bytes(content)
                with self.subTest(content=content[:12]):
                    code, result = self.run_cli(["lower", "--input", str(bad)])
                    self.assertEqual((code, result["verdict"]), (1, "FAIL"))
            code, result = self.run_cli(["lower", "--input", str(Path(tmp) / "missing.json")])
            self.assertEqual((code, result["verdict"]), (1, "FAIL"))


class NoLlmNoNetworkTests(unittest.TestCase):
    FORBIDDEN = {"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "requests", "httpx", "aiohttp",
                 "anthropic", "openai", "google", "cohere", "mistralai", "ollama", "websockets"}

    def test_the_integration_package_cannot_reach_a_network_or_a_model(self):
        for path in sorted((ROOT / "integration").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    with self.subTest(file=path.name, module=name):
                        self.assertNotIn(name.split(".")[0], self.FORBIDDEN)
                if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                    self.fail(f"{path.name} reads the environment (credentials or keys)")


if __name__ == "__main__":
    unittest.main()
