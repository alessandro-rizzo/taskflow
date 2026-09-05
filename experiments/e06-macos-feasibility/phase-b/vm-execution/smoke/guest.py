"""Fixed guest scripts and a deterministic typed ledger, never executed here."""
import json
import shlex
from pathlib import PurePosixPath

import model as m

APP = m.GUEST + '/DerivedData/Build/Products/Debug-iphonesimulator/E06SmokeApp.app'
PROJECT = m.GUEST + '/workspace/E06SmokeApp/E06SmokeApp.xcodeproj'
DRIVER = m.GUEST + '/driver.sh'
TOOLS = ['/bin/sh', '/bin/mkdir', '/bin/rm', '/bin/test', '/bin/date',
         '/usr/bin/base64', '/usr/bin/shasum', '/usr/bin/find', '/usr/bin/sort', '/usr/bin/xargs',
         '/usr/bin/xcrun', '/usr/bin/xcodebuild', '/usr/bin/env', '/usr/libexec/PlistBuddy']
IDENTITY = [
    ('macos_version', ['/usr/bin/sw_vers', '-productVersion']),
    ('macos_build', ['/usr/bin/sw_vers', '-buildVersion']),
    ('architecture', ['/usr/bin/uname', '-m']),
    ('xcode', ['/usr/bin/xcodebuild', '-version']),
    ('developer_directory', ['/usr/bin/xcode-select', '-p']),
    ('iphoneos_version', ['/usr/bin/xcrun', '--sdk', 'iphoneos', '--show-sdk-version']),
    ('iphoneos_build', ['/usr/bin/xcrun', '--sdk', 'iphoneos', '--show-sdk-build-version']),
    ('iphonesimulator_version', ['/usr/bin/xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']),
    ('iphonesimulator_build', ['/usr/bin/xcrun', '--sdk', 'iphonesimulator', '--show-sdk-build-version']),
    ('cpu_count', ['/usr/sbin/sysctl', '-n', 'hw.ncpu']),
    ('memory_bytes', ['/usr/sbin/sysctl', '-n', 'hw.memsize']),
    ('sip', ['/usr/bin/csrutil', 'status']),
    ('console_user', ['/usr/bin/stat', '-f', '%Su', '/dev/console']),
    ('runtimes', ['/usr/bin/xcrun', 'simctl', 'list', 'runtimes', '--json']),
    ('devicetypes', ['/usr/bin/xcrun', 'simctl', 'list', 'devicetypes', '--json']),
    ('guest_disk', ['/bin/df', '-Pk', '/']),
]


def quote(argv):
    return ' '.join(shlex.quote(x) for x in argv)


def sim(*args):
    return ['/usr/bin/xcrun', 'simctl', '--set', m.SET, *args]


def safe_parents(paths):
    parents = set()
    for path in paths:
        m.canonical_path(path, m.GUEST)
        parents.update(str(x) for x in PurePosixPath(path).parents if str(x) != '/')
    return '\n'.join('test ! -L ' + shlex.quote(x) for x in sorted(parents)) + '\n'


def driver():
    """A closed operation dispatcher; arbitrary command strings are not admitted."""
    q = shlex.quote
    script = 'set -eu\numask 077\n'
    script += safe_parents([APP, PROJECT, DRIVER, m.SET + '/device'])
    script += 'test "$#" -eq 1\ncase "$1" in\n'
    script += 'build)\n' + quote([
        '/usr/bin/xcodebuild', '-project', PROJECT, '-scheme', 'E06SmokeApp',
        '-configuration', 'Debug', '-sdk', 'iphonesimulator26.5',
        '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', m.GUEST + '/DerivedData',
        '-resultBundlePath', m.GUEST + '/results/build.xcresult',
        'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO',
        '-disableAutomaticPackageResolution', 'build']) + '\n;;\n'
    script += 'artifact)\n'
    script += 'test -d ' + q(APP) + '\n'
    script += 'test ! -L ' + q(APP) + '\n'
    script += 'test -z "$(/usr/bin/find ' + q(APP) + ' -type l -print)"\n'
    script += 'test "$(/usr/libexec/PlistBuddy -c Print:CFBundleIdentifier ' + q(APP + '/Info.plist') + ')" = ' + q(m.BUNDLE) + '\n'
    script += 'test -s ' + q(APP + '/E06SmokeApp') + '\n'
    script += '/usr/bin/find ' + q(APP) + ' -type f -print0 > ' + q(m.GUEST + '/results/artifact.files0') + '\n'
    script += '/usr/bin/xargs -0 /usr/bin/shasum -a 256 < ' + q(m.GUEST + '/results/artifact.files0') + ' > ' + q(m.GUEST + '/results/artifact.sha256') + '\n'
    script += '/usr/bin/sort ' + q(m.GUEST + '/results/artifact.sha256') + '\n;;\n'
    script += 'cleanup)\n' + quote(['/bin/rm', '-rf', m.GUEST]) + '\n'
    script += 'test ! -e ' + q(m.GUEST) + '\n;;\n*) exit 64;;\nesac\n'
    return script


