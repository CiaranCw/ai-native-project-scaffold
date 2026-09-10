# DIVE Pilot Scaffold Correction 02

Post-P10 real-pilot correction. This is **not** P11.

Historical status remains:

- FA-2: PASS / CLOSED
- P9: PASS / CLOSED
- P10: PASS / CLOSED
- POST-P10 DIVE PILOT CORRECTION 01: PASS / CLOSED

This note records three deterministic cross-Skill defects exposed by DIVE E2E
Submit. The DIVE repositories are evidence only and are not modified here.

## MAJ-005 — first-adoption `skills.lock` / first Submit deadlock

Bootstrap may lawfully create `.scaffold/skills.lock` before any Commit. First
Submit then observes that lock as untracked. S3 must not apply the generic
lock-change blocker when observational `skills_lock_review_authority` proves
**initial adoption lock creation**:

- baseline has no lock
- after state is newly added/untracked
- ownership resolves GENERATED
- current lock is `complete_authoritative`
- Understand is CURRENT and binds the exact current lock bytes
- Submit preflight is EXACT or COMPATIBLE
- host lifecycle is ACTIVE

The lock remains visible in S2 and in the candidate digest. Ordinary
modification or deletion of a tracked lock, malformed/incomplete locks, and
UNKNOWN/CONFLICTING ownership remain fail-closed.

## MAJ-006 — unresolved project identity vs Session identity

`project.yaml.name: ""` with a CONFLICTING `project_name` fact is lawful.
Develop no longer writes that empty product name into new Sessions. New
Sessions use the declared name when nonempty, otherwise the workspace /
project-root basename. That fallback does not rewrite discovery facts.

Historical sealed Sessions that stored `project_name: ""` remain
reconstructable. A missing or non-string `project_name` stays malformed.

## MAJ-007 — consume a published P6 report

Develop may bind Test authority from an already published durable P6
`report_id` without executing a new Test run. Caller report dicts, raw
evidence, `trusted=true`, and caller candidate digests are not authority.
`invoke_test` and `published_test_report_id` are mutually exclusive.

A READY Task may use the same published-report path as a no-source-write
revalidation: load the report, re-check READY gates, and emit the Submit
route without creating a Session or inventing completion.

Lawful `EXTERNAL_RESULT` / `CI_RESULT` / `HUMAN_OBSERVATION` provenance is
preserved. P6 remains sole Test/Evidence authority.

## Preservation

Exactly four Skills. Exactly three canonical development records. Submit
S1–S12. No S13. Unreleased candidates are not mechanically bumped:
`understand@2.1.0`, `develop@2.1.0`, `test@2.0.1`, `submit@2.1.0`.
