# Develop modes

Exactly two modes are declared for Develop `2.0.0`.

## normal_task

Implement an authoritative Task Book task.

1. Perform the observational host / package execution gate. Execute only on a coherent ACTIVE host with EXACT or COMPATIBLE Develop identity.
2. Resolve the Task Book by identity. Do not invent a task from caller prose.
3. Accept only `IN_PROGRESS` tasks. `DRAFT`, `READY_FOR_REVIEW`, and `CANCELED` are incompatible unless a later contract explicitly reopens them.
4. Open a Develop Session bound to project, task, mode, and observed candidate. Session memory is advisory.
5. Mutate only paths inside declared task scope with known GENERATED (or explicitly bounded MANAGED) ownership. Core machine artifacts and HUMAN_OWNED whole-file overwrite remain blocked.
6. Optionally hand off a bounded Develop→Test payload to the published Test Skill.
7. `TEST_PASS` updates no Task completion state by itself. Develop publishes `READY_FOR_REVIEW` only when P3 §11 holds and the transition is requested explicitly. That write is a second expected-revision publication. After it succeeds, Develop re-observes the current candidate and emits a bounded Develop→Submit route bound to that candidate.

## repair

Correct a candidate after a bounded Test/Submit failure or blocker.

1. Use the same host / package gate as `normal_task`.
2. Remain `skill_id: develop` with `mode: repair`.
3. Require failure/blocker context. Do not treat a passing Test result as repair authority.
4. Apply the same mutation authority rules. Do not Commit, Push, Submit, Refresh, or Migrate.
5. After a material edit, stale candidate-bound Test evidence is unusable for the new candidate.
