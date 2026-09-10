# DIVE Pilot Scaffold Correction 05

Post-P10 real-pilot correction. This is **not** P11.

Historical status remains:

- FA-2 / P9 / P10 / Correction 01 / Correction 02 / Correction 03 / Correction 04: PASS / CLOSED

This note records DIVE-PILOT-SCF-MAJ-012: fresh Understand `refresh action=resume`
routed a historically `READY_FOR_REVIEW` Task back into Submit after that Task
had already been consumed by a valid Change Record plus proven S10 durability.

DIVE repositories are evidence only and are not modified here.

## MAJ-012 — post-S10 durable-finalized Task resume routing

Task Book intentionally has no `SUBMITTED` status. Correction 05 does not add
one, does not falsify Task status, and does not mutate or delete Task Books
during resume.

Canonical P8 Change Record / S10 durability helpers remain the only
finalization authority. P10/Understand resume consumes derived durability
truth; it is not a second Submit engine.

Derived sets:

```text
all_ready_task_ids
durably_finalized_task_ids   # proven S10 Change Record references only
continuable_ready_task_ids = all_ready_task_ids - durably_finalized_task_ids
```

Routing uses `continuable_ready_task_ids`, not raw READY Task Books.
Repair, required Test failure, and open Develop Session routes also ignore
supporting state bound only to a durably finalized Task. That leftover
state remains visible on the observational surfaces; it is not independent
unfinished work.

A Task is durably finalized only when a valid Change Record references its
`task_id` **and** the corresponding S10 durability is proven against current
P8 rules (Git history or no-SCM publication). Discovery therefore includes
live Change Record files, Git history under `.scaffold/changes/`, and
no-SCM publication identities. A missing live file is not enough to hide a
proven S10 record, and a broken live/history linkage fails closed. Insufficient:

- a merely present Change Record
- a non-durable / pre-S10 Change Record
- a malformed, UNKNOWN, or conflicting Change Record
- a Change Record that references another Task
- broken Commit / Change Record linkage

Those cases remain visible as blocker / recovery / UNKNOWN and do **not**
retire the READY Task from routing.

## Handoff

Fresh resume exposes the derived lists on `work` / `submit` so a new Agent can
see why a historical READY Task is not active. Per-task `durably_finalized`
and `continuable` flags are derived. Status remains `READY_FOR_REVIEW`.
