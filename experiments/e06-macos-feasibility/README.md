# E06 macOS VM, Xcode, and simulator feasibility inventory

Roadmap experiment: E06. Ticket: TF-003.13. Risks: R4, R8, R9.

Status: Phase A inventory and measurement contract. No feasibility candidate
has been executed and no E06 branch has been selected.

## Question

Can Taskflow use native macOS capacity, Xcode, and simulators through a worker,
sandbox, and session model that is reproducible enough, fast enough, and safe
enough for W3?

This ticket buys the information needed to run that experiment safely. It
records the current read-only host inventory, classifies candidate mechanisms,
predeclares timing and fault measurements, and makes missing representative
infrastructure an explicit blocker. TF-003.14 owns all VM/simulator mutations,
measurements, and the eventual branch decision.

## Frozen inputs

`fixture-bindings.json` binds the W3 v1 specification, both namespace examples,
all six W3 fault scenarios, and the T1 benchmark-v2 record and validator. W3 is
still specification-only: this experiment must not imply that endpoint routing,
runtime authorization, or native infrastructure already exists.

The current product specification defines no `MAC-*` requirement identifiers.
The ticket's `MAC-1` through `MAC-5` labels are retained only as stale
provenance. `contract.json` maps this work to the current EXEC, REP, and AGENT
requirements without inventing aliases.

## Inventory result

The retained snapshot was collected on 2026-09-04 with non-mutating local
queries. It establishes:

- an Apple M5 Max MacBook Pro with 64 GiB of memory and macOS 26.5.2 build
  25F84;
- Xcode 26.6 build 17F113 and iOS/iOS Simulator 26.5 SDKs;
- an installed arm64 iOS 26.5 simulator runtime image, build 23F77;
- Apple Virtualization and Hypervisor frameworks;
- no installed Tart, Orchard, vfkit, UTM, Parallels, VirtualBox, or macOS image
  management CLI;
- a shared default simulator set containing a recently booted device, which is
  explicitly forbidden for E06;
- managed-sandbox restrictions that prevent live CoreSimulator, hardware
  `sysctl`, `diskutil`, debugger-rights, and process inventory checks.

Lima, Colima, and Docker CLI presence is recorded but does not establish a
macOS-guest candidate. Unknown and blocked observations stay unknown; command
presence is never credited as exercised behavior.

## Candidate and safety boundary

`candidate-matrix.json` covers the roadmap mechanisms. Only a trusted native
host with an experiment-owned workspace and custom simulator device set is
conditionally viable on the inventoried machine, and it is not reserved. VM
and external-runner candidates are externally blocked by absent pinned
tooling, immutable images, credentials, or dedicated capacity.

Every future mutation must be described by an instance of
`execution-manifest.schema.json` and separately approved. The manifest must
name exact experiment-prefixed VM, workspace, DerivedData, and custom device
set targets, resource and thermal limits, commands, cleanup allowlists, and an
operator. Approval of this Phase A implementation is not approval to execute
that manifest.

The default simulator set, existing devices, user workspaces, existing VMs,
and immutable base images are never cleanup targets.

## Predeclared measurement protocol

`measurement-plan.json` freezes:

- 15 descriptive cold-boot samples;
- 30 warm workspace-ready samples, gated at p95 strictly below 3 seconds;
- 30 simulator-ready-to-install samples, gated at p95 strictly below 15
  seconds;
- 15 samples for build, install, test, reset, cleanup, and image update/import
  where applicable;
- namespace handoff, two-namespace, bounded concurrency, contamination,
  immutable-base, image-update, and loss/recovery probes.

Timing records use `taskflow-t1-benchmark/v2`. Candidate execution is serial
except for an explicitly named concurrency probe, and its exact concurrency
levels plus memory/thermal stop conditions must be sealed before results are
observed.

## Decision boundary

TF-003.14 may select one roadmap branch only after the frozen contract is
committed and representative infrastructure is approved: warm VM plus cloned
workspace, per-namespace VM, trusted native host, coarse external runner,
serialized macOS capacity, or stop/narrow. This ticket selects none.

## Limitations and threats to validity

- The current host is shared and unreserved.
- No VM or external runner was exercised.
- Simulator inventory was derived from installed plist metadata because the
  managed environment cannot connect to CoreSimulatorService.
- The SDK build (23F81a) and installed runtime image build (23F77) differ and
  must remain distinct profile fields.
- Local tool and framework presence does not prove entitlement, license,
  automation, performance, isolation, or recovery behavior.
- E06 does not own Linux-to-macOS endpoint routing or authorization; E07 does.
- The bounded concurrency result will be a maximum within the approved test
  envelope, not a universal hardware limit.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e06-macos-feasibility check:phase-a
```

The command is dependency-free beyond Python 3 and Task. It verifies the
frozen artifacts and repository bindings, runs mutation tests, and rejects
Phase B evidence or a selected decision branch.
