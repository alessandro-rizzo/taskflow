# E06 VM smoke adapter

TF-003.14; risks R4/R8/R9. This is an experimental single-cycle executable
adapter, not a production worker, full-matrix runner or E06 branch decision.
It never imports the native backend or changes accepted Phase-A inputs.

## Current boundary

Preflight observed macOS 26.4/25E246, Xcode 26.5/17F42 and available iOS
Simulator 26.5/23F77, six CPUs, 16 GiB RAM and guest SIP disabled. Separately
approved identity completion resolved both SDK build identifiers to 23F73.
`profile-observation.json` remains historical observation, not approval; the
approval packet must bind the completed identity. Two separately approved smoke
attempts are retained as failed evidence below. Parent acquisition files remain
historical proposal snapshots; subsequent Softnet/preflight approvals are in
task receipts.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e06-macos-feasibility/phase-b/vm-execution check
```

This runs acquisition and smoke recording/tests, never Tart, Xcode, Simulator,
the watchdog, guest commands or a network connection. Fake tests use synthetic
SDK build IDs, never live observations or approval files. Test scratch files
are disposable. From the parent directory, `python3 smoke/runner.py describe`
prints the full ledger, fixed script payload, identity-completion queries and
deferred cleanup ledger. `record-plan` reports zero execution/benchmark samples.

## Implemented cycle

Only a fresh `taskflow-e06-vm-a-smoke-003` clone of the pinned local base is admitted;
never reuse the preflight clone or boot the base. Admission checks capacity,
stopped state, binary/base hashes, helper root/setuid permissions and DHCP state.
The available-memory estimate is free + inactive + speculative pages, not
guaranteed immediately free RAM. The 400 GiB du ceiling is conservative because
APFS can count shared extents repeatedly; the separate 200 GiB free-disk floor
remains binding.

After a bounded headless host-only boot, compare a complete guest profile before
copying the three pinned smoke-local fixture files and closed shell driver
through guest-agent stdin. Verify paths/sizes/hashes; no shares, SSH,
credentials or downloads.
Required macOS system tools must already exist; no guest Python is assumed.

Build with explicit SDK/developer directory/destination, credential-free manual
ad-hoc signing, and dedicated workspace/cache/DerivedData/results paths. The
build never enables provisioning updates or selects a development team. Verify
the signature, effective application-identifier/default Keychain access group,
app identity, binary presence and complete file hashes, rechecking hashes before
each install. Create one device in the custom guest set and validate its returned
UUID against name/type/runtime/state. Never select `booted` or a default-set
device.

Three launches use Simulator's PTY console attachment to prove initial empty
canaries, persistence, then empty canaries after shutdown/erase/reboot/reinstall.
The report includes every Keychain pre-read/delete/add/immediate-verify OSStatus;
only the exact not-found/success transition is accepted. Missing, duplicate,
malformed or wrong-namespace reports fail. Remove the owned device/workspace
and check absence; stop/delete only the smoke clone and check base hashes. This is not p95,
cross-namespace isolation, concurrency or failure-recovery benchmark evidence.

## Approval gate

After implementation review/commit, `validate-approval` and `execute-smoke`
require exactly `phase-b/vm-approval/smoke.json` and `identity.json`. This code
does not generate a usable approval packet. The closed approval object has:

- `schema`: `taskflow-e06-vm-smoke-approval/v1`;
- `operator`, timezone-qualified `approved_at`, `not_before`, `expires_at`;
- `commit`, `tree`, exact implementation `bindings`, `ledger_sha256`;
- complete `profile`, `identity_evidence_sha256`, exact `scopes` from model.py.

All implementation files must be tracked/unchanged; fixture bytes are separately
pinned. The window is at most two hours, with enough time remaining after
admission for the bounded run/cleanup. Null SDK builds, modified code/commands,
wrong identities/tools and expired scope fail before VM mutations.

The identity evidence has exactly `kind: live-guest-identity`, `profile`,
`base_sha256`, and `tool_checks: {system_tools_available: true}`. Derive it from
the separately approved identity-completion queries printed by `describe`;
review and seal it before execution. Live smoke re-attests those facts instead
of learning a new expected profile during the run.

## Bounds, recovery and evidence

Commands have ceilings of 900 seconds or less. A 30-minute watchdog starts
before cloning; host health is rechecked during long VM commands. Each output
stream is capped at 8 MiB; overflow fails rather than accepting truncation.
Complete bounded streams, operation results and monotonic durations go under
exclusive mode-0700 `/private/tmp/taskflow-e06-vm-a/smoke-run-003`. Normal retained
text redacts user-directory names. Overflow/crash spools are private diagnostics
requiring review before export. No evidence goes to a provider.

Normal/error cleanup stops before deleting an unconfirmed-running VM. It must
finish within 30 seconds or report a precise orphan/deadline failure. Only host
child groups created by this invocation are terminated; stopping the VM ends
guest work even if guest-command transport is lost.

The independent watchdog watches parent-pipe loss/deadline. On caller loss it
attempts to stop the exact clone and retains a precise stopped/unconfirmed
orphan. If a clone command may still be in flight, that ambiguity is explicit.
It never kills unrelated PIDs/deletes the base. An existing run directory blocks
automatic retry; inspect receipts/in-flight owned commands before recovery.
These recovery paths are fake-tested, not proven on a live VM.

The accepted shared Phase-B fixture remains byte-for-byte frozen for the retained
native executor. Signing/status instrumentation lives only in `smoke/fixture`.

The first approved attempt is retained unchanged at
`/private/tmp/taskflow-e06-vm-a/smoke-run`. It reached the initial application
launch, but Xcode 26.5 `simctl launch --console` returned only the bundle/PID
line, so the strict result parser failed and exact cleanup removed that attempt's
clone. The second fixed ledger uses Apple's documented `--console-pty` standard-
stream attachment mode. Attempt two is retained unchanged at
`/private/tmp/taskflow-e06-vm-a/smoke-run-002`: PTY result capture worked and
preferences/document data persisted, but the fixture's Keychain write did not.
That fixture disabled code signing and discarded every Security OSStatus, so it
could not prove the precise cause or reach erase/reset. Attempt three uses a
distinct evidence root/clone, preserves both failures, verifies its effective
signing entitlements before install, and reports every Keychain transition.

## Network and eventual cleanup

Host-only is not hermetic: host services remain reachable. Preflight listed
IPv6 tunnel routes and guest SSH/VNC listeners. Guest SIP is disabled. There
is no packet-level isolation claim. No global HOME/PATH, Gatekeeper, sudoers
or host security-policy setting is changed by this adapter.

Softnet writes `bootpd` in `com.apple.InternetSharing.default.plist` with
`DHCPLeaseTimeSecs=600` and `dhcp_ignore_client_identifier=true`. The original
key was absent. Admission refuses unexpected state. The helper and DHCP setting
currently remain on the host for this experiment.

`model.cleanup_plan()` is a separate non-executing end-of-experiment ledger.
It covers retained preflight/base/helper paths and preserves small receipts.
Restoration must lock preferences, compare the exact current key, remove only
the matching experiment-created key, commit/apply/unlock and read back. Stop on
concurrent changes or absent administrator authority. The user authorised
eventual image/helper removal; it still waits for experiment completion and
ownership/dependency checks. Report filesystem free-space changes rather than
summing clone allocations. Repository checks perform none of this cleanup.

## Recommendation

Review/commit implementation, complete SDK identity, then obtain fresh smoke
execution approval. Smoke acceptance precedes the full-matrix implementation
and approval. Frozen measurement counts/boundaries, p95 below 3/15 seconds,
contamination/concurrency, five loss cases per kind and actual image-update/
rollback remain unchanged and unmeasured. No full-matrix mode is provided.
