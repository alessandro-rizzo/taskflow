# Retained failed E07 evidence set 1

The live experiment and frozen thresholds passed, but the Phase B verifier
correctly rejected `benchmarks/fake-macos-relay/record.json`: scheduler noise
made some direct-subtracted relay deltas negative, while the bound T1 v2
benchmark schema permits only non-negative duration samples.

The mechanical correction leaves every threshold, sample count, order, and
decision rule unchanged. The rerun retains the signed difference in raw JSONL
and records `max(0, fake_macos_seconds - direct_seconds)` as non-negative
incremental overhead in the T1 duration record. Per the frozen failed-sample
policy, the entire first set is retained here and the complete workload is
restarted from sample one.
