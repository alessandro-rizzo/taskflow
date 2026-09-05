"""Owned-VM reaper: parent pipe EOF or bounded window; never runs in checks."""
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import model as m
from backend import no_links


def reap(command):
    """Injected command function makes caller-loss cleanup testable without processes."""
    rows = json.loads(command([m.TART, 'list', '--format', 'json'], 2))
    matches = [r for r in rows if r.get('Name') == m.VM]
    if not matches:
        # Parent may have died while cloning. Absence now is not proof no child can finish later.
        return {'status': 'orphan-review', 'vm': m.VM, 'path': m.VM_DIR,
                'reason': 'caller lost; check in-flight clone/host command before removing lock'}
    m.require(len(matches) == 1, 'ambiguous owned VM')
    if matches[0].get('State') != 'stopped' or matches[0].get('Running') is not False:
        command([m.TART, 'stop', m.VM, '--timeout', '20'], 23)
    rows = json.loads(command([m.TART, 'list', '--format', 'json'], 2))
    matches = [r for r in rows if r.get('Name') == m.VM]
    m.require(len(matches) == 1 and matches[0].get('State') == 'stopped' and
              matches[0].get('Running') is False, 'stop unconfirmed')
    # Retention is intentional on caller loss: command completion/diagnostic collection is unknown.
    return {'status': 'stopped-orphan', 'vm': m.VM, 'path': m.VM_DIR,
            'reason': 'caller lost; retained clone and diagnostics, no base deletion'}


def main():
    m.require(len(sys.argv) == 2 and sys.argv[1].isdigit(), 'owned pipe descriptor required')
    fd = int(sys.argv[1])
    m.require(fd > 2, 'invalid pipe')
    no_links(m.RUN)
    owner = json.loads((Path(m.RUN) / 'ownership.json').read_text())
    m.require(owner == {'vm': m.VM, 'path': m.VM_DIR, 'root_absent_before_claim': True}, 'missing claim')
    ready, _, _ = select.select([fd], [], [], m.LIVE_SECONDS)
    if ready and os.read(fd, 1) == b'D':
        return
    start = time.monotonic()

    def command(argv, timeout):
        p = subprocess.run(argv, env=m.ENV, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=timeout)
        m.require(p.returncode == 0 and len(p.stdout) <= m.MAX_OUTPUT, 'reaper command failed')
        return p.stdout

    try:
        result = reap(command)
    except Exception as exc:
        result = {'status': 'unconfirmed-orphan', 'vm': m.VM, 'path': m.VM_DIR, 'error': str(exc)}
    result['duration_seconds'] = time.monotonic() - start
    result['within_grace'] = result['duration_seconds'] <= m.CLEANUP_SECONDS
    with (Path(m.RUN) / 'watchdog-result.json').open('x') as output:
        json.dump(result, output, indent=2)


if __name__ == '__main__':
    main()
