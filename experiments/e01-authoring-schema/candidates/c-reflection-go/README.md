# Candidate C: reflection-heavy Go registration

Candidate C reflects typed function signatures and struct tags into the same
experimental schema as candidates A and B. Operation bodies are never called
during discovery or argument validation.

Run from this directory:

```sh
mise exec -- task check
```

This is disposable E01 evidence. It is not a production SDK or a recommendation
to use reflection as Taskflow's protocol identity source.
