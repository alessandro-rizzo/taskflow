# E02 Phase B evidence summary

Decision: **continue-canonical-json** as Gate 1 input; no production protocol is selected.

- w1-plan: median 6.560 ms, p95 10.366 ms (30 samples).
- large-generation-canonicalization: median 185.641 ms, p95 189.869 ms (15 samples).
- large-reader-validation-digest: median 204.434 ms, p95 208.509 ms (15 samples).
- Large graph: 10000 nodes, 3370219 canonical bytes.

All bound T1 plans matched with zero structural differences; 20-process determinism, Go/Python byte identity, eleven reorder paths, four semantic mutations, strict rejection, shape, and sentinel gates passed.

Limitations: Candidate B does not produce its optional diagnostics value; E02 therefore treats it as schema-only and uses the synthetic plan for optional-artifact evidence. Formats remain experimental and disposable until Gate 1.
