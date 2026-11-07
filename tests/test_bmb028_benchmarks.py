"""BMB-028: the measurement harness itself must be right, repeatable and unable to report a false PASS."""
from __future__ import annotations

import ast
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentctx.budget import estimate_tokens  # noqa: E402
from evaluation import metrics, run as runner, trial  # noqa: E402
from evaluation.metrics import McpObserver, describe, median, percentile  # noqa: E402

SCHEMA = json.loads((ROOT / "schemas" / "benchmark-result-v1.schema.json").read_text(encoding="utf-8"))
ASSEMBLY = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text(encoding="utf-8"))


def request(rid, method, tool=None, module=None):
    params = {"_meta": {}}
    if tool:
        params["name"], params["arguments"] = tool, ({"moduleId": module} if module else {})
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}


def reply(rid, *, error=None, protocol_error=None):
    if protocol_error is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": protocol_error, "message": "x"}}
    if error:
        return {"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "structuredContent": {"ok": False, "error": {"code": error}}}}
    return {"jsonrpc": "2.0", "id": rid, "result": {"isError": False, "structuredContent": {"ok": True, "data": {}}}}


def feed(observer, exchanges, ms=10.0):
    payload = b"".join(json.dumps(r).encode() + b"\n" for r, _ in exchanges)
    stdout = b"".join(json.dumps(p).encode() + b"\n" for _, p in exchanges)
    observer._record(payload, stdout, ms)


class StatisticsTests(unittest.TestCase):
    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2.0)
        self.assertEqual(median([4, 1, 3, 2]), 2.5)
        self.assertEqual(median([7]), 7.0)

    def test_nearest_rank_percentile(self):
        self.assertEqual(percentile([5], 95), 5.0)
        self.assertEqual(percentile([1, 2, 3], 95), 3.0)                        # with 3 trials P95 is the maximum
        self.assertEqual(percentile(list(range(1, 21)), 95), 19.0)
        self.assertEqual(percentile(list(range(1, 21)), 50), 10.0)
        self.assertEqual(percentile([9, 1, 5], 0), 1.0)

    def test_empty_input_is_refused_not_averaged(self):
        for fn in (median, lambda v: percentile(v, 95), describe):
            with self.assertRaises(ValueError):
                fn([])

    def test_describe(self):
        self.assertEqual(describe([2, 4, 6]), {"n": 3, "min": 2.0, "median": 4.0, "p95": 6.0, "max": 6.0})


