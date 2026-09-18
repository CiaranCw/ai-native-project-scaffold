# Develop

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `develop`
- `skill_version`: `2.1.0`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: `normal_task`, `repair`

This package provides `develop.implement`, `develop.repair`, and the additive
`develop.task_intake` prelude of Develop `normal_task`. Task Intake is not a
third mode or a fifth Skill. Skill results report `skill_id: develop`,
`mode: normal_task`, and `extras.operation: task_intake`. That selected mode
does not mean implementation ran. Intake can publish bounded canonical Task
authority, but never a Develop Session, source mutation, Test result, Commit,
Push, or Submit authorization. Repair is a Develop mode, not a fifth Skill,
not Test, and not Submit. Bounded migration apply is Task-bound
supporting work, not a fifth mode and not Adoption. Full Plan+Task
machine binding is proven before Session/Task mutation. A preview without that
binding does not advance Task or Session state. Physical `project.yaml`
mutation is not Migration completion; post-validation must be `EXACT` or
`COMPATIBLE`, and that post-state is the current compatibility result.
Interrupted apply conforms to P5 `RECOVERY_REQUIRED` recovery, not a
parallel P7 state machine.

Develop owns task-driven implementation, Task Book progress updates, Develop Sessions, normal task execution, Repair, handoff to Test, and the P3 `IN_PROGRESS` → `READY_FOR_REVIEW` transition. Canonical Task Book writes use expected-revision conditional publication. Stage `IN_PROGRESS` → `COMPLETE` and Task READY use FA2-FND-002 candidate-bound Stage/Task Completion Decisions plus current P6 Evidence; `TEST_PASS` alone never causes either transition. A `READY_FOR_REVIEW` Task is reopened only by a current Stage-targeted `submit_to_develop` handoff. Ordinary intake does not silently reopen a Task already in `READY_FOR_REVIEW`. An explicit no-source-write `refresh_ready_authority` may refresh candidate-stale SATISFIED completion decisions from a current published P6 report without reopening the Task.

Develop MUST NOT invent a Task Book from caller prose, treat `TEST_PASS` as `TASK_COMPLETE` or `READY_FOR_REVIEW`, manufacture S10 apply-intent, finalize a Change Record, Commit, Push, or Refresh. Develop does not invent Migration Plans or rewrite `skills.lock`. Fresh persistent Migration application MUST be initiated as Task-bound work only when machine bindings name that Plan plus the current Task identity, revision, and candidate before durable Develop mutation. Title/goal keywords are not that binding. Understand Plan-only preview is not that authority. A preview that still needs exact Plan+Task binding does not advance Task/Session state. That is not Adoption and not a fifth Skill.

## task_intake prelude

Task Intake is the bounded prelude of Develop `normal_task`. It accepts
Agent-interpreted structured intent plus a bounded Task proposal grounded in
current human intent, project knowledge, Rules, ownership, and repository
currentness. Raw prose never becomes Task authority. Ambiguity, scope
expansion, inferred product decisions, governance choices, or Rule conflicts
require human resolution. A clear explicit implementation request may publish a
fully grounded proposal directly as `IN_PROGRESS`; otherwise an honest grounded
proposal may remain `DRAFT`.

Intake Skill results therefore report `mode: normal_task` with
`extras.operation: task_intake`. They do not bind a Session, mutate source,
invoke Test, authorize Submit, Commit, or Push.

Initial revision-1 publication is atomic and non-overwriting. Matching Tasks
are status-aware: reuse `IN_PROGRESS`; activate `DRAFT` only through current
grounded intent and expected revision; never reopen `READY_FOR_REVIEW` or
resurrect `CANCELED`. Multiple matches are a conflict. Proposal identity is
derived from canonical Task semantics, including optional FND3
`execution_binding` on planned tests, without adding a Task Book field or
persisting caller prose. A `requirement_id`-only test remains valid and does
not invent a profile binding. Unbound requirement identities are not looked up
in `tests.yaml`. Only an explicit `execution_binding.profile_id` must exist
among current Test profiles. Malformed explicit `execution_binding` fails
closed.

## normal_task

Resolve an authoritative existing Task Book task. Before any mutation, establish
usable SCM/candidate truth and D1 currentness from local configured-upstream
refs. `CURRENT`, local `AHEAD`, and legitimate `NOT_CONFIGURED` local-only Git
may continue; `STALE`, `DIVERGED`, and configured-upstream `UNKNOWN` block.
Do not fetch, pull, merge, rebase, reset, or checkout. Bind a Develop Session
to the current project, task, mode, and workspace/candidate context. Load
applicable global/module/path/test Project Rules and resolve the path through
the project ownership registry. Test-specific Rules follow the Task's declared
test identifiers even when the caller omits `selected`. A current Task-scoped
instruction may authorize HUMAN_OWNED ordinary project content when the
Task requires it, including tests, docs, configuration, and equivalent
paths. It does not override a hard Rule or protected Scaffold governance
boundary. Invoke Test only through its
public boundary with a bounded handoff, or consume an already published durable
P6 `report_id`. Caller report dictionaries are not Test authority. The two
paths are mutually exclusive.

## repair

Correct a candidate after a bounded Test/Submit failure or blocker handoff. Remain inside Develop `repair`. A material source edit creates a new candidate reality. Previous candidate-bound Test evidence cannot transfer.

Details: [references/modes.md](references/modes.md).
