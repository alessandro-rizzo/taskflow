import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model as m
import guest
import runner
import backend
import watchdog

DEVICE = '11111111-2222-4333-8444-555555555555'


def complete_profile():
    # Deliberately synthetic; never emitted as live identity or a usable approval file.
    p = {k: v for k, v in m.observation().items() if k in m.profile_fields()}
    p.update(iphoneos_build='TESTONLY1', iphonesimulator_build='TESTONLY2')
    return p


def devices(state='Booted', handle=DEVICE):
    return {'devices': {m.observation()['runtime_identifier']: [
        {'name': m.VM, 'udid': handle, 'state': state, 'isAvailable': True,
         'deviceTypeIdentifier': m.observation()['device_type']} ]}}


def report(previous=''):
    return 'TASKFLOW_E06_RESULT:' + json.dumps({'status': 'ok', 'namespace': m.NS,
          'previous_default': previous, 'previous_file': previous, 'previous_keychain_name': previous})


class FakeBackend:
    def __init__(self, fail=None):
        self.ops = guest.ledger()['operations']
        self.command_ops = [o for o in self.ops if o['action'] in ('host-command', 'guest-command')]
        self.index = 0
        self.cleaned = 0
        self.finished = 0
        self.fail = fail

    def host_checks(self): return {'synthetic': True}
    def start_watchdog(self): pass
    def start_vm(self, argv): return {'synthetic': True}
    def wait_guest(self, argv): return {'stdout': '', 'exit_code': 0}
    def base_checks(self): return dict(m.BASE_HASHES)
    def cleanup(self):
        self.cleaned += 1
        return {'status': 'absent', 'synthetic': True}
    def finish_watchdog(self): self.finished += 1

    def command(self, argv, timeout, stdin):
        op = self.command_ops[self.index]
        self.index += 1
        expected = [DEVICE if x == '{device}' else x for x in op['argv']]
        assert argv == expected
        if op['id'] == self.fail:
            raise m.Rejected('injected guest timeout')
        identifier = op['id']
        p = complete_profile()
        raw = ''
        if identifier.startswith('identity-'):
            key = identifier[len('identity-'):]
            if key == 'xcode': raw = 'Xcode 26.5\nBuild version 17F42\n'
            elif key == 'sip': raw = 'System Integrity Protection status: disabled.\n'
            elif key == 'runtimes':
                raw = json.dumps({'runtimes': [{'identifier': p['runtime_identifier'], 'isAvailable': True,
                       'buildversion': p['runtime_build'], 'supportedArchitectures': ['arm64']}]})
            elif key == 'devicetypes':
                raw = json.dumps({'devicetypes': [{'identifier': p['device_type']}]})
            elif key == 'guest_disk': raw = 'Filesystem 1024-blocks Used Available Capacity Mounted\ndisk 100000000 1 50000000 1% /\n'
            elif key != 'tools': raw = str(p[key]) + '\n'
        elif identifier == 'artifact' or identifier.endswith('-artifact'):
            raw = '\n'.join('a'*64 + '  ' + guest.APP + '/' + x for x in ('Info.plist', 'E06SmokeApp'))
        elif identifier == 'create': raw = DEVICE + '\n'
        elif identifier.endswith('-identity'): raw = json.dumps(devices())
        elif identifier.endswith('-container'): raw = m.SET + '/' + DEVICE + '/data/Containers/Bundle/a/E06SmokeApp.app\n'
        elif identifier.endswith('-launch'): raw = report(m.NS if identifier.startswith('persisted') else '')
        elif identifier == 'sim-residue': raw = '{"devices":{}}'
        return {'stdout': raw, 'stderr': '', 'exit_code': 0, 'duration_ns': 1000, 'synthetic': True}


