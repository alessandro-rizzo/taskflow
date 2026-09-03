# Candidate A: explicit generic Go registration

Run `task check`. The command tests positive typing, compiles both negative
fixtures expecting failure, emits four schemas and the W1 trace ten times,
checks diagnostics and body sentinels, and retains outputs under `outputs/`
and evidence under `evidence/`.
