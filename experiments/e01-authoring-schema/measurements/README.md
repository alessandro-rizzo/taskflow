# E01 comparative measurements

Roadmap experiment: E01. Task: TF-003.07.

`protocol.json` freezes the execution order, samples, cache states, thresholds,
candidate bindings, rerun rule, and agent-trial rule before results are
collected. `protocol.sha256` binds that file and is also recorded in the ticket
before the first timing run.

The measurements use the T1 benchmark v2 runner. Candidates run serially, in
the deterministic order C, D, B, A, with separate paths below
`/tmp/taskflow-e01-tf00307`. Go candidates use separate `GOCACHE` roots.
Candidate D uses a separate Bun runtime-transpiler cache for discovery and
disables it for no-emit type checking; its locked package installation is not
included in timed samples.

Run from the repository root:

```sh
python3 experiments/e01-authoring-schema/measurements/scripts/verify_protocol.py
python3 experiments/e01-authoring-schema/measurements/scripts/run_benchmarks.py
```

The runner refuses to overwrite an existing result set. A failed sample set is
retained under `failures/`; rerunning it requires a dated amendment matching
the rule in `protocol.json`.

These measurements describe disposable candidates. They do not make the
provisional schema, SDK surface, generator, or runtime into a production
contract.
