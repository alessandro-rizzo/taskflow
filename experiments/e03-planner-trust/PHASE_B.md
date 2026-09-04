# E03 Phase B execution

Phase B is bound to contract commit
`b8039d4dc48410c43dec7702ff88086714327b2e`. It implements a disposable Go
probe module, a trusted local supervisor, an independent Python validator, and
retained sanitized evidence. Nothing in this directory is a production API or
sandbox implementation.

The accepted run used only experiment-owned temporary files, synthetic marker
values, a loopback listener, an experiment-owned Unix socket, host Seatbelt,
and a locally built scratch container with networking disabled. No real secret,
external endpoint, remote image, provider credential, or VM was used.

## Reproduction

The exact attack and benchmark entry points remain the Phase A wrappers. A
reproduction must rebuild the local binaries, provide a fresh explicitly named
container that matches `policies/container.json`, and use a new output path;
retained evidence is never overwritten.

The retained result is verified without re-executing candidates:

```sh
python3 experiments/e03-planner-trust/scripts/verify_phase_b.py
```

The Docker container and image are experimental execution capacity, not
repository outputs. Their normalized identity and controls are recorded under
`evidence/availability/`.
