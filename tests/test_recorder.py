"""WP2: recorder isolation, recursive redaction, bounds and failure containment."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.recorder import Recorder


class RecorderTests(unittest.TestCase):
    def test_nested_secrets_are_redacted_and_sessions_have_independent_sequences(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = Recorder(Path(tmp), True)
            for session in ('a' * 32, 'b' * 32, 'a' * 32):
                recorder.append('codex', session, 'describe_scene',
                                {'nested': [{'Authorization': 'private', 'ticketValue': 'private'}], 'text': 'safe'},
                                True, {'accessToken': 'private', 'revision': 3}, 1.25, 3)
            files = list(Path(tmp).glob('*/*.jsonl'))
            self.assertEqual(len(files), 2)
            first = next(f for f in files if 'aaaaaaaa' in f.name)
            rows = [json.loads(line) for line in first.read_text().splitlines()]
            self.assertEqual([r['seq'] for r in rows], [1, 2])
            self.assertEqual(rows[0]['revision'], 3)
            self.assertEqual(rows[0]['args']['nested'][0]['Authorization'], '[redacted]')
            self.assertEqual(rows[0]['result']['accessToken'], '[redacted]')
            self.assertNotIn('private', first.read_text())

    def test_cap_emits_one_marker_and_then_stops(self):
        with tempfile.TemporaryDirectory() as tmp, patch('service.recorder.MAX_BYTES', 600):
            recorder = Recorder(Path(tmp), True)
            for _ in range(10):
                recorder.append('codex', 'a' * 32, 'measure', {'a': 'x' * 200}, True, {}, 0, None)
            rows = [json.loads(line) for line in next(Path(tmp).glob('*/*.jsonl')).read_text().splitlines()]
            self.assertEqual(rows[-1], {'truncated': True})
            self.assertEqual(sum(r.get('truncated', False) for r in rows), 1)

    def test_io_failure_warns_once_per_session_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'file'
            root.write_text('not a directory')
            stream = io.StringIO()
            with contextlib.redirect_stderr(stream):
                recorder = Recorder(root, True)
                for _ in range(3):
                    recorder.append('codex', 'a' * 32, 'measure', {}, False, {}, 0, None)
            self.assertEqual(len(stream.getvalue().splitlines()), 1)
            self.assertNotIn('not a directory', stream.getvalue())

    def test_disabled_and_unsafe_identity_never_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            for recorder, slot, session in [(Recorder(Path(tmp), False), 'codex', 'a' * 32),
                                            (Recorder(Path(tmp), True), '../escape', 'a' * 32),
                                            (Recorder(Path(tmp), True), 'codex', '../../escape')]:
                recorder.append(slot, session, 'measure', {}, True, {}, 0, None)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_non_d_windows_root_is_disabled_without_creating_files(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp, patch('service.recorder.os', SimpleNamespace(name='nt')):
            # On Windows use a C: path; on Linux a POSIX path has no D: drive.
            import os
            root = Path('C:/sibambo-recorder-refused') if os.name == 'nt' else Path(tmp)
            with contextlib.redirect_stderr(io.StringIO()) as output:
                recorder = Recorder(root, True)
                recorder.append('codex', 'a' * 32, 'measure', {}, True, {}, 0, None)
            self.assertFalse(recorder.enabled)
            self.assertEqual(len(output.getvalue().splitlines()), 1)
