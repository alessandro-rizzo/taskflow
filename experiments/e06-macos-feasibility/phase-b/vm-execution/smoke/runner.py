#!/usr/bin/env python3
"""E06 one-cycle VM smoke runner. Default modes are strictly recording-only."""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import guest
import model as m


def attest(results, expected):
    actual = dict(expected)
    for key, _ in guest.IDENTITY:
        raw = results['identity-' + key]['stdout'].strip()
        if key in ('runtimes', 'devicetypes', 'guest_disk'):
            continue
        if key == 'xcode':
            match = re.fullmatch(r'Xcode ([^\n]+)\nBuild version ([^\n]+)', raw)
            m.require(match is not None, 'invalid Xcode identity')
            actual['xcode_version'], actual['xcode_build'] = match.groups()
        elif key == 'sip':
            m.require(raw == 'System Integrity Protection status: disabled.', 'SIP profile drift')
            actual['sip'] = 'disabled'
        elif key in ('cpu_count', 'memory_bytes'):
            actual[key] = int(raw)
        else:
            actual[key] = raw
    runtimes = json.loads(results['identity-runtimes']['stdout'])['runtimes']
    matches = [r for r in runtimes if r.get('identifier') == expected['runtime_identifier']]
    m.require(len(matches) == 1 and matches[0].get('isAvailable') is True and
              matches[0].get('buildversion') == expected['runtime_build'] and
              matches[0].get('supportedArchitectures') == [expected['runtime_architecture']],
              'runtime identity mismatch/unavailable')
    device_types = json.loads(results['identity-devicetypes']['stdout'])['devicetypes']
    matches = [d for d in device_types if d.get('identifier') == expected['device_type']]
    m.require(len(matches) == 1, 'device type identity mismatch/unavailable')
    disk = results['identity-guest_disk']['stdout'].splitlines()
    m.require(len(disk) == 2 and int(disk[1].split()[3]) >= 10 * 1024**2,
              'guest free disk below 10 GiB')
    m.profile(actual)
    m.require(actual == expected, 'guest differs from approved complete profile')
    return {'profile': actual, 'guest_tools': 'checked'}


def artifact(raw):
    rows = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        m.require(match is not None, 'malformed artifact manifest')
        checksum, path = match.groups()
        m.canonical_path(path, guest.APP)
        m.require(path not in rows, 'duplicate artifact path')
        rows[path] = checksum
    m.require(guest.APP + '/Info.plist' in rows and guest.APP + '/E06SmokeApp' in rows,
              'app outputs incomplete')
    return rows


class RecordingBackend:
    def __init__(self):
        self.records = []

    def record(self, operation):
        self.records.append(json.loads(json.dumps(operation)))


def record_plan():
    spec = guest.ledger()
    backend = RecordingBackend()
    for op in spec['operations']:
        backend.record(op)
    return {'stage': 'smoke-only', 'operation_count': len(backend.records),
            'ledger_sha256': m.digest(spec), 'execution_count': 0, 'benchmark_samples': 0,
            'live_blockers': ['SDK build IDs unresolved', 'reviewed implementation commit required',
                              'fresh exact smoke execution approval required'],
            'full_matrix_supported': False}


