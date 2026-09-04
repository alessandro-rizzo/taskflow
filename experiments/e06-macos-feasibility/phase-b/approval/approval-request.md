# Proposed approval request — not yet actionable

The following is the exact boundary proposed for a future approval. It is not
an assertion that TF-003.14 is ready to execute.

> Approve only the native-host actions described by frozen implementation
> commit `6decbbd1323fd9a69137129db234028d80b1151d`, Phase-B protocol digest
> `12170d8effa3ce838c49c3180bd662ae879ea2a66ffe990ef5d793119af6f1bd`,
> frozen command-ledger digest
> `ce8592f5be1075361f51ae3bc60b55cdd0ad7254deb65fbb2a4a9124fa082db0`,
> and cleanup-ledger digest
> `db43ac71bb1088c8e4e122bd2e365e8687c715499031322a3345ad8bd7a649c1`.
> The only writable root is `/private/tmp/taskflow-e06-native-a`; the only
> permitted simulators are newly created names beginning
> `taskflow-e06-native-a-` in the custom device set
> `/private/tmp/taskflow-e06-native-a/CoreSimulator`; and the only build target
> is the committed E06SmokeApp fixture using the two explicit DerivedData roots
> and signing disabled. Cleanup may shut down/delete only those custom-set
> devices and may remove only the exact owned root after its ownership and
> symlink guards pass. Any guard, attestation, command, signal, or cleanup
> failure must record the exact orphan and stop without widening scope.

Before that text can become execution approval, the approver must supply all of
the following in one fresh response:

1. Approval identity.
2. Approval timestamp.
3. Exclusive window start and end for resource
   `taskflow-e06-local-mac17-7`.
4. Acceptance of every sentence in the quoted mutation boundary.
5. A current attestation, gathered at the start of that window, confirming the
   expected profile, RAM/disk/thermal floors, mutable-root absence, and custom
   CoreSimulator runtime/device-type access.

Execution remains independently blocked because the frozen runner is
description-only and the 31 exact commands cover a bounded fixture lifecycle,
not the predeclared measurement and fault-injection sample schedule. That
runner and expanded exact ledger must be implemented, reviewed, committed,
re-digested, schema-checked, and included in a replacement approval packet.
Because that would change the implementation commit and command ledger, the
approval above must then be requested afresh; approval of this proposal cannot
be carried forward.

The approval never includes the default device set, existing/currently booted
simulators, user workspaces or DerivedData, VM/image/provider lifecycle,
network, downloads/installation, broad signals, broad deletion, or any command
not present in the replacement manifest.
