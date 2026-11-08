"""BMB-029: the optional, feature-flagged room-evidence adapter. Off = no effect; on = typed, complete, deterministic findings."""
from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.assembly import assemble  # noqa: E402
from core.validator import ValidationReport, validate_assembly  # noqa: E402
from integration.rooms import ENV_FLAG, __main__ as cli, check as check_module, enabled  # noqa: E402
from integration.rooms.check import EnhancedReport, validate_with_rooms  # noqa: E402
from integration.rooms import compare as compare_module, geometry as geometry_module  # noqa: E402
from integration.rooms.compare import MAX_PAIR_WORK, Policy, compare  # noqa: E402
from integration.rooms.evidence import (  # noqa: E402
    MAX_BYTES, MAX_ROOMS, MAX_VERTICES, EvidenceError, evidence_sha256, validate_evidence,
)
from integration.rooms.geometry import convex_intersection_area, intersection_area, shoelace, triangles  # noqa: E402
from integration.rooms.intended import intended_rooms  # noqa: E402
from tests.qa import harness as h  # noqa: E402

EX = ROOT / "examples" / "rooms"
ASSEMBLY = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text(encoding="utf-8"))
MODULES = ASSEMBLY["modules"]
GOOD = json.loads((EX / "evidence-two-rooms.json").read_text(encoding="utf-8"))
OPEN_PLAN = json.loads((EX / "evidence-open-plan.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "schemas" / "rooms-evidence-v1.schema.json").read_text(encoding="utf-8"))
LIVING, HALL = "house/floor-1/living", "house/floor-1/hall"


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def evidence(*rooms, **extra):
    base = {"schemaVersion": "rooms-evidence-v1", "evidenceId": "t", "detector": {"name": "t", "version": "0"},
            "rooms": [{"id": rid, "polygon": poly, **({"confidence": conf} if conf is not None else {})} for rid, poly, conf in rooms]}
    base.update(extra)
    return validate_evidence(base)


def run(ev, policy=None):
    rooms, skipped = intended_rooms(MODULES, elevation_m=ev["elevationM"], level_tolerance=(policy or Policy()).level_tolerance)
    return compare(rooms, ev, policy, skipped=skipped)


def codes(report):
    return sorted(d.code for d in report.diagnostics)


def star(vertices, outer, inner, cx=3.0, cy=1.5):
    """A concave star room: the shape on which the core triangulator produces the most triangles per vertex."""
    return [[round(cx + (outer if k % 2 == 0 else inner) * math.cos(2 * math.pi * k / vertices), 4),
             round(cy + (outer if k % 2 == 0 else inner) * math.sin(2 * math.pi * k / vertices), 4)] for k in range(vertices)]


def deep(n=200_000):
    out: list = []
    for _ in range(n):
        out = [out]
    return out


class FlagTests(unittest.TestCase):
    def test_off_by_default_and_for_anything_that_is_not_an_explicit_on(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_FLAG, None)
            self.assertFalse(enabled())
        for value in ("", "0", "false", "no", "off", "2", "enable", "ture", " ", "None"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {ENV_FLAG: value}):
                self.assertFalse(enabled())

    def test_explicit_on_values(self):
        for value in ("1", "true", "TRUE", "Yes", "on", " on "):
            with self.subTest(value=value), mock.patch.dict(os.environ, {ENV_FLAG: value}):
                self.assertTrue(enabled())

    def test_the_override_wins_but_only_the_real_boolean_true_turns_it_on(self):
        with mock.patch.dict(os.environ, {ENV_FLAG: "1"}):
            self.assertFalse(enabled(False))
            self.assertTrue(enabled(True))
        with mock.patch.dict(os.environ, {ENV_FLAG: "0"}):
            self.assertTrue(enabled(True))
            for truthy in ("true", "1", 1, [1], "yes", object()):
                with self.subTest(override=repr(truthy)):
                    self.assertFalse(enabled(truthy), "a truthy non-boolean must not enable the adapter")


class EvidenceTests(unittest.TestCase):
    def test_examples_are_valid_and_satisfy_the_schema(self):
        for doc in (GOOD, OPEN_PLAN):
            validate_evidence(doc)
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - CI installs the pinned validator
            return
        v = jsonschema.Draft202012Validator(SCHEMA)
        for doc in (GOOD, OPEN_PLAN):
            self.assertEqual(list(v.iter_errors(doc)), [])

    def test_normalization_is_deterministic_and_sorted(self):
        reversed_rooms = copy.deepcopy(GOOD)
        reversed_rooms["rooms"].reverse()
        self.assertEqual(validate_evidence(GOOD), validate_evidence(reversed_rooms))
        self.assertEqual(evidence_sha256(GOOD), evidence_sha256(reversed_rooms))
        ints = copy.deepcopy(GOOD)
        ints["rooms"][0]["polygon"] = [[0, 0], [4, 0], [4, 3], [0, 3]]
        self.assertEqual(evidence_sha256(GOOD), evidence_sha256(ints))

    def test_each_rule_rejects_with_a_typed_error(self):
        def mutate(fn):
            doc = copy.deepcopy(GOOD)
            fn(doc)
            return doc
        cases = {
            "unknown field": mutate(lambda d: d.update(extra=1)),
            "bad version": mutate(lambda d: d.update(schemaVersion="rooms-evidence-v2")),
            "missing detector": {k: v for k, v in GOOD.items() if k != "detector"},
            "empty rooms": mutate(lambda d: d.update(rooms=[])),
            "duplicate room id": mutate(lambda d: d["rooms"].append(dict(d["rooms"][0]))),
            "two vertices": mutate(lambda d: d["rooms"][0].update(polygon=[[0, 0], [1, 1]])),
            "bowtie": mutate(lambda d: d["rooms"][0].update(polygon=[[0, 0], [4, 4], [4, 0], [0, 4]])),
            "collinear": mutate(lambda d: d["rooms"][0].update(polygon=[[0, 0], [1, 0], [2, 0]])),
            "tiny area": mutate(lambda d: d["rooms"][0].update(polygon=rect(0, 0, 0.05, 0.05))),
            "point with 3 numbers": mutate(lambda d: d["rooms"][0].update(polygon=[[0, 0, 0], [4, 0, 0], [4, 3, 0]])),
            "coordinate out of range": mutate(lambda d: d["rooms"][0].update(polygon=rect(0, 0, 1e9, 3))),
            "NaN coordinate": mutate(lambda d: d["rooms"][0].update(polygon=[[float("nan"), 0], [4, 0], [4, 3]])),
            "infinite coordinate": mutate(lambda d: d["rooms"][0].update(polygon=[[float("inf"), 0], [4, 0], [4, 3]])),
            "huge integer": mutate(lambda d: d["rooms"][0].update(polygon=[[10 ** 400, 0], [4, 0], [4, 3]])),
            "boolean coordinate": mutate(lambda d: d["rooms"][0].update(polygon=[[True, 0], [4, 0], [4, 3]])),
            "string coordinate": mutate(lambda d: d["rooms"][0].update(polygon=[["0", 0], [4, 0], [4, 3]])),
            "confidence above 1": mutate(lambda d: d["rooms"][0].update(confidence=1.5)),
            "confidence below 0": mutate(lambda d: d["rooms"][0].update(confidence=-0.1)),
            "empty label": mutate(lambda d: d["rooms"][0].update(label="")),
            "control character in label": mutate(lambda d: d["rooms"][0].update(label="a\x00b")),
            "elevation out of range": mutate(lambda d: d.update(elevationM=5000)),
            "not an object": [GOOD],
        }
        for label, doc in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(EvidenceError):
                    validate_evidence(doc)

    def test_identifiers_never_accept_a_trailing_newline_or_path_text(self):
        for bad in ("a\n", "a\r\n", "../x", "a/b", "A", "é", "a" * 37, "", "1a", "-a"):
            for where in ("evidenceId", "room"):
                with self.subTest(value=bad[:12], where=where):
                    doc = copy.deepcopy(GOOD)
                    if where == "evidenceId":
                        doc["evidenceId"] = bad
                    else:
                        doc["rooms"][0]["id"] = bad
                    with self.assertRaises(EvidenceError):
                        validate_evidence(doc)

    def test_limits(self):
        many = copy.deepcopy(GOOD)
        many["rooms"] = [{"id": f"r{k}", "polygon": rect(k * 5, 0, k * 5 + 4, 3)} for k in range(MAX_ROOMS)]
        self.assertEqual(len(validate_evidence(many)["rooms"]), MAX_ROOMS)
        many["rooms"].append({"id": "extra", "polygon": rect(1000, 0, 1004, 3)})
        with self.assertRaises(EvidenceError):
            validate_evidence(many)
        big = copy.deepcopy(GOOD)
        big["rooms"][0]["label"] = "x" * (MAX_BYTES + 1)
        with self.assertRaises(EvidenceError):
            validate_evidence(big)
        circle = copy.deepcopy(GOOD)
        circle["rooms"][0]["polygon"] = [[10 * __import__("math").cos(2 * 3.14159265 * k / (MAX_VERTICES + 1)),
                                          10 * __import__("math").sin(2 * 3.14159265 * k / (MAX_VERTICES + 1))] for k in range(MAX_VERTICES + 1)]
        with self.assertRaises(EvidenceError):
            validate_evidence(circle)

    def test_a_value_nested_200_000_levels_is_a_typed_rejection_everywhere(self):
        nested = deep()
        for path in (("evidenceId",), ("detector",), ("detector", "name"), ("elevationM",), ("rooms",), ("rooms", 0, "id"),
                     ("rooms", 0, "polygon"), ("rooms", 0, "polygon", 0), ("rooms", 0, "confidence"), ("rooms", 0, "label")):
            doc = copy.deepcopy(GOOD)
            target = doc
            for step in path[:-1]:
                target = target[step]
            target[path[-1]] = nested
            with self.subTest(path=path), self.assertRaises(EvidenceError):
                validate_evidence(doc)

    def test_seeded_fuzz_only_ever_raises_the_typed_error(self):
        for seed, doc in enumerate((GOOD, OPEN_PLAN)):
            defects = h.run(validate_evidence, doc, random.Random(seed), 300, (EvidenceError,))
            self.assertEqual(defects, [], "\n".join(h.describe(defects, 8)))

    def test_the_schema_agrees_on_the_shape_rules(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover
            self.skipTest("jsonschema is not installed")
        v = jsonschema.Draft202012Validator(SCHEMA)
        for label, doc in {"unknown field": {**GOOD, "extra": 1}, "newline id": {**GOOD, "evidenceId": "e\n"},
                           "confidence 2": {**GOOD, "rooms": [{**GOOD["rooms"][0], "confidence": 2}]},
                           "two vertices": {**GOOD, "rooms": [{"id": "a", "polygon": [[0, 0], [1, 1]]}]},
                           "no rooms": {**GOOD, "rooms": []}}.items():
            with self.subTest(case=label):
                self.assertTrue(list(v.iter_errors(doc)))
                with self.assertRaises(EvidenceError):
                    validate_evidence(doc)


class GeometryTests(unittest.TestCase):
    def area(self, a, b):
        return intersection_area(triangles(a), triangles(b))

    def test_known_intersections(self):
        sq = lambda *c: [(c[0], c[1]), (c[2], c[1]), (c[2], c[3]), (c[0], c[3])]  # noqa: E731
        self.assertAlmostEqual(self.area(sq(0, 0, 4, 3), sq(2, 1, 6, 2)), 2.0)
        self.assertAlmostEqual(self.area(sq(0, 0, 4, 3), sq(0, 0, 4, 3)), 12.0)
        self.assertEqual(self.area(sq(0, 0, 4, 3), sq(10, 10, 11, 11)), 0.0)
        self.assertAlmostEqual(self.area(sq(0, 0, 4, 3), sq(4, 0, 6, 3)), 0.0)            # touching edges share no area
        l_shape = [(0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)]
        self.assertAlmostEqual(self.area(l_shape, sq(1, 1, 3, 3)), 3.0)                      # concave room
        self.assertAlmostEqual(self.area(l_shape, sq(2, 2, 4, 4)), 0.0)                      # the notch
        self.assertAlmostEqual(shoelace(l_shape), 12.0)

    def test_winding_orientation_and_argument_order_do_not_matter(self):
        a, b = [(0, 0), (5, 0), (5, 4), (0, 4)], [(3, 2), (8, 2), (8, 6), (3, 6)]
        forward = self.area(a, b)
        self.assertAlmostEqual(forward, 2 * 2.0 + 0.0 + 4.0 - 4.0 + 0.0 + 0.0 if False else 2 * 2.0)
        self.assertAlmostEqual(forward, self.area(b, a))
        self.assertAlmostEqual(forward, self.area(list(reversed(a)), b))

    def test_intersection_never_exceeds_the_smaller_polygon(self):
        rng = random.Random(7)
        for _ in range(60):
            x0, y0 = rng.uniform(0, 3), rng.uniform(0, 3)
            a = [(x0, y0), (x0 + rng.uniform(1, 4), y0), (x0 + rng.uniform(1, 4), y0 + rng.uniform(1, 4)), (x0, y0 + rng.uniform(1, 4))]
            b = [(rng.uniform(0, 4), rng.uniform(0, 4)) for _ in range(3)]
            try:
                ta, tb = triangles(a), triangles(b)
            except ValueError:
                continue
            x = intersection_area(ta, tb)
            self.assertLessEqual(x, min(shoelace(a), shoelace(b)) + 1e-9)
            self.assertGreaterEqual(x, -1e-12)


class IntendedRoomsTests(unittest.TestCase):
    def test_two_room_fixture_in_the_assembly_frame(self):
        rooms, skipped = intended_rooms(MODULES, elevation_m=0.0, level_tolerance=0.25)
        self.assertEqual(skipped, [])
        by_id = {r["id"]: r for r in rooms}
        self.assertEqual(sorted(by_id), [HALL, LIVING])
        self.assertAlmostEqual(by_id[LIVING]["area"], 12.0)
        self.assertAlmostEqual(by_id[HALL]["area"], 6.0)
        self.assertEqual(by_id[HALL]["box"], (4.0, 0.0, 6.0, 3.0))                           # the hall sits at x 4..6

    def test_other_levels_are_not_compared(self):
        self.assertEqual(intended_rooms(MODULES, elevation_m=3.0, level_tolerance=0.25), ([], []))

    def test_a_translated_assembly_moves_its_rooms(self):
        moved = copy.deepcopy(MODULES)
        for module in moved:                                                                   # the whole assembly 10 m along +Y
            module["localFrame"]["transform"][7] += 10.0
        boxes = {r["id"]: r["box"] for r in intended_rooms(moved, elevation_m=0.0, level_tolerance=0.25)[0]}
        self.assertEqual(boxes[LIVING], (0.0, 10.0, 4.0, 13.0))
        self.assertEqual(boxes[HALL], (4.0, 10.0, 6.0, 13.0))

    def test_a_mirrored_assembly_keeps_positive_areas_and_mirrored_positions(self):
        mirrored = copy.deepcopy(MODULES)
        mirrored[0]["localFrame"]["transform"][0] = -1.0                                       # living: x -> -x
        mirrored[1]["localFrame"]["transform"][0] = -1.0                                       # hall: mirrored and moved to x = -4
        mirrored[1]["localFrame"]["transform"][3] = -4.0
        rooms = {r["id"]: r for r in intended_rooms(mirrored, elevation_m=0.0, level_tolerance=0.25)[0]}
        self.assertAlmostEqual(rooms[LIVING]["area"], 12.0)
        self.assertAlmostEqual(rooms[HALL]["area"], 6.0)
        self.assertEqual(rooms[LIVING]["box"], (-4.0, 0.0, 0.0, 3.0))
        self.assertEqual(rooms[HALL]["box"], (-6.0, 0.0, -4.0, 3.0))
        mirrored_rooms, skipped = intended_rooms(mirrored, elevation_m=0.0, level_tolerance=0.25)
        good = compare(mirrored_rooms, evidence(("living", rect(-4, 0, 0, 3), None), ("hall", rect(-6, 0, -4, 3), None)), skipped=skipped)
        self.assertTrue(good.ok, codes(good))
        unmirrored_guess = compare(mirrored_rooms, evidence(("living", rect(0, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None)))
        self.assertFalse(unmirrored_guess.ok, "evidence on the wrong side of the mirror must not match")

    def test_an_assembly_that_cannot_be_placed_is_refused_not_compared(self):
        from core.assembly import AssemblyError
        apart = copy.deepcopy(MODULES)
        apart[1]["localFrame"]["transform"][7] = 10.0                                          # only the hall moves: ports no longer meet
        with self.assertRaises(AssemblyError):
            intended_rooms(apart, elevation_m=0.0, level_tolerance=0.25)

    def test_a_tilted_floor_is_reported_and_skipped_not_guessed(self):
        tilted = copy.deepcopy(MODULES)
        for module in tilted:
            module["localFrame"]["transform"][9] = 0.5                                         # z depends on y in both modules
        rooms, skipped = intended_rooms(tilted, elevation_m=0.0, level_tolerance=5.0)
        self.assertEqual(rooms, [])
        self.assertEqual(sorted(s["id"] for s in skipped), [HALL, LIVING])
        report = run(evidence(("living", rect(0, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None)))
        self.assertTrue(report.ok)
        tilted_report = compare(rooms, evidence(("living", rect(0, 0, 4, 3), None)), skipped=skipped)
        self.assertEqual(sorted(c for c in codes(tilted_report) if c == "INTENDED_UNUSABLE"), ["INTENDED_UNUSABLE", "INTENDED_UNUSABLE"])

    def test_two_slabs_in_one_module_get_distinct_ids(self):
        twin = copy.deepcopy(MODULES)
        twin[0]["operations"].append({**twin[0]["operations"][0], "opId": "floor-2",
                                      "footprint": [[0, 0], [1, 0], [1, 1], [0, 1]]})
        rooms, _ = intended_rooms(twin, elevation_m=0.0, level_tolerance=0.25)
        self.assertIn(f"{LIVING}#floor-1", [r["id"] for r in rooms])
        self.assertIn(f"{LIVING}#floor-2", [r["id"] for r in rooms])


class CompareTests(unittest.TestCase):
    def test_a_perfect_match(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), 1.0), ("hall", rect(4, 0, 6, 3), 1.0)))
        self.assertTrue(report.ok)
        self.assertEqual(codes(report), [])
        self.assertEqual([(m["intendedId"], m["detectedId"]) for m in report.matches], [(HALL, "hall"), (LIVING, "living")])

    def test_a_detector_that_is_a_couple_of_centimetres_off_still_matches(self):
        report = run(evidence(("living", rect(0.02, -0.02, 4.02, 2.98), None), ("hall", rect(4.01, 0.01, 6.01, 3.01), None)))
        self.assertTrue(report.ok, codes(report))

    def test_a_room_in_the_wrong_place_is_a_shape_mismatch(self):
        report = run(evidence(("living", rect(0.5, 0, 4.5, 3), None), ("hall", rect(4, 0, 6, 3), None)))
        self.assertFalse(report.ok)
        self.assertIn("SHAPE_MISMATCH", codes(report))

    def test_a_slightly_smaller_room_is_an_area_mismatch_only(self):
        report = run(evidence(("living", rect(0, 0, 4, 2.88), None), ("hall", rect(4, 0, 6, 3), None)))       # 96% overlap, 4% smaller
        self.assertEqual(codes(report), ["AREA_MISMATCH"])

    def test_open_plan_merging_two_rooms_is_reported(self):
        report = run(validate_evidence(OPEN_PLAN))
        self.assertEqual(codes(report), ["ROOM_MERGED"])
        d = report.diagnostics[0]
        self.assertEqual(sorted(d.intended_ids), [HALL, LIVING])
        self.assertEqual(d.detected_ids, ("everything",))

    def test_one_room_cut_in_two_is_a_split(self):
        report = run(evidence(("living-a", rect(0, 0, 2, 3), None), ("living-b", rect(2, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None)))
        self.assertEqual(codes(report), ["ROOM_SPLIT"])
        self.assertEqual(report.diagnostics[0].intended_ids, (LIVING,))

    def test_a_room_nobody_detected_is_missing(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), None)))
        self.assertEqual(codes(report), ["ROOM_MISSING"])
        self.assertEqual(report.diagnostics[0].intended_ids, (HALL,))

    def test_a_detection_that_is_not_in_the_model_is_unexpected(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None), ("ghost", rect(20, 20, 23, 23), None)))
        self.assertEqual(codes(report), ["ROOM_UNEXPECTED"])
        self.assertEqual(report.diagnostics[0].detected_ids, ("ghost",))

    def test_a_low_confidence_detection_is_ignored_and_reported(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), 1.0), ("hall", rect(4, 0, 6, 3), 0.2)))
        self.assertEqual(codes(report), ["LOW_CONFIDENCE", "ROOM_MISSING"])
        self.assertEqual(report.detected_count, 1)
        report = run(evidence(("living", rect(0, 0, 4, 3), 1.0), ("hall", rect(4, 0, 6, 3), 0.2)), Policy(min_confidence=0.1))
        self.assertEqual(codes(report), [])

    def test_a_partial_overlap_that_matches_nothing_is_still_reported(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None), ("offset", rect(2.5, 5, 6.5, 8), None)))
        self.assertIn("ROOM_UNEXPECTED", codes(report))
        shifted = run(evidence(("living", rect(2.2, 0, 6.2, 3), None), ("hall", rect(7, 0, 9, 3), None)))
        self.assertFalse(shifted.ok)

    def test_a_detector_that_contradicts_itself_gets_a_warning_not_an_error(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None), ("dup", rect(0.2, 0.2, 3.8, 2.8), 0.9)))
        self.assertIn("DETECTED_OVERLAP", codes(report))
        self.assertEqual({d.severity for d in report.diagnostics if d.code == "DETECTED_OVERLAP"}, {"WARNING"})

    def test_the_report_is_deterministic_whatever_order_the_detector_listed_rooms(self):
        ev = evidence(("living-a", rect(0, 0, 2, 3), None), ("living-b", rect(2, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None))
        rooms = list(ev["rooms"])
        for seed in range(6):
            random.Random(seed).shuffle(rooms)
            shuffled = validate_evidence({**ev, "rooms": rooms})
            self.assertEqual(run(shuffled).to_dict(), run(ev).to_dict())

    def test_every_room_is_matched_or_named_by_an_error(self):
        rng = random.Random(11)
        for case in range(80):
            rooms = []
            for k in range(rng.randrange(1, 5)):
                x0, y0 = rng.uniform(-1, 6), rng.uniform(-1, 3)
                rooms.append((f"r{k}", rect(x0, y0, x0 + rng.uniform(0.8, 4.5), y0 + rng.uniform(0.8, 3.5)), rng.choice([None, 0.9, 0.3])))
            report = run(evidence(*rooms))
            matched_i = {m["intendedId"] for m in report.matches}
            matched_d = {m["detectedId"] for m in report.matches}
            named_i = {i for d in report.diagnostics if d.severity == "ERROR" for i in d.intended_ids}
            named_d = {x for d in report.diagnostics if d.severity == "ERROR" for x in d.detected_ids}
            usable = {rid for rid, _, conf in rooms if conf is None or conf >= 0.5}
            with self.subTest(case=case):
                self.assertTrue({LIVING, HALL} <= matched_i | named_i, "an intended room was silently dropped")
                self.assertTrue(usable <= matched_d | named_d, "a detected room was silently dropped")
                if report.ok:
                    self.assertEqual({LIVING, HALL}, matched_i)

    def test_policy_is_validated(self):
        for kwargs in ({"accept_iou": 0.2}, {"accept_iou": 2}, {"overlap_fraction": 0}, {"area_tolerance": -1},
                       {"min_confidence": 1.5}, {"level_tolerance": "x"}, {"accept_iou": True and "0.9"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Policy(**kwargs)

    def test_a_stricter_policy_turns_a_pass_into_a_finding(self):
        ev = evidence(("living", rect(0.1, 0, 4.1, 3), None), ("hall", rect(4, 0, 6, 3), None))
        self.assertTrue(run(ev, Policy(accept_iou=0.9)).ok)
        self.assertFalse(run(ev, Policy(accept_iou=0.99)).ok)


class NoComparisonIsNotAPassTests(unittest.TestCase):
    """Review P1: an enabled adapter that compared nothing must not report success."""

    def tilted(self):
        tilted = copy.deepcopy(MODULES)
        for module in tilted:
            module["localFrame"]["transform"][9] = 0.5
        return tilted

    def test_wrong_elevation_and_every_detection_below_the_confidence_floor(self):
        ev = evidence(("a", rect(0, 0, 4, 3), 0.2), ("b", rect(4, 0, 6, 3), 0.1), elevationM=100)
        report = run(ev)
        self.assertEqual((report.intended_count, report.detected_count), (0, 0))
        self.assertFalse(report.ok)
        self.assertEqual(codes(report), ["LOW_CONFIDENCE", "LOW_CONFIDENCE", "NO_COMPARABLE_ROOMS"])
        self.assertEqual([d.severity for d in report.diagnostics if d.code == "NO_COMPARABLE_ROOMS"], ["ERROR"])

    def test_the_enabled_adapter_is_not_ok_either(self):
        ev = {**GOOD, "elevationM": 100, "rooms": [{**r, "confidence": 0.2} for r in GOOD["rooms"]]}
        result = validate_with_rooms(MODULES, ev, enabled=True)
        self.assertIsInstance(result, EnhancedReport)
        self.assertTrue(result.core.ok)
        self.assertFalse(result.rooms.ok)
        self.assertFalse(result.ok)

    def test_every_intended_floor_unusable_and_every_detection_low_confidence(self):
        tilted = self.tilted()
        rooms, skipped = intended_rooms(tilted, elevation_m=0.0, level_tolerance=5.0)
        report = compare(rooms, evidence(("a", rect(0, 0, 4, 3), 0.2)), skipped=skipped)
        self.assertFalse(report.ok)
        self.assertEqual(codes(report), ["INTENDED_UNUSABLE", "INTENDED_UNUSABLE", "LOW_CONFIDENCE", "NO_COMPARABLE_ROOMS"])
        result = validate_with_rooms(tilted, {**GOOD, "rooms": [{**r, "confidence": 0.2} for r in GOOD["rooms"]]}, enabled=True)
        self.assertFalse(result.ok)

    def test_a_wrong_elevation_with_confident_detections_is_also_named(self):
        report = run(evidence(("a", rect(0, 0, 4, 3), None), elevationM=100))
        self.assertFalse(report.ok)
        self.assertEqual(codes(report), ["NO_COMPARABLE_ROOMS", "ROOM_UNEXPECTED"])

    def test_no_usable_detection_at_all_is_named_beside_the_missing_rooms(self):
        report = run(evidence(("a", rect(0, 0, 4, 3), 0.2)))
        self.assertFalse(report.ok)
        self.assertEqual(codes(report), ["LOW_CONFIDENCE", "NO_COMPARABLE_ROOMS", "ROOM_MISSING", "ROOM_MISSING"])

    def test_an_honestly_matched_case_still_passes_and_says_nothing_about_it(self):
        report = run(evidence(("living", rect(0, 0, 4, 3), 1.0), ("hall", rect(4, 0, 6, 3), 1.0)))
        self.assertTrue(report.ok)
        self.assertNotIn("NO_COMPARABLE_ROOMS", codes(report))
        self.assertEqual(len(report.matches), 2)
        low = run(evidence(("living", rect(0, 0, 4, 3), 1.0), ("hall", rect(4, 0, 6, 3), 1.0), ("noise", rect(20, 20, 21, 21), 0.1)))
        self.assertTrue(low.ok, "a low-confidence extra beside real matches is only a warning")
        self.assertEqual(codes(low), ["LOW_CONFIDENCE"])

    def test_ok_always_means_at_least_one_room_was_matched(self):
        rng = random.Random(29)
        passed = 0
        for case in range(120):
            rooms = [(f"r{k}", rect(x0, y0, x0 + rng.uniform(0.8, 4.5), y0 + rng.uniform(0.8, 3.5)), rng.choice([None, 0.9, 0.2]))
                     for k in range(rng.randrange(1, 4)) for x0, y0 in [(rng.uniform(-1, 6), rng.uniform(-1, 3))]]
            report = run(evidence(*rooms, elevationM=rng.choice([0.0, 0.0, 7.0, 100.0])))
            passed += report.ok
            with self.subTest(case=case):
                if report.ok:
                    self.assertGreaterEqual(len(report.matches), 1)

    def test_the_command_line_exits_one_for_a_comparison_that_compared_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "elsewhere.json"
            path.write_text(json.dumps({**GOOD, "elevationM": 100, "rooms": [{**r, "confidence": 0.2} for r in GOOD["rooms"]]}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["check", "--enable", "--assembly", str(ROOT / "examples" / "module-ir-two-rooms.json"), "--evidence", str(path)])
        result = json.loads(out.getvalue())
        self.assertEqual((code, result["ok"]), (1, False))
        self.assertIn("NO_COMPARABLE_ROOMS", [d["code"] for d in result["rooms"]["diagnostics"]])


class HostileComplexityTests(unittest.TestCase):
    """Review P2: the evidence limits must also bound the work, not only the size. These tests count work; none of them times it."""

    def test_triangle_pruning_does_not_change_the_area(self):
        rng = random.Random(5)

        def blob():
            n = rng.randrange(5, 40)
            return star(n * 2, rng.uniform(1.5, 4), rng.uniform(0.4, 1.4), rng.uniform(0, 3), rng.uniform(0, 3))

        for case in range(25):
            a, b = triangles(blob()), triangles(blob())
            brute = sum(convex_intersection_area(x, y) for x in a for y in b)
            with self.subTest(case=case):
                self.assertAlmostEqual(intersection_area(a, b), brute, places=9)

    def test_pruning_really_skips_triangle_pairs_that_cannot_touch(self):
        a, b = triangles(star(64, 5, 3, 0, 0)), triangles(star(64, 5, 3, 4.5, 0))        # two overlapping stars, mostly apart
        calls = []
        real = geometry_module.convex_intersection_area
        with mock.patch.object(geometry_module, "convex_intersection_area", side_effect=lambda x, y: calls.append(1) or real(x, y)):
            intersection_area(a, b)
        self.assertGreater(len(calls), 0)
        self.assertLess(len(calls), len(a) * len(b), "every triangle pair was clipped: no pruning")

    def test_evidence_that_needs_too_many_triangles_is_refused_before_it_is_compared(self):
        one = {"schemaVersion": "rooms-evidence-v1", "evidenceId": "star", "detector": {"name": "t", "version": "0"},
               "rooms": [{"id": "s0", "polygon": star(256, 5, 3)}]}
        self.assertEqual(len(validate_evidence(one)["rooms"]), 1, "one 256-vertex star (about 4000 triangles) is within the budget")
        two = {**one, "rooms": [{"id": f"s{k}", "polygon": star(256, 5 + 0.01 * k, 3)} for k in range(16)]}
        self.assertLess(len(json.dumps(two)), MAX_BYTES, "inside every size and vertex limit, so only the triangle budget stops it")
        with self.assertRaisesRegex(EvidenceError, "too complex"):
            validate_evidence(two)
        with self.assertRaisesRegex(EvidenceError, "too complex"):
            validate_with_rooms(MODULES, two, enabled=True)

    def test_rooms_too_complex_to_compare_are_refused_without_clipping_anything(self):
        ev = evidence(("s0", star(128, 5, 3), None), ("s1", star(128, 5.02, 3), None))     # about 1000 triangles each, overlapping
        self.assertGreater(len(triangles(ev["rooms"][0]["polygon"])) ** 2, MAX_PAIR_WORK)
        with mock.patch.object(geometry_module, "convex_intersection_area", side_effect=AssertionError("clipping ran over budget")):
            report = run(ev)
        self.assertFalse(report.ok)
        self.assertIn("COMPLEXITY_LIMIT", codes(report))
        self.assertEqual(report.matches, ())
        result = validate_with_rooms(MODULES, {"schemaVersion": "rooms-evidence-v1", "evidenceId": "t", "detector": {"name": "t", "version": "0"},
                                               "rooms": [{"id": r["id"], "polygon": r["polygon"]} for r in ev["rooms"]]}, enabled=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.core.ok, True)

    def test_the_work_done_never_exceeds_the_budget(self):
        ev = evidence(("s0", star(64, 5, 3), None), ("s1", star(64, 5.02, 3), None), ("hall", rect(4, 0, 6, 3), None))
        calls = []
        real = geometry_module.convex_intersection_area
        with mock.patch.object(geometry_module, "convex_intersection_area", side_effect=lambda x, y: calls.append(1) or real(x, y)):
            report = run(ev)
        self.assertNotIn("COMPLEXITY_LIMIT", codes(report), "within the budget: it is compared")
        self.assertGreater(len(calls), 0)
        self.assertLessEqual(len(calls), MAX_PAIR_WORK)

    def test_the_limit_is_an_exact_count_not_a_timing(self):
        ev = evidence(("living", rect(0, 0, 4, 3), None), ("hall", rect(4, 0, 6, 3), None))
        rooms, skipped = intended_rooms(MODULES, elevation_m=0.0, level_tolerance=0.25)
        work = 8                                  # two rooms against their own slab, 2 x 2 triangles each; touching boxes do not count
        with mock.patch.object(compare_module, "MAX_PAIR_WORK", work):
            self.assertTrue(compare(rooms, ev, skipped=skipped).ok)
        with mock.patch.object(compare_module, "MAX_PAIR_WORK", work - 1):
            self.assertEqual(codes(compare(rooms, ev, skipped=skipped)), ["COMPLEXITY_LIMIT"])


class FeatureFlagBehaviourTests(unittest.TestCase):
    def test_off_returns_the_core_report_untouched(self):
        core = validate_assembly(MODULES)
        for off in (None, False):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(ENV_FLAG, None)
                result = validate_with_rooms(MODULES, GOOD, enabled=off)
            self.assertIsInstance(result, ValidationReport)
            self.assertEqual(result.to_dict(), core.to_dict())

    def test_off_never_looks_at_the_evidence(self):
        garbage = [{"this": "is not evidence"}, "not even an object", 12, [1, 2, 3], deep()]
        with mock.patch.object(check_module, "validate_evidence", side_effect=AssertionError("evidence was read")):
            for value in garbage:
                with self.subTest(evidence=type(value).__name__):
                    result = validate_with_rooms(MODULES, value)
                    self.assertIsInstance(result, ValidationReport)

    def test_off_gives_the_same_answer_for_a_broken_assembly(self):
        broken = copy.deepcopy(MODULES)
        broken[0]["schemaVersion"] = "9.9.9"
        self.assertEqual(validate_with_rooms(broken, GOOD).to_dict(), validate_assembly(broken).to_dict())

    def test_on_without_evidence_is_still_just_the_core_report(self):
        self.assertIsInstance(validate_with_rooms(MODULES, None, enabled=True), ValidationReport)

    def test_on_adds_the_comparison_beside_an_unchanged_core_report(self):
        result = validate_with_rooms(MODULES, GOOD, enabled=True)
        self.assertIsInstance(result, EnhancedReport)
        self.assertEqual(result.core.to_dict(), validate_assembly(MODULES).to_dict())
        self.assertTrue(result.ok)
        self.assertEqual(len(result.rooms.matches), 2)
        self.assertEqual(result.to_dict()["evidenceSha256"], evidence_sha256(GOOD))

    def test_on_via_the_environment_variable(self):
        with mock.patch.dict(os.environ, {ENV_FLAG: "1"}):
            self.assertIsInstance(validate_with_rooms(MODULES, GOOD), EnhancedReport)

    def test_on_and_a_room_finding_makes_the_combined_report_not_ok_while_the_core_stays_ok(self):
        result = validate_with_rooms(MODULES, OPEN_PLAN, enabled=True)
        self.assertTrue(result.core.ok)
        self.assertFalse(result.rooms.ok)
        self.assertFalse(result.ok)

    def test_on_with_unusable_evidence_raises_the_typed_error(self):
        for bad in ({"schemaVersion": "x"}, "nope", [], deep()):
            with self.subTest(evidence=type(bad).__name__), self.assertRaises(EvidenceError):
                validate_with_rooms(MODULES, bad, enabled=True)

    def test_on_with_an_assembly_that_cannot_be_placed_is_a_finding_not_a_crash(self):
        broken = copy.deepcopy(MODULES)
        broken[1]["parentId"] = broken[1]["moduleId"]
        result = validate_with_rooms(broken, GOOD, enabled=True)
        self.assertIsInstance(result, EnhancedReport)
        self.assertEqual(codes(result.rooms), ["ASSEMBLY_INVALID"])
        self.assertFalse(result.ok)


class OptionalNoCoreDependencyTests(unittest.TestCase):
    OWNERS = ("core", "agent", "agentctx", "agentguide", "bomc", "cli", "evaluation", "tools")

    def test_no_other_package_imports_the_adapter(self):
        offenders = []
        for package in self.OWNERS + ("integration/generator",):
            for path in sorted((ROOT / package).rglob("*.py")):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                        [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                    if any(n == "integration.rooms" or n.startswith("integration.rooms.") for n in names):
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_importing_the_core_the_mcp_server_and_the_cli_never_loads_the_adapter(self):
        code = ("import sys; import core.validator, core.assembly, agent.bmb_mcp, cli.bmb, bomc.compiler.graph_to_bomc, evaluation.run;"
                "bad=[m for m in sys.modules if m.startswith('integration.rooms')]; sys.exit(1 if bad else 0)")
        self.assertEqual(subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode, 0)

    def test_the_package_import_itself_is_lightweight(self):
        code = ("import sys; import integration.rooms;"
                "heavy=[m for m in ('core.validator','core.assembly','core.geometry.triangulation','agent','cli') if m in sys.modules];"
                "sys.exit(1 if heavy else 0)")
        self.assertEqual(subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode, 0)

    FORBIDDEN = {"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "requests", "httpx", "aiohttp", "anthropic", "openai",
                 "google", "cohere", "mistralai", "ollama", "websockets", "psutil", "numpy", "scipy", "shapely"}

    def test_no_network_model_or_third_party_geometry_library_and_the_environment_is_read_only_by_the_flag(self):
        for path in sorted((ROOT / "integration" / "rooms").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for name in names:
                    with self.subTest(file=path.name, module=name):
                        self.assertNotIn(name.split(".")[0], self.FORBIDDEN)
                if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                    self.assertEqual(path.name, "flag.py", f"{path.name} reads the environment")


class CommandLineTests(unittest.TestCase):
    def run_cli(self, argv, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False):
            if env is None:
                os.environ.pop(ENV_FLAG, None)
            with contextlib.redirect_stdout(out):
                code = cli.main(argv)
        return code, json.loads(out.getvalue())

    def paths(self):
        return str(ROOT / "examples" / "module-ir-two-rooms.json"), str(EX / "evidence-two-rooms.json"), str(EX / "evidence-open-plan.json")

    def test_off_by_default_reads_no_evidence_and_reports_the_core_result(self):
        assembly, good, _ = self.paths()
        code, result = self.run_cli(["check", "--assembly", assembly, "--evidence", good])
        self.assertEqual((code, result["enabled"], result["ok"]), (0, False, True))
        self.assertNotIn("rooms", result)
        code, result = self.run_cli(["check", "--assembly", assembly, "--evidence", "/definitely/not/there.json"])
        self.assertEqual(code, 0, "with the adapter off even a missing evidence file must not matter")

    def test_on_with_matching_evidence(self):
        assembly, good, _ = self.paths()
        code, result = self.run_cli(["check", "--enable", "--assembly", assembly, "--evidence", good])
        self.assertEqual((code, result["ok"], result["enabled"]), (0, True, True))
        self.assertEqual(len(result["rooms"]["matches"]), 2)

    def test_on_by_environment(self):
        assembly, good, _ = self.paths()
        code, result = self.run_cli(["check", "--assembly", assembly, "--evidence", good], env={ENV_FLAG: "1"})
        self.assertEqual((code, result["enabled"]), (0, True))

    def test_on_with_a_finding_exits_one(self):
        assembly, _, merged = self.paths()
        code, result = self.run_cli(["check", "--enable", "--assembly", assembly, "--evidence", merged])
        self.assertEqual((code, result["ok"]), (1, False))
        self.assertEqual([d["code"] for d in result["rooms"]["diagnostics"]], ["ROOM_MERGED"])

    def test_bad_input_exits_two_with_a_fail_verdict(self):
        assembly, good, _ = self.paths()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            for content in (b"not json", b"[1]", b'{"schemaVersion": "nope"}', b"\xff\xfe", b'{"a": 1, "a": 2}', b'{"x": NaN}',
                            b"x" * (MAX_BYTES + 5)):
                bad.write_bytes(content)
                with self.subTest(content=content[:14]):
                    code, result = self.run_cli(["check", "--enable", "--assembly", assembly, "--evidence", str(bad)])
                    self.assertEqual((code, result["verdict"]), (2, "FAIL"))
            code, result = self.run_cli(["check", "--enable", "--assembly", assembly, "--evidence", str(Path(tmp) / "missing.json")])
            self.assertEqual((code, result["verdict"]), (2, "FAIL"))
            bad.write_bytes(b"[]")
            code, result = self.run_cli(["check", "--enable", "--assembly", str(bad), "--evidence", good])
            self.assertEqual((code, result["verdict"]), (2, "FAIL"))


if __name__ == "__main__":
    unittest.main()
