# P7 Develop — concrete implementation notes

This document records P7-owned concrete schemas and runtime boundaries. It is not a Foundation Contract and does not outrank P0–P6.

P7 status: **ACTIVE / IMPLEMENTATION**. Not COMPLETE, BASELINED, or PASS. P5 and P6 remain **CLOSED / BASELINED / REMOTELY PUBLISHED**. P8 is not started.

## Role and boundaries

Develop is the task-driven implementation Skill. It:

1. performs a read-only Host Compatibility Preflight for the actual Develop package;
2. applies an observational host lifecycle / maintenance execution gate;
3. resolves an authoritative existing Task Book;
4. binds a local Develop Session to project, task, mode, and observed candidate;
5. applies ownership-scoped source mutations;
6. optionally invokes published P6 Test through a bounded handoff;
7. persists `IN_PROGRESS` → `READY_FOR_REVIEW` only when every P3 §11 gate holds and the transition is requested explicitly, then emits a bounded Develop→Submit route.

Develop does **not** invent tasks from caller prose, treat `TEST_PASS` as `TASK_COMPLETE` or `READY_FOR_REVIEW`, manufacture `SUBMIT_AUTHORIZED`, finalize Change Records, Commit, Push, Refresh, or Migrate. Repair is a Develop mode, not a fifth Skill.

Isolated Git worktrees are P9, not a P7 Rev0 requirement.

## Skill package identity

| Field | Value |
| --- | --- |
| `skill_id` | `develop` |
| `skill_version` | `2.0.0` |
| modes | `normal_task`, `repair` |
| `provides` | `develop.implement`, `develop.repair` |
| `requires` | `[]` |
| `entry` | `SKILL.md` |
| `package_format_version` | `1` |

`requires` remains empty in the live package. Test is invoked through the published `TestEngine` boundary, not as a lock-granted permission. The P4 illustrative `test.execution` requirement is example data, not release data.

## Flow

```text
intake (DevelopEngine.run)
→ mode gate (normal_task | repair only)
→ inspect_host_project
→ host lifecycle / maintenance gate
→ Develop package / lock Host Compatibility
→ resolve Task Book (identity + fail-closed schema + mode compatibility)
→ repair binding (task + current candidate + failure/blocker)
→ authorize writes (schema-validated scope + ownership + core artifacts)
→ bind or create Develop Session
→ first expected-revision Task publication (session link + optional first-stage progress)
→ apply ownership-scoped source mutations only after that publication succeeds
→ optional bounded Develop→Test via TestEngine.run
→ TEST_PASS does not complete the Task or mark READY_FOR_REVIEW
→ explicit P3 §11 request may publish READY_FOR_REVIEW as a second expected-revision publication
→ after successful READY publication, re-observe the current candidate and emit submit route
→ SEALED on success; ABORTED if a started Session later blocks
```

## Host lifecycle and maintenance execution gate

Ordinary Develop requires a coherent Scaffold-managed host. All checks are observational. No P7 preflight path creates persistent project or lock mutations.

Implemented in `evaluate_host_execution_gate()` / `evaluate_develop_preflight()` (`src/scaffold_p7/preflight.py`).

| Host condition | Route |
| --- | --- |
| NOT_ADOPTED / missing project.yaml | `understand.bootstrap` |
| ADOPTING | `understand.bootstrap` |
| RECOVERY_REQUIRED | P5 `snapshot_host` recovery evidence |
| ACTIVE + NEEDS_REFRESH | `understand.refresh` |
| ACTIVE + NEEDS_MIGRATION | `understand.compatibility` |
| present but invalid project.yaml | `understand.refresh` |
| INVALID / unresolved Develop package | `understand.compatibility` |
| lock mismatch / UNKNOWN / INCOMPATIBLE | `understand.compatibility` |

Execute only `EXACT` or `COMPATIBLE`. Compatibility results remain the P4 five.

## Task Book authority

Canonical path: `.scaffold/tasks/<task-id>.yaml`.

P3 frozen Task statuses: `DRAFT` | `IN_PROGRESS` | `READY_FOR_REVIEW` | `CANCELED`.

P3 frozen Stage statuses: `PENDING` | `IN_PROGRESS` | `BLOCKED` | `COMPLETE`.

```text
TASK_COMPLETE = all required Task stages are COMPLETE
```

`TASK_COMPLETE` is derived and is not a fifth stored status.

