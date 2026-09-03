# E01 blinded agent trials

Roadmap experiment: E01. Task: TF-003.07.

Two fresh, ephemeral Codex CLI sessions receive identical copies of one sealed
bundle. The bundle contains the canonically shared W1-W3/effect schemas,
invalid W1 arguments, invocation help, a response schema, and a compiled fake
interface. It contains no candidate source, generated source, repository
documentation, or unrestricted repository path.

The trial runner wraps each session in a retained macOS Seatbelt profile which
denies reads and writes to the primary Taskflow checkout, every worktree known
when the trial starts, and Codex memory. A preflight proves those denials and
proves the sealed interface remains readable and executable. Sessions run
sequentially so they cannot share mutable bundle state.

This trial evaluates the shared schema and invocation help, not relative
candidate UX: the four candidate schemas are canonically identical.
