"""Live primitives. Construct only after validating the immutable approval."""
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import model as m


def sanitize(value):
    if isinstance(value, str):
        return re.sub(r'/Users/[^/\s]+', '/Users/<redacted>', value)
    if isinstance(value, list):
        return [sanitize(x) for x in value]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    return value


def dhcp_baseline(raw):
    m.require('failed' not in raw.lower() and 'error' not in raw.lower(), 'DHCP preference read failed')
    if 'no paths.' in raw and 'No such key' in raw:
        return None
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    expected = ['path [0] = /bootpd', '<dictionary> {', 'DHCPLeaseTimeSecs : 600',
                'dhcp_ignore_client_identifier : TRUE', '}']
    m.require(lines == expected, 'DHCP settings changed; do not overwrite')
    return m.cleanup_plan()['dhcp']['expected']


def no_links(path):
    p = Path(path)
    for part in [p, *p.parents]:
        m.require(not part.is_symlink(), 'symlink: ' + str(part))


def hash_file(path):
    import hashlib
    no_links(path)
    h = hashlib.sha256()
    deadline = time.monotonic() + 900
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            m.require(time.monotonic() <= deadline, 'checksum deadline exceeded')
            h.update(chunk)
    return h.hexdigest()


def validate_helper(st, checksum):
    m.require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and
              st.st_mode & stat.S_ISUID and not st.st_mode & 0o022,
              'helper must be root-owned setuid and not group/world writable')
    m.require(checksum == m.SOFTNET_SHA, 'helper digest changed')


def validate_root(st, uid):
    m.require(stat.S_ISDIR(st.st_mode) and st.st_uid == uid and not st.st_mode & 0o077,
              'task root must be an owned private directory')


def capacity(memory, disk, thermal):
    page = re.search(r'page size of (\d+) bytes', memory)
    m.require(page is not None, 'unknown memory page size')
    # A declared estimate of available/reclaimable pages, not all nominal RAM.
    pages = []
    for field in ['free', 'inactive', 'speculative']:
        found = re.search(r'Pages ' + field + r':\s+(\d+)\.', memory)
        m.require(found is not None, 'unknown available memory')
        pages.append(int(found[1]))
    available = sum(pages) * int(page[1])
    m.require(available >= 16 * 1024**3, 'host available-memory estimate below 16 GiB')
    rows = disk.splitlines()
    m.require(len(rows) == 2, 'ambiguous host disk output')
    fields = rows[1].split()
    m.require(len(fields) >= 6 and fields[3].isdigit(), 'unknown disk capacity')
    m.require(int(fields[3]) * 1024 >= 200 * 1024**3, 'host disk below 200 GiB')
    m.require(thermal.strip() in ('0', '1'), 'serious/unknown host thermal state')
    return {'available_memory_estimate_bytes': available, 'free_disk_bytes': int(fields[3]) * 1024,
            'thermal_state': int(thermal.strip())}


def validate_vm_list(raw, *, clone_allowed):
    rows = json.loads(raw)
    m.require(isinstance(rows, list), 'invalid Tart list')
    names = [r.get('Name') for r in rows]
    m.require(len(set(names)) == len(names), 'duplicate VM identities')
    base = [r for r in rows if r.get('Name') == m.IMAGE]
    m.require(len(base) == 1 and base[0].get('Source') == 'OCI' and
              base[0].get('State') == 'stopped' and base[0].get('Running') is False,
              'cached base unavailable or not stopped')
    for row in rows:
        if clone_allowed and row.get('Name') == m.VM:
            continue
        m.require(row.get('Running') is False and row.get('State') == 'stopped',
                  'another owned VM is active or suspended')
    if not clone_allowed:
        m.require(m.VM not in names, 'smoke clone already exists')
    return rows