class ObserverTests(unittest.TestCase):
    def test_counts_tool_calls_separately_from_discovery(self):
        obs = McpObserver()
        feed(obs, [(request(1, "server/discover"), reply(1)), (request(2, "tools/list"), reply(2)),
                   (request(3, "tools/call", "bmb_create_module", "a/b"), reply(3))])
        s = obs.summary()
        self.assertEqual((s["requests"], s["toolCalls"], s["rejectedToolCalls"], s["retries"]), (3, 1, 0, 0))

    def test_tokens_are_the_documented_estimate_of_what_was_written_and_read(self):
        obs = McpObserver()
        pair = (request(1, "tools/call", "bmb_inspect_module", "a/b"), reply(1))
        feed(obs, [pair])
        s = obs.summary()
        self.assertEqual(s["estimatedOutputTokens"], estimate_tokens(pair[0]))
        self.assertEqual(s["estimatedInputTokens"], estimate_tokens(pair[1]))
        self.assertIsNone(s["providerTokens"])
        self.assertIn("ceil", s["tokenEstimator"])

    def test_a_recoverable_rejection_followed_by_success_is_one_retry(self):
        obs = McpObserver()
        feed(obs, [(request(1, "tools/call", "bmb_edit_module", "a/b"), reply(1, error="REVISION_CONFLICT"))])
        feed(obs, [(request(2, "tools/call", "bmb_edit_module", "a/b"), reply(2))])
        s = obs.summary()
        self.assertEqual((s["rejectedToolCalls"], s["retries"], s["rejectionCodes"]), (1, 1, ["REVISION_CONFLICT"]))

    def test_things_that_are_not_retries(self):
        cases = {
            "terminal rejection then an unrelated success": [("bmb_edit_module", "a/b", "PERMISSION_DENIED"), ("bmb_edit_module", "a/b", None)],
            "invalid then success": [("bmb_create_module", "a/b", "INVALID_ARGUMENT"), ("bmb_create_module", "a/b", None)],
            "conflict never repaired": [("bmb_edit_module", "a/b", "REVISION_CONFLICT")],
            "conflict then success on ANOTHER module": [("bmb_edit_module", "a/b", "REVISION_CONFLICT"), ("bmb_edit_module", "c/d", None)],
            "conflict then success of ANOTHER tool": [("bmb_edit_module", "a/b", "REVISION_CONFLICT"), ("bmb_inspect_module", "a/b", None)],
        }
        for label, calls in cases.items():
            with self.subTest(case=label):
                obs = McpObserver()
                for n, (tool, module, error) in enumerate(calls, 1):
                    feed(obs, [(request(n, "tools/call", tool, module), reply(n, error=error))])
                self.assertEqual(obs.summary()["retries"], 0)

    def test_two_conflicts_each_repaired_are_two_retries(self):
        obs = McpObserver()
        for n, (module, error) in enumerate([("a/b", "REVISION_CONFLICT"), ("a/b", None), ("c/d", "REVISION_CONFLICT"), ("c/d", None)], 1):
            feed(obs, [(request(n, "tools/call", "bmb_edit_module", module), reply(n, error=error))])
        self.assertEqual(obs.summary()["retries"], 2)

    def test_a_protocol_level_error_counts_as_a_rejection(self):
        obs = McpObserver()
        feed(obs, [(request(1, "tools/call", "bmb_nope"), reply(1, protocol_error=-32602))])
        s = obs.summary()
        self.assertEqual((s["rejectedToolCalls"], s["rejectionCodes"]), (1, ["-32602"]))

    def test_bytes_and_batches_are_summed_and_latency_is_measured_per_batch(self):
        obs = McpObserver()
        a, b = [(request(1, "server/discover"), reply(1))], [(request(2, "tools/list"), reply(2)), (request(3, "tools/list"), reply(3))]
        feed(obs, a, ms=5.0)
        feed(obs, b, ms=20.0)
        s = obs.summary()
        self.assertEqual((s["mcpBatches"], s["slowestBatchMs"], s["mcpProcessMs"]), (2, 20.0, 25.0))
        self.assertEqual(s["requestBytes"], sum(len(json.dumps(r).encode()) + 1 for r, _ in a + b))

    def test_it_is_transparent_and_always_restores_subprocess_run(self):
        original = subprocess_run = __import__("subprocess").run
        obs = McpObserver()
        with self.assertRaises(RuntimeError):
            with obs:
                self.assertIsNot(__import__("subprocess").run, original)
                done = __import__("subprocess").run([sys.executable, "-c", "print(41+1)"], capture_output=True, check=False)
                self.assertEqual(done.stdout.strip(), b"42", "the command's result must pass through untouched")
                self.assertEqual(obs.requests, [], "an unrelated command must not be recorded")
                raise RuntimeError("boom")
        self.assertIs(__import__("subprocess").run, subprocess_run)


class WorldBoundsTests(unittest.TestCase):
    def test_translation_only_modules(self):
        self.assertEqual(trial.expected_world_bounds(ASSEMBLY), (0, 0, 0, 6, 3, 2.8))

    def test_anything_beyond_a_translation_is_not_guessed(self):
        doc = copy.deepcopy(ASSEMBLY)
        doc["modules"][1]["localFrame"]["transform"][0] = 2
        self.assertIsNone(trial.expected_world_bounds(doc))


