# E06 local macOS VM acquisition and measurement contract

Ticket: TF-003.14. Risks: R4, R8, R9. This directory records the acquisition
proposal and measurement requirements. The user approved acquisition and
subsequently authorised removal of experiment VM images/clones after the
experiment. Current acquisition progress is in the ticket and task-root
receipts. The single-cycle executable adapter is in [smoke/](smoke/README.md).
Its checks are recording-only; reviewed implementation commit, missing SDK
build identity and fresh execution approval are still required. It does not
implement the full measurement matrix.
The zero execution fields in the proposal describe repository recording mode,
not the current state of external acquisition.

## Proposed acquisition

Acquire Tart **2.36.0** as a standalone application bundle and the published
Cirrus Labs **macOS Tahoe / Xcode 26.5** image. The proposed guest profile is
different from the existing native Xcode 26.6 profile. Approving acquisition
accepts trying this alternative; it does not assert matching SDK/runtime builds
or accept benchmark results. Preserve all native artifacts through `e794e61`.

| Item | Immutable identity | Size from public metadata |
| --- | --- | --- |
| Tart 2.36.0 archive | SHA-256 `c72a8ab8d78a6498a1e42688b1a1ec6c512ce46ca35a3a3be130c3de1440c7e8` | 22,905,967 bytes |
| Tahoe / Xcode 26.5 OCI manifest | SHA-256 `61f6e857a3d65dd2f8daf9c51c7b837fa458bcc9181ae8556e645b534dab6bf6` | 68,828,940,474 compressed layer bytes; 140,000,000,000-byte virtual disk |

Registry metadata was inspected on 2026-09-04. The compressed total counts all
layer descriptors; repeated blobs can reduce actual transfer (unique total:
68,528,981,834 bytes). Neither total predicts the allocated APFS footprint.
Download duration, actual transferred bytes, and allocated storage must be
measured during acquisition. Reserve at least 600 GiB free before starting;
limit new task allocation to 400 GiB and preserve the 200 GiB host floor.

The advertised `macos-tahoe-xcode:26.6` returned HTTP 404 and was absent from
the registry tag list. The alternative multi-Xcode `macos-runner:tahoe` resolved
to `98acf50794306bc293f2e30e40115f1452772e4e17eb257968b7c98f39ebf231`,
with approximately 190 GB of compressed layers and a 520 GB virtual disk.
The smaller available image is proposed first. `pins.json` retains both
metadata summaries; these are not raw disk verification or live attestation.

All task files go beneath `/private/tmp/taskflow-e06-vm-a`:

- `downloads/`: the checksum-verified Tart archive;
- `tools/tart-2.36.0/`: the signed application bundle, including its embedded
  provisioning profile, and the archive's plain-text `LICENSE` file;
- `tart/`: isolated `TART_HOME`, OCI cache, future base and disposable VMs;
- `tmp/`: task-specific temporary files;
- `receipts/`: acquisition hashes, sizes, timestamps, failures and paths.

No Homebrew installation is needed. Before extraction, inspect the tar paths
and relative symbolic links; reject paths or links escaping `tart.app`, cycles,
hard links, special files, or top-level content other than the regular `LICENSE`
file observed in the pinned archive. If the published archive
has a different layout, stop and revise the concrete proposal. Verify the
signature and Gatekeeper acceptance before invoking the program. Keep
`TART_NO_AUTO_PRUNE=1`; Tart's internal temporary-file collection remains scoped
to this fresh `TART_HOME`.

`acquisition-ledger.json` contains the full acquisition ledger;
`contract.py describe` reproduces and verifies it: prerequisites,
commands, targets, timeout ceilings, expected outcomes, receipt paths, and
retention. These are review data, not a script that runs them. Acquisition
requires HTTPS to GitHub releases/CDNs and GHCR/CDNs; public registry tokens
stay in memory. macOS signature/Gatekeeper assessment may maintain normal
system security caches. `CFFIXED_USER_HOME` directs Foundation's HTTP cache
beneath the task root; `TART_HOME` alone did not cover that cache. No host
security settings are changed. A failed step
retains its exact partial files for inspection; no automatic cleanup is allowed.
The image pull may take up to four hours; that acquisition ceiling is separate
from the frozen 900-second measurement-command ceiling.

## Guest preflight after acquisition

The next proposal clones the pinned base into `taskflow-e06-vm-a-preflight`,
sets that disposable clone to 6 vCPUs and 16 GiB RAM, and starts one VM with
`--net-host --no-clipboard --no-audio`. Do not mount host directories or disks.
`--net-host` is host-only networking, **not isolation from host services or
other VMs on the segment**. Boot-side macOS network/service mutations and
guest SSH trust/bootstrap must be included in that preflight approval. Do not
disable SSH host verification, forward an agent, copy personal credentials,
or enable Remote Login on the host.

