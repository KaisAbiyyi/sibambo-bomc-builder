"""Negative and positive tests for se00_cross_repo_check.py (self-contained; builds throwaway git repos).

Run: python -I -m unittest docs/two-phase/test_se00_cross_repo_check.py  (or from this directory:
python -m unittest test_se00_cross_repo_check -v). Deliberately outside ``tests/`` so the inherited
Builder baseline test count is unchanged.
"""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import se00_cross_repo_check as check  # noqa: E402

SCRIPT = HERE / 'se00_cross_repo_check.py'
FIXTURE = check.FIXTURE_DIR

STUB = '''import argparse, json, os, pathlib
parser = argparse.ArgumentParser(); parser.add_argument('--out-dir', required=True)
out = pathlib.Path(parser.parse_args().out_dir)
MODE = os.environ.get('SE00_STUB_MODE', '')
out.joinpath('baseline.bomc').write_bytes(b'BASE-BOMC-' + b'x' * 20)
out.joinpath('revised.bomc').write_bytes(b'REVISED-BOMC-' + b'y' * 20)
out.joinpath('baseline.json').write_bytes(b'{"label":"baseline"}')
out.joinpath('revised.json').write_bytes(b'{"label":"revised"}')
out.joinpath('receipt.json').write_text(json.dumps({'gates': {'builder_source_assembly_compiler_reader': 'PASS'},
    'preservedModuleHashes': {'a': 1, 'b': 2, 'c': 3, 'd': 4}}))
'''
GOOD = {
    'baseline.bomc': b'BASE-BOMC-' + b'x' * 20,
    'revised.bomc': b'REVISED-BOMC-' + b'y' * 20,
    'baseline.json': b'{"label":"baseline"}',
    'revised.json': b'{"label":"revised"}',
    'receipt.json': json.dumps({'gates': {'builder_source_assembly_compiler_reader': 'PASS'},
                                'preservedModuleHashes': {'a': 1, 'b': 2, 'c': 3, 'd': 4}}).encode(),
}
PINS = {n: (hashlib.sha256(GOOD[n]).hexdigest(), len(GOOD[n])) for n in ('baseline.bomc', 'revised.bomc')}


def git(root, *args):
    env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
    done = subprocess.run(['git', '-C', str(root), '-c', 'commit.gpgsign=false', *args], capture_output=True,
                          text=True, env=env)
    if done.returncode:
        raise RuntimeError(done.stderr)
    return done.stdout.strip()


def commit_all(root, message='c'):
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD')


def manifest_for(files):
    return {'files': {n: {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)} for n, b in files.items()}}


