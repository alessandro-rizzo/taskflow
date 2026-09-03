# Candidate D limitations

- It compares authoring and schema discovery only; execution and plan IR are
  fake.
- It adds a language toolchain and one locked checker dependency.
- The TypeScript compiler API printer supplies the counting normalization; it
  is deterministic but is not a general-purpose style formatter.
- Nominal artifact and endpoint safety requires explicit invariant phantom
  members because TypeScript otherwise uses structural typing.
- Passing D only authorizes the bounded second-SDK branch when Go A and B fail;
  it does not select a production SDK by itself.
