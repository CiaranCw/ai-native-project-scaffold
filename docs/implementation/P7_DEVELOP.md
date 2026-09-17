# P7 Develop — concrete implementation notes

This document records P7-owned concrete schemas and runtime boundaries. It is not a Foundation Contract and does not outrank P0–P6.

P7 status: **CLOSED / BASELINED / REMOTELY PUBLISHED.** Implementation phase closed; later FA-2 corrections were applied in the current unreleased candidate. FA-2 is independently PASS / CLOSED. P9 Repair/Migration is ready for human review; see [P9_REPAIR_MIGRATION.md](P9_REPAIR_MIGRATION.md). This note does not claim P9 closed or v2.0 released.

## Role and boundaries

Develop is the task-driven implementation Skill. It:

1. performs a read-only Host Compatibility Preflight for the actual Develop package;
2. applies an observational host lifecycle / maintenance execution gate;
3. resolves an authoritative existing Task Book;
4. binds a local Develop Session to project, task, mode, and observed candidate;
5. applies ownership-scoped source mutations;
6. optionally invokes published P6 Test through a bounded handoff;
7. persists `IN_PROGRESS` → `READY_FOR_REVIEW` only when every P3 §11 gate holds and the transition is requested explicitly, then emits a bounded Develop→Submit route.

An already READY Task whose SATISFIED decisions are stale only because they bind an old candidate may use `refresh_ready_authority` plus a current published P6 `report_id` to publish new current decisions without source writes or a Session. `task_contract_digest` must remain unchanged.

Develop does **not** invent tasks from caller prose, treat `TEST_PASS` as `TASK_COMPLETE` or `READY_FOR_REVIEW`, manufacture `SUBMIT_AUTHORIZED`, finalize Change Records, Commit, Push, or Refresh. Repair is a Develop mode, not a fifth Skill. Develop does not invent Migration Plans or rewrite `skills.lock`. Fresh persistent Migration application MUST be initiated as Task-bound Develop work when the human approval binds that exact P5 Plan to the current Task identity, Task revision, and candidate digest **before** Session creation or Task publication; that is not Adoption. Understand may plan and recover; it does not start a fresh apply from Plan-only approval. Unrelated Tasks cannot carry another Task's approval. A no-approval preview is non-mutating. Post-apply `MIGRATION_REQUIRED` / `UNKNOWN` / `INCOMPATIBLE` is not successful Migration completion. Successful completion reports current post compatibility truthfully. Interrupted apply leaves P5-canonical `RECOVERY_REQUIRED` recovery state for Understand resume.

Isolated Git worktrees remain out of P9's compressed scope.

## Skill package identity

| Field | Value |
| --- | --- |
| `skill_id` | `develop` |
| `skill_version` | `2.1.0` |
| modes | `normal_task`, `repair` |
| `provides` | `develop.implement`, `develop.repair`, `develop.task_intake` |
| `requires` | `[]` |
| `entry` | `SKILL.md` |
| `package_format_version` | `1` |

`requires` remains empty in the live package. Test is invoked through the published `TestEngine` boundary, not as a lock-granted permission. The P4 illustrative `test.execution` requirement is example data, not release data.

`develop.task_intake` is an additive prelude of `normal_task`, not a third
mode. The two modes remain `normal_task` and `repair`; both retain their existing
Task-state rules. Task Intake Skill results report `mode: normal_task` and
`extras.operation: task_intake`. That selected mode does not mean
implementation, Session creation, Test, Submit, Commit, or Push occurred.

## Task Intake prelude

`DevelopEngine.intake()` accepts Agent-interpreted structured intent and a
bounded proposal. It never derives workflow authority from raw keywords and
never persists caller prose. Proposal identity is a digest of normalized
canonical Task semantics, including optional FND3 `execution_binding` on
planned Stage/final tests, and is compared with existing Tasks without adding a
Task Book field. Task Intake does not attach Evidence or execute Test.
Malformed explicit bindings fail closed; `requirement_id`-only tests remain
valid without inventing a profile association. Unbound requirement identities
are not looked up in `tests.yaml`. Only an explicit `execution_binding.profile_id`
must exist among current Test profiles.

