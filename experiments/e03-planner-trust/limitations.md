# E03 limitations and threats to validity

- The native candidate ran on one Apple M5 Max host with macOS 26.5.2. Its
  frozen Seatbelt profile failed even the benign positive control, so the
  experiment makes no native denial claim from the later cases.
- Darwin did not accept the frozen 256 MiB address-space rlimit. Wall time,
  CPU, file-descriptor, and captured-output limits do not substitute for a hard
  memory ceiling.
- The pooled candidate used Docker 29.2.1 through a local Colima Linux VM. It
  proves only the recorded image digest and runtime controls, not every Docker
  host or production container policy.
- Docker supplied a default `HOME` to the planner process. The accepted evidence
  preserves this as a trusted-local limitation; the threshold was not relaxed
  and the result was not selectively rerun.
- No helper VM endpoint was available. Presence of Lima tooling did not count as
  evidence, and no instance was created.
- Loopback and Unix-socket probes targeted only listeners created by the local
  harness. No public network or unrelated local service was contacted.
- Resource probes demonstrate the observed outer bounds, not resistance to
  kernel, runtime, or container-engine vulnerabilities.
- The static descriptor uses the frozen W1 plan. It does not demonstrate
  arbitrary runtime-dependent graph construction or every future Taskflow
  value type.
- Python 3.9 is the sole independent policy reader in this experiment.
- Two incomplete setup attempts preceded the first complete candidate set. The
  first complete set was then invalidated wholesale because the native trusted
  launcher exited before the probe. The accepted set is the single permitted
  full corrected rerun; no individual sample or candidate result was replaced.
- The benchmark measures one host under light local load. It is a provisional
  Risk Lab result, not a product latency promise.