class LiveBackend:
    def __init__(self, expires_at=None):
        self.deadline = None
        self.vm = None
        self.watchdog = None
        self.watch_write = None
        self.claimed = False
        self.cleaned = False
        self.counter = 0
        self.expires_at = expires_at
        self.last_health = 0

    @staticmethod
    def terminate_child(p):
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=2)

    def health(self):
        def probe(argv):
            r = subprocess.run(argv, env=m.ENV, stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=5)
            m.require(r.returncode == 0 and len(r.stdout) < 65536, 'host health probe failed')
            return r.stdout
        value = capacity(probe(['/usr/bin/vm_stat']), probe(['/bin/df', '-Pk', m.ROOT]),
                         probe(['/usr/bin/osascript', '-l', 'JavaScript', '-e',
                                'ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState']))
        allocated = probe(['/usr/bin/du', '-sk', m.ROOT]).split()[0]
        m.require(allocated.isdigit() and int(allocated) <= 400 * 1024**2,
                  'task allocation/du ceiling exceeded')
        value['task_du_bytes'] = int(allocated) * 1024
        if self.vm:
            m.require(self.vm.poll() is None, 'owned VM exited unexpectedly')
            for name in ('vm.stdout', 'vm.stderr'):
                m.require((Path(m.RUN) / name).stat().st_size <= m.MAX_OUTPUT, 'VM log limit exceeded')
        self.persist('health-%d.json' % time.monotonic_ns(), value)
        return value

    def command(self, argv, timeout=60, stdin=None, *, allow_failure=False, monitor=True):
        if monitor and self.deadline is not None:
            m.require(time.monotonic() < self.deadline, 'live window exceeded')
            timeout = min(timeout, max(0.1, self.deadline - time.monotonic()))
            if self.watchdog:
                m.require(self.watchdog.poll() is None, 'watchdog terminated unexpectedly')
        if monitor and self.vm and time.monotonic() - self.last_health >= 5:
            self.health()
            self.last_health = time.monotonic()
        self.counter += 1
        label = '%04d' % self.counter
        stdout_path = Path(m.RUN) / (label + '.stdout')
        stderr_path = Path(m.RUN) / (label + '.stderr')
        start = time.monotonic_ns()
        with stdout_path.open('xb') as out, stderr_path.open('xb') as err:
            p = subprocess.Popen(argv, env=m.ENV, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
            # Never block the timeout loop while writing to a stalled guest transport.
            writer = None
            if stdin is not None:
                def feed():
                    try:
                        p.stdin.write(stdin.encode())
                    except (BrokenPipeError, OSError):
                        pass
                    finally:
                        try:
                            p.stdin.close()
                        except OSError:
                            pass
                writer = threading.Thread(target=feed, daemon=True)
                writer.start()
            failure = None
            health_at = time.monotonic() + 5
            try:
                while p.poll() is None:
                    elapsed = (time.monotonic_ns() - start) / 1e9
                    if elapsed > timeout:
                        failure = 'command timeout'
                    elif max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size) > m.MAX_OUTPUT:
                        failure = 'output limit exceeded'
                    elif monitor and self.watchdog and self.watchdog.poll() is not None:
                        failure = 'watchdog terminated'
                    if failure:
                        break
                    if monitor and self.vm and time.monotonic() >= health_at:
                        self.health()
                        self.last_health = time.monotonic()
                        health_at = time.monotonic() + 5
                    time.sleep(0.05)
            finally:
                self.terminate_child(p)
                if writer:
                    writer.join(timeout=2)
        result = {'argv': argv, 'exit_code': p.returncode, 'duration_ns': time.monotonic_ns() - start,
                  'stdout_file': stdout_path.name, 'stderr_file': stderr_path.name}
        if failure or max(stdout_path.stat().st_size, stderr_path.stat().st_size) > m.MAX_OUTPUT:
            result['error'] = failure or 'output limit exceeded'
            self.persist(label + '.json', result)
            raise m.Rejected(result['error'])
        result['stdout'] = stdout_path.read_text(errors='replace')
        result['stderr'] = stderr_path.read_text(errors='replace')
        # Keep complete bounded streams, but redact user-directory names in retained text.
        stdout_path.write_text(sanitize(result['stdout']))
        stderr_path.write_text(sanitize(result['stderr']))
        self.persist(label + '.json', result)
        m.require(allow_failure or p.returncode == 0, 'command failed: ' + label)
        return result

    def persist(self, name, value):
        m.require(re.fullmatch(r'[a-zA-Z0-9.-]+\.json', name), 'unsafe evidence name')
        path = Path(m.RUN) / name
        no_links(path)
        with path.open('x') as output:
            json.dump(sanitize(value), output, indent=2, sort_keys=True)

    def create_run(self):
        no_links(m.ROOT)
        validate_root(os.stat(m.ROOT), os.getuid())
        no_links(m.RUN)
        m.require(not os.path.lexists(m.RUN), 'existing evidence/run lock; never overwrite')
        Path(m.RUN).mkdir(mode=0o700)

    def base_checks(self):
        checked = {}
        record = {'status': 'failed', 'hashes': checked}
        try:
            for name, expected in m.BASE_HASHES.items():
                value = hash_file(m.BASE + '/' + name)
                checked[name] = value
                m.require(value == expected, 'base integrity failure: ' + name)
            record['status'] = 'passed'
            return checked
        finally:
            self.persist('base-hashes-%d.json' % time.monotonic_ns(), record)

    def host_checks(self):
        no_links(m.ROOT)
        no_links(m.VM_DIR)
        m.require(not os.path.lexists(m.VM_DIR), 'clone already exists')
        m.require(hash_file(m.TART) == m.TART_SHA, 'controller changed')
        no_links(m.SOFTNET)
        validate_helper(os.stat(m.SOFTNET), hash_file(m.SOFTNET))
        validate_vm_list(self.command([m.TART, 'list', '--format', 'json'])['stdout'], clone_allowed=False)
        mem = self.command(['/usr/bin/vm_stat'])['stdout']
        disk = self.command(['/bin/df', '-Pk', m.ROOT])['stdout']
        therm = self.command(['/usr/bin/osascript', '-l', 'JavaScript', '-e',
                              'ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState'])['stdout']
        result = capacity(mem, disk, therm)
        allocated = self.command(['/usr/bin/du', '-sk', m.ROOT])['stdout'].split()[0]
        m.require(allocated.isdigit() and int(allocated) <= 400 * 1024**2, 'task allocation ceiling exceeded')
        dhcp = self.command(['/usr/sbin/scutil', '--prefs', 'com.apple.InternetSharing.default.plist'],
                            stdin='list\nget /bootpd\nd.show\nquit\n')['stdout']
        result['dhcp_before'] = dhcp_baseline(dhcp)
        self.base_checks()
        result['after_hash_capacity'] = self.health()
        self.persist('ownership.json', {'vm': m.VM, 'path': m.VM_DIR, 'root_absent_before_claim': True})
        self.claimed = True
        return result

    def start_watchdog(self):
        m.require(self.expires_at is not None and self.expires_at - time.time() >= m.LIVE_SECONDS + 30,
                  'insufficient approved execution window after admission')
        self.deadline = time.monotonic() + m.LIVE_SECONDS
        read_fd, self.watch_write = os.pipe()
        self.watchdog = subprocess.Popen(['/usr/bin/python3', str(m.HERE / 'watchdog.py'), str(read_fd)],
                                         env=m.ENV, pass_fds=(read_fd,), start_new_session=True,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(read_fd)

    def start_vm(self, argv):
        m.require(self.vm is None, 'VM already started')
        out = open(Path(m.RUN) / 'vm.stdout', 'xb')
        err = open(Path(m.RUN) / 'vm.stderr', 'xb')
        try:
            self.vm = subprocess.Popen(argv, env=m.ENV, start_new_session=True,
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        finally:
            out.close()
            err.close()
        return {'started': True}

    def wait_guest(self, argv):
        end = min(self.deadline, time.monotonic() + 300)
        while time.monotonic() < end:
            m.require(self.vm.poll() is None, 'VM exited during readiness')
            r = self.command(argv, timeout=min(30, end-time.monotonic()), allow_failure=True)
            if r['exit_code'] == 0:
                return r
            time.sleep(1)
        raise m.Rejected('guest readiness deadline exceeded')

    def cleanup(self):
        if self.cleaned:
            return {'status': 'already-cleaned'}
        if not self.claimed:
            return {'status': 'not-claimed'}
        start = time.monotonic()
        verdict = {'vm': m.VM, 'path': m.VM_DIR, 'status': 'orphan'}
        try:
            rows = json.loads(self.command([m.TART, 'list', '--format', 'json'], timeout=2, monitor=False)['stdout'])
            matches = [x for x in rows if x.get('Name') == m.VM]
            m.require(len(matches) <= 1, 'duplicate cleanup VM')
            if matches:
                if matches[0].get('State') != 'stopped' or matches[0].get('Running') is not False:
                    self.command([m.TART, 'stop', m.VM, '--timeout', '20'], timeout=23,
                                 allow_failure=True, monitor=False)
                rows = json.loads(self.command([m.TART, 'list', '--format', 'json'], timeout=2, monitor=False)['stdout'])
                matches = [x for x in rows if x.get('Name') == m.VM]
                m.require(len(matches) == 1 and matches[0].get('State') == 'stopped' and
                          matches[0].get('Running') is False, 'VM stop unconfirmed; retain orphan')
                if self.vm:
                    # Retain the stopped clone if the owned Tart run process has not exited.
                    self.vm.wait(timeout=2)
                no_links(m.VM_DIR)
                self.command([m.TART, 'delete', m.VM], timeout=2, monitor=False)
            m.require(not os.path.lexists(m.VM_DIR), 'clone residue')
            m.require(time.monotonic() - start <= m.CLEANUP_SECONDS, 'cleanup exceeded 30 seconds')
            verdict['status'] = 'absent'
            self.cleaned = True
            return verdict
        except Exception as exc:
            verdict['error'] = str(exc)
            raise
        finally:
            verdict['duration_seconds'] = time.monotonic() - start
            name = 'cleanup-%d.json' % time.monotonic_ns()
            self.persist(name, verdict)

    def finish_watchdog(self):
        if self.watch_write is not None:
            # Only disarm after cleanup proved absence. EOF otherwise triggers the reaper.
            if self.cleaned:
                try:
                    os.write(self.watch_write, b'D')
                except BrokenPipeError:
                    pass
            os.close(self.watch_write)
            self.watch_write = None
            self.watchdog.wait(timeout=35)
