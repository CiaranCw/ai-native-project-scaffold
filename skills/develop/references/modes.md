# Develop modes

Exactly two modes are declared for Develop `2.1.0`. Task Intake is the
bounded prelude of `normal_task`, not a third mode. Intake Skill results select
`mode: normal_task` and set `extras.operation: task_intake`.

## normal_task

Implement an authoritative Task Book task. Task Intake is the bounded prelude
of this mode: it may publish Task Book authority first, then ordinary
`normal_task` execution still requires an `IN_PROGRESS` Task, a Develop
Session, and the mutation gates below.

1. Perform the observational host / package execution gate. Execute only on a coherent ACTIVE host with EXACT or COMPATIBLE Develop identity.
2. Resolve the Task Book by identity. Do not invent a task from caller prose.
3. Accept `IN_PROGRESS` tasks for ordinary work. `DRAFT` and `CANCELED` remain incompatible. `READY_FOR_REVIEW` is incompatible with ordinary `normal_task` mutation. A narrow no-source-write revalidation may load a current published P6 `report_id` against an already READY Task and, if READY gates still hold, emit the Submit route without creating a Session or inventing completion. An explicit `refresh_ready_authority=true` plus `published_test_report_id` may refresh candidate-stale SATISFIED completion decisions on an already READY Task without source writes, Session creation, or reopening Stages; it publishes new current decisions and must leave `task_contract_digest` and candidate identity unchanged.
4. Establish usable candidate truth and D1 currentness from local SCM/tracking refs. Allow current, local-ahead, and no-configured-upstream repositories; block stale, diverged, configured-upstream UNKNOWN, or failed SCM observation. Never auto-sync.
5. Open a Develop Session bound to project, task, mode, and observed candidate. Session memory is advisory. `project.yaml.name` may be empty when product identity is CONFLICTING/UNKNOWN; new Sessions use that declared name when nonempty and otherwise a stable operational fallback (workspace/project-root basename). That fallback does not rewrite discovery facts. Historical Sessions that stored `project_name: ""` remain reconstructable; a missing or non-string field stays malformed.
6. Resolve ownership and applicable Project Rules before mutation. Test-specific Rules use Task-declared test identifiers plus any caller-selected ids. Task-scoped ordinary business source may use explicit HUMAN_OWNED source-area authority; GENERATED remains whole-file writable, and MANAGED requires a bounded region. Core machine artifacts, unresolved ownership, Rule conflicts, and applicable prohibitions remain blocked.
7. Optionally obtain Test authority through exactly one of: a bounded Develop→Test payload that executes a fresh Test run, or `published_test_report_id` that independently loads a durable P6 report. They are mutually exclusive. Caller report dicts, raw evidence, `trusted=true`, and caller candidate digests are not Test authority. The payload carries explicit Task `requirement_id`→Test `profile_id` execution bindings derived from current Task `execution_binding` authority. Test executes profiles; Develop attaches a locator to a requirement only when the P6-resolved producer profile equals that binding. Equal names do not create the association. Consuming a published report does not relabel lawful `EXTERNAL_RESULT` / `CI_RESULT` / `HUMAN_OBSERVATION` as `LOCAL_EXECUTION`.
8. `TEST_PASS` updates no Task completion state by itself. Develop publishes Stage `COMPLETE` only when the current Stage Completion Decision is `SATISFIED` for the actual candidate, required Stage tests satisfy defined acceptance via P6 Evidence, and no required-test blocker remains. It publishes `READY_FOR_REVIEW` only when Records §11 holds, including a current `SATISFIED` Task Completion Decision, and the transition is requested explicitly. Those writes are expected-revision publications. After READY succeeds, Develop re-observes the current candidate and emits a bounded Develop→Submit route bound to that candidate.

## repair

Correct a candidate after a bounded Test/Submit failure or blocker.

1. Use the same host / package gate as `normal_task`.
2. Remain `skill_id: develop` with `mode: repair`.
3. Require failure/blocker context. Do not treat a passing Test result as repair authority.
4. Apply the same mutation authority rules. Do not Commit, Push, Submit, or Refresh. Do not invent a Migration Plan or rewrite `skills.lock`. Approved Migration apply, when used, is Task-bound P5 work: full Plan+Task application approval before Session/Task mutation, truthful current EXACT/COMPATIBLE completion, and P5 recovery state after interruption.
5. After a material edit, stale candidate-bound Test evidence is unusable for the new candidate.
6. A `READY_FOR_REVIEW` Task may enter repair only through a current `submit_to_develop` handoff with nonempty `target_stage_ids`. Develop publishes READY→IN_PROGRESS and target COMPLETE→IN_PROGRESS in one Task CAS and replaces current Stage/Task completion authority with UNKNOWN repair-reopen decisions. P8 does not write the Task.
7. Persist supporting Repair recovery state under `.scaffold/runtime/repair-state/` so a later Agent can reconstruct the open Repair without chat history. This is not a fourth canonical record.
8. Automated Test-failure Stage mapping requires `execution_binding.kind: test_profile`. Name collision without that binding does not invent targets.
