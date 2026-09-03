# E01 measurement summary

Roadmap experiment: E01. Task: TF-003.07. Candidate source revision:
`ca87b81869b3b22630a3772da481d5088b0816ef`.

The frozen protocol digest is
`4b77693a513a4fe7d74500f52eae5fccd339af59666ec3773a60d6946e4a02c2`.
Candidates ran serially in the predeclared order C, D, B, A. No warm result
was within 10 ms of the 150 ms boundary, so no reverse-order run was permitted
or performed.

## Results

| Candidate | W1 LOC | Concepts | Warm discovery median | Warm discovery p95 | Budget | Cold discovery p95 | Cold build/type-check p95 | Warm build/type-check p95 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| A explicit Go | 31 | 4 | 6.56 ms | 10.81 ms | pass | 89.99 ms | 2,179.13 ms | 154.82 ms |
| B generated Go | 21 | 3 | 6.63 ms | 8.57 ms | pass | 127.79 ms | 2,465.05 ms | 194.75 ms |
| C reflection Go | 30 | 4 | 6.30 ms | 6.70 ms | pass | 92.94 ms | 2,132.65 ms | 296.70 ms |
| D TypeScript | 35 | 4 | 18.30 ms | 19.50 ms | pass | 19.03 ms | 377.95 ms | 340.55 ms |

The build/type-check and cold-discovery measurements are descriptive; the
predeclared pass threshold applies only to warm discovery. Candidate D's
no-emit semantic checker has no persistent incremental output, so its
cold/warm distinction records fresh versus pre-invoked processes with Bun's
runtime transpiler cache disabled.

All four candidates passed the common schema, typing, diagnostics,
determinism, body non-evaluation, isolation, and material-improvement gates.
Candidate B also passed stale-generated-output rejection and mapped malformed
metadata diagnostics back to authored declarations.

## Agent trial

Two fresh, sequential, ephemeral agents received identical copies of sealed
bundle `dbc05e5d86ecf0237bbc0c8102ea46b0f91685bee9918908b65c123300746261`.
Both identified the W3 operation/output/capabilities, repaired all three W1
argument faults, validated and invoked the fake interface, and reported the
typed W1 outputs. Seatbelt denied repository, worktree, and Codex-memory reads;
neither transcript contains a blocked source-read attempt.

Two pre-inference response-schema failures and two nested-sandbox setup
failures are retained separately and are not counted as agent attempts.

## Recommendation

Candidate B wins under the frozen rule. Relative to viable A, B reduces W1
authored LOC from 31 to 21 (32.3%) and concepts from four to three (25%). Both
clear the `floor(A * 0.85)` boundaries of 26 lines and three concepts. The
generator burden—seven annotation lines, 171 generator lines, 158 generated
lines, and one tag-reflection site—is acceptable as bounded E01 evidence
because stale output and source-mapped diagnostic gates pass. It is not a
production implementation or a stabilised generator contract.

## Limitations

- Results come from one macOS/arm64 machine and establish contract/budget
  conformance, not population-level latency.
- The pre-result protocol hash bound the candidates, states, order, sample
  counts, cache-isolation method, thresholds, and rerun rule. It did not
  separately bind the runner script bytes. Every accepted T1 record retains
  its exact timed and preparation commands, and all warm p95 values are more
  than 130 ms below the decision boundary, but a future experiment should
  hash its runner together with its protocol before sampling.
- Candidate D's non-incremental no-emit checker has no persistent compiler
  output; its cold/warm type-check sets mainly distinguish a fresh process from
  a just-preinvoked process with the runtime transpiler cache disabled.
- Two agent sessions establish basic usability for one model family and one
  sealed interface, not broad agent reliability or comparative authoring UX.
