# Develop

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `develop`
- `skill_version`: `2.0.0`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: `normal_task`, `repair`

This package provides `develop.implement` and `develop.repair`. Repair is a Develop mode, not a fifth Skill, not Migration, not Test, and not Submit.

Develop owns task-driven implementation, Task Book progress updates, Develop Sessions, normal task execution, Repair, handoff to Test, and the P3 `IN_PROGRESS` → `READY_FOR_REVIEW` transition. Canonical Task Book writes use expected-revision conditional publication. When every P3 §11 gate holds and the transition is requested explicitly, Develop publishes `READY_FOR_REVIEW` once, re-observes the current candidate, and emits a bounded Develop→Submit route bound to that post-READY candidate. `TEST_PASS` alone never causes that transition. Ordinary intake does not silently reopen a Task already in `READY_FOR_REVIEW`.

Develop MUST NOT invent a Task Book from caller prose, treat `TEST_PASS` as `TASK_COMPLETE` or `READY_FOR_REVIEW`, manufacture `SUBMIT_AUTHORIZED`, finalize a Change Record, Commit, Push, Refresh, or Migrate.

## normal_task

Resolve an authoritative existing Task Book task. Bind a Develop Session to the current project, task, mode, and workspace/candidate context. Apply only ownership-scoped source mutations. Invoke Test only through its public boundary with a bounded handoff.

## repair

Correct a candidate after a bounded Test/Submit failure or blocker handoff. Remain inside Develop `repair`. A material source edit creates a new candidate reality. Previous candidate-bound Test evidence cannot transfer.

Details: [references/modes.md](references/modes.md).
