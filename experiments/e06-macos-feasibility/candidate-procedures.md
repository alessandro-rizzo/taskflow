# E06 candidate setup, reset, and cleanup procedures

These are frozen Phase B procedures, not authorization to execute them. Every
literal placeholder must be resolved in a fresh approved execution manifest.
All mutable names start `taskflow-e06-`; all local mutable paths start
`/private/tmp/taskflow-e06-`. A guard must resolve and compare every target
against the manifest before a lifecycle or cleanup command runs.

The default CoreSimulator device set, existing devices, existing VMs, user
workspaces, and immutable base images are forbidden targets.

## PROC:warm-immutable-vm-restore

Setup:

1. Verify the pinned controller version and locally present base-image digest
   without pulling or updating it.
2. Verify that the manifest VM name starts `taskflow-e06-` and does not already
   exist.
3. Clone the read-only base or suspended clean template to that exact VM name.
4. Start the clone headlessly, wait for the guest runner, then attest macOS,
   Xcode, SDK/runtime, runner, sandbox policy, and reset policy against the
   planned profile digest.
5. Create only the manifest workspace, DerivedData, HOME, TMPDIR, and custom
   simulator device-set roots inside the clone.

Reset between namespace samples:

1. Stop the experiment clone, never the base/template.
2. Delete only the exact manifest clone after its prefix and ownership guard
   passes.
3. Re-clone from the same immutable base/template and repeat attestation.

Cleanup:

1. Collect sanitized diagnostics and checksums.
2. Stop and delete only manifest-listed experiment clones.
3. Prove no experiment VM remains and the base digest is unchanged.

Tart-shaped command semantics are `tart clone BASE RUN_VM`, `tart run RUN_VM
--no-graphics`, `tart stop RUN_VM`, and `tart delete RUN_VM`; TF-003.14 must
verify exact syntax against its pinned installed version before declaring this
candidate viable. Orchard must express the same lifecycle through pinned API
operations and resource IDs; it may not widen cleanup to a worker or cluster.

## PROC:warm-vm-apfs-workspaces

Setup:

1. Acquire and attest one already-clean warm VM using the preceding procedure.
2. Verify the guest source base is immutable and its digest matches the
   manifest.
3. Create a namespace workspace with APFS clonefile semantics, then assign
   namespace-private HOME, TMPDIR, DerivedData, results, tool-cache partition,
   and custom simulator device set.
4. Verify the clone contains the source digest and no prior namespace marker.

Reset between samples:

1. Shut down only namespace-owned simulator sessions and bounded descendants.
2. Remove only the namespace roots named in the cleanup allowlist.
3. Recreate the clone from the immutable source base and rerun contamination
   probes before reassignment.

Cleanup destroys namespace roots and then either returns the attested clean VM
to the pool or discards the VM if any reset/attestation probe fails. A dirty VM
is quarantined; it is never silently reused.

## PROC:vm-per-namespace

Setup clones the same digest-pinned base to one unique `taskflow-e06-<run>-<ns>`
VM per namespace, assigns one reservation/lease, starts it headlessly, attests
it, and creates namespace-private workspace and simulator state. No VM serves
two active namespaces.

Reset discards the whole namespace VM after diagnostics; it does not attempt to
scrub and reassign a dirty instance. Cleanup stops/deletes only manifest-listed
namespace clones, verifies their absence, and proves the immutable base digest
is unchanged.

## PROC:trusted-native-host

Setup:

1. Require an exclusive approved window and confirm the manifest root is a new
   `/private/tmp/taskflow-e06-<manifest-id>` directory.
2. Pin `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` and attest the
   host, Xcode, SDK, runtime, runner, and policies.
3. Create namespace-private `workspace`, `home`, `tmp`, `DerivedData`, `results`,
   and `CoreSimulator` roots beneath the manifest root.
4. Pass the custom device set explicitly to every future `xcrun simctl --set
   DEVICE_SET ...` call and pass the namespace DerivedData root explicitly to
   every `xcodebuild -derivedDataPath ...` call.
5. Reject any resolved path outside the manifest root before execution.

Reset shuts down/erases or deletes only an experiment-created custom-set
device, terminates only PIDs recorded as descendants of the experiment runner,
removes only one namespace subtree, recreates it, and runs residue checks before
reuse. It never invokes `killall`, touches the default device set, or removes a
user DerivedData directory.

Cleanup shuts down/deletes experiment-created custom-set devices, verifies no
experiment child remains, and removes the exact manifest root after every
allowlist guard passes. A failed guard leaves the resource for manual review
and records an orphan instead of broadening deletion.

## PROC:coarse-external-runner

Setup reserves one provider resource through an approved credential mediator,
captures a read-only instance/image/toolchain/capacity manifest, uploads only an
immutable source bundle, and verifies the remote profile before invoking one
coarse W3 macOS leaf. Reset uses the provider's documented instance/session
reset API and checks namespace residue. Cleanup releases only the recorded
reservation and queries orphan state. If the provider lacks exact reset,
attestation, cancellation, or orphan APIs, record the candidate rejected; do
not approximate them with an unscoped host command.

## PROC:simulator-clone-from-golden

Within the custom device set only:

1. Create and boot an experiment golden from the pinned runtime/device type,
   complete deterministic setup, shut it down, and record its manifest.
2. For each sample, run `xcrun simctl --set DEVICE_SET clone GOLDEN NAME`, boot
   the clone, and wait with `bootstatus -b` until it is ready to install.
3. Reset by shutting down and deleting only the clone; re-hash/check the golden
   before the next sample.
4. Cleanup deletes all clones and then the golden from the custom set, followed
   by removal of the custom set root. No operation omits `--set DEVICE_SET`.

## PROC:simulator-erase-reset

Within the custom device set only, create one experiment device from pinned
runtime/device type, boot it, and wait for readiness. Between samples shut it
down, run `erase` on that exact device, boot it again, and verify contamination
markers are absent before installation. Cleanup shuts down and deletes the
exact experiment device, then removes the custom set root. A reset failure
quarantines the set and rejects reuse.

## PROC:simulator-fresh-create-boot

For every sample, run `xcrun simctl --set DEVICE_SET create NAME DEVICE_TYPE
RUNTIME`, boot the returned experiment device, and wait with `bootstatus -b`.
After diagnostics, shut down and delete that exact device. Cleanup verifies the
custom set contains no experiment device and removes only its manifest root.

## Failure rule

Any command targeting an unresolved variable, a path outside the mutable root,
a name without the experiment prefix, the default simulator set, an existing
unowned resource, or an immutable base stops before mutation. Cleanup failure
records an orphan with the exact next safe action; it never escalates to a
broader delete.
