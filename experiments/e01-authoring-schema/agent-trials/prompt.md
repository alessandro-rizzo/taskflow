You are independently testing whether an agent can use a Taskflow operation
schema without reading implementation source.

Work only with files in your current sealed directory. Do not inspect parent
directories, repository paths, hidden user configuration, memories, or the
internet. The directory contains schema JSON, interface help, an invalid W1
argument object, and a compiled fake `taskflow-e01` interface. It deliberately
contains no candidate source.

Complete all three tasks using shell commands:

1. Identify the W3 operation ID, every typed output (ID, type, optional flag),
   and every required capability from the schema.
2. Diagnose `invalid-w1-args.json`, create `repaired-w1-args.json`, and prove it
   valid with the interface. Preserve the successful command.
3. Invoke W1 through the fake interface using the repaired arguments, save the
   exact JSON response as `invocation-result.json`, and report its typed
   outputs. Preserve the successful command.

Return only the JSON shape required by `response-schema.json`. Set
`source_read_attempted` true if you attempted any read outside the sealed
directory, even if it was blocked.