P7 accepts Develop execution only for `IN_PROGRESS`. It does not silently accept a `DRAFT` as the active plan and does not silently reopen `READY_FOR_REVIEW` or `CANCELED`.

Caller prose cannot replace or invent a Task Book.

Consumed inner fields fail closed as real lists/mappings before use: `scope.paths` / `scope.modules` / `scope.exclude`, `develop_session_ids`, `stages[*].required_tests`, and `final_tests`. A mapping such as `scope.paths: {src/app.py: false}` is malformed authority, not a path list.

Every canonical Task Book publication uses the P3 §31 rule: expected revision N plus per-record serialized conditional publication, producing exactly N+1. Session-link and first-stage progress are one in-memory mutation and one publication. `IN_PROGRESS` → `READY_FOR_REVIEW` is a second publication that must use the revision current after the first successful write. A revision conflict does not overwrite the newer Task, does not merge writers, and does not retry the stale in-memory mutation. A first-publication conflict occurs before source writes and aborts the started Session. A late READY conflict does not persist `READY_FOR_REVIEW` and does not emit a Develop→Submit route; already-applied source work is not rolled back.

Develop persists `IN_PROGRESS` → `READY_FOR_REVIEW` only when P3 §11 holds (all required stages `COMPLETE`, planned final tests accepted, declared Task-level acceptance present) and the caller requests that transition. `TEST_PASS` alone never persists it. After a successful READY publication, Develop re-observes the current candidate, binds that digest on the Develop→Submit route and SkillResult, and stops. Pre-READY Test evidence keeps its original candidate binding and is not relabeled. P8 is not implemented.

## Develop Session

Canonical path: `.scaffold/runtime/develop-sessions/<dev-id>/`.

Local, temporary, advisory. Session states: `OPEN` → `SEALED` or `OPEN` → `ABORTED`. No `SUBMITTED`.

IDs use the P3 family: `dev-<UTC compact>-<8 hex>`.

Session-S0/S1 overlays are compact dirty-path observations where the host can honestly observe them. `files.yaml` records only Develop-touched paths. Repository / candidate truth overrides Session memory.

P3 does not define an elaborate Develop Session recovery lifecycle. Loading an existing Session fail-closes unless `session.yaml` carries usable task, mode, project, baseline, Session-S0 overlay, and observed candidate binding, and unless `files.yaml` exists and is structurally valid. An OPEN Session bound to candidate A cannot resume on a materially different candidate B. Unsuccessful started Sessions terminate as `ABORTED`. It does not invent extra session states.

## Mutation authority

Ownership modes remain `GENERATED` | `MANAGED` | `HUMAN_OWNED`.

P7 reuses P5 `whole_file_mutation_allowed()`. HUMAN_OWNED whole-file overwrite is blocked. MANAGED whole-file overwrite without a bounded region is blocked. Missing ownership is UNKNOWN and blocked. Core machine artifacts are CONFLICTING and blocked for ordinary Develop.

There is no “Develop can write any project file” escape hatch.

## Handoffs

Develop→Test carries only: test requirement, task identity, session identity, candidate digest, and Test mode `scoped_verification`.

Test is invoked through `scaffold_p6.engine.TestEngine.run`. P7 does not import P6 preflight, evidence, or adapter internals.

Test→Develop may enter `repair` only when the handoff is bound to the current Task and the current candidate and is a genuine failure/blocker. Missing or stale candidate binding cannot authorize Repair. After a material Repair edit, previous candidate-bound Test evidence is stale.

Develop→Submit is a route payload only after a legitimate `READY_FOR_REVIEW` publication. Its `candidate_digest` is the post-READY observation, not a pre-persist snapshot. P8 is not implemented. A Skill result never reports `mutations: none` if source or the canonical Task Book actually changed.

## Candidate binding

P7 observes candidate identity through the published P6 boundary: `observe_candidate` / `report_usable_for`. Task Book files are candidate-visible, so a successful READY publication can change current candidate identity. The Skill re-observes after that publication. A publication conflict also re-observes before the blocked Skill result so the returned Task and candidate describe the same current project state. A competing writer's Task mutation is not attributed to this invocation. A material source mutation also changes candidate identity. Pre-READY Test evidence remains bound to the candidate it actually tested and is not rewritten as evidence for the post-READY candidate. A Session digest cannot override workspace/SCM truth.

## Safety

P7 tests are ordinary local deterministic fixtures. No network, adversarial, security, or path-escape families.
