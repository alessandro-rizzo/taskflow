# E05 Phase B evidence

Phase A is the immutable contract commit `fbf1fbe`. Its README and complete
digest envelope intentionally remain a historical Phase A snapshot. The live
Phase B verifier materializes that commit and its bound fixtures in a temporary
repository, runs the original verifier there, and separately proves that the
live decision inputs remain byte-identical to the commit.

Phase B implements six deterministic scheduling modes over the frozen 1-, 4-,
and 20-agent scales and all 30 seeds. Eighteen compressed JSONL files retain
normalized state/resource traces. The safe independent provider guard, not the
unsafe negative control, is the material-benefit comparator.

The SQLite adapter couples state, event sequence, resource use, and cleanup in
one `WAL`/`synchronous=FULL` transaction. Sixty new child processes die
abruptly before or after admission, execution, or cleanup commits. Recovery
then checks visibility, sequence, integrity, and capacity.

Operational evidence includes 30 real disconnect/reaper samples, 30 seconds
of quiescent controller self-measurement, a T1 benchmark-v2 record for 30 warm
fresh-process reopens, incompatible-schema fail-closed behaviour, and a
backup/restore rehearsal. See `limitations.md` before interpreting these
simulator-proxy figures.

The reproducible verification command is:

```sh
mise exec -- task --dir experiments/e05-daemon-simulation check
```

The selected recommendation and its frozen-gate inputs are in `decision.md`
and `results/scorecard.json`.
