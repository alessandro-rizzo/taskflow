# E03 Phase A threat model

## Protected authority

The experiment models a future privileged daemon that owns policy,
credentials, provider access, source selection, and accepted-plan identity.
The planner must not inherit any of that authority merely because it is
compiled Go project code.

Protected assets are represented only by experiment-owned synthetic canaries:

- a daemon token;
- a provider token;
- a secret-store value;
- a file outside the selected source view;
- a TCP listener and Unix socket owned by the harness; and
- the trusted policy document and its digest.

No real credential, agent socket, cloud endpoint, signing identity, provider
API, keychain item, or user file is an attack target.

## Adversary

The compiled project planner is fully hostile. It may ignore cooperative
cancellation, fork a descendant, emit unlimited bytes, attempt path traversal
or symlink escape, inspect ambient environment, connect to local sockets,
exhaust bounded resources, emit malformed JSON, and request authority it does
not possess. Its stdout, stderr, plan bytes, exit status, and claimed policy
identity are untrusted.

## Trusted computing base

Only these components may carry authority:

- the outer E03 supervisor and immutable-view builder;
- the host kernel and the isolation mechanism actually exercised;
- the trusted limit-setting launcher;
- the independent Python policy validator;
- the Phase A protocol, policy documents, and their verified digests; and
- the T1 conformance checker as an additional structural oracle only.

The E01 generator, E02 planner, malicious project binary, plan JSON, Docker or
VM guest, and any in-planner validation are not trusted authorization points.
The T1 conformance harness does not authorize targets, networks, secrets, or
effects.

## Input boundary

An executable planner receives exactly:

1. one digest-verified immutable selected source view;
2. one declared-input JSON document;
3. a fixed minimal environment containing only contract-declared runtime keys;
4. one invocation-private writable scratch directory; and
5. stdout/stderr pipes controlled and capped by the supervisor.

It receives no inherited daemon/provider/secret environment, Docker/Lima
socket, SSH agent, keychain, cloud configuration, user home, repository root,
or arbitrary host path. The static descriptor receives only trusted selected
source and input digests and runs no project process.

## Safe attack boundary

Every attempted external path is a sibling inside one temporary directory
created and owned by E03. Network cases target only still-open listeners that
the harness created. The process case creates one known experiment binary.
Resource cases are bounded by the outer supervisor before hostile code starts.
Synthetic markers use an obvious E03 test-only prefix and are scanned in raw,
hex, and base64 form before evidence is persisted.

The suite must never read a real external file, inspect a real credential,
contact a public or unrelated local endpoint, pull an image, create a VM, or
perform an external effect.

## Trust claims and exclusions

A blocked operation proves only the exact candidate, policy digest, operating
system, and case recorded in evidence. A bounded operation proves only the
recorded ceiling. Detection is weaker than denial. Unsupported controls,
nested-sandbox denial, missing container access, or absent VM capacity are
limitations or unavailability, never passing isolation evidence.

This experiment does not select a production sandbox API, policy language,
plan format, daemon deployment model, container runtime, or VM provider. It
does not prove Linux behavior from macOS results, and it does not authorize a
new production Go module before Gate 1.
