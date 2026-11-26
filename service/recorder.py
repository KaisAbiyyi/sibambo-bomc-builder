"""Best-effort local session recording; never stores credential values."""
import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

MAX_BYTES = 50 * 1024 * 1024
SLOT = re.compile(r'[a-z][a-z0-9-]{0,31}\Z')
SESSION = re.compile(r'[0-9a-f]{32}\Z')
SENSITIVE = re.compile(r'secret|token|password|authorization|ticket', re.I)


def redact(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if SENSITIVE.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Recorder:
    def __init__(self, root, enabled=True):
        self.root, self.enabled = Path(root), enabled
        self._sessions, self._lock = {}, threading.Lock()
        if enabled and os.name == 'nt' and self.root.resolve().drive.upper() != 'D:':
            self.enabled = False
            print('Sibambo recorder disabled: recording root must be on D:.', file=sys.stderr)

    def append(self, slot, session, tool, args, ok, payload, ms, revision):
        if not self.enabled or not isinstance(slot, str) or not SLOT.fullmatch(slot) or not isinstance(session, str) or not SESSION.fullmatch(session):
            return
        with self._lock:
            now = datetime.now().astimezone()
            state = self._sessions.setdefault((slot, session), {'seq': 0, 'bytes': 0, 'stopped': False,
                'path': self.root / now.strftime('%Y-%m-%d') / f'{slot}-{now:%H%M%S}-{session[:8]}.jsonl'})
            if state['stopped']:
                return
            try:
                state['seq'] += 1
                row = {'t': now.isoformat(timespec='milliseconds'), 'seq': state['seq'], 'slot': slot,
                       'session': session, 'tool': tool, 'args': redact(args), 'ok': ok,
                       'result' if ok else 'error': redact(payload), 'ms': ms, 'revision': revision}
                raw = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
                if state['bytes'] + len(raw) > MAX_BYTES:
                    raw, state['stopped'] = b'{"truncated":true}\n', True
                state['path'].parent.mkdir(parents=True, exist_ok=True)
                with state['path'].open('ab') as handle:
                    handle.write(raw)
                state['bytes'] += len(raw)
            except (OSError, ValueError, TypeError, RecursionError):
                state['stopped'] = True
                print('Sibambo recorder disabled for this session: unable to record.', file=sys.stderr)
