# DIVE Pilot Scaffold Correction 03

Post-P10 real-pilot correction. This is **not** P11.

Historical status remains:

- FA-2 / P9 / P10 / Correction 01 / Correction 02: PASS / CLOSED

This note records two coupled defects: SAV currentness bound to whole Task
`record_revision`, and the missing no-source-write path to refresh READY
completion authority after a candidate-significant control-plane update.

## MAJ-008 — Task verification-authority digest

`task_contract_digest` is the SHA-256 of the canonical YAML dump of
`task_contract_projection(task)`.

Included, with stable key order and sorted collections:

- `record_id`
- `scope.paths` / `scope.modules` / `scope.exclude`
- Task-level `acceptance`
- Test-relevant `constraints`
- each Stage `stage_id` and `acceptance`
- Stage `required_tests` and Task `final_tests` as
  `{requirement_id, execution_binding.kind, execution_binding.profile_id}`

Excluded:

- `record_revision`, `status`, Develop Session IDs
- Stage status
- Stage/Task Completion Decisions
- READY/control timestamps
- result-side Evidence locators and observed outcomes

New SAV plans persist `task_revision` (trace) and `task_contract_digest`
(currentness). Exact `record_revision` equality is not required when only
excluded lifecycle/result/control fields change. Substantive contract change
or bound `candidate_digest` mismatch still stales the plan.

Legacy plans without `task_contract_digest` keep strict `task_revision`
equality.

## MAJ-009 — READY completion-authority refresh

Develop `normal_task` with `refresh_ready_authority=true` and
`published_test_report_id` may refresh an already `READY_FOR_REVIEW` Task
whose SATISFIED decisions are stale only because they bind an old candidate.

It does not reopen Stages, does not create a Session, does not change
scope/requirements/acceptance, and does not Repair. It publishes new current
SATISFIED Stage/Task Completion Decisions and a new Task revision. Candidate
identity and `task_contract_digest` must remain unchanged after publication.
`ready_for_review_gates` must then PASS and `next_route` is `submit`.

The old DIVE lock-update Plan is stale if package identity changes and must
be regenerated after this candidate freezes. It is not applied here.