def transport():
    files = m.payload_files()
    data = driver().encode()
    import base64
    files = [dict(f, path='workspace/E06SmokeApp/' + f['path']) for f in files]
    files.append({'path': 'driver.sh', 'size': len(data), 'sha256': m.sha(data),
                  'base64': base64.b64encode(data).decode()})
    script = 'set -eu\numask 077\n'
    script += safe_parents([m.GUEST + '/' + f['path'] for f in files])
    script += 'test ! -e ' + shlex.quote(m.GUEST) + '\n'
    dirs = {m.GUEST + '/' + x for x in ('home', 'tmp', 'cache', 'DerivedData', 'results', 'CoreSimulator')}
    dirs.update(str(PurePosixPath(m.GUEST + '/' + f['path']).parent) for f in files)
    script += quote(['/bin/mkdir', '-p', *sorted(dirs)]) + '\n'
    for f in files:
        target = m.canonical_path(m.GUEST + '/' + f['path'], m.GUEST)
        script += 'printf %s ' + shlex.quote(f['base64']) + ' | /usr/bin/base64 -D > ' + shlex.quote(target) + '\n'
        script += 'test "$(/usr/bin/stat -f %z ' + shlex.quote(target) + ')" = ' + str(f['size']) + '\n'
        script += 'test "$(/usr/bin/shasum -a 256 ' + shlex.quote(target) + ' | /usr/bin/cut -d " " -f 1)" = ' + shlex.quote(f['sha256']) + '\n'
    return script


def guest_argv(argv, *, prepared=False, stdin=False):
    env = ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin:/usr/sbin:/sbin', 'LANG=C', 'LC_ALL=C',
           'DEVELOPER_DIR=' + m.observation()['developer_directory']]
    if prepared:
        env += ['CFFIXED_USER_HOME=' + m.GUEST + '/home', 'TMPDIR=' + m.GUEST + '/tmp',
                'CLANG_MODULE_CACHE_PATH=' + m.GUEST + '/cache/clang',
                'SWIFT_MODULE_CACHE_PATH=' + m.GUEST + '/cache/swift']
    return [m.TART, 'exec', *(['-i'] if stdin else []), m.VM, *env, *argv]