The prebuilt CI image's templates disable SIP and supply default automation
credentials in the guest. Treat it as third-party software and record the live
security settings. No personal Apple account, signing material, provider keys,
or untrusted workload belongs in this trial. Guest SIP changes do not change
host SIP, but results from this guest do not prove SIP-enabled guest behavior.

Attest guest OS/build/architecture, Xcode version/build/path, SDKs, Simulator
runtime/build/device types, logged-in session, free RAM/disk, image identity,
network behavior and services. The template suggests
`/Applications/Xcode_26.5.app/Contents/Developer`; verify it before setting the
guest build environment. The 140 GB guest disk may have insufficient free
space even though the host has ample space. Any expansion belongs to a new
explicit setup step and applies only to an owned clone.

Existing native profile fields and digests remain unchanged. Guest values
stay null until observed. A mismatch is a failed placement or a reason to
propose another profile before measurements; it never rewrites a planned
profile during a run.

## Measurement contract after guest attestation

The compiler reads the hash-bound Phase-A `measurement-plan.json` directly.
It preserves exact start/end boundaries, counts, correctness probes, failure
rules and decision branches. Initial order is warm VM with APFS workspaces,
warm immutable restore, then VM per namespace; admit or reject each before
timing. Disk cloning alone is not proof of suspended-memory restore.

Required evidence includes 15 cold boots; 30 warm-workspace samples with p95
strictly below 3 seconds; 30 simulator-ready samples per admitted mechanism
with p95 strictly below 15 seconds; and 15 build/install/test/reset/cleanup
samples per applicable pair. Fresh create/boot, erase/reset, and golden clone
remain distinct simulator mechanisms. Restore the VM-specific obligations:
15 image import/update samples, one actual image update/rollback, and five
VM-loss cases. Reimporting the same digest does not prove an update/rollback.

Retain twenty alternating handoffs, ten two-namespace repetitions, and five
repetitions at each namespace-concurrency level 1, 2, 3, 4. Namespace count is
not VM count. Do not infer that four namespaces require or permit four macOS
VMs. Record actual host/framework capacity and licensing constraints before
choosing multi-VM execution; unsupported levels remain explicit limitations.
Retain five simulator-loss, cancellation and caller-loss cases each, the
30-second cleanup grace, and zero-tolerance contamination/identity/base
integrity gates. A smoke pass never substitutes for this matrix.

An executable VM/guest adapter and full operation ledger follow the preflight.
They must identify every host Tart and guest command, signal, fault, evidence
write, timeout, runtime handle and cleanup target. Reuse immutable fixture and
measurement specifications; do not redirect the native runner at a guest.
Host-only networking does not satisfy a no-host-access claim. The measurement
boundary needs its own attestation and approval. The native approval packet
does not authorize VM work.

Later sanitized raw measurements belong under
`experiments/e06-macos-feasibility/evidence/taskflow-e06-vm-a/` with T1 v2
records, timing traces, contamination matrices, capacity/recovery results,
base hashes, image cost, exact orphans and limitations. Acquisition receipts
remain separate from warm-path benchmark evidence. No result files are created
by the checks here. The Gate 1 decision remains pending.

## Verification and recommendation

From the repository root:

```sh
mise exec -- task --dir experiments/e06-macos-feasibility/phase-b/vm-execution check
```

The check validates pins and immutable inputs, rejects changed paths/commands,
and records the acquisition proposal with zero execution and zero benchmark
samples. Negative tests block native, filesystem-write and network primitives
during recording. Synthetic unit-test scratch files are disposable test state.
The ordinary check is independent of whether the acquired image exists.
`contract.py check-acquisition-readiness` is the separate initial absence check;
it must reject an already-existing task root before a new acquisition.
Run the existing native execution checks and repository `mise exec -- task check`
as well. This stage intentionally has no `execute` or `acquire` CLI mode.

Recommendation: approve the smaller pinned image acquisition, then use live
guest attestation to decide whether the VM is suitable for a smoke cycle.
No E06 feasibility branch is selected yet.

Sources: [Tart release](https://github.com/openai/tart/releases/tag/2.36.0),
[pinned run flags](https://github.com/openai/tart/blob/2.36.0/Sources/tart/Commands/Run.swift),
[clone/pruning behavior](https://github.com/openai/tart/blob/2.36.0/Sources/tart/Commands/Clone.swift),
[Tart storage](https://github.com/openai/tart/blob/2.36.0/Sources/tart/Config.swift),
[Xcode image template](https://github.com/cirruslabs/macos-image-templates/blob/26.5/templates/xcode.pkr.hcl).