Direct `IN_PROGRESS` publication requires an explicit implementation intent,
grounding for every material field, project/Rule/ownership/currentness
authority, and no uncertainty or inferred governance/product decision. A
grounded planning proposal may publish as `DRAFT`; ambiguity produces
`NEEDS_HUMAN` without a Task. Intake creates no Develop Session and performs no
source, Test, Submit, Commit, or Push operation. Intake does not transition
Stage merely to manufacture editor mutation authority.

Initial revision 1 is published atomically only if its identity is absent.
Matching Tasks are status-aware: `IN_PROGRESS` is reused; `DRAFT` activation
uses expected-revision publication; `READY_FOR_REVIEW` is surfaced without
reopening; `CANCELED` is surfaced without resurrection; multiple matches are a
conflict.

Version `2.1.0` is a MINOR additive capability. The existing generic
`may_substitute_for` declaration supports reproducible `COMPATIBLE` execution
against a `2.0.0` lock while surfacing actual `2.1.0` and leaving the lock
unchanged. No version-number-only compatibility rule is used.

Installed structured intake transport:

```text
python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>
python .scaffold/install/run.py develop intake --intake-json-b64 <envelope>
```

`--intake-json` is also accepted. These flags are valid only on those two
positionals.

## Develop execution window

After Task Intake, editor mutation still requires an explicit execution
Session. This remains Develop; it is not a fifth Skill.

```text
python .scaffold/install/run.py develop session --task-id <task-id>
python .scaffold/install/run.py develop seal --task-id <task-id>
python .scaffold/install/run.py develop abort --task-id <task-id>
```

Canonical sequence:

```text
business request
→ Develop intake (Task Book created / continued; no Session)
→ develop session (OPEN Session + mutable Stage)
→ in-scope editor mutation under current execution authority
→ develop seal or develop abort
→ no mutation authority remains
```

The current execution is identified by runtime control-plane binding
`.scaffold/runtime/develop-execution.yaml`. Multiple durable `IN_PROGRESS`
Tasks are legal. Unique current editor authority is that pointer, not a
raw OPEN Session and not Task count. A missing pointer, a pointer to a
missing/invalid/SEALED/ABORTED Session, or any number of pointerless OPEN
Sessions all DENY ordinary editor mutation. Deleting the pointer cannot
resurrect authority from leftover OPEN history. Explicit `develop session`
is the canonical rebind. `DevelopEngine.run` reuses that current OPEN
Session when present and seals it on successful completion; it does not
leak a second OPEN Session.

## Flow

```text
intake (DevelopEngine.intake)
→ Task Book created / continued
→ NO Develop Session
→ develop session (DevelopEngine.open_develop_session)
→ bind current execution pointer
→ first PENDING Stage becomes IN_PROGRESS
→ editor mutation uses authorize_path_mutation
→ develop seal / abort OR DevelopEngine.run completion seals
```

Ordinary `DevelopEngine.run` after a Task already exists:

