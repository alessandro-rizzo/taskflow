"""Pure smoke specification and validation. Never imports the native backend."""
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
FIXTURE = REPO / 'experiments/e06-macos-feasibility/phase-b/fixture/E06SmokeApp'
ROOT = '/private/tmp/taskflow-e06-vm-a'
RUN = ROOT + '/smoke-run'
GUEST = ROOT + '/smoke'
VM = 'taskflow-e06-vm-a-smoke'
VM_DIR = ROOT + '/tart/vms/' + VM
SET = GUEST + '/CoreSimulator'
NS = 'taskflow-e06-vm-a-smoke-namespace-a'
BUNDLE = 'dev.taskflow.e06.smoke'
IMAGE_SHA = '61f6e857a3d65dd2f8daf9c51c7b837fa458bcc9181ae8556e645b534dab6bf6'
IMAGE = 'ghcr.io/cirruslabs/macos-tahoe-xcode@sha256:' + IMAGE_SHA
BASE = ROOT + '/tart/cache/OCIs/ghcr.io/cirruslabs/macos-tahoe-xcode/sha256:' + IMAGE_SHA
TART = ROOT + '/tools/tart-2.36.0/tart.app/Contents/MacOS/tart'
SOFTNET = ROOT + '/tools/softnet-0.23.0/softnet'
TART_SHA = 'e0d71385a2974229c3e97f71862020cce4911c16c3a2fb74ab5e6f540a62131e'
SOFTNET_SHA = '5982c8cde55cd039d4aa71add54356224b8b8a040df1a8786f16327b421f701d'
BASE_HASHES = {
    'manifest.json': IMAGE_SHA,
    'config.json': 'cf4ace9e40323ec8d0c4b233a3e54bcce28b62a4211f94d7349350a3e726dc03',
    'nvram.bin': '954c8f723cdd1e34567167ebe972f57308833a2cb588535ddefd644d54271f66',
    'disk.img': '39457bd2f67d82eafebca964ca7d6e5ce01e72de64b2ade50d4c96636d07f692',
}
FIXTURE_HASHES = {
    'E06SmokeApp/AppDelegate.swift': '13096655127f5220e28eb7416aa721dd4a8f00c46f991e3612ea648c9993b92f',
    'E06SmokeApp.xcodeproj/project.pbxproj': 'ea2b83080242c2974548cbcca4631badde396c8484002bcaf0d453f252c549e5',
    'E06SmokeApp.xcodeproj/xcshareddata/xcschemes/E06SmokeApp.xcscheme': '5c2bb049fc2869f94d9b0522772ba4c48cd6d1ba42147362d13882275bbfeec5',
}
ENV = {
    'PATH': str(Path(SOFTNET).parent) + ':/usr/bin:/bin:/usr/sbin:/sbin',
    'LANG': 'C', 'LC_ALL': 'C', 'CFFIXED_USER_HOME': ROOT,
    'TART_HOME': ROOT + '/tart', 'TART_NO_AUTO_PRUNE': '1', 'TMPDIR': ROOT + '/tmp',
}
SCOPES = ['smoke-only', 'unsigned-helper', 'host-only-not-hermetic',
          'guest-sip-disabled', 'delete-smoke-clone']
MAX_OUTPUT = 8 * 1024 * 1024
LIVE_SECONDS = 1800
CLEANUP_SECONDS = 30


