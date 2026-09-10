# P9 Repair / Migration — implementation notes

This note records the compressed P9 Repair/Migration capability. It is not a
Foundation Contract and does not outrank P0–P8.

P9 status: **PASS / CLOSED.** Authoritative global regression was 1126/1126 PASS.
P9 does not start DIVE or v2.0. P10 consumes Repair/Migration recovery surfaces
and must not reopen P9 absent a deterministic P10 regression. FA-2 remains
independently PASS / CLOSED.

Repair is a Develop **mode**, not a fifth Skill. Migration is not Adoption
and is not a fourth canonical development record.

## Role

P9 makes a scaffold-aware project recoverable after a failed or incomplete
development state, and able to continue under current project-local truth.

Two bounded tracks:

1. **Repair** — reopen exact Stage(s), re-test, restore `READY_FOR_REVIEW`
   only with current Evidence and Completion Decisions.
2. **Migration** — when a VALID host is honestly `MIGRATION_REQUIRED`,
   represent, approve, apply, and revalidate a bounded contract-generation
   change instead of pretending compatibility or forcing re-bootstrap.

## Repair lifecycle

```text
READY / failed-current state
  → explicit repair request (task_id + target_stage_ids when READY)
  → CAS against current Task revision
  → target Stage(s) reopen; affected completion authority becomes UNKNOWN
  → Develop Session OPEN
  → source/project changes (new candidate if substantive)
  → Test (P6 Evidence)
  → new Stage Completion Decisions
  → new Task Completion Decision
  → READY_FOR_REVIEW only if Records §11 holds
```

READY repair requires `kind: submit_to_develop` and nonempty
`target_stage_ids`. Develop does not infer first, last, failed-by-name, or
all Stages. A missing or nonexistent target fails closed.

IN_PROGRESS Test→Develop repair may omit targets when mapping is unresolved;
the route is then `human`, not a guessed Stage.

Non-target Stages stay `COMPLETE` when still current. Downstream completion
is not mechanically reopened. If a candidate change makes a non-target
decision stale, READY still requires current `SATISFIED` authority — it is
not restored from C1.

## Test → Develop Repair handoff

Test remains the sole Test/Evidence authority. Repair consumes portable P6
report locators (`fail_ids` from report profiles), not a caller PASS/FAIL
dictionary.

Automated requirement→Stage mapping exists only for:

```text
execution_binding:
  kind: test_profile
  profile_id: <current Test profile>
```

Equal `requirement_id` and `profile_id` names do not create a mapping.

When mapping succeeds, `test_to_develop` carries `target_stage_ids` and
`next_route` is `develop.repair`. When it does not, `target_mapping` is
`unresolved` and the route is `human`.

## Fresh-agent recovery

Supporting Repair state lives at:

```text
.scaffold/runtime/repair-state/<task-id>.yaml
```

This is runtime supporting state, not a fourth canonical record. A later
process reconstructs from Task Book + this file + current candidate:

- which Task is being repaired;
- which Stage(s) were requested;
- why (blockers / Evidence locators);
- current candidate;
- which completion decisions are UNKNOWN/superseded;
- whether READY is currently possible.

Do not rely on chat history.

## CAS / replay

Repair uses existing P7 expected-revision Task publication.

- stale expected revision → reject; no reopen
- concurrent READY reopens against the same revision → at most one
  authoritative mutation
- replaying an already-consumed reopen (same targets, Stages already
  IN_PROGRESS with UNKNOWN repair-reopen decisions) → no new Session and
  no second reopen

## Migration vs Adoption

Adoption (Understand bootstrap B1–B9) attaches an ordinary/non-normalized
project.

Migration applies only to an already scaffold-aware **VALID** host whose
compatibility evaluation is `MIGRATION_REQUIRED`. INVALID is not a
compatibility state and must not be reported as migration.

`EXACT` and `COMPATIBLE` do not force migration. A version difference with
an explicit `may_substitute_for` relationship is `COMPATIBLE`, not
migration, and does not rewrite `skills.lock`.

Understand still owns compatibility evaluation, Migration Plan
construction, Migration Execution lifecycle, checkpoints, recovery, and
post-migration validation. Fresh persistent Migration application MUST
be initiated through Task-bound Develop work
(`execute_approved_migration`) that calls that P5 authority. Understand
compatibility may plan and route; it MUST NOT start a fresh persistent
apply from Plan-only approval. That is not a fifth mode, not Understand
Adoption, and not a second Migration state machine.

