# Candidate D: minimal TypeScript descriptors

Candidate D uses ordinary TypeScript values and invariant generic handles to
emit the same experimental schema and W1 composition trace as the Go
candidates. TypeScript `5.9.3` is pinned in the candidate-local lockfile and is
the semantic checker; Bun transpilation is not accepted as type evidence.

Run from this directory:

```sh
mise exec -- task check
```

This is a bounded E01 comparison, not a production TypeScript SDK.