def run_smoke(backend, expected, spec):
    """Interpret only the deterministic closed ledger; injected backend is testable."""
    m.require(spec == guest.ledger(), 'modified operation ledger')
    m.profile(expected)
    results = {}
    handle = None
    primary = None
    try:
        for op in spec['operations']:
            identifier, action = op['id'], op['action']
            argv = [m.uuid(handle) if x == '{device}' else x for x in op['argv']]
            if action == 'host-checks':
                value = backend.host_checks()
            elif action == 'start-watchdog':
                backend.start_watchdog()
                value = {'status': 'started'}
            elif action in ('host-command', 'guest-command'):
                value = backend.command(argv, op['timeout_seconds'], op.get('stdin'))
            elif action == 'start-vm':
                value = backend.start_vm(argv)
            elif action == 'wait-guest':
                value = backend.wait_guest(argv)
            elif action == 'compare-profile':
                value = attest(results, expected)
            elif action == 'verify-artifact':
                value = artifact(results['artifact']['stdout'])
            elif action == 'verify-artifact-again':
                value = artifact(results[op['requires']]['stdout'])
                m.require(value == results['artifact-verify'], 'artifact changed before installation')
            elif action == 'capture-device':
                m.require(handle is None, 'device handle already assigned')
                handle = m.uuid(results['create']['stdout'].strip())
                value = {'device': handle}
            elif action == 'verify-device':
                value = m.device(results[op['requires']]['stdout'], handle, op['state'])
            elif action == 'verify-container':
                path = results[op['requires']]['stdout'].strip()
                m.canonical_path(path, m.SET + '/' + m.uuid(handle))
                m.require(path.endswith('/E06SmokeApp.app'), 'installed bundle path mismatch')
                value = {'container': path}
            elif action == 'verify-report':
                value = m.app_report(results[op['requires']]['stdout'], op['previous'])
            elif action == 'verify-no-devices':
                devices = json.loads(results[op['requires']]['stdout'])['devices']
                m.require(all(not rows for rows in devices.values()), 'custom device-set residue')
                value = {'device_count': 0}
            elif action == 'owned-vm-cleanup':
                value = backend.cleanup()
                backend.finish_watchdog()
            elif action == 'base-checks':
                value = backend.base_checks()
            else:
                raise m.Rejected('unknown action')
            results[identifier] = value
        return {'status': 'passed', 'stage': 'smoke-only', 'benchmark_samples': 0,
                'results': results, 'full_matrix_supported': False}
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            backend.cleanup()
        except Exception:
            if primary is None:
                raise
        finally:
            try:
                backend.finish_watchdog()
            except Exception:
                if primary is None:
                    raise
            if primary is not None and getattr(backend, 'claimed', False):
                # Even a failed candidate must retain post-run base-integrity evidence.
                # Keep the original failure; the backend records hash failure separately.
                try:
                    backend.base_checks()
                except Exception:
                    pass


def current_revision():
    def git(*args):
        return subprocess.run(['/usr/bin/git', '-C', str(m.REPO), *args], check=True,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    relative = str(m.HERE.relative_to(m.REPO))
    m.require(git('status', '--porcelain', '--', relative,
                  str(m.FIXTURE.relative_to(m.REPO))) == '', 'uncommitted executable inputs')
    tracked = set(git('ls-tree', '-r', '--name-only', 'HEAD', '--', relative).splitlines())
    m.require(tracked == set(m.implementation_bindings()), 'untracked/missing implementation input')
    return git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')


def approved_inputs(path, identity_path):
    from backend import no_links
    expected_dir = m.HERE.parent.parent / 'vm-approval'
    m.require(Path(path).absolute() == expected_dir / 'smoke.json', 'wrong approval location')
    m.require(Path(identity_path).absolute() == expected_dir / 'identity.json', 'wrong identity location')
    no_links(path)
    no_links(identity_path)
    a = json.loads(Path(path).read_text())
    e = json.loads(Path(identity_path).read_text())
    m.validate_approval(a, guest.ledger(), m.implementation_bindings(), current_revision(), datetime.now(timezone.utc))
    m.validate_identity_evidence(e, a)
    return a


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['describe', 'record-plan', 'validate-approval', 'execute-smoke'])
    parser.add_argument('--approval')
    parser.add_argument('--identity')
    args = parser.parse_args()
    if args.mode in ('describe', 'record-plan'):
        value = record_plan()
        if args.mode == 'describe':
            value.update(ledger=guest.ledger(), identity_completion=guest.identity_completion_plan(), cleanup=m.cleanup_plan())
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    m.require(args.approval and args.identity, 'approval and identity files required')
    approval = approved_inputs(args.approval, args.identity)
    if args.mode == 'validate-approval':
        print(json.dumps({'valid': True, 'execution_count': 0}))
        return
    from backend import LiveBackend
    backend = LiveBackend(expires_at=datetime.fromisoformat(approval['expires_at'].replace('Z', '+00:00')).timestamp())
    backend.create_run()
    backend.persist('approval.json', approval)
    try:
        result = run_smoke(backend, approval['profile'], guest.ledger())
    except BaseException as exc:
        backend.persist('failure.json', {'status': 'failed', 'error': str(exc), 'benchmark_samples': 0})
        raise
    backend.persist('result.json', result)
    print(json.dumps({'status': result['status'], 'evidence': m.RUN, 'benchmark_samples': 0}))


if __name__ == '__main__':
    try:
        main()
    except (m.Rejected, ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit('e06-vm-smoke: ' + str(exc))