class SmokeTests(unittest.TestCase):
    def test_recording_has_no_execution_or_network_or_writes(self):
        def forbidden(*a, **k): raise AssertionError('live primitive reached')
        with patch.object(subprocess, 'run', forbidden), patch.object(subprocess, 'Popen', forbidden), \
             patch.object(socket, 'socket', forbidden), patch.object(os, 'kill', forbidden), \
             patch.object(os, 'killpg', forbidden), patch.object(Path, 'write_text', forbidden), \
             patch.object(Path, 'write_bytes', forbidden), patch.object(os, 'mkdir', forbidden), \
             patch.object(os, 'unlink', forbidden):
            a = runner.record_plan()
            self.assertEqual(a, runner.record_plan())
            self.assertEqual(a['execution_count'], 0)
            self.assertEqual(a['benchmark_samples'], 0)
            self.assertFalse(a['full_matrix_supported'])

    def test_complete_smoke_fake_backend(self):
        fake = FakeBackend()
        result = runner.run_smoke(fake, complete_profile(), guest.ledger())
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['results']['persisted-report']['previous_file'], m.NS)
        self.assertEqual(result['results']['reset-report']['previous_file'], '')
        self.assertGreaterEqual(fake.cleaned, 1)
        self.assertGreaterEqual(fake.finished, 1)

    def test_guest_failure_still_cleans_and_disarms(self):
        for phase in ('clone', 'build', 'initial-install', 'persisted-launch', 'reset-erase', 'guest-cleanup'):
            with self.subTest(phase=phase):
                fake = FakeBackend(fail=phase)
                with self.assertRaises(m.Rejected): runner.run_smoke(fake, complete_profile(), guest.ledger())
                self.assertEqual(fake.cleaned, 1)
                self.assertEqual(fake.finished, 1)

    def test_cancellation_still_finalizes(self):
        fake = FakeBackend()
        fake.command = lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt): runner.run_smoke(fake, complete_profile(), guest.ledger())
        self.assertEqual(fake.cleaned, 1)

    def test_changed_ledger_rejected_before_backend(self):
        fake = FakeBackend()
        for mutation in ('command', 'timeout', 'stdin', 'omit'):
            spec = guest.ledger()
            if mutation == 'command': spec['operations'][2]['argv'] = ['/usr/bin/xcodebuild']
            elif mutation == 'timeout': spec['operations'][2]['timeout_seconds'] = 99999
            elif mutation == 'stdin': spec['operations'][20]['stdin'] = 'curl evil'
            else: spec['operations'].pop()
            with self.assertRaises(m.Rejected): runner.run_smoke(fake, complete_profile(), spec)
            self.assertEqual(fake.index, 0)

    def test_missing_sdk_identity_blocks_execution(self):
        for key in ('iphoneos_build', 'iphonesimulator_build'):
            p = complete_profile(); p[key] = None
            with self.assertRaises(m.Rejected): m.profile(p)

    def test_profile_drift_and_type_confusion(self):
        for key, value in [('memory_bytes', True), ('xcode_build', 'other'), ('sip', 'enabled'), ('architecture', 'x86_64')]:
            p = complete_profile(); p[key] = value
            with self.assertRaises(m.Rejected): m.profile(p)

    def test_wrong_duplicate_unavailable_device(self):
        for variant in ('duplicate', 'wrong-name', 'wrong-type', 'unavailable', 'wrong-state'):
            doc = devices(); row = next(iter(doc['devices'].values()))[0]
            if variant == 'duplicate': next(iter(doc['devices'].values())).append(dict(row))
            elif variant == 'wrong-name': row['name'] = 'someone-else'
            elif variant == 'wrong-type': row['deviceTypeIdentifier'] = 'other'
            elif variant == 'unavailable': row['isAvailable'] = False
            else: row['state'] = 'Shutdown'
            with self.assertRaises(m.Rejected): m.device(json.dumps(doc), DEVICE, 'Booted')

    def test_uuid_rejects_executable_or_ambiguous_text(self):
        for text in ('', DEVICE + '\nother', 'booted', '$(id)', '../x'):
            with self.assertRaises(m.Rejected): m.uuid(text)

    def test_reports_require_all_canaries_and_one_exact_result(self):
        for raw in ('', report() + '\n' + report(), report(m.NS), 'TASKFLOW_E06_RESULT:{',
                    report().replace('"ok"', '"invalid"')):
            with self.assertRaises((m.Rejected, ValueError)): m.app_report(raw, '')
        with self.assertRaises(m.Rejected): m.app_report(report(), m.NS)

    def test_artifact_manifest_bounds_and_completeness(self):
        for raw in ('', 'a'*64 + '  /Users/admin/app', 'truncated',
                    'a'*64 + '  ' + guest.APP + '/Info.plist'):
            with self.assertRaises(m.Rejected): runner.artifact(raw)

    def test_transport_only_contains_expected_hashed_files(self):
        script = guest.transport()
        for f in m.payload_files(): self.assertIn(f['sha256'], script)
        self.assertIn(m.sha(guest.driver().encode()), script)
        self.assertIn('test ! -e ' + m.GUEST, script)
        self.assertNotIn('ssh', script)
        self.assertNotIn('/Users/', script)
        self.assertIn('test ! -L ' + guest.APP, guest.driver())

    def test_host_commands_never_target_xcode_or_default_set(self):
        for op in guest.ledger()['operations']:
            argv = op['argv']
            if not argv: continue
            self.assertEqual(argv[0], m.TART)
            if 'simctl' in argv and 'devices' in argv:
                self.assertIn(m.SET, argv)
            self.assertNotIn('--dir', argv)
            self.assertNotIn('--net-bridged', argv)

    def test_second_attempt_uses_pty_launch_and_preserves_first_evidence(self):
        self.assertEqual(m.RUN, m.ROOT + '/smoke-run-002')
        self.assertEqual(m.VM, 'taskflow-e06-vm-a-smoke-002')
        self.assertIn(m.ROOT + '/smoke-run', m.cleanup_plan()['preserve'])
        launches = [op for op in guest.ledger()['operations'] if op['id'].endswith('-launch')]
        self.assertEqual(len(launches), 3)
        for operation in launches:
            self.assertIn('--console-pty', operation['argv'])
            self.assertNotIn('--console', operation['argv'])

    def test_path_prefix_traversal_and_symlink(self):
        for value in (m.GUEST+'-evil/x', m.GUEST+'/../x', m.GUEST+'/a//x', m.GUEST+'/*', '/Users/a'):
            with self.assertRaises(m.Rejected): m.canonical_path(value, m.GUEST)
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / 'link'; link.symlink_to(Path(d) / 'missing')
            with self.assertRaises(m.Rejected): backend.no_links(link)

    def test_helper_permissions_and_digest(self):
        good = SimpleNamespace(st_mode=stat.S_IFREG | 0o4755, st_uid=0)
        backend.validate_helper(good, m.SOFTNET_SHA)
        for mode, owner, checksum in [(0o755, 0, m.SOFTNET_SHA), (0o4777, 0, m.SOFTNET_SHA),
                                      (0o4755, 502, m.SOFTNET_SHA), (0o4755, 0, '0'*64)]:
            with self.assertRaises(m.Rejected):
                backend.validate_helper(SimpleNamespace(st_mode=stat.S_IFREG|mode, st_uid=owner), checksum)

    def test_task_root_must_be_private_and_owned(self):
        backend.validate_root(SimpleNamespace(st_mode=stat.S_IFDIR|0o700, st_uid=502), 502)
        for mode, owner in [(stat.S_IFDIR|0o755,502), (stat.S_IFREG|0o700,502),
                            (stat.S_IFDIR|0o700,0)]:
            with self.assertRaises(m.Rejected):
                backend.validate_root(SimpleNamespace(st_mode=mode,st_uid=owner),502)

    def test_dhcp_cleanup_requires_exact_state_and_admin(self):
        current = m.cleanup_plan()['dhcp']['expected']
        self.assertEqual(m.dhcp_restore_allowed(current, True, True)['remove_key'], 'bootpd')
        for value, admin, stopped in [(dict(current, other=1), True, True), (current, False, True),
                                      (current, True, False), (dict(current, dhcp_ignore_client_identifier=1), True, True)]:
            with self.assertRaises(m.Rejected): m.dhcp_restore_allowed(value, admin, stopped)
        self.assertFalse(m.cleanup_plan()['execute_supported'])

    def test_vm_admission_rejects_existing_or_active(self):
        base = {'Name':m.IMAGE, 'Source':'OCI', 'State':'stopped', 'Running':False}
        backend.validate_vm_list(json.dumps([base]), clone_allowed=False)
        for rows in ([base, {'Name':m.VM}], [dict(base, Running=True)], [base, base], []):
            with self.assertRaises(m.Rejected): backend.validate_vm_list(json.dumps(rows), clone_allowed=False)

    def test_capacity_fail_closed(self):
        mem = 'page size of 16384 bytes\nPages free: 2000000.\nPages inactive: 0.\nPages speculative: 0.'
        disk = 'header\ndisk 2000000000 1 1000000000 1% /'
        backend.capacity(mem, disk, '0')
        for a,b,c in [('bad',disk,'0'),(mem,'bad','0'),(mem,disk,'2'),
                      (mem.replace('2000000','1'),disk,'0')]:
            with self.assertRaises(m.Rejected): backend.capacity(a,b,c)

    def test_watchdog_stops_only_owned_clone_and_retains_orphan(self):
        calls = []
        def command(argv, timeout):
            calls.append(argv)
            if len(calls) == 1:
                return json.dumps([{'Name':m.VM, 'State':'running', 'Running':True}])
            return json.dumps([{'Name':m.VM, 'State':'stopped', 'Running':False}])
        result = watchdog.reap(command)
        self.assertEqual(result['status'], 'stopped-orphan')
        self.assertEqual(calls[1], [m.TART,'stop',m.VM,'--timeout','20'])
        self.assertFalse(any('delete' in x for x in calls))
        self.assertEqual(watchdog.reap(lambda *a: '[]')['status'], 'orphan-review')

    def test_live_command_timeout_terminates_only_owned_group(self):
        class Process:
            pid=12345
            returncode=None
            def poll(self): return self.returncode
            def wait(self,timeout): self.returncode=-15; return self.returncode
        p = Process()
        with tempfile.TemporaryDirectory() as d, patch.object(m,'RUN',d), \
             patch.object(subprocess,'Popen',return_value=p), patch.object(os,'killpg') as kill, \
             patch.object(backend.time,'monotonic_ns',side_effect=[0,2000000000,3000000000]):
            with self.assertRaises(m.Rejected): backend.LiveBackend().command(['/fake'],timeout=1)
            kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_approval_strict_schema_scope_revision_and_expiry(self):
        now = datetime.now(timezone.utc)
        spec = guest.ledger(); bindings={'synthetic':'a'*64}; revision=('a'*40,'b'*40)
        a={'schema':'taskflow-e06-vm-smoke-approval/v1','operator':'unit-test-only',
           'approved_at':(now-timedelta(seconds=5)).isoformat(), 'not_before':(now-timedelta(seconds=2)).isoformat(),
           'expires_at':(now+timedelta(hours=1)).isoformat(), 'commit':revision[0],'tree':revision[1],
           'bindings':bindings,'ledger_sha256':m.digest(spec),'profile':complete_profile(),
           'identity_evidence_sha256':'c'*64,'scopes':m.SCOPES}
        m.validate_approval(a,spec,bindings,revision,now)
        for key,value in [('scopes',[]),('commit','0'*40),('bindings',{}),('ledger_sha256','0'*64),
                          ('expires_at',(now-timedelta(seconds=1)).isoformat()),('operator','')]:
            bad=copy.deepcopy(a); bad[key]=value
            with self.assertRaises(m.Rejected): m.validate_approval(bad,spec,bindings,revision,now)
        bad=dict(a, unknown=True)
        with self.assertRaises(m.Rejected): m.validate_approval(bad,spec,bindings,revision,now)

    def test_invalid_approval_cli_never_constructs_backend(self):
        with patch.object(sys,'argv',['runner.py','execute-smoke']), \
             patch.object(backend,'LiveBackend',side_effect=AssertionError('constructed')):
            with self.assertRaises(m.Rejected): runner.main()

    def test_dhcp_admission_preserves_unknown_settings(self):
        self.assertIsNone(backend.dhcp_baseline('  no paths.\n  No such key\n<dictionary> {\n}\n'))
        good = '  path [0] = /bootpd\n<dictionary> {\n  DHCPLeaseTimeSecs : 600\n  dhcp_ignore_client_identifier : TRUE\n}\n'
        self.assertEqual(backend.dhcp_baseline(good), m.cleanup_plan()['dhcp']['expected'])
        for bad in (good.replace('600','500'), good+'  path [1] = /other', 'AuthorizationCreate() failed'):
            with self.assertRaises(m.Rejected): backend.dhcp_baseline(bad)

    def test_identity_evidence_bound_and_strictly_typed(self):
        e = {'kind':'live-guest-identity','profile':complete_profile(),
             'tool_checks':{'system_tools_available':True},'base_sha256':m.IMAGE_SHA}
        a = {'profile':complete_profile(),'identity_evidence_sha256':m.digest(e)}
        m.validate_identity_evidence(e,a)
        for key,value in [('kind','synthetic'),('base_sha256','0'*64),
                          ('tool_checks',{'system_tools_available':1})]:
            bad=copy.deepcopy(e); bad[key]=value
            with self.assertRaises(m.Rejected): m.validate_identity_evidence(bad,a)

    def test_sdk_drift_detected_before_fixture_transfer(self):
        fake=FakeBackend(); command=fake.command
        def wrong(argv, timeout, stdin):
            value=command(argv,timeout,stdin)
            if '--show-sdk-build-version' in argv: value['stdout']='DIFFERENT'
            return value
        fake.command=wrong
        with self.assertRaises(m.Rejected): runner.run_smoke(fake,complete_profile(),guest.ledger())
        self.assertNotIn('transfer', [x['id'] for x in fake.command_ops[:fake.index]])

    def test_missing_device_type_detected_before_fixture_transfer(self):
        fake=FakeBackend(); command=fake.command
        def wrong(argv, timeout, stdin):
            value=command(argv,timeout,stdin)
            if fake.command_ops[fake.index-1]['id']=='identity-devicetypes':
                value['stdout']='{"devicetypes":[]}'
            return value
        fake.command=wrong
        with self.assertRaises(m.Rejected): runner.run_smoke(fake,complete_profile(),guest.ledger())
        self.assertNotIn('transfer', [x['id'] for x in fake.command_ops[:fake.index]])

    def test_artifact_change_detected_before_install(self):
        fake=FakeBackend(); command=fake.command
        def wrong(argv, timeout, stdin):
            value=command(argv,timeout,stdin)
            if fake.command_ops[fake.index-1]['id']=='initial-artifact':
                value['stdout']=value['stdout'].replace('a'*64,'b'*64)
            return value
        fake.command=wrong
        with self.assertRaises(m.Rejected): runner.run_smoke(fake,complete_profile(),guest.ledger())
        self.assertNotIn('initial-install', [x['id'] for x in fake.command_ops[:fake.index]])

    def test_orphan_not_deleted_when_stop_unconfirmed(self):
        calls=[]
        def command(argv,timeout):
            calls.append(argv)
            return json.dumps([{'Name':m.VM,'Running':True,'State':'running'}])
        with self.assertRaises(m.Rejected): watchdog.reap(command)
        self.assertFalse(any('delete' in x for x in calls))

    def test_duplicate_and_truncated_artifact_rejected(self):
        lines=['a'*64+'  '+guest.APP+'/'+p for p in ('Info.plist','E06SmokeApp')]
        self.assertEqual(len(runner.artifact('\n'.join(lines))),2)
        for raw in ('\n'.join(lines+lines), '\n'.join(lines)+'\npartial'):
            with self.assertRaises(m.Rejected): runner.artifact(raw)

    def test_normal_logs_redact_user_directory_names(self):
        self.assertEqual(backend.sanitize({'stdout':'/Users/admin/log.txt'}),
                         {'stdout':'/Users/<redacted>/log.txt'})

    def test_existing_run_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d, patch.object(m,'RUN',d):
            with self.assertRaises(m.Rejected): backend.LiveBackend().create_run()

    def test_watchdog_requires_time_for_entire_bounded_run(self):
        b=backend.LiveBackend(expires_at=0)
        with patch.object(subprocess,'Popen',side_effect=AssertionError('spawned')):
            with self.assertRaises(m.Rejected): b.start_watchdog()

    def test_watchdog_does_not_stop_an_already_stopped_clone(self):
        calls=[]
        def command(argv,timeout):
            calls.append(argv)
            return json.dumps([{'Name':m.VM,'Running':False,'State':'stopped'}])
        self.assertEqual(watchdog.reap(command)['status'],'stopped-orphan')
        self.assertEqual(calls, [[m.TART,'list','--format','json'],
                                 [m.TART,'list','--format','json']])

    def test_cleanup_retains_clone_until_owned_run_process_exits(self):
        class Process:
            def wait(self,timeout): raise subprocess.TimeoutExpired('tart-run',timeout)
        calls=[]
        with tempfile.TemporaryDirectory(dir='/private/tmp') as d, patch.object(m,'RUN',d+'/run'), \
             patch.object(m,'VM_DIR',d+'/vm'):
            Path(m.RUN).mkdir(); Path(m.VM_DIR).mkdir()
            live=backend.LiveBackend(); live.claimed=True; live.vm=Process()
            def command(argv, *args, **kwargs):
                calls.append(argv)
                return {'stdout':json.dumps([{'Name':m.VM,'Running':False,'State':'stopped'}])}
            live.command=command
            with self.assertRaises(subprocess.TimeoutExpired): live.cleanup()
            self.assertTrue(Path(m.VM_DIR).is_dir())
            self.assertFalse(any('delete' in argv for argv in calls))

    def test_ledger_declares_all_evidence_write_classes(self):
        writes=guest.ledger()['evidence_writes']
        self.assertEqual(writes['root'],m.RUN)
        self.assertTrue(writes['exclusive'])
        self.assertFalse(writes['overwrite'])
        self.assertIn('NNNN.json',writes['per_command'])
        self.assertEqual(writes['terminal_one_of'],['result.json','failure.json'])


if __name__ == '__main__':
    unittest.main()