Develop application approval is not Plan-digest-only. Full application
authority is established **before** any durable Develop mutation
(Session creation, Task Book publication, `project.yaml` write, or
Migration Execution creation):

```text
approved + plan_id + plan_digest + task_id + task_revision + candidate_digest
```

A request that only needs human approval (`NEEDS_HUMAN` preview) does
not advance Task revision, Stage status, or Session linkage. Invalid
Plan identity/digest or Task binding is rejected the same way, with
Task/session/project bytes unchanged.

A Plan approval issued for Task A is not reusable through Task B. Stale
Task revision or candidate digest requires re-review. Task title/goal
keywords such as "migration" are not authority. The supporting Migration
Execution may record `develop_binding` (`task_id`, `task_revision`,
optional Develop Session id, `candidate_digest`) so a later process can
inspect the Task that owns the execution. That field does not create a
fourth canonical record. A later Task cannot silently take over another
Task's Execution; resume remains Understand/P5 recovery.

Immediately before P5 apply, Develop rebuilds the current Plan and
requires the same `plan_id`/`digest` as the approved Plan. Silent plan
substitution is blocked.

The mutation envelope remains `.scaffold/project.yaml` contract generation.
`skills.lock` is not rewritten unless a current contract later authorizes
that exact change. This P9 path does not authorize lock rewrite.

## MIGRATION_REQUIRED lifecycle

```text
VALID host
  → compatibility evaluation = MIGRATION_REQUIRED
  → explicit causes (expected vs actual identity, why COMPATIBLE is insufficient)
  → Migration Plan (source, target, envelope, ownership, revalidation)
  → explicit Task / Stage
  → current Plan+Task application approval
  → Develop starts bounded project.yaml generation through P5
    PREPARED → APPLYING → VALIDATING → COMPLETED
    (interrupt after persistent mutation: VALIDATING or RECOVERY_REQUIRED)
  → compatibility re-evaluation (EXACT | COMPATIBLE | MIGRATION_REQUIRED | INCOMPATIBLE | UNKNOWN)
```

Physical apply is not Migration completion. Top-level Develop/Migration
results report successful completion only when post-migration validation
is `EXACT` or `COMPATIBLE`. The authoritative current compatibility field
is that post-migration result, not the pre-migration `MIGRATION_REQUIRED`
need. Pre-migration state remains inspectable as `pre_compatibility` /
`migration_need`. `MIGRATION_REQUIRED`, `INCOMPATIBLE`, and `UNKNOWN`
keep the Execution unfinished (`RECOVERY_REQUIRED`) and route to
compatibility/recovery resolution. P7 does not invent a parallel status
taxonomy.

After a persistent mutation is checkpointed, P7 must leave P5-valid
recovery state: completed prefix `CONTRACT_GENERATION_UPDATED`,
`observed_expected_state: VALIDATING`, and status `VALIDATING` or
`RECOVERY_REQUIRED` — never `APPLYING` with a completed validation
checkpoint. Intentional interruption uses `RECOVERY_REQUIRED` on both
the Execution and `project.yaml` lifecycle so a fresh Understand Agent
can resume without classifying the artifact as internally contradictory.
Ordinary Develop cannot bypass unresolved Migration recovery.

HUMAN_OWNED whole-file mutation is blocked. MANAGED whole-file mutation
without a bounded region is blocked. GENERATED `project.yaml` may follow
current generator/migration authority.

Pending/in-progress executions remain reconstructable from
`.scaffold/runtime/migration-executions/` (existing P5 operational artifact,
not a canonical development record).

## Ownership

Unchanged: `GENERATED` | `MANAGED` | `HUMAN_OWNED`. `project.yaml` remains
the canonical registry. Repair source writes follow existing Develop
mutation rules. Migration does not take whole-file authority over
HUMAN_OWNED content.

## DIVE-readiness fixture

`tests/test_p9_repair_migration.py` includes a small movement-smoke fixture:

Develop → Test FAIL → explicit Repair → source correction → Test PASS →
current completion decisions → `READY_FOR_REVIEW`, then a fresh-process
reconstruction that the Repair loop is complete.

It is a scaffold fixture, not the real DIVE pilot, and not
Scenario-Aware Verification.

## Versioning

Live candidate identities are unchanged:

- released `understand@2.0.0` (immutable fixture)
- working-tree `understand@2.1.0`, `develop@2.1.0`, `test@2.0.1`, `submit@2.1.0`

P9 adds supporting runtime and Develop-bound approved-migration execution
without a Skill version bump.

## Safety

P9 tests are ordinary local deterministic fixtures. No network, adversarial,
security, fuzz, or path-escape families.
