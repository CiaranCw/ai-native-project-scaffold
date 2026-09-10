# FA-2 Batch 5 — Develop lifecycle (C-MAJ-009 / C-MAJ-015)

This implementation note does not modify or outrank P0–P4. FA2-FND-001,
FA2-FND-002, and FA2-FND-003 are effective Foundation input.

Batch 5 implements the missing P7 runtime path for candidate-bound Stage
`IN_PROGRESS` → `COMPLETE` and Task `READY_FOR_REVIEW`, the Stage-targeted
READY repair reopen required by a valid `submit_to_develop` handoff, the
FND3 content-deterministic P6 Task projection, explicit Task
`execution_binding` (including preservation through Task Intake, with
`tests.yaml` grounding only for explicit bound profiles), and
unresolved Submit repair routing.

It does not start Batch 6, P9, or DIVE, and it does not claim C-MAJ-009 or
C-MAJ-015 closed.

## Versioning

`develop@2.1.0` remains the unreleased MINOR candidate introduced during Pilot
Readiness. This batch refines that candidate. `develop@2.0.0` is not modified.

`submit@2.1.0` emits the frozen `target_stage_ids` field when P8 can map a
blocker deterministically, and does not emit executable `develop.repair`
when mapping is unresolved. `submit@2.0.0` is not modified.

`test@2.0.1` remains the current unreleased PATCH candidate. FND3 changes
candidate projection inside that candidate; no additional Test version is
created. `skills.lock` is not rewritten. C-MIN-005 remains Batch 9.

## C-MAJ-009 — normal lifecycle

P7 now publishes Stage completion and Task READY through `publish_task`
expected-revision CAS. The Stage Completion Decision and Task Completion
Decision live inside the Task Book. P6 remains the sole Evidence owner; P7
stores portable locators, not raw reports.

P6 `candidate_digest` uses the FND3 semantic Task projection. Bounded
control-plane/result fields do not change candidate identity. After READY
publication, a fresh `observe_candidate` remains on the same digest when only
those fields changed. Substantive source or Task-plan mutation still yields a
new digest. candidate-equivalent is not publication-authorized; P3/P7 CAS
remains mandatory.

`IN_PROGRESS` → `COMPLETE` requires a current `SATISFIED` Stage decision, satisfied
required Stage tests, and no required-test blocker. `TEST_PASS` and successful
writes do not infer SATISFIED.

READY requires Records §11: structural `TASK_COMPLETE`, current SATISFIED
Stage decisions, accepted final required tests, current SATISFIED Task
Completion Decision, and no required blocker. A UNKNOWN Task decision blocks
READY even when every Stage is COMPLETE.

A COMPLETE Stage may remain COMPLETE after C1→C2 while its C1 decision is
stale. That stale decision cannot support READY(C2). P7 revalidates through
CAS: SATISFIED(C2) keeps COMPLETE; UNKNOWN/UNSATISFIED moves the Stage to
IN_PROGRESS. No REVALIDATING state is added.

## C-MAJ-015 — READY repair

For `mode=repair` and Task `READY_FOR_REVIEW`, P7 validates a bounded
`submit_to_develop` handoff before applying the ordinary READY incompatibility.
`normal_task` on a READY Task remains blocked.

A valid handoff must match task, current candidate, nonempty `target_stage_ids`,
existing COMPLETE targets, and non-escalating capabilities. P7 then
publishes one CAS: READY→IN_PROGRESS, target COMPLETE→IN_PROGRESS, target Stage
decisions UNKNOWN with supersedes, Task Completion Decision UNKNOWN with
supersedes.

P8 may emit `target_stage_ids` and `next_route=develop.repair` only from a
deterministic mapping (single-stage missing source, Stage-required FAIL ids,
or an explicit `execution_binding.profile_id` match). It does not guess first,
last, or all Stages. Unmappable blockers return `BLOCKED` with `next_route=human`
and no executable repair handoff. P8 does not write the Task.

Existing IN_PROGRESS `test_to_develop` repair remains supported without targets.

## Evidence join

P7 does not implement a second TEST_COMPLETE. After Test, it persists P6
published locators onto planned Task refs only when that ref has
`execution_binding.kind=test_profile` and P6-resolved producer `profile_id`
equals `execution_binding.profile_id`. `requirement_id == profile_id` is not a
binding. Completeness still uses the locator through `TestEngine.resolve_evidence`.
Equal names without an explicit binding remain unresolved. A legitimate
HUMAN/CI/EXTERNAL locator may satisfy a requirement when attached explicitly,
without a `test_profile` binding.

Task Intake grounds `tests.yaml` only for explicit `execution_binding.kind=test_profile`
`profile_id` values. An unbound `requirement_id` is not treated as a Test profile
identity, is not looked up in `tests.yaml`, and does not invent a binding. A
bound unknown profile still fails closed.

## Non-absorption

C-MAJ-001, C-MAJ-003, C-MAJ-007, C-MAJ-008, C-MAJ-013, C-MAJ-014, C-MAJ-018,
C-MAJ-019, C-MIN-001, C-MIN-004, C-MIN-005, and C-MIN-006 remain later findings.
