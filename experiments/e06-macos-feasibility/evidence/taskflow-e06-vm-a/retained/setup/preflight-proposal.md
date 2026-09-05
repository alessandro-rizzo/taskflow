# E06 single-VM preflight proposal

Status: awaiting explicit first-boot approval. Task TF-003.14.
This is a setup/compatibility check, not benchmark execution or a Gate 1 decision.

## Ownership and identities

- Agent: @codex-root.
- Branch/worktree: tf-003.14-e06-measurements at /private/tmp/taskflow-tf-003.14.
- Controller: /private/tmp/taskflow-e06-vm-a/tools/tart-2.36.0/tart.app/Contents/MacOS/tart.
- Controller binary SHA-256: e0d71385a2974229c3e97f71862020cce4911c16c3a2fb74ab5e6f540a62131e.
- Source: ghcr.io/cirruslabs/macos-tahoe-xcode@sha256:61f6e857a3d65dd2f8daf9c51c7b837fa458bcc9181ae8556e645b534dab6bf6.
- New clone name: taskflow-e06-vm-a-preflight.
- Clone directory: /private/tmp/taskflow-e06-vm-a/tart/vms/taskflow-e06-vm-a-preflight (verify actual resolved location).
- Receipts: /private/tmp/taskflow-e06-vm-a/receipts/preflight-*.
- No repository implementation, commit, merge, push or ticket completion in this stage.

## Execution environment

Use env -i with PATH=/usr/bin:/bin:/usr/sbin:/sbin, LANG=C, LC_ALL=C,
CFFIXED_USER_HOME=/private/tmp/taskflow-e06-vm-a,
TART_HOME=/private/tmp/taskflow-e06-vm-a/tart, TART_NO_AUTO_PRUNE=1,
TMPDIR=/private/tmp/taskflow-e06-vm-a/tmp. Do not repurpose HOME.

## Exact lifecycle and guest command scope

1. Read-only host capacity, thermal and ownership checks. Require at least
   16 GiB available RAM, 200 GiB free disk, task allocation below 400 GiB,
   thermal state below serious, no existing target clone, and no owned running VM.
   Verify controller and cached base identity against acquisition receipts.
   Reject missing/incomplete cache; no further image pull is authorised.
2. Controller: clone SOURCE taskflow-e06-vm-a-preflight --prune-limit 0.
   Use the cached standalone image, not stacked storage. Do not boot the base.
3. Controller: set taskflow-e06-vm-a-preflight --cpu 6 --memory 16384.
   No guest disk expansion or host resource configuration changes.
4. Controller: run --no-graphics --net-host --no-clipboard --no-audio taskflow-e06-vm-a-preflight.
   Start one headless VM. No host directory/disk shares, VNC, bridged/NAT/Softnet,
   nested virtualisation, credentials, forwarded agents or personal accounts.
5. Through controller exec taskflow-e06-vm-a-preflight COMMAND only, inspect:
   - /usr/bin/true (bounded guest-agent readiness probe)
   - /usr/bin/sw_vers
   - /usr/bin/uname -m
   - /usr/bin/id
   - /usr/bin/stat -f %Su /dev/console
   - /usr/bin/date -u +%Y-%m-%dT%H:%M:%SZ
   - /usr/sbin/sysctl hw.ncpu hw.memsize
   - /usr/bin/vm_stat
   - /bin/df -k /
   - /usr/bin/csrutil status
   - /usr/bin/xcode-select -p
   - /usr/bin/xcodebuild -version
   - /usr/bin/xcodebuild -showsdks
   - /usr/bin/xcodebuild -checkFirstLaunchStatus
   - /usr/bin/xcrun simctl list runtimes --json
   - /usr/bin/xcrun simctl list devicetypes --json
   - /sbin/route -n get default
   - /usr/sbin/netstat -rn
   - /usr/sbin/netstat -an -p tcp
   Record the selected Xcode path; do not change it or accept licenses.
   Version/SDK/runtime queries may start guest developer services and write
   guest caches/logs. No simulator create/boot/install/test/reset is authorised.
   If guest agent is absent, stop; no automatic SSH/bootstrap fallback.
6. Controller: stop taskflow-e06-vm-a-preflight --timeout 30.
   This authorises graceful shutdown and Tart's force-stop fallback for this
   one clone only, including on preflight failure or the time/resource limit.
7. Controller: list --format json; verify the clone is stopped. Record actual
   allocation and base integrity, command results, guest profile and limitations.
   Retain stopped clone and base until the experiment is finished.

## Limits and disclosed effects

- Boot/guest-agent readiness ceiling: five minutes; individual queries: 60 seconds.
- Total live-VM preflight window: at most 20 minutes; stop on capacity/thermal breach.
- Clone/checksum operations: at most 900 seconds each, outside the live-VM window.
- Host-only networking creates framework-managed host networking/service state
  and can reach host services and other VMs on that segment. It is not hermetic.
  Do not probe host services or external endpoints. Record routing/listeners,
  not a proven network-denial boundary.
- Boot executes the third-party image's existing services, writes clone disk/NVRAM,
  and uses host Virtualization.framework resources. Guest defaults include a
  SIP-disabled CI template and automation account; verify, do not change them.
- No host SIP/firewall/Remote Login change, software install/update/download,
  provider action, benchmark workload or build is included.
- End-of-experiment deletion of owned VM images/clones is already authorised.
  Preserve small evidence, recheck ownership/dependencies, and measure reclaimed
  space. No deletion at this preflight checkpoint.

## Sources checked

Installed Tart 2.36.0 clone/set/run/exec/stop help was read without lifecycle execution.
Pinned implementation confirms cached-image cloning and guest-agent execution:
https://raw.githubusercontent.com/openai/tart/2.36.0/Sources/tart/Commands/Clone.swift
https://raw.githubusercontent.com/openai/tart/2.36.0/Sources/tart/Commands/Exec.swift
