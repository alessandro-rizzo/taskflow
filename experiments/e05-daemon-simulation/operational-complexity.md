# E05 operational-complexity ledger

Measured experimental shape:

- one on-demand Python controller process;
- one SQLite state directory and WAL-capable database;
- no external service and no manual pre-run startup;
- foreign keys, WAL journal mode, `synchronous=FULL`, explicit schema version;
- fail-closed incompatible-schema diagnostic;
- SQLite backup/restore rehearsal;
- clean SIGTERM shutdown measured over the 30-second quiescent sample.

Complexity not implemented or measured:

- installation, launch-agent registration, signing, upgrade orchestration;
- authenticated local RPC and caller identity;
- schema migration sequencing and downgrade compatibility;
- logs, metrics, tracing, support tooling, or corrupt-state repair;
- multi-user host isolation or remote provider reconciliation.

The absence of those production concerns keeps this evidence disposable. It
also means the operational result must not be read as the cost of a shippable
daemon.
