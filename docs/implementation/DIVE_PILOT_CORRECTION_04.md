# DIVE Pilot Scaffold Correction 04

Post-P10 real-pilot correction. This is **not** P11.

Historical status remains:

- FA-2 / P9 / P10 / Correction 01 / Correction 02 / Correction 03: PASS / CLOSED

This note records two coupled defects exposed by a real DIVE S9 blocker:
Adoption did not provision the P6 durable Evidence ownership area, and S9
persisted a candidate-significant Change Record before P6 materialization
succeeded.

DIVE repositories are evidence only and are not modified here.

## MAJ-010 — P6 durable Evidence ownership

The durable support-artifact root is `.scaffold/ext/test/evidence/`. Fresh
Adoption Plans now declare that **area** as `CREATE` / `GENERATED` in the
human-reviewed Plan and `ownership_presentation`. Bootstrap does not create
the directory and does not grant `.scaffold/ext/`.

Already-adopted hosts use Understand `compatibility` `action="ownership_update"`:

- plan-first, digest-bound, human-approved
- mutation envelope is `.scaffold/project.yaml` only
- adds only `.scaffold/ext/test/evidence/: GENERATED`
- requires ACTIVE executable `project.yaml`, UNKNOWN ownership for that path,
  and no HUMAN_OWNED / MANAGED / CONFLICTING or more-specific covering
  declaration

## MAJ-011 — S9 pre-durable atomicity

S9 now:

1. allocates `change_id` in memory
2. builds the Change Record in memory
3. PREPARE/materializes required P6 durable Evidence
4. persists the Change Record only after materialization succeeds
5. observes the finalization candidate
6. consumes the trusted S10 grant
7. executes S10

Ordinary failure before a durable S10 boundary aborts only artifacts created
by that attempt (P6 PREPARED coordination and, if present, the non-durable
Change Record). Git reset/restore/clean/stash are not used.

A stranded non-durable Change Record is recovered only through Submit
`abandon_pre_durable_change`: plan-first, exact approval, one `change_id`,
and only when S10 durability is proven absent. Durable Change Records cannot
be abandoned by this path.
