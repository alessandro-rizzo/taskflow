# E06 native-host execution approval proposal

This directory is an uncommitted, non-executing proposal bound to immutable
contract commit `6decbbd1323fd9a69137129db234028d80b1151d`. It does not amend that
contract and is not an approved execution manifest.

`approval-packet.json` binds the accepted schema, the frozen Phase-B protocol,
the exact 30-command native ledger, the exact final root-removal command, and a
safe read-only host refresh. `scripts/verify_approval.py` checks those bindings,
materializes an in-memory specimen for all resolved schema fields, and proves
that the real manifest remains blocked on the named unresolved approval and
execution-window facts. It never invokes the native toolchain or performs a
mutation.

The frozen runner has no execution entrypoint. The current ledger describes one
bounded fixture lifecycle, not the complete measurement/fault sample schedule.
Consequently this packet is suitable for reviewing the proposed native-host
mutation boundary, but it is not sufficient authority to execute TF-003.14's
measurements. A separately reviewed executable measurement runner and expanded
sample/fault ledger would be required before any native command may run.

Verification from the repository root:

```sh
python3 experiments/e06-macos-feasibility/phase-b/approval/scripts/verify_approval.py
python3 -m unittest discover -s experiments/e06-macos-feasibility/phase-b/approval/tests -p 'test_*.py'
```