class Fixture:
    def __init__(self, stub=STUB, fixtures=None, manifest=None):
        self.tmp = tempfile.mkdtemp(prefix='se00-test-')
        self.builder, self.editor = Path(self.tmp, 'builder'), Path(self.tmp, 'editor')
        for root in (self.builder, self.editor):
            root.mkdir()
            git(root, 'init', '-q')
        (self.builder / 'examples').mkdir()
        (self.builder / 'examples' / '__init__.py').write_text('')
        (self.builder / 'examples' / 'bmb026_house.py').write_text(stub)
        fixtures = GOOD if fixtures is None else fixtures
        directory = self.editor / FIXTURE
        directory.mkdir(parents=True)
        for name, data in fixtures.items():
            (directory / name).write_bytes(data)
        if manifest is not False:
            (directory / 'manifest.json').write_text(json.dumps(manifest_for(GOOD) if manifest is None else manifest))
        self.builder_sha, self.editor_sha = commit_all(self.builder), commit_all(self.editor)

    def run(self, **override):
        args = dict(builder=self.builder, editor=self.editor, expected_builder_sha=self.builder_sha,
                    expected_editor_sha=self.editor_sha, pins=PINS)
        args.update(override)
        return check.run_check(args['builder'], args['editor'], args['expected_builder_sha'],
                               args['expected_editor_sha'], pins=args['pins'])

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class CrossRepoCheckTests(unittest.TestCase):
    def fixture(self, **kwargs):
        fx = Fixture(**kwargs)
        self.addCleanup(fx.cleanup)
        return fx

    def refused(self, call, fragment):
        with self.assertRaises(check.CheckFailure) as caught:
            call()
        self.assertIn(fragment, str(caught.exception))

    # ----- positive control -----
    def test_clean_matching_pair_passes_with_every_claim_set(self):
        result = self.fixture().run()
        self.assertEqual(result['verdict'], 'PASS')
        self.assertTrue(result['expectedShaVerified'] and result['cleanTrees'] and result['generatedFromGitArchive'])
        self.assertEqual(set(result['files']), set(check.NAMES))

    # ----- expected-SHA verification -----
    def test_wrong_builder_sha_refused(self):
        fx = self.fixture()
        self.refused(lambda: fx.run(expected_builder_sha='0' * 40), 'does not match expected SHA')

    def test_wrong_editor_sha_refused(self):
        fx = self.fixture()
        self.refused(lambda: fx.run(expected_editor_sha='1' * 40), 'does not match expected SHA')

    def test_malformed_expected_sha_refused(self):
        fx = self.fixture()
        for bad in ('', 'HEAD', 'main', fx.builder_sha[:12], fx.builder_sha.upper(), fx.builder_sha + '0', None, 5):
            with self.subTest(bad=bad):
                self.refused(lambda bad=bad: fx.run(expected_builder_sha=bad), '40 lowercase hex')

    def test_new_commit_after_pinning_is_refused(self):
        fx = self.fixture()
        (fx.builder / 'examples' / 'extra.py').write_text('x = 1\n')
        commit_all(fx.builder, 'moved head')
        self.refused(lambda: fx.run(), 'does not match expected SHA')

    # ----- clean working tree -----
    def test_modified_tracked_file_in_builder_refused(self):
        fx = self.fixture()
        (fx.builder / 'examples' / 'bmb026_house.py').write_text(STUB + '\n# dirty\n')
        self.refused(lambda: fx.run(), 'Builder working tree is not clean')

    def test_untracked_file_in_builder_refused(self):
        fx = self.fixture()
        (fx.builder / 'stray.py').write_text('x = 1\n')
        self.refused(lambda: fx.run(), 'Builder working tree is not clean')

    def test_dirty_editor_fixture_refused(self):
        fx = self.fixture()
        (fx.editor / FIXTURE / 'baseline.bomc').write_bytes(b'tampered after commit')
        self.refused(lambda: fx.run(), 'Editor working tree is not clean')

    def test_subdirectory_of_a_repository_is_not_accepted(self):
        fx = self.fixture()
        self.refused(lambda: fx.run(builder=fx.builder / 'examples'), 'not the repository top level')

    def test_non_repository_and_missing_directory_refused(self):
        fx = self.fixture()
        plain = Path(fx.tmp, 'plain')
        plain.mkdir()
        self.refused(lambda: fx.run(builder=plain), 'git')
        self.refused(lambda: fx.run(builder=Path(fx.tmp, 'absent')), 'not a directory')

    # ----- fixture / manifest / pin integrity -----
    def test_committed_fixture_tamper_refused(self):
        tampered = dict(GOOD, **{'baseline.bomc': GOOD['baseline.bomc'] + b'!'})
        fx = self.fixture(fixtures=tampered)  # manifest still describes GOOD bytes
        self.refused(lambda: fx.run(), 'disagree with its own manifest')

    def test_consistently_tampered_fixture_and_manifest_refused_by_independent_pin(self):
        tampered = dict(GOOD, **{'revised.bomc': b'other bomc bytes'})
        fx = self.fixture(fixtures=tampered, manifest=manifest_for(tampered))
        self.refused(lambda: fx.run(), 'disagrees with independent pin')

    def test_missing_manifest_refused(self):
        fx = self.fixture(manifest=False)
        self.refused(lambda: fx.run(), 'git cat-file failed')

    def test_invalid_manifest_json_refused(self):
        fx = self.fixture()
        (fx.editor / FIXTURE / 'manifest.json').write_text('{not json')
        commit_all(fx.editor, 'bad manifest')
        self.refused(lambda: fx.run(expected_editor_sha=git(fx.editor, 'rev-parse', 'HEAD')), 'not valid JSON')

    def test_manifest_missing_entry_or_malformed_hash_refused(self):
        partial = manifest_for(GOOD)
        del partial['files']['receipt.json']
        self.refused(lambda: self.fixture(manifest=partial).run(), 'lacks entry receipt.json')
        malformed = manifest_for(GOOD)
        malformed['files']['baseline.json']['sha256'] = 'abc'
        self.refused(lambda: self.fixture(manifest=malformed).run(), 'sha256 malformed')
        boolean = manifest_for(GOOD)
        boolean['files']['baseline.json']['bytes'] = True
        self.refused(lambda: self.fixture(manifest=boolean).run(), 'byte count malformed')

    # ----- generator behaviour -----
    def test_generator_output_differing_from_fixture_refused(self):
        fx = self.fixture(stub=STUB.replace("b'BASE-BOMC-'", "b'BASE-BOMX-'"))
        self.refused(lambda: fx.run(), 'differs from Editor pinned fixture')

    def test_nondeterministic_generator_refused(self):
        stub = STUB + "\nout.joinpath('receipt.json').write_text(out.joinpath('receipt.json').read_text() + os.urandom(4).hex())\n"
        fx = self.fixture(stub=stub)
        self.refused(lambda: fx.run(), 'not deterministic')

    def test_failing_generator_refused(self):
        fx = self.fixture(stub=STUB + '\nraise SystemExit(3)\n')
        self.refused(lambda: fx.run(), 'generator exited 3')

    def test_generator_missing_output_refused(self):
        fx = self.fixture(stub=STUB + "\nout.joinpath('revised.json').unlink()\n")
        self.refused(lambda: fx.run(), 'did not produce regular file revised.json')

    def test_receipt_gate_not_pass_refused(self):
        bad = dict(GOOD, **{'receipt.json': json.dumps({'gates': {'builder_source_assembly_compiler_reader': 'FAIL'},
                                                        'preservedModuleHashes': {'a': 1, 'b': 2, 'c': 3, 'd': 4}}).encode()})
        stub = STUB.replace("'PASS'", "'FAIL'")
        fx = self.fixture(stub=stub, fixtures=bad, manifest=manifest_for(bad))
        self.refused(lambda: fx.run(), 'gate is not PASS')

    def test_untracked_or_ignored_builder_files_cannot_influence_generation(self):
        fx = self.fixture()
        # an ignored sitecustomize in the working tree must not be seen: generation uses git archive
        (fx.builder / '.gitignore').write_text('sitecustomize.py\n')
        fx.builder_sha = commit_all(fx.builder, 'ignore rule')
        (fx.builder / 'sitecustomize.py').write_text("raise SystemExit('ignored file executed')\n")
        self.assertEqual(fx.run()['verdict'], 'PASS')

    # ----- fail-closed structure -----
    def test_script_contains_no_assert_statements(self):
        for path in (SCRIPT, Path(__file__)):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            self.assertEqual([n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert)], [], path.name)

    def test_cli_exit_codes_and_no_pass_verdict_on_failure_even_with_optimization(self):
        fx = self.fixture()
        base = [str(SCRIPT), '--builder', str(fx.builder), '--editor', str(fx.editor)]
        for flags in ([], ['-O'], ['-OO']):
            with self.subTest(flags=flags):
                run = lambda *extra: subprocess.run([sys.executable, *flags, '-I', *base, *extra], capture_output=True, text=True)
                wrong = run('--expected-builder-sha', '0' * 40, '--expected-editor-sha', fx.editor_sha)
                self.assertEqual(wrong.returncode, 1)
                self.assertEqual(json.loads(wrong.stdout)['verdict'], 'FAIL')
                self.assertNotIn('PASS', wrong.stdout)
                # fake fixtures do not match the independent real-world pins compiled into the script
                pinned = run('--expected-builder-sha', fx.builder_sha, '--expected-editor-sha', fx.editor_sha)
                self.assertEqual(pinned.returncode, 1)
                self.assertIn('independent pin', json.loads(pinned.stdout)['reason'])
                missing = subprocess.run([sys.executable, *flags, '-I', *base], capture_output=True, text=True)
                self.assertEqual(missing.returncode, 2)
                self.assertNotIn('PASS', missing.stdout)

    def test_unexpected_internal_error_fails_closed(self):
        fx = self.fixture()
        original = check.generate
        check.generate = lambda *a, **k: (_ for _ in ()).throw(MemoryError('boom'))
        self.addCleanup(setattr, check, 'generate', original)
        code = check.main(['--builder', str(fx.builder), '--editor', str(fx.editor),
                           '--expected-builder-sha', fx.builder_sha, '--expected-editor-sha', fx.editor_sha])
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
