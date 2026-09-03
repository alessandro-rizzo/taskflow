# Agent-trial setup amendment: strict response schema

Date: 2026-09-03

The first two Codex requests were rejected with HTTP 400 before inference
because `repaired_w1_arguments` omitted `additionalProperties: false`, which is
required by the structured-output API. Both JSONL failures, thread IDs, exit
codes, commands, timings, bundle digest, and access-control preflight are
retained under `setup-failures/2026-09-03-invalid-response-schema/`.

Neither request began agent work, accessed task files, issued a tool command,
or produced a response. They are setup failures, not the two independent E01
agent attempts.

Correction: make the nested object strict and declare only the two legal W1
argument properties. The prompt, schema documents, invalid input, fake
interface, Seatbelt policy, success criteria, and required count of two fresh
sessions remain unchanged. The corrected bundle receives a new digest and is
used identically for both counted attempts.