class InputPinTests(unittest.TestCase):
    """Found on the first hosted Windows run: raw hashes of text files differ per OS (CRLF checkout), so the pins of
    two runs of the same commit were not comparable. Text is hashed with CRLF folded to LF."""

    def test_line_endings_do_not_change_a_text_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            lf, crlf, mixed = (Path(tmp) / n for n in ("lf.txt", "crlf.txt", "mixed.txt"))
            lf.write_bytes(b"a\nb\nc\n")
            crlf.write_bytes(b"a\r\nb\r\nc\r\n")
            mixed.write_bytes(b"a\r\nb\nc\r\n")
            self.assertEqual(trial.text_sha256(lf), trial.text_sha256(crlf))
            self.assertEqual(trial.text_sha256(lf), trial.text_sha256(mixed))

    def test_a_real_content_change_still_changes_the_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.txt", Path(tmp) / "b.txt"
            a.write_bytes(b"x = 1\n")
            b.write_bytes(b"x = 2\n")
            self.assertNotEqual(trial.text_sha256(a), trial.text_sha256(b))
            b.write_bytes(b"x = 1\n\n")                  # an extra blank line is a change, not a line-ending artefact
            self.assertNotEqual(trial.text_sha256(a), trial.text_sha256(b))

    def test_the_recorded_pins_use_that_normalization(self):
        result = runner.run_trial_process(1)
        want = trial._sha((ROOT / "examples" / "bmb025-prompts.json").read_bytes().replace(b"\r\n", b"\n"))
        self.assertEqual(result["inputs"]["promptFixtureSha256"], want)
        self.assertIn("CRLF", result["inputs"]["textHashing"])
        for path, digest in result["inputs"]["compilerSources"].items():
            self.assertEqual(digest, trial.text_sha256(ROOT / path))


class MemoryTests(unittest.TestCase):
    def test_peak_memory_is_a_positive_integer_or_an_honest_none(self):
        own = metrics.peak_rss_self()
        self.assertTrue(own is None or (isinstance(own, int) and own > 1_000_000), own)
        if os.name == "nt":
            self.assertIsNone(metrics.peak_rss_children(), "Windows has no stdlib child peak; it must say so, not guess")
        else:
            self.assertTrue(own is not None)

    def test_a_child_that_allocates_is_visible_in_the_children_peak(self):
        if os.name == "nt":
            self.skipTest("no stdlib child peak memory on Windows")
        before = metrics.peak_rss_children() or 0
        subprocess.run([sys.executable, "-c", "x = bytearray(180 * 1024 * 1024); x[-1] = 1"], check=True)
        self.assertGreater(metrics.peak_rss_children(), max(before, 150 * 1024 * 1024))


class ProbeTests(unittest.TestCase):
    def probe(self, *args):
        done = subprocess.run([sys.executable, "-m", "evaluation.probe", *args], cwd=ROOT, capture_output=True, timeout=120, check=False)
        return done.returncode, json.loads(done.stdout.decode().strip().splitlines()[-1]), done.stderr

    def test_compile_reports_hash_size_and_its_own_peak_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "x.bomc"
            code, data, err = self.probe("compile", "--input", str(ROOT / "examples" / "module-ir-two-rooms.json"), "--output", str(out))
            self.assertEqual((code, data["ok"], err), (0, True, b""))
            self.assertEqual(len(out.read_bytes()), data["receipt"]["sizeBytes"])
            self.assertEqual(data["receipt"]["sha256"], "a21109c137b943e5afc4a50776dcbf2eb3def36b93eaa63e951a9311ee46f632")
            self.assertGreater(data["compileMs"], 0)
            self.assertTrue(data["peakRssBytes"] is None or data["peakRssBytes"] > 1_000_000)

    def test_bad_input_is_a_typed_refusal_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            for content in (b"not json", b'{"schemaVersion": "9", "modules": []}', b"[]"):
                bad.write_bytes(content)
                with self.subTest(content=content[:14]):
                    code, data, err = self.probe("compile", "--input", str(bad))
                    self.assertEqual((code, data["ok"], err), (2, False, b""))
            code, data, err = self.probe("compile", "--input", str(Path(tmp) / "missing.json"))
            self.assertEqual((code, data["ok"], err), (2, False, b""))


class ReadbackAndGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.bomc"
            data = trial.cold_compile(trial.ASSEMBLY, out)
            cls.payload, cls.receipt = out.read_bytes(), data["receipt"]

    def test_the_real_output_passes_every_check(self):
        checks = trial.readback_checks(ASSEMBLY, self.payload, self.receipt)
        self.assertEqual([c["status"] for c in checks], ["PASS"] * len(checks))
        self.assertGreaterEqual(len(checks), 5)

    def regions(self):
        """offset -> label for every byte that the container's own integrity data covers; the rest is padding."""
        from tests.interop.reader import ENTRY, HEADER
        count = HEADER.unpack_from(self.payload)[5]
        rows = [ENTRY.unpack_from(self.payload, HEADER.size + i * ENTRY.size) for i in range(count)]
        covered = {o: "header" for o in range(HEADER.size)}
        covered.update({o: "directory" for o in range(HEADER.size, HEADER.size + count * ENTRY.size)})
        for row in rows:
            covered.update({o: f"section-{row[0]}" for o in range(row[3], row[3] + row[4])})
        return covered, rows

    def test_a_damaged_file_is_a_failure_not_a_pass(self):
        _, rows = self.regions()
        geometry = next(r for r in rows if r[0] == 13)             # the section holding the face/vertex data
        damaged = bytearray(self.payload)
        damaged[geometry[3] + 8] ^= 0xFF
        checks = trial.readback_checks(ASSEMBLY, bytes(damaged), self.receipt)
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertEqual(len(checks), 1, "after a rejected decode no other check may run on the damaged bytes")

    def test_every_single_byte_flip_outside_alignment_padding_is_rejected(self):
        # Integrity evidence for the model file the benchmark reports: only bytes the container does not cover
        # (the zero padding that aligns sections to 8) may survive a flip; everything else must be refused.
        from tests.interop.reader import read
        covered, _ = self.regions()
        survivors = []
        for offset in range(len(self.payload)):
            flipped = bytearray(self.payload)
            flipped[offset] ^= 0xFF
            try:
                read(bytes(flipped))
            except Exception:  # noqa: BLE001 - any typed rejection counts
                continue
            survivors.append(offset)
        self.assertEqual([o for o in survivors if o in covered], [], "a covered byte was accepted after corruption")
        self.assertLess(len(survivors), 100, "padding is a few dozen bytes, not a hole in the format")

    def test_a_receipt_that_disagrees_with_the_bytes_is_a_failure(self):
        for field in ("faceCount", "triangleCount"):
            with self.subTest(field=field):
                wrong = {**self.receipt, field: self.receipt[field] + 1}
                self.assertIn("FAIL", [c["status"] for c in trial.readback_checks(ASSEMBLY, self.payload, wrong)])
        wrong = {**self.receipt, "sections": self.receipt["sections"][:-1]}
        self.assertIn("FAIL", [c["status"] for c in trial.readback_checks(ASSEMBLY, self.payload, wrong)])

    def test_bounds_that_disagree_with_the_ir_are_a_failure(self):
        shifted = copy.deepcopy(ASSEMBLY)
        shifted["modules"][1]["bounds"]["max"][0] = 5.0
        statuses = {c["id"]: c["status"] for c in trial.readback_checks(shifted, self.payload, self.receipt)}
        self.assertEqual(statuses["world_bounds"], "FAIL")

    def test_floor_area(self):
        checks, area = trial.geometry_checks(ASSEMBLY)
        self.assertEqual(area, 18.0)
        self.assertEqual({c["status"] for c in checks}, {"PASS"})


class TrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = runner.run_trial_process(1)

    def test_result_matches_the_schema(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - CI installs the pinned validator
            self.skipTest("jsonschema is not installed")
        self.assertEqual(list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(self.result)), [])

    def test_deterministic_quantities_are_exactly_what_the_scenario_implies(self):
        w, m = self.result["metrics"]["workflow"], self.result["metrics"]["model"]
        self.assertEqual((w["requests"], w["toolCalls"], w["rejectedToolCalls"], w["retries"]), (21, 19, 4, 1))
        self.assertEqual(w["rejectionCodes"], ["INVALID_ARGUMENT", "PERMISSION_DENIED", "REVISION_CONFLICT"])
        self.assertEqual(w["mcpBatches"], 16)
        self.assertEqual((m["bomcBytes"], m["faceCount"], m["triangleCount"], m["vertexCount"], m["floorAreaM2"]), (8364, 58, 116, 60, 18.0))
        self.assertEqual(m["sha256"], "a21109c137b943e5afc4a50776dcbf2eb3def36b93eaa63e951a9311ee46f632")
        self.assertEqual((m["identicalAcrossColdProcesses"], m["matchesCheckedInGolden"]), (True, True))
        self.assertEqual(len(m["coldCompiles"]), 2)

    def test_gates_say_exactly_what_was_and_was_not_run(self):
        g = self.result["gates"]
        for gate in ("geometry", "revision_locality", "determinism", "metrics_recorded"):
            self.assertEqual(g[gate], "PASS", gate)
        for gate in ("security", "editor_import", "model_eval_import", "baseline_four_room_fixture", "live_llm_tokens"):
            self.assertEqual(g[gate], "NOT_RUN", gate)
        self.assertEqual(self.result["overall"], "INCOMPLETE", "a NOT_RUN mandatory gate can never read PASS")
        self.assertEqual(self.result["baselineStatus"], "NOT_RUN")
        self.assertIsNone(self.result["metrics"]["workflow"]["providerTokens"])

    def test_the_inputs_that_pin_the_run_are_recorded(self):
        i = self.result["inputs"]
        self.assertEqual(len(i["promptFixtureSha256"]), 64)
        self.assertEqual(set(i["compilerSources"]), set(trial.COMPILER_SOURCES))
        self.assertEqual(self.result["environment"]["llm"], "none")

    def test_memory_is_recorded_with_its_method_or_an_explicit_gap(self):
        w = self.result["metrics"]["workflow"]
        self.assertGreater(w["driverPeakPythonBytes"], 0)
        if os.name == "nt":
            self.assertIsNone(w["childPeakRssBytes"])
            self.assertIn("not measured", w["childPeakRssNote"])
        else:
            self.assertGreater(w["childPeakRssBytes"], 1_000_000)


