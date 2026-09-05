# E06 VM terminal smoke evidence

This directory retains the sanitized, allowlisted evidence needed to audit the
three approved VM smoke attempts. The complete live evidence directories were
kept unchanged until this bundle was produced. They are represented by exact
file counts, allocated sizes, and deterministic hashes of their sorted file
hash records.

The retained subset includes approval, failure, bounded clone cleanup, immutable
base-integrity, and decisive launch/signing records. Simulator device IDs and
user-directory names are redacted. Large repetitive build logs, the 161 GiB
Tart image/cache, host identifiers, and credentials are not committed.

The complete 23-file setup/acquisition/preflight receipt directory is also
retained in sanitized form. It includes the original cleanup authorization,
image/controller acquisition receipts, guest identity and security limitations,
the preflight DHCP baseline, and the experiment-owned helper inventory.

This is negative feasibility evidence, not benchmark evidence. All three
attempts contain zero benchmark samples. Attempt three stopped before simulator
creation because the credential-free ad-hoc signature did not embed the
intermediate application identifier. The full measurement matrix was therefore
not run and its frozen 3 s and 15 s thresholds were not relaxed.

Verify from this directory with:

```sh
task check
```

`scripts/materialize_smoke_evidence.py` reproduces the retained subset while the
three source directories remain present. It refuses to overwrite evidence and
checks every source digest before copying. `scripts/update_checksums.py` is a
deliberate maintenance command; run it only when reviewing an intentional
evidence or decision change.

End-of-experiment cleanup completed on 2026-09-05 after verifying that every
owned VM was stopped and the host `bootpd` preference had already returned to
its originally absent state. The exact task root and two small temporary
evidence workspaces were removed. `cleanup-result.json` records 81.9 GiB of
filesystem-level space reclaimed; this is lower than the root's allocated-size
reading because the Tart image and clone shared APFS blocks.