def ledger():
    rows = []

    def add(identifier, action, argv=None, timeout=60, **extra):
        rows.append({'id': identifier, 'action': action, 'argv': argv or [],
                     'timeout_seconds': timeout, 'requires': rows[-1]['id'] if rows else None, **extra})

    add('host-admit', 'host-checks')
    add('watchdog', 'start-watchdog', timeout=30)
    add('clone', 'host-command', [m.TART, 'clone', m.IMAGE, m.VM, '--prune-limit', '0'], 900)
    add('configure', 'host-command', [m.TART, 'set', m.VM, '--cpu', '6', '--memory', '16384'])
    add('boot', 'start-vm', [m.TART, 'run', '--no-graphics', '--net-host', '--no-clipboard', '--no-audio', m.VM])
    add('ready', 'wait-guest', guest_argv(['/usr/bin/true']), 300)
    for key, argv in IDENTITY:
        add('identity-' + key, 'guest-command', guest_argv(argv))
    add('identity-tools', 'guest-command', guest_argv(['/bin/sh', '-s'], stdin=True),
        stdin='set -eu\n' + '\n'.join('test -x ' + shlex.quote(x) for x in TOOLS + ['/usr/bin/stat', '/usr/bin/cut']) + '\n')
    add('attest', 'compare-profile')
    add('transfer', 'guest-command', guest_argv(['/bin/sh', '-s'], stdin=True),
        stdin=transport())
    add('build', 'guest-command', guest_argv(['/bin/sh', DRIVER, 'build'], prepared=True), 900)
    add('artifact', 'guest-command', guest_argv(['/bin/sh', DRIVER, 'artifact'], prepared=True))
    add('artifact-verify', 'verify-artifact')
    add('create', 'guest-command', guest_argv(sim('create', m.VM, m.observation()['device_type'],
                                               m.observation()['runtime_identifier']), prepared=True))
    add('capture-device', 'capture-device')
    for label, previous in [('initial', ''), ('persisted', m.NS), ('reset', '')]:
        if label == 'reset':
            add('reset-shutdown', 'guest-command', guest_argv(sim('shutdown', '{device}'), prepared=True))
            add('reset-erase', 'guest-command', guest_argv(sim('erase', '{device}'), prepared=True), 900)
        if label != 'persisted':
            add(label + '-boot', 'guest-command', guest_argv(sim('boot', '{device}'), prepared=True), 900)
            add(label + '-bootstatus', 'guest-command', guest_argv(sim('bootstatus', '{device}', '-b'), prepared=True), 900)
        add(label + '-identity', 'guest-command', guest_argv(sim('list', 'devices', '--json'), prepared=True))
        add(label + '-identity-verify', 'verify-device', state='Booted')
        if label != 'persisted':
            add(label + '-artifact', 'guest-command', guest_argv(['/bin/sh', DRIVER, 'artifact'], prepared=True))
            add(label + '-artifact-verify', 'verify-artifact-again')
            add(label + '-install', 'guest-command', guest_argv(sim('install', '{device}', APP), prepared=True), 900)
            add(label + '-container', 'guest-command', guest_argv(sim('get_app_container', '{device}', m.BUNDLE, 'app'), prepared=True))
            add(label + '-container-verify', 'verify-container')
        add(label + '-launch', 'guest-command', guest_argv(sim('launch', '--console-pty', '--terminate-running-process',
                                                        '{device}', m.BUNDLE, '--taskflow-namespace', m.NS), prepared=True), 900)
        add(label + '-report', 'verify-report', previous=previous)
    add('sim-shutdown', 'guest-command', guest_argv(sim('shutdown', '{device}'), prepared=True))
    add('sim-delete', 'guest-command', guest_argv(sim('delete', '{device}'), prepared=True))
    add('sim-residue', 'guest-command', guest_argv(sim('list', 'devices', '--json'), prepared=True))
    add('sim-residue-verify', 'verify-no-devices')
    add('guest-cleanup', 'guest-command', guest_argv(['/bin/sh', DRIVER, 'cleanup'], prepared=True))
    add('guest-residue', 'guest-command', guest_argv(['/bin/test', '!', '-e', m.GUEST]))
    add('host-cleanup', 'owned-vm-cleanup', timeout=30)
    add('base-integrity', 'base-checks', timeout=900)
    return {'schema': 'taskflow-e06-vm-smoke-ledger/v1', 'stage': 'smoke-only',
            'benchmark_samples': 0, 'live_seconds': m.LIVE_SECONDS,
            'cleanup_seconds': m.CLEANUP_SECONDS, 'host_environment': m.ENV,
            'output_bytes_per_stream': m.MAX_OUTPUT, 'operations': rows,
            'host_health_commands': [['/usr/bin/vm_stat'], ['/bin/df', '-Pk', m.ROOT],
                                    ['/usr/bin/du', '-sk', m.ROOT],
                                    ['/usr/bin/osascript', '-l', 'JavaScript', '-e',
                                     'ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState']],
            'host_admission': {'tart': [m.TART, 'list', '--format', 'json'],
                               'dhcp_argv': ['/usr/sbin/scutil', '--prefs', 'com.apple.InternetSharing.default.plist'],
                               'dhcp_stdin': 'list\nget /bootpd\nd.show\nquit\n',
                               'base_hashes': m.BASE_HASHES, 'helper_sha256': m.SOFTNET_SHA,
                               'controller_sha256': m.TART_SHA, 'du_ceiling_gib': 400},
            'host_cleanup_commands': [[m.TART, 'list', '--format', 'json'],
                                      [m.TART, 'stop', m.VM, '--timeout', '20'],
                                      [m.TART, 'list', '--format', 'json'],
                                      [m.TART, 'delete', m.VM]],
            'watchdog': {'argv': ['/usr/bin/python3', str(m.HERE / 'watchdog.py'), '{owned-pipe-fd}'],
                         'caller_loss': 'stop exact clone; retain precise orphan; never delete base',
                         'deadline_seconds': m.LIVE_SECONDS},
            'evidence_writes': {
                'fixed': ['approval.json', 'ownership.json', 'vm.stdout', 'vm.stderr'],
                'terminal_one_of': ['result.json', 'failure.json'],
                'per_command': ['NNNN.stdout', 'NNNN.stderr', 'NNNN.json'],
                'periodic': ['health-MONOTONIC_NS.json'],
                'cleanup': ['cleanup-MONOTONIC_NS.json', 'base-hashes-MONOTONIC_NS.json'],
                'caller_loss_optional': ['watchdog-result.json'],
                'root': m.RUN, 'exclusive': True, 'overwrite': False,
            },
            'finalizer': {'always': True, 'scope': m.VM, 'keep_base': True,
                          'orphan_on_unconfirmed_stop': True},
            'transport_sha256': m.sha(transport().encode()), 'driver_sha256': m.sha(driver().encode())}


def identity_completion_plan():
    return {'stage': 'identity-completion-only', 'execute_supported': False,
            'requires': 'separate bounded clone/boot/query/shutdown approval; no workload',
            'commands': [argv for _, argv in IDENTITY], 'tools': TOOLS + ['/usr/bin/stat', '/usr/bin/cut'],
            'promote_to_profile': False, 'unresolved': ['iphoneos_build', 'iphonesimulator_build']}