class FailureDetectionTests(unittest.TestCase):
    """The harness must turn a broken system into FAIL, never into a quietly smaller PASS."""

    def test_nondeterministic_compilation_is_detected(self):
        calls = {"n": 0}
        real = trial.cold_compile

        def flaky(document_path, out_path):
            result = real(document_path, out_path)
            calls["n"] += 1
            if calls["n"] == 2:                       # the second cold process "produces" different bytes
                out_path.write_bytes(out_path.read_bytes() + b"\x00")
            return result

        with mock.patch.object(trial, "cold_compile", flaky):
            result = trial.run_trial(1)
        self.assertEqual(result["gates"]["determinism"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")
        self.assertFalse(result["metrics"]["model"]["identicalAcrossColdProcesses"])

    def test_an_observer_that_disagrees_with_the_controller_fails_the_trial(self):
        real = trial.run_scenario

        def lying(root, scenario, assembly):
            evidence = real(root, scenario, assembly)
            evidence["observations"]["mcpToolCalls"] += 1        # the controller "reports" one call more than the wire shows
            return evidence

        with mock.patch.object(trial, "run_scenario", lying):
            with self.assertRaises(Exception) as caught:
                trial.measure_workflow()
        self.assertIn("observer counted 19", str(caught.exception))

    def test_a_workflow_failure_is_a_fail_verdict_not_a_traceback(self):
        from agentguide.controller import ControllerError
        buffer = io.StringIO()
        with mock.patch.object(trial, "run_scenario", side_effect=ControllerError("stale edit not rejected")):
            with mock.patch("sys.stdout", buffer):
                code = trial.main(["--trial", "7"])
        data = json.loads(buffer.getvalue())
        self.assertEqual((code, data["overall"], data["trialId"]), (1, "FAIL", 7))
        self.assertIn("stale edit not rejected", data["error"])

    def test_a_broken_compile_fails_the_gates(self):
        def broken(document_path, out_path):
            return {"ok": False, "error": "boom", "wallMs": 1.0, "exitCode": 2}

        with mock.patch.object(trial, "cold_compile", broken):
            result = trial.run_trial(1)
        self.assertEqual(result["gates"]["metrics_recorded"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")


class AggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = runner.run_trial_process(1)

    def clones(self, n):
        out = []
        for i in range(n):
            t = copy.deepcopy(self.base)
            t["trialId"] = i + 1
            out.append(t)
        return out

    def test_identical_deterministic_values_and_descriptive_statistics(self):
        trials = self.clones(3)
        for t, ms in zip(trials, (100.0, 300.0, 200.0)):
            t["metrics"]["workflow"]["elapsedMs"] = ms
        s = runner.summarize(trials)
        self.assertEqual((s["trialsCompleted"], s["trialsFailed"], s["overall"]), (3, 0, "INCOMPLETE"))
        self.assertTrue(s["deterministic"]["identical"])
        d = s["descriptive"]["workflowElapsedMs"]
        self.assertEqual((d["min"], d["median"], d["p95"], d["max"], d["n"]), (100.0, 200.0, 300.0, 300.0, 3))
        self.assertEqual(s["descriptive"]["coldCompileMs"]["n"], 6)

    def test_a_deterministic_metric_that_differs_between_trials_fails_the_run(self):
        trials = self.clones(3)
        trials[1]["metrics"]["workflow"]["estimatedInputTokens"] += 1
        s = runner.summarize(trials)
        self.assertFalse(s["deterministic"]["identical"])
        self.assertEqual(s["deterministic"]["differingSections"], ["workflow"])
        self.assertEqual(s["overall"], "FAIL")

    def test_a_failed_trial_stays_in_the_denominator(self):
        trials = self.clones(2) + [{"schemaVersion": "bmb028-result-v1", "trialId": 3, "overall": "FAIL", "error": "boom"}]
        s = runner.summarize(trials)
        self.assertEqual((s["trialsRequested"], s["trialsCompleted"], s["trialsFailed"], s["overall"]), (3, 2, 1, "FAIL"))
        self.assertEqual(s["failures"], ["boom"])

    def test_all_trials_failed(self):
        s = runner.summarize([{"trialId": 1, "overall": "FAIL", "error": "x"}])
        self.assertEqual((s["trialsCompleted"], s["overall"]), (0, "FAIL"))

    def test_timing_differences_never_count_as_nondeterminism(self):
        trials = self.clones(3)
        for i, t in enumerate(trials):
            t["metrics"]["workflow"]["elapsedMs"] = 1000.0 * (i + 1)
            t["metrics"]["workflow"]["driverPeakPythonBytes"] += i
            t["metrics"]["model"]["coldCompiles"][0]["wallMs"] = float(i)
        self.assertTrue(runner.summarize(trials)["deterministic"]["identical"])


class EndToEndTests(unittest.TestCase):
    def test_three_cold_trials_are_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            done = subprocess.run([sys.executable, "-m", "evaluation.run", "--trials", "3", "--out", str(out)],
                                  cwd=ROOT, capture_output=True, timeout=600, check=False)
            self.assertEqual(done.returncode, 0, done.stderr.decode()[-500:])
            full = json.loads(out.read_text(encoding="utf-8"))
        summary = full["summary"]
        self.assertEqual((summary["trialsCompleted"], summary["deterministic"]["identical"], summary["overall"]), (3, True, "INCOMPLETE"))
        self.assertEqual(len(full["trials"]), 3)
        self.assertEqual({t["trialId"] for t in full["trials"]}, {1, 2, 3})
        self.assertEqual(json.loads(done.stdout.decode()), summary)

    def test_bad_arguments(self):
        for argv in (["--trials", "0"], ["--trials", "21"], ["--trials", "x"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                with mock.patch("sys.stderr", io.StringIO()):
                    runner.main(argv)


class NoNetworkNoModelTests(unittest.TestCase):
    FORBIDDEN = {"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "requests", "httpx", "aiohttp", "anthropic",
                 "openai", "google", "cohere", "mistralai", "ollama", "websockets", "psutil"}

    def test_the_evaluation_package_needs_no_network_model_or_third_party_dependency(self):
        for path in sorted((ROOT / "evaluation").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for name in names:
                    with self.subTest(file=path.name, module=name):
                        self.assertNotIn(name.split(".")[0], self.FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
