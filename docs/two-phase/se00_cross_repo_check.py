"""SE-00 CP0 cross-repository check (read-only on both checkouts).

Usage: python -I se00_cross_repo_check.py BUILDER_CHECKOUT EDITOR_CHECKOUT
Generates the BMB-026 four-room corpus twice from the Builder candidate, requires both runs to be
byte-identical, and requires equality with the Editor's pinned original fixtures and manifest hashes.
Prints one JSON receipt. Exit code 0 only on PASS.
"""
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path

builder, editor = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
fx = editor / 'packages/e4-import/src/bmb026-fixtures'
manifest = json.loads((fx / 'manifest.json').read_text())
names = ['baseline.bomc', 'revised.bomc', 'baseline.json', 'revised.json', 'receipt.json']
sha = lambda b: hashlib.sha256(b).hexdigest()
git = lambda root, *a: subprocess.check_output(['git', '-C', str(root), *a], text=True).strip()
runs = []
for _ in range(2):
    with tempfile.TemporaryDirectory(prefix='se00-xrepo-') as t:
        subprocess.run([sys.executable, '-m', 'examples.bmb026_house', '--out-dir', t], cwd=builder, check=True, stdout=subprocess.DEVNULL)
        runs.append({n: (Path(t) / n).read_bytes() for n in names})
assert runs[0] == runs[1], 'generation not deterministic'
out = {'builderSha': git(builder, 'rev-parse', 'HEAD'), 'editorSha': git(editor, 'rev-parse', 'HEAD'), 'files': {}}
for n in names:
    pinned = (fx / n).read_bytes()
    assert runs[0][n] == pinned, n + ' differs from Editor pinned original fixture'
    assert sha(pinned) == manifest['files'][n]['sha256'] and len(pinned) == manifest['files'][n]['bytes'], n
    out['files'][n] = {'sha256': sha(pinned), 'bytes': len(pinned)}
out['verdict'] = 'PASS'
print(json.dumps(out, indent=2))
