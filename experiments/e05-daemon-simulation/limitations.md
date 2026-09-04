# E05 Phase B limitations

- Scheduler ticks and provider capacities are deterministic models. They do
  not measure real builds, macOS hosts, simulators, devices, networks, or API
  rate limits.
- SQLite crash cases prove the visibility boundary of transactions whose
  commit returned across abrupt process death. They do not prove hardware
  power-loss durability, filesystem guarantees, or a production schema/API.
- The Python controller's startup, RSS, CPU, and stop measurements are local
  operational proxies. They do not prove packaging, launch-agent behaviour,
  authenticated RPC, upgrades, migrations, or service observability.
- Namespace and lease ownership partially exercise AGENT-4 only. Filesystem,
  endpoint, port, service, volume, and mutable-data isolation are not tested.
- Attachment authorization is a state-machine case table, not an identity
  provider or security boundary. The experiment makes no AGENT-6 claim.
- The workload binds W1/W2/W3 and lifecycle fixtures by digest but neither
  imports nor executes them. No production Go module or public package is
  created before Gate 1.
