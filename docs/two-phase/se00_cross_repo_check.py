"""SE-00 CP0 cross-repository check: Builder candidate -> original Editor pinned fixtures.

Fail-closed by construction: every condition is an explicit ``if``/``raise`` (no ``assert``, so
``python -O`` cannot disable a check), every error path ends in a non-zero exit, and the PASS
verdict is printed only after every step has completed.

Usage (both expected SHAs are mandatory 40-hex lowercase commit ids):

    python -I se00_cross_repo_check.py --builder DIR --editor DIR \
        --expected-builder-sha SHA --expected-editor-sha SHA

Steps: (1) each checkout must be the repository top level, HEAD must equal its expected SHA and the
working tree must be clean; (2) all pinned inputs are read from the expected commit objects, and the
Builder source is exported with ``git archive`` so ignored/untracked files cannot influence output;
(3) the generator runs twice under different PYTHONHASHSEED values and both runs must be byte-identical;
(4) output must equal the Editor's pinned original fixtures, the fixture manifest and the independent
pins compiled into this script (so a tampered fixture+manifest pair is rejected).

Exit codes: 0 PASS, 1 FAIL (any validation or unexpected error), 2 usage error.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

NAMES = ('baseline.bomc', 'revised.bomc', 'baseline.json', 'revised.json', 'receipt.json')
FIXTURE_DIR = 'packages/e4-import/src/bmb026-fixtures'
# Independent pins (original BMB-026 binaries, D11 baseline). Not read from the Editor manifest.
PINNED_BOMC = {
    'baseline.bomc': ('071ebe152b44d2bae387818094ad67a6f461645d45d1ad33c195848dbb0b49aa', 32660),
    'revised.bomc': ('e56924fead241df9a1a76c9de9e0e647b13caf2785cf14bc4c679a8979192233', 32660),
}
SHA40 = re.compile(r'[0-9a-f]{40}')
SHA256 = re.compile(r'[0-9a-f]{64}')
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
GENERATOR_TIMEOUT_SECONDS = 300


class CheckFailure(Exception):
    """A validation condition did not hold. Always fatal."""


def require(condition, message):
    if not condition:
        raise CheckFailure(message)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args, binary=False):
    try:
        done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=60,
                              env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, subprocess.SubprocessError) as error:
        raise CheckFailure('git %s failed to run: %s' % (args[0], error)) from error
    require(done.returncode == 0, 'git %s failed (exit %d): %s' % (
        args[0], done.returncode, done.stderr.decode('utf-8', 'replace').strip()[:200]))
    return done.stdout if binary else done.stdout.decode('utf-8').strip()


def verify_checkout(path, expected_sha, label):
    require(isinstance(expected_sha, str) and SHA40.fullmatch(expected_sha) is not None,
            '%s expected SHA must be 40 lowercase hex characters' % label)
    root = Path(path)
    require(root.is_dir(), '%s checkout is not a directory' % label)
    top = Path(git(root, 'rev-parse', '--show-toplevel'))
    require(top.resolve() == root.resolve(), '%s path is not the repository top level' % label)
    head = git(root, 'rev-parse', '--verify', 'HEAD^{commit}')
    require(head == expected_sha, '%s HEAD %s does not match expected SHA %s' % (label, head, expected_sha))
    require(git(root, 'status', '--porcelain', '--untracked-files=all') == '',
            '%s working tree is not clean' % label)
    return root


def commit_file(root, sha, relative):
    return git(root, 'cat-file', 'blob', '%s:%s' % (sha, relative), binary=True)


def export_tree(root, sha, destination):
    data = git(root, 'archive', '--format=tar', sha, binary=True)
    require(0 < len(data) <= MAX_ARCHIVE_BYTES, 'Builder archive size outside accepted range')
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(destination, filter='data')
    except (tarfile.TarError, OSError, TypeError) as error:
        raise CheckFailure('Builder archive extraction refused: %s' % error) from error


def generate(source_root, hash_seed):
    with tempfile.TemporaryDirectory(prefix='se00-generate-') as out:
        env = {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': str(hash_seed),
               'PATH': os.environ.get('PATH', '')}
        if os.environ.get('SYSTEMROOT'):
            env['SYSTEMROOT'] = os.environ['SYSTEMROOT']
        try:
            done = subprocess.run([sys.executable, '-B', '-m', 'examples.bmb026_house', '--out-dir', out],
                                  cwd=str(source_root), env=env, capture_output=True,
                                  timeout=GENERATOR_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as error:
            raise CheckFailure('generator did not complete: %s' % error) from error
        require(done.returncode == 0, 'generator exited %d: %s' % (
            done.returncode, done.stderr.decode('utf-8', 'replace').strip()[-200:]))
        produced = {}
        for name in NAMES:
            file = Path(out) / name
            require(file.is_file() and not file.is_symlink(), 'generator did not produce regular file ' + name)
            require(file.stat().st_size <= MAX_FILE_BYTES, 'generator output too large: ' + name)
            produced[name] = file.read_bytes()
        return produced


def validate_manifest(manifest, pins):
    require(isinstance(manifest, dict) and isinstance(manifest.get('files'), dict),
            'fixture manifest has no files table')
    for name in NAMES:
        entry = manifest['files'].get(name)
        require(isinstance(entry, dict), 'fixture manifest lacks entry ' + name)
        require(isinstance(entry.get('sha256'), str) and SHA256.fullmatch(entry['sha256']) is not None,
                'fixture manifest sha256 malformed for ' + name)
        require(isinstance(entry.get('bytes'), int) and not isinstance(entry['bytes'], bool) and entry['bytes'] > 0,
                'fixture manifest byte count malformed for ' + name)
    for name, (digest, size) in pins.items():
        entry = manifest['files'][name]
        require(entry['sha256'] == digest and entry['bytes'] == size,
                'fixture manifest disagrees with independent pin for ' + name)


def run_check(builder, editor, expected_builder_sha, expected_editor_sha, pins=None):
    pins = PINNED_BOMC if pins is None else pins
    builder_root = verify_checkout(builder, expected_builder_sha, 'Builder')
    editor_root = verify_checkout(editor, expected_editor_sha, 'Editor')

    try:
        manifest = json.loads(commit_file(editor_root, expected_editor_sha, FIXTURE_DIR + '/manifest.json'))
    except ValueError as error:
        raise CheckFailure('fixture manifest is not valid JSON: %s' % error) from error
    validate_manifest(manifest, pins)
    fixtures = {name: commit_file(editor_root, expected_editor_sha, FIXTURE_DIR + '/' + name) for name in NAMES}

    with tempfile.TemporaryDirectory(prefix='se00-builder-') as exported:
        export_tree(builder_root, expected_builder_sha, exported)
        first, second = generate(exported, 1), generate(exported, 2)
    require(first == second, 'generator output is not deterministic across runs')

    files = {}
    for name in NAMES:
        entry = manifest['files'][name]
        require(len(fixtures[name]) == entry['bytes'] and sha256_hex(fixtures[name]) == entry['sha256'],
                'Editor fixture bytes disagree with its own manifest: ' + name)
        require(first[name] == fixtures[name], 'generated %s differs from Editor pinned fixture' % name)
        files[name] = {'sha256': sha256_hex(fixtures[name]), 'bytes': len(fixtures[name])}
    # Defense in depth: after the manifest-vs-pin check and the byte-equality checks above this cannot differ.
    for name, (digest, size) in pins.items():
        require(files[name] == {'sha256': digest, 'bytes': size}, 'generated %s differs from independent pin' % name)

    try:
        receipt = json.loads(first['receipt.json'])
        gate = receipt['gates']['builder_source_assembly_compiler_reader']
        preserved = receipt['preservedModuleHashes']
    except (ValueError, KeyError, TypeError) as error:
        raise CheckFailure('generated receipt structure invalid: %s' % error) from error
    require(gate == 'PASS', 'generated receipt gate is not PASS')
    require(isinstance(preserved, (list, dict)) and len(preserved) == 4, 'receipt must preserve exactly four module hashes')

    return {'builderSha': expected_builder_sha, 'editorSha': expected_editor_sha,
            'expectedShaVerified': True, 'cleanTrees': True, 'generatedFromGitArchive': True,
            'deterministicAcrossHashSeeds': True, 'files': files, 'verdict': 'PASS'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='SE-00 CP0 fail-closed cross-repository check')  # no __doc__ use: stripped by -OO
    parser.add_argument('--builder', required=True)
    parser.add_argument('--editor', required=True)
    parser.add_argument('--expected-builder-sha', required=True)
    parser.add_argument('--expected-editor-sha', required=True)
    args = parser.parse_args(argv)  # argparse exits with status 2 on usage errors
    try:
        result = run_check(args.builder, args.editor, args.expected_builder_sha, args.expected_editor_sha)
    except CheckFailure as failure:
        print(json.dumps({'verdict': 'FAIL', 'reason': str(failure)}, indent=2))
        return 1
    except Exception as error:  # fail closed on anything unanticipated
        print(json.dumps({'verdict': 'FAIL', 'reason': 'unexpected %s: %s' % (type(error).__name__, error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
