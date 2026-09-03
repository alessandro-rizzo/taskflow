# Candidate B: generated Go declarations

Run `task check`. B parses its own embedded Go declaration source with the
standard-library AST and formatter packages. Generation never reads fixtures,
goldens, the prototype, candidate A, or another candidate.
