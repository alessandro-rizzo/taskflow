# Candidate C limitations

- Schema identity depends on runtime reflection over Go function signatures and
  struct tags.
- Renames and tag edits are only diagnosed when discovery runs.
- The fake W1 trace proves typed composition shape, not executable plan IR.
- Discovery is not a hostile-code sandbox and execution is deliberately fake.
- Passing this comparator would not make reflection an acceptable sole source
  of stable protocol identity; the committed E01 contract requires redesign if
  only C works.