class Rejected(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Rejected(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def observation():
    return json.loads((HERE / 'profile-observation.json').read_text())


def profile_fields():
    return set(observation()) - {'kind', 'observed_at', 'source_receipt_sha256'}


def profile(value):
    require(isinstance(value, dict) and set(value) == profile_fields(), 'profile keys differ')
    for key, expected in observation().items():
        if key not in profile_fields():
            continue
        if expected is None:
            require(isinstance(value[key], str) and re.fullmatch(r'[0-9A-Za-z.]{2,32}', value[key]),
                    'unresolved SDK build: ' + key)
        else:
            require(type(value[key]) is type(expected) and value[key] == expected, 'profile drift: ' + key)
    return value


def canonical_path(value, root):
    require(isinstance(value, str) and value.startswith(root + '/'), 'path outside owned root')
    require(str(PurePosixPath(value)) == value and '..' not in PurePosixPath(value).parts,
            'noncanonical path')
    require(not any(c in value for c in '\n\r\0*?[]'), 'unsafe path')
    return value


def uuid(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', value),
            'invalid device handle')
    return value.upper()


def device(raw, handle, state):
    doc = json.loads(raw)
    matches = [(runtime, d) for runtime, rows in doc['devices'].items() for d in rows
               if d.get('udid', '').upper() == uuid(handle)]
    require(len(matches) == 1, 'missing or duplicate device handle')
    runtime, d = matches[0]
    require(runtime == observation()['runtime_identifier'] and d.get('name') == VM,
            'device namespace/runtime mismatch')
    require(d.get('deviceTypeIdentifier') == observation()['device_type'] and d.get('isAvailable') is True,
            'device type unavailable/mismatch')
    require(d.get('state') == state, 'wrong device state')
    return d


def app_report(output, previous):
    lines = [x.removeprefix('TASKFLOW_E06_RESULT:') for x in output.splitlines()
             if x.startswith('TASKFLOW_E06_RESULT:')]
    require(len(lines) == 1, 'missing/duplicate app report')
    report = json.loads(lines[0])
    require(report == {'namespace': NS, 'status': 'ok', 'previous_default': previous,
                       'previous_file': previous, 'previous_keychain_name': previous},
            'canary persistence/reset failed')
    return report


def payload_files():
    actual = {str(p.relative_to(FIXTURE)) for p in FIXTURE.rglob('*') if p.is_file()}
    require(actual == set(FIXTURE_HASHES), 'fixture fileset changed')
    files = []
    for name, expected in sorted(FIXTURE_HASHES.items()):
        p = FIXTURE / name
        require(not any(x.is_symlink() for x in [p, *p.parents]), 'fixture symlink')
        data = p.read_bytes()
        require(sha(data) == expected and len(data) < 1024 * 1024, 'fixture bytes changed')
        files.append({'path': name, 'sha256': expected, 'size': len(data),
                      'base64': base64.b64encode(data).decode()})
    return files


def implementation_bindings():
    result = {}
    for p in sorted(HERE.rglob('*')):
        require(not p.is_symlink(), 'symlink in implementation')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            result[str(p.relative_to(REPO))] = sha(p.read_bytes())
    return result


def validate_approval(a, ledger, bindings, revision, now):
    keys = {'schema', 'operator', 'approved_at', 'not_before', 'expires_at', 'commit', 'tree',
            'bindings', 'ledger_sha256', 'profile', 'identity_evidence_sha256', 'scopes'}
    require(isinstance(a, dict) and set(a) == keys, 'approval keys differ')
    require(a['schema'] == 'taskflow-e06-vm-smoke-approval/v1', 'wrong approval schema')
    require(isinstance(a['operator'], str) and 0 < len(a['operator']) <= 128, 'missing operator')
    require(a['bindings'] == bindings and a['ledger_sha256'] == digest(ledger), 'unbound code/ledger')
    require((a['commit'], a['tree']) == revision and all(re.fullmatch('[0-9a-f]{40}', x) for x in revision),
            'implementation revision mismatch')
    require(a['scopes'] == SCOPES, 'approval scope differs')
    require(isinstance(a['identity_evidence_sha256'], str) and
            re.fullmatch('[0-9a-f]{64}', a['identity_evidence_sha256']), 'identity evidence not bound')
    dates = [datetime.fromisoformat(a[k].replace('Z', '+00:00'))
             for k in ('approved_at', 'not_before', 'expires_at')]
    require(all(x.tzinfo is not None for x in dates), 'timestamps need timezone')
    approved, start, end = dates
    require(approved <= start <= now <= end and (end - start).total_seconds() <= 7200,
            'approval expired, future or unbounded')
    profile(a['profile'])
    return a


def validate_identity_evidence(evidence, approved):
    require(isinstance(evidence, dict) and set(evidence) == {'kind', 'profile', 'tool_checks', 'base_sha256'},
            'identity evidence keys differ')
    require(evidence['kind'] == 'live-guest-identity' and evidence['base_sha256'] == IMAGE_SHA,
            'not live identity for pinned base')
    require(evidence['profile'] == approved['profile'], 'identity evidence/profile mismatch')
    require(digest(evidence['tool_checks']) == digest({'system_tools_available': True}), 'guest tools unverified')
    require(digest(evidence) == approved['identity_evidence_sha256'], 'identity evidence digest mismatch')


def cleanup_plan():
    return {'execute_supported': False, 'stage': 'end-of-experiment-only',
            'requires': ['fresh explicit completion checkpoint', 'zero owned running VMs',
                         'no retained dependent clones', 'exact paths and no symlinks',
                         'administrator authority for DHCP restoration'],
            'vm_names': [VM, 'taskflow-e06-vm-a-preflight'], 'base_directory': BASE,
            'helper_files': [SOFTNET, str(Path(SOFTNET).parent / 'LICENSE'),
                             str(Path(SOFTNET).parent / 'README.md'), ROOT + '/downloads/softnet-0.23.0.tar.gz'],
            'preserve': [ROOT + '/receipts', RUN],
            'dhcp': {'preferences_id': 'com.apple.InternetSharing.default.plist', 'key': 'bootpd',
                     'original': None, 'expected': {'DHCPLeaseTimeSecs': 600, 'dhcp_ignore_client_identifier': True},
                     'action': 'lock; compare exact key; remove only key; commit/apply; unlock; read back',
                     'on_concurrent_change': 'stop; never overwrite'},
            'space': 'record host free bytes before/after; du may double-count shared APFS extents',
            'note': 'Data only; smoke runner never removes base/helper or edits DHCP.'}


def dhcp_restore_allowed(current, admin, stopped):
    require(admin and stopped, 'DHCP restoration lacks authority/quiescence')
    require(digest(current) == digest(cleanup_plan()['dhcp']['expected']), 'concurrent DHCP change')
    return {'remove_key': 'bootpd', 'preserve_other_keys': True}
