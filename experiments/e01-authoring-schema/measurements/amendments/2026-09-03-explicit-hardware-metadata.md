# Measurement rerun amendment: explicit hardware metadata

Date: 2026-09-03

Affected set: primary Candidate C warm discovery, the first set in the frozen
order.

The 30 commands ran, but the T1 v2 validator rejected the record before writing
`record.json` or `samples.txt`: automatic RAM detection returned zero inside
the managed sandbox (`hardware.ram_gib: must be positive`). The failed command,
validator output, exit code, and elapsed wall time are retained in
`measurements/failures/primary-C-warm-discovery.log` and its JSON companion.

Correction: pass the current machine metadata explicitly to every T1 harness
invocation: Apple M5 Max, 18 cores, 64 GiB RAM, macOS 26.5.2 build 25F84,
arm64. `system_profiler SPHardwareDataType` and `sw_vers` supplied these values;
the retained records intentionally omit serial number and other unique device
identifiers.

No candidate, command under test, preparation command, cache state, sample
count, threshold, ordering rule, or decision rule changed. The full primary
sequence restarts from Candidate C under the permitted failed-sample rerun rule.
