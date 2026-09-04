# E03 evidence summary

Contract commit: `b8039d4dc48410c43dec7702ff88086714327b2e`.

Selected branch: **static-descriptor**.

- Native: unavailable after the frozen Seatbelt profile failed its benign positive control; Darwin RLIMIT_AS is unsupported.
- Pooled container: 17 blocked, 7 bounded, 1 trusted-local limitation (`HOME` was ambient); not eligible.
- Helper VM: unavailable; no endpoint existed and no VM was created.
- Static descriptor: 25 project-code cases blocked by no execution; validator 19/19 negative cases passed and known-good W1 was accepted.
- Warm static planning: median 109.754 ms, p95 118.060 ms across 30 serial samples; threshold p95 < 250 ms.
- Hard-gate counters: all zero.

Verification: `python3 experiments/e03-planner-trust/scripts/verify_phase_b.py`.