```text
intake (if needed)
→ mode gate (normal_task | repair only)
→ inspect_host_project
→ host lifecycle / maintenance gate
→ Develop package / lock Host Compatibility
→ resolve Task Book (identity + fail-closed schema + mode compatibility)
→ D1 resolve SCM truth and configured-upstream currentness
→ repair binding (task + current candidate + failure/blocker)
→ authorize writes (schema-validated scope + ownership + core artifacts)
→ bind or reuse the current OPEN Develop Session
→ first expected-revision Task publication (session link + optional first-stage progress)
→ apply ownership-scoped source mutations only after that publication succeeds
→ optional Test authority via TestEngine.run **or** independently loaded published `report_id` (mutually exclusive; caller dicts are not authority)
→ persist portable P6 Evidence locators onto planned Task test refs
→ P7 may publish Stage IN_PROGRESS→COMPLETE when FA2-FND-002 holds
→ TEST_PASS does not complete the Task or mark READY_FOR_REVIEW
→ explicit Records §11 request may publish READY_FOR_REVIEW as a later expected-revision publication
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

P7 accepts ordinary Develop execution for `IN_PROGRESS`. It does not silently accept a `DRAFT` as the active plan and does not silently reopen `READY_FOR_REVIEW` or `CANCELED`. A current Stage-targeted `submit_to_develop` handoff is the only READY reopen path.

Caller prose cannot replace or invent a Task Book.

Consumed inner fields fail closed as real lists/mappings before use: `scope.paths` / `scope.modules` / `scope.exclude`, `develop_session_ids`, `stages[*].required_tests`, and `final_tests`. A mapping such as `scope.paths: {src/app.py: false}` is malformed authority, not a path list.

Every canonical Task Book publication uses the P3 §31 rule: expected revision N plus per-record serialized conditional publication, producing exactly N+1. A matching expected revision does not authorize `READY_FOR_REVIEW`; `publish_task` still requires the current `evaluate_ready_for_review` / Records §11 evaluator before those bytes can become canonical. READY publication also fails closed when the proposed Task's P6 substantive authority projection differs from the current canonical Task (Records §8.7 / FND3-E04). That mixed mutation must be published as non-READY, then revalidated for the new candidate; old current-candidate decisions are not evaluated against a candidate-changing READY write. Session-link and first-stage progress are one in-memory mutation and one publication. `IN_PROGRESS` → `READY_FOR_REVIEW` is a second publication that must use the revision current after the first successful write. A revision conflict does not overwrite the newer Task, does not merge writers, and does not retry the stale in-memory mutation. A first-publication conflict occurs before source writes and aborts the started Session. A late READY conflict does not persist `READY_FOR_REVIEW` and does not emit a Develop→Submit route; already-applied source work is not rolled back.

Develop persists Stage `IN_PROGRESS` → `COMPLETE` only when the current Stage Completion Decision is `SATISFIED` for the actual candidate, required Stage tests satisfy defined acceptance through P6 Evidence locators, and no required-test blocker remains. `TEST_PASS`, `TEST_COMPLETE`, and successful writes are each insufficient. P7 then publishes `IN_PROGRESS` → `READY_FOR_REVIEW` only when Records §11 holds (all required Stages `COMPLETE`, every relied-upon Stage decision `SATISFIED` and current, final required tests accepted, Task Completion Decision `SATISFIED` and current, no required blocker) and the caller requests that transition. `TASK_COMPLETE` remains the derived aggregation of Stage statuses and is not a fifth Task status. After a successful READY publication, Develop re-observes the current candidate, binds that digest on the Develop→Submit route and SkillResult, and stops. Pre-READY Test evidence keeps its original candidate binding and is not relabeled.

A `READY_FOR_REVIEW` Task is not generic Develop permission. `normal_task` still cannot reopen it. Repair may reopen it only after a current `submit_to_develop` handoff with nonempty `target_stage_ids` is validated, then P7 publishes READY→IN_PROGRESS and target COMPLETE→IN_PROGRESS with UNKNOWN repair-reopen Stage/Task decisions through expected-revision CAS. P8 does not write the Task.

## Develop Session

Canonical path: `.scaffold/runtime/develop-sessions/<dev-id>/`.

Local, temporary, advisory. Session states: `OPEN` → `SEALED` or `OPEN` → `ABORTED`. No `SUBMITTED`.

IDs use the P3 family: `dev-<UTC compact>-<8 hex>`.

Session-S0/S1 overlays are compact dirty-path observations where the host can honestly observe them. `files.yaml` records Develop-authorized mutations for the current execution (engine writes and client-authorized editor events). Repository / candidate truth overrides Session memory.

Loading an existing Session fail-closes unless `session.yaml` carries usable task, mode, project, baseline, Session-S0 overlay, and observed candidate binding, and unless `files.yaml` exists and is structurally valid. Raw `status == OPEN` plus a matching `task_id` is not sufficient current editor authority. Hand-written partial Session files do not grant authority.

Editor mutation authority requires an explicit current execution pointer. A raw OPEN Session is durable history/recovery evidence, not a mutation grant. The execution also freezes `open-inventory.yaml` at bind time. Task scope says WHERE a Task may change; `files.yaml` records successful observed mutations and `mutation-attempts.yaml` records pending/failed authorizations. Scope is not provenance. In-scope editor evolution remains valid only when the path has successful observed provenance from the current execution. New product-scope or supporting-scope paths without an observed mutation, and outside-scope drift, fail closed. Inherited dirty files that are unchanged since open remain distinct and do not false-fail. Open-inventory bytes are physical starting observation, not proof that those bytes were legitimate or accepted.

Client recording model: Cursor `preToolUse` authorizes a mutation attempt and writes a durable pending transaction (`authorized_pending` in `mutation-attempts.yaml`). That row is not mutation provenance: it does not explain the path, does not let seal stamp live bytes as execution-produced, and does not make P8 `DEVELOP_KNOWN`. Successful `postToolUse` observes the actual filesystem post-state (digest or absence) and records `observed_success` into `files.yaml`. `postToolUseFailure` fails/cancels the pending row and leaves no whitelist. `afterFileEdit` / `afterTabFileEdit` may complete a unique pending authorization that belongs to the **current** Develop execution and the same normalized path; they must not attach a replayed/late event to whichever Session happens to be current, and an ambiguous match is ignored as provenance. Delete success is source-absent. Move/Rename success is source-absent plus destination observed. Unresolved pending rows fail closed at seal; they are never upgraded by hashing whatever bytes exist at seal time. Same-path rewrite after a successful observation is out-of-band drift. Same-path rewrite after failure or with no terminal event is unexplained / unresolved, never `DEVELOP_KNOWN`. After seal the pointer is removed and no editor authority remains. Submit reviews the sealed historical delta without reopening execution.

Hard live mutation enforcement is validated for the supported Cursor hook surface registered in the Scaffold fragment (`preToolUse`, `postToolUse`, `postToolUseFailure`, `afterFileEdit`, `afterTabFileEdit`, plus the existing shell/subagent/MCP gates). Cursor environments do not all expose identical hook coverage; cloud-agent / early read-only surfaces may omit some hooks. Those environments cannot claim the same live mutation-enforcement guarantee. Unrecorded changes still fail closed at Develop seal where provenance reconciliation observes them. This is input to a later Client Adapter Capability Matrix; this package does not implement multi-client or Cursor-cloud portability.

`DevelopEngine.run` still requires exact candidate match when resuming a Session by `session_id` without the current execution pointer.

Unsuccessful started Sessions terminate as `ABORTED`. It does not invent extra session states.

FA2-FND-005: ABORT means this Session is not trustworthy as a completed
Develop result. ABORT does NOT mean current workspace bytes are accepted,
that successful `observed_success` mutations never occurred, or that
unexplained drift may be forgotten. `observed_success` provenance remains
attribution after abort and is not `DEVELOP_KNOWN`. Pending authorization
is not upgraded to provenance. Candidate acceptance does not occur.

Abort MUST remain an escape path: persist unresolved physical truth, then
proceed. Drift MUST NOT make abort impossible.

Opening a new Develop Session MAY observe current disk, create its own
open-inventory / `workspace_overlay_s0`, and bind execution authority. The
Session open snapshot is physical starting observation, not acceptance. It
MUST NOT accept current disk state, erase existing unexplained drift,
reinterpret attributed changes as accepted, mint a new accepted anchor, or
launder prior physical divergence. Opening a Session MUST NOT mint a new
accepted anchor.

Unexplained drift is host/workspace-level, Task-agnostic, Session-independent
durable support at `.scaffold/ext/develop/unexplained.yaml`. The one-time
existing-host compatibility boundary is NOT witnessed by any support file. It
is the tracked `project_contract_generation` advance in `.scaffold/project.yaml`,
owned by Understand / project-migration authority. Develop reconciliation only
consumes that boundary and MUST NOT create, recreate, or re-grant it. Because
the generation lives in tracked project authority, ordinary untracked cleanup
such as a bare `git clean -fd` can destroy `.scaffold/ext/` without ever
returning the host to never-initialized. A malformed or missing drift payload
after the boundary has been consumed is unusable authority, not a second
compatibility initialization. A legacy-generation host that still carries a
drift payload is likewise unusable. It is
not a fourth canonical development record. It MUST NOT depend indefinitely on
walking the full historical Session directory chain. MUST NOT introduce
per-Task full-workspace accepted baselines. Task B's attributed mutation
MUST NOT become Task A rogue drift merely because Task A did not produce it.

Runtime observation boundaries that persist unexplained facts:

- Session open / bind, including pointer resume
- seal, including run-completion seal
- abort / blocked abort, before pointer clear
- Submit S2 after a successful physical Diff observation
- successful S10, after accepted-anchor advancement

Status / entry may observe candidate identity but do not write unexplained
facts. Drift that occurs with no Session open is detected at the next
Session open or Submit S2. Perfect client pre-write interception is not
required.

Known unexplained drift on path X does not automatically deny legitimate
mutation on unrelated path Y. Path-scoped Develop permissiveness does NOT
mean Submit may ignore known unexplained drift.

If an unexplained physical mutation reaches disk because a client lacked a
pre-write hook, later Scaffold observation MUST still preserve that physical
fact. MAJ-008 MUST NOT depend on solving MAJ-007.

No new normal-path Agent command, flag, or abort/reopen ritual is introduced.
MUST NOT require a longer abort/reopen ritual. Implementation strategy and
source exploration order are not constrained. Generic human clear of
unexplained bytes is forbidden. S10 remains the existing acceptance boundary.

On a no-SCM host the accepted anchor is existing durable publication /
baseline authority. If that authority is unavailable, UNKNOWN / fail-closed
remains valid. Do NOT fabricate an anchor. Ordinary mutation authority MUST
fail closed while accepted physical authority is UNKNOWN or durable drift
authority is unusable. Abort remains an escape path. Unknowable pre-upgrade physical
divergence MAY be inherited-at-initialization ONLY during the one-time
compatibility initialization of an existing established host, recorded by a
durable initialization boundary. After that boundary exists, UNKNOWN /
missing evidence / future divergence MUST NOT fall back to
inherited-at-initialization. Post-initialization unexplained drift MUST NOT
be downgraded to inherited-at-initialization. Do NOT fabricate historical
certainty.

Attribution may retire unexplained status ONLY when the current physical
state / current bytes of that path are proven consistent with the durable
trustworthy mutation provenance being used. Historical provenance for a
different byte/digest state MUST NOT clear a newer unexplained mutation.

## Mutation authority

Ownership modes remain `GENERATED` | `MANAGED` | `HUMAN_OWNED`.

P7 uses the shared P5 ownership resolver. P5-registered source areas such as
`src/` resolve ordinary business files as `HUMAN_OWNED`; a current
`IN_PROGRESS` Task whose authoritative scope contains the requested path is
the explicit current instruction permitting that business-source write.
HUMAN_OWNED routers/knowledge/client files remain protected. MANAGED
whole-file overwrite without a bounded region is blocked. Missing ownership is
UNKNOWN and blocked. Core machine artifacts are CONFLICTING and blocked.

Applicable global/module/path/test Project Rules are resolved before mutation.
Test-specific Rules use the union of caller-selected test ids and the
authoritative Task's `final_tests` / stage `required_tests` identifiers; the
caller need not restate Task-declared tests. A hard prohibition or
conflicting applicable Rule blocks before any source write. Rules constrain
existing authority; they cannot grant mutation or submission permissions.

There is no “Develop can write any project file” escape hatch.

P7 `authorize_writes`, the Cursor first-use mutation gate, and Submit S3
structural ownership review share one path-authorization function:
`authorize_path_mutation`. Task affiliation AND path authority. Supporting
declaration is not an ownership override.

Task `scope.supporting_paths` is first-class supporting-delta affiliation. It
lets a Task declare bounded tests/tools/evidence (or other non-product
prefixes) that belong to the current candidate without becoming
`project.yaml` product/module ownership. Supporting prefixes are explicit,
non-wildcard, capped at 32, grounded in an existing path, a bounded new
child under an existing parent, or discovered tests.yaml/commands.yaml
facts, and cannot name `.scaffold` / `.cursor` governance. An arbitrary
invented nested prefix is not grounded merely because a top-level directory
such as `tests/` exists. Inherited dirty baseline remains distinct from Task
supporting delta.

Declared supporting UNKNOWN test/tool/evidence may be eligible. Explicit
MANAGED or HUMAN_OWNED authority is not downgraded by supporting
affiliation. Protected Scaffold governance is always denied.

Submit S2 records `task_delta_classes` in parallel with provenance classes:
`inherited_baseline`, `task_product_delta`, `task_supporting_delta`,
`unrelated_delta`. S3 uses the same path-authority model as Develop:
legitimate UNKNOWN supporting does not false-fail; MANAGED / protected /
disallowed HUMAN_OWNED smuggled as supporting fails closed; unrelated delta
fails closed.

P6 may ingest/reference evidence whose source file is inside the current
Task's declared supporting scope. Runtime callers pass canonical `task_id`
(installed `run.py test --task-id`, Develop handoff, Submit completeness).
`task_book` is only an already-loaded mapping, not a string identifier.
SAV supplied-evidence compilation uses the same host_root + Task supporting
check. Candidate binding remains authoritative. Supporting-path membership
never manufactures `TEST_PASS` or `TEST_COMPLETE`. Requirement → Test still
requires explicit `execution_binding`. P6 remains the sole Test/Evidence
authority. A missing project-local `file_artifact` locator fails closed.
Opaque Human/CI/External locators that are not host files keep existing
P6 semantics.

Installed Consumer first-Task creation uses
`python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>`
(or `develop intake`). Intake creates no Develop Session. Execution uses
`develop session --task-id`, then Cursor mutation checks the current
execution Session, Task, mutable Stage, and shared path authority. Close
with `develop seal` or `develop abort`. An OPEN Session is not a
repository-global capability.

## Handoffs

Develop→Test carries only: test requirement, task identity, session identity, candidate digest, and Test mode `scoped_verification`.

Test is invoked through `scaffold_p6.engine.TestEngine.run`. P7 does not import P6 preflight, evidence, or adapter internals.

Test→Develop may enter `repair` only when the handoff is bound to the current Task and the current candidate and is a genuine failure/blocker. Missing or stale candidate binding cannot authorize Repair. After a material Repair edit, previous candidate-bound Test evidence is stale. READY repair requires nonempty `target_stage_ids`. Automated Test-failure Stage mapping exists only through `execution_binding.kind: test_profile`. Unresolved mapping routes to human clarification. Fresh-agent Repair recovery uses Task Book plus `.scaffold/runtime/repair-state/<task-id>.yaml` supporting state, not chat history.

Develop→Submit is a route payload only after a legitimate `READY_FOR_REVIEW` publication. Its `candidate_digest` is the post-READY observation, not a pre-persist snapshot. Submit repair handoffs may carry `target_stage_ids`; P8 does not write the Task. A Skill result never reports `mutations: none` if source or the canonical Task Book actually changed.

## D1 repository currentness

Before any Session or source/Task mutation, Develop uses the shared read-only
SCM observation and local tracking refs. Git states `CURRENT`, local `AHEAD`,
and `NOT_CONFIGURED` (legitimate local-only repository) may continue.
Configured-upstream `STALE`, `DIVERGED`, or unresolved/`UNKNOWN` currentness
blocks before mutation and surfaces the observed basis. Develop performs no
implicit fetch, pull, merge, rebase, reset, checkout, or other synchronization.
Nested projects use their parent Git worktree currentness while candidate paths
remain projected to the project root.

## Candidate binding

P7 observes candidate identity through the published P6 boundary: `observe_candidate` / `report_usable_for`. P6 hashes a semantic Task projection (FA2-FND-003): bounded control-plane/result fields, including READY status and Completion Decisions, do not change `candidate_digest`. The Skill still re-observes after publication so the returned candidate matches current P6 observation. A publication conflict also re-observes before the blocked Skill result so the returned Task and candidate describe the same current project state. A competing writer's substantive Task mutation is not attributed to this invocation and does change candidate identity. A material source mutation also changes candidate identity. Test evidence remains bound to the candidate it actually tested; control-plane READY does not by itself stale that Evidence. A Session digest cannot override workspace/SCM truth.

## Safety

P7 tests are ordinary local deterministic fixtures. No network, adversarial, security, or path-escape families.
