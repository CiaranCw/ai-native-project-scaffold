# P6 Test — concrete implementation notes

This document records P6-owned concrete schemas and runtime boundaries. It is not a Foundation Contract and does not outrank P0–P5.

P6 status: **CLOSED / BASELINED / REMOTELY PUBLISHED.** Implementation phase closed; later FA-2 corrections were applied in the current unreleased candidate. FA-2 is independently PASS / CLOSED. P9 Repair/Migration is PASS / CLOSED. P10 is PASS / CLOSED. Post-P10 Scenario-Aware Verification supporting plans are recorded in [DIVE_PILOT_CORRECTION_01.md](DIVE_PILOT_CORRECTION_01.md). This note does not claim DIVE Day-1 closed or v2.0 released.

Rev4 closes remaining completed-report semantic coherence and fail-closed reader defects. Rev1–Rev3 host, GENERATED-authority, and cleanup corrections remain in force. The accepted P6 architecture is unchanged.

P6 completeness is a support-artifact summary consumed by P8 S5. Foundation
`TEST_COMPLETE` cannot become true from a required FAIL or from unknown
required policy. P6 `test_complete` is required-verification obligation
completeness. `coverage_complete` is terminal accounting. They are not
`SUBMIT_AUTHORIZED`.

Develop may consume an already published completed report by `report_id`.
`consume_published_report` reloads durable P6 storage, revalidates schema,
`COMPLETED` status, local locators, candidate currentness, `candidate_match`,
and claimed SAV coverage. Caller report dictionaries are not authority. This
does not re-execute Test and does not relabel lawful `EXTERNAL_RESULT`.

## Role and boundaries

Test is the verification/evidence Skill. It:

1. performs a read-only Host Compatibility Preflight for the actual Test package;
2. applies an observational host lifecycle / maintenance execution gate;
3. binds to the current real candidate using a P6-owned projection;
4. resolves `.scaffold/tests.yaml` and command authority;
5. executes or collects permitted verification;
6. compiles Evidence and a candidate-bound Test Report;
7. computes batch `TEST_PASS`, terminal coverage, and required-obligation completeness separately.

Test does **not** develop or repair source, authorize Submit, perform Structural Review, Commit, Push, create Develop Sessions, finalize Change Records, persist `NEEDS_MIGRATION`, update `skills.lock`, modify `project.yaml`, run Refresh or Migration, or treat a test PASS as Submit Test Completeness.

P6 produces a candidate-bound completeness **support summary**. P8 later owns Submit Test Completeness judgment.

Task Book and Develop Session are optional references only. Neither is required.

Runtime input `task_id` loads the authoritative Task Book for that Test run.
Engine kwarg `task_book` is only an already-loaded Task Book mapping; it is
not a string identifier. Published `optional_refs.task_book` is the durable
Task id of the Task that produced the report. `consume_published_report`
reuses that published binding: a report bound to Task A cannot be consumed
as authority for Task B, even when Candidate identity is identical.

## Skill package identity

Frozen from P4 package/release convention and the P4 Test fixture identity:

| Field | Value |
| --- | --- |
| `skill_id` | `test` |
| `skill_version` | `2.0.1` |
| modes | `scoped_verification` |
| `provides` | `test.scoped_verification` |
| `requires` | `[]` |
| `entry` | `SKILL.md` |
| `package_format_version` | `1` |

The generic Skill result and Test Report report the **actual** executed package version, which may differ from the lock when the read-only result is `COMPATIBLE`. They never fall back to a hardcoded `2.0.0` after an INVALID or unresolved package.

Cleanup is local support-artifact housekeeping. It is not a fifth Skill, not a Test mode, and not a lifecycle state.

## Flow

```text
intake (TestEngine.run)
→ observe_candidate (pre)
→ read-only Host Compatibility Preflight
   including host lifecycle / maintenance gate
→ inspect_host_project / ownership schema
→ resolve_contract (tests.yaml + commands.yaml)
→ validate selected ids
→ Target Adapter or supplied evidence
→ Evidence Compiler
→ observe_candidate (post)
→ analyze completeness (batch TEST_PASS ⊥ coverage_complete ⊥ test_complete)
→ persist evidence blobs / human summary
→ validate final report (schema + semantic consistency)
→ atomically publish report.yaml LAST
→ generic Skill result + routing
```

## Host lifecycle and maintenance execution gate

Ordinary Test requires a coherent Scaffold-managed host. P6 is not an alternate pre-adoption runtime. All checks are observational. No P6 preflight path creates persistent project or lock mutations.

Implemented in `evaluate_host_execution_gate()` / `evaluate_test_preflight()` (`src/scaffold_p6/preflight.py`).

Ordering:

```text
host adoption / lifecycle / maintenance gate
→ only if executable ACTIVE host:
   package / lock Host Compatibility gate
```

An INVALID or unresolved Test package cannot override host routing. `NOT_ADOPTED` / `ADOPTING` still route `understand.bootstrap`. `ACTIVE + NEEDS_REFRESH` still routes `understand.refresh`. `ACTIVE + NEEDS_MIGRATION` still routes `understand.compatibility`.

Normal execution requires:

- `project.yaml` VALID
- lifecycle `ACTIVE`
- maintenance does not include `NEEDS_REFRESH` or `NEEDS_MIGRATION`
- plus the existing package/lock Host Compatibility gate (`EXACT` or `COMPATIBLE` only)

| Host observation | Ordinary Test | Route |
| --- | --- | --- |
| `project.yaml` ABSENT / not adopted | BLOCK; adapter not invoked | `understand.bootstrap` |
| `project.yaml` present but not VALID (MALFORMED / INCOMPLETE / …) | BLOCK; `non-executable` | `understand.refresh` |
| `ADOPTING` | BLOCK | `understand.bootstrap` |
| `RECOVERY_REQUIRED` | BLOCK; do not guess Adoption vs Migration | P5 read-only `snapshot_host` recovery evidence: adoption-only → `understand.bootstrap`; migration-only → `understand.compatibility`; otherwise `understand` |
| `ACTIVE` + `NEEDS_REFRESH` | BLOCK; stale tests/commands are not authoritative | `understand.refresh` |
| `ACTIVE` + `NEEDS_MIGRATION` | BLOCK; no Migration / lock / project write | `understand.compatibility` |
| coherent `ACTIVE` + EXACT/COMPATIBLE package | allow | continue |

Standalone `tests.yaml` / `commands.yaml` without a valid adopted host do **not** confer Test authority. Only Understand owns first attachment/adoption.

P6 does not add a third Preflight context, a sixth compatibility result, or a new project lifecycle.

## Read-only Host Compatibility Preflight

Implemented in `src/scaffold_p6/preflight.py`. Observational only. Reuses P5 `load_package`, `inspect_lock`, `inspect_project`, `snapshot_host`, and `evaluate_package`. Does **not** call `evaluate_host`, `lock_update_plan`, Migration, or any path that persists `NEEDS_MIGRATION` or rewrites lock/project.

Conceptual sequence for an ACTIVE host that already passed the lifecycle/maintenance gate:

```text
valid ACTIVE project.yaml
→ complete authoritative skills.lock
→ expected Test identity from the lock
→ resolve actual Test package
→ validate actual package
→ evaluate_package(expected, actual)
→ execute only on EXACT or COMPATIBLE
```

Package / lock execution gate:

| Preflight result | Normal Test execution |
| --- | --- |
| actual package unresolved | BLOCK |
| actual package INVALID | BLOCK; report actual validity, not `test@2.0.0` |
| skills.lock missing / malformed / unsupported / non-authoritative / incomplete four-core | BLOCK |
| Test lock entry missing | BLOCK |
| `EXACT` | allow |
| `COMPATIBLE` | allow; surface expected vs actual; do not report EXACT; do not rewrite the lock |
| `MIGRATION_REQUIRED` | BLOCK; no Migration; project.yaml and skills.lock unchanged |
| `INCOMPATIBLE` | BLOCK; Target Adapter not invoked |
| `UNKNOWN` | BLOCK; Target Adapter not invoked |

P6 does not infer a lock from installed packages and does not regenerate one.

A present-but-invalid `project.yaml` is `non-executable`, not treated as an unadopted host. Package validity is observed for reporting, but it is applied only after the host gate has already passed.

## Candidate identity

Implemented in `src/scaffold_p6/candidate.py`. This remains the canonical
**P6-owned** candidate-binding projection. Shared P5 SCM observation supplies
repository/worktree membership and project-root-scoped status; it does not
create a second candidate digest.

### Git

Uses ordinary local Git metadata (HEAD/branch/detached/unborn plus NUL-delimited
porcelain status). Repository membership is resolved through Git even when the
project root is nested below the worktree root. Status is filtered and
re-expressed relative to the Scaffold project root, so unrelated parent-repo
changes do not enter the candidate. Porcelain `-z` preserves rename/copy source
and destination as separate paths.

A clean tree is not required. No commit is invented.

Git membership with failed, malformed, or indeterminate observation produces
an unusable candidate with an empty `candidate_digest`, explicit
`OBSERVATION_FAILED`, and unknown dirty-state fields. Test blocks before
adapter invocation; observation failure is never an empty clean candidate or a
no-SCM fallback. Observation metadata is excluded from the successful
candidate identity body, preserving the published digest semantics.

Binding includes:

- HEAD revision
- branch / detached / unborn `head_state`
- tracked candidate modifications and content digests
- untracked **non-ignored** candidate files and content digests
- durable Scaffold authority digests for the five core machine artifacts
- workspace fingerprint over those inputs

Git-ignored ordinary test/build output does not change candidate identity. Tracked changes remain candidate truth even when a Test Contract `generated_outputs` prefix overlaps them.

Dirty rename with no Test mutation of the destination may keep pre/post candidate match. Mutation of the renamed destination must mismatch.

### Generated-output exclusion authority

A Test Contract string does **not** gain authority to erase real candidate source.

Before profile execution, P6 loads applicable global/module/path/test Project
Rules through the shared P5-owned resolver. Structured hard prohibitions and
Rule conflicts block before adapter invocation and route toward Understand
Refresh. Rule loading is observational and never grants source mutation,
Commit, Push, or Submit authority.

Rules:

- Git **tracked** paths are never excluded by `generated_outputs`
- explicit untracked / no-SCM exclusions require a **positive normalized GENERATED classification** from current `modules.yaml` (`kind: generated`)
- a declared exclusion is authorized only when it equals the GENERATED authority path or is a descendant of that path
- a narrow GENERATED path such as `build/generated` does **not** authorize a parent declaration such as `build`
- unknown classification: do not exclude
- no filename guesses such as `build`, `tmp`, `cache`, or `src` as generic truth
- never exclude `.scaffold/project.yaml`, `.scaffold/skills.lock`, `.scaffold/modules.yaml`, `.scaffold/commands.yaml`, or `.scaffold/tests.yaml`, even when another declaration claims an overlapping generated prefix

### no-SCM

Conservative portable path/type/digest inventory minus:

- `.scaffold/runtime/`
- bytecode / `__pycache__` / `*.pyc`
- explicit declared outputs that are also positively classified GENERATED

No Git identity is invented. Source mutation and durable Scaffold authority changes still mismatch.

### Candidate change

These still cause pre/post mismatch:

- tracked source content changes
- non-ignored untracked candidate source appears/disappears
- relevant Scaffold durable authority changes
- Test Contract / command authority file changes
- mutation of a Git-renamed destination path

Expected ignored output, or untracked/no-SCM output that is both declared and positively classified GENERATED, must not.

If pre/post digests differ, executed PASS/FAIL results are marked stale/`BLOCKED` and both `test_pass` and `test_complete` are false.

## Test Contract / profile model

`.scaffold/tests.yaml` remains the P2 machine testing index. Contract identity and authority are rejected at the resolution boundary.

Identity:

- every profile `id` must be a nonempty string and unique
- every command `id` must be a nonempty string and unique
- duplicate ids are a controlled contract blocker; no last-write-wins collapse

`required` is a real boolean when present. `"true"`, `1`, `[]`, and `{}` are invalid and do not coerce to optional.

Implemented profile fields are type-checked: `id`, `purpose`, `required`, `adapter`, `command_ref`, `working_directory`, `timeout_seconds`, `success`, `evidence_required`, `provenance`, `applicability`, `confidence`. This is not a general CI schema.

### Top-level applicable / applicability

When `applicable` is present it must be a real boolean. `"false"`, `0`, `[]`, and `{}` are contract blockers.

`applicable` and `applicability` must be coherent:

- `applicable: false` + `applicability: APPLICABLE` → CONFLICT / BLOCK
- `applicable: true` + `applicability: NOT_APPLICABLE` → CONFLICT / BLOCK
- `UNKNOWN` / `CONFLICTING` remain unresolved; P6 does not guess

### Profile applicability

A profile with `applicability = NOT_APPLICABLE` is not locally executed merely because it appears in `profiles[]`. If it is also declared required, that is a contract contradiction.

A required profile with `UNKNOWN` or `CONFLICTING` applicability cannot count as covered and cannot execute by guessing.

An optional profile with `UNKNOWN` / `CONFLICTING` that is explicitly selected blocks that selected verification rather than silently executing it.

No new lifecycle states are added.

### Profile confidence

Profile availability/confidence remains evidence-derived. `UNKNOWN` / `CONFLICTING` profile authority is not executable truth. `INFERRED` availability is not silently promoted to `VERIFIED`. The Rev1 required-policy authority rule is preserved.

### Required-policy authority

Observed test availability is not declared REQUIRED policy. A profile MUST NOT become authoritative REQUIRED solely from `INFERRED` detection or `policy: observed` without `required_authority: VERIFIED`.

INFERRED-only required relationship → unresolved authority → blocker / Understand Refresh / human governance. Not `TEST_COMPLETE`.

VERIFIED observed existence alone does not invent a new required policy.

### Required-set authority

`required_set_authoritative` is an implementation-local boolean. It is **not** a Foundation lifecycle state.

Discovery `confidence` and required-set authority are separate. Publishing `required_authority: VERIFIED` does not rewrite discovery `confidence` to `VERIFIED`. A current `required-tests-1` grounding record can still make the required set authoritative when discovery confidence is `UNKNOWN` or `INFERRED`, provided top-level and per-profile `required_authority` are `VERIFIED` and the grounding still matches the accepted policy. Optional profiles do not inherit that authority and stay blocked when their own discovery confidence is `UNKNOWN` or `CONFLICTING`. The first successful required-tests publication records `required_authority_format: required-tests-1` on `.scaffold/project.yaml`. That field is Understand-owned project metadata. Develop does not write it. Refresh, later publication, and project-metadata migration copy it and do not clear it. While it is present, missing or stale grounding is not authoritative and does not fall back to the legacy rule, including when the policy file and every grounding field are gone. A grounding remnant without that field is still publication evidence and does not fall back to legacy. A `required_authority: VERIFIED` flag with no grounding record and no format identity is a legacy contract: discovery confidence must still be `VERIFIED`, and `INFERRED` or `UNKNOWN` is not authority. Historical non-empty contracts that omit `required_authority`, already have discovery `confidence: VERIFIED`, and have never published required-tests-1 remain authoritative by the previous fallback. An empty legacy set still needs explicit `required_authority: VERIFIED`; verified discovery alone does not establish it.

`test_complete` with `required_total == 0` is allowed only when the current valid Test Contract authoritatively establishes that the required set is empty. Examples that may establish it:

- an explicit no-required / no-applicable-test contract with
  `required_authority: VERIFIED`, `NOT_APPLICABLE`, `applicable: false`, and no
  required profiles
- a fully authoritative Test Contract whose profiles are explicitly optional
  and whose empty required-policy set is declared complete with
  `required_authority: VERIFIED`

Examples that must not:

- INFERRED empty profiles
- empty profiles with availability `confidence: VERIFIED` but no explicit
  required-policy authority
- verified absence of a discovered test surface
- UNKNOWN applicability
- observed availability with `required_authority: UNKNOWN`
- `required: false` written only because a test surface was observed
- malformed contract
- absent `tests.yaml`
- unresolved required-policy authority

Absence is not verified zero.

### Command authority

A nonempty `argv` is not enough. Command `confidence`:

| confidence | Execution |
| --- | --- |
| `VERIFIED` | may execute if argv is a nonempty string list |
| `INFERRED` | not upgraded to VERIFIED; not executed |
| `UNKNOWN` | not guessed; BLOCK / Understand Refresh |
| `CONFLICTING` | not guessed; not executed |
| absent | treated as unresolved; not executed |

### success.exit_code

When declared, `success` must be a mapping. When declared, `success.exit_code` must be an integer. `bool` is not an integer. Malformed success criteria are a controlled contract blocker, not an uncaught `ValueError`. P6 does not implement a general assertion language.

### selected invocation input

`selected` must be `null` or a list of unique nonempty known profile ids. A plain string is an invocation-input blocker; it is not expanded with `list("unit")`. An unknown selected id is a controlled BLOCK, not a COMPLETED empty run.

Selection is request scope, not Test Contract mutation.

Report `selected` is the profiles actually selected/requested for this batch. It is not populated with every Contract profile, including `NOT_RUN` profiles. Keep separate: `selected`, `executed`, `required`, `optional`, `terminal_usable`.

Report `scope.paths` and `scope.modules` persist the normalized,
project-relative invocation area used for Project Rule resolution. Empty scope
stays empty. Absolute machine paths are excluded. Together with the candidate
digest, selected profiles, and required-policy state, this gives a zero-context
consumer the effective verification scope.

Malformed `tests.yaml` or `commands.yaml` blocks before Target Adapter execution.

Analysis does not use a lossy identity map: if duplicate profile ids ever reach it, the worst result wins (`BLOCKED` > `FAIL` > `NOT_RUN` > `PASS`).

## Target Adapter

Interface: `TargetAdapter.execute(command, working_directory, timeout_seconds) -> ExecutionObservation`.

Implemented adapter: `local` (`LocalTargetAdapter`). SSH, cloud, container, and Kubernetes adapters are out of scope. An unsupported adapter is `BLOCKED`. Target Adapter is not a fifth Skill.

Local observation captures resolved argv, working directory, timestamps, duration, exit code, stdout/stderr, timeout/termination, and adapter identity. The process environment is not dumped into reports.

### Project-bound working directory

`working_directory` must be a portable project-relative directory. Machine-absolute declarations in shared Test Contract metadata are rejected. Commands are not executed outside the project root.

`working_directory_declaration_valid()` / `resolve_project_working_directory()` establish project containment before adapter execution. Ordinary `"."` is valid. Absolute paths and `..` segments are rejected by pure path/contract validation.

## Evidence trust boundary

Support-artifact metadata, not Foundation lifecycle states.

### Provenance is a requirement

If a profile declares `provenance: LOCAL_EXECUTION` (or defaults to local), `EXTERNAL_RESULT` / `HUMAN_OBSERVATION` / `CI_RESULT` cannot silently satisfy it.

If a profile declares `EXTERNAL_RESULT`, `CI_RESULT`, or `HUMAN_OBSERVATION` and the required supplied evidence is absent, P6 does **not** fall back to `LocalTargetAdapter`. The result is `BLOCKED` / `NEEDS_HUMAN` as appropriate.

Only a profile that permits or defaults LOCAL execution may invoke the LocalTargetAdapter.

Caller-supplied evidence that claims `LOCAL_EXECUTION` is still rejected. It is not rewritten to an external provenance.

Allowed supplied provenance: `EXTERNAL_RESULT`, `HUMAN_OBSERVATION`, `CI_RESULT`. Unknown provenance is blocked. Arbitrary strings are not persisted.

Evidence kinds: `command_result`, `structured_assertion`, `log_text`, `structured_state`, `event_trace`, `file_artifact`, `visual_checkpoint`, `human_observation`, `external_ci`. Unknown kind is blocked.

### Multiple evidence items

Supplied items are grouped `profile_id → list[evidence]`. Every supplied item is preserved. A profile requiring both `structured_assertion` and `visual_checkpoint` is satisfiable only when both valid items are supplied.

If multiple supplied items for one profile carry verification results, they must agree. Conflicting PASS / FAIL claims are an unresolved evidence conflict (`BLOCKED`). There is no last-item-wins arbitration.

### Kind-specific usability

An item is not usable merely because its kind is a supported enum. `evidence_item_usable()` is a small P6-local validator:

| kind | minimum usable content |
| --- | --- |
| `command_result` | nonempty command list plus result or exit code |
| `structured_assertion` | nonempty assertion/content payload or nonempty summary |
| `log_text` | inline content or locator |
| `structured_state` | state/content or locator |
| `event_trace` | trace/content or locator |
| `file_artifact` | locator/reference |
| `visual_checkpoint` | locator, artifact, or content |
| `human_observation` | nonempty observation/summary |
| `external_ci` | locator, run URL, CI id, or nonempty identity summary |

Empty `visual_checkpoint` / empty human observation / file artifact without a locator are unusable and cannot complete required evidence.

### Candidate binding

Any externally identified evidence that claims a concrete `candidate_digest` must match the current P6 candidate. This applies to `EXTERNAL_RESULT`, `CI_RESULT`, and `HUMAN_OBSERVATION` when a digest is present. Candidate A evidence is not rebound to candidate B.

`HUMAN_OBSERVATION` without a pre-existing digest may bind synchronously to the current invocation:

- `binding_mechanism`: `synchronous_invocation`
- `candidate_digest`: current candidate
- `provenance`: `HUMAN_OBSERVATION`

This convenience is **not** applied to `EXTERNAL_RESULT` or `CI_RESULT`; those require an explicit matching digest.

Every usable supplied item must independently satisfy correct candidate, correct profile, supported provenance, supported kind, and kind-specific required content. One valid item does not hide a second invalid required item.

### Required evidence set

After filtering unusable evidence:

```text
required_evidence_kinds ⊆ usable_actual_evidence_kinds
```

There is no `command_result` special case. Example: required `visual_checkpoint` with actual `structured_assertion` only → `evidence_complete = false`.

The concrete Test Report schema validator runs before final completed publication. Unsupported provenance, unsupported kind, malformed candidate binding, or malformed required fields cannot be published as a valid COMPLETED report.

The Evidence Compiler may summarize and attach references. It must not rewrite PASS/FAIL truth.

## Test Report

Schema version `"1"`. Kind `test_report`. `record_class: support_artifact`.

Minimum fields: report identity, Test Skill identity/version, candidate pre/post, candidate match, expected/actual package and compatibility, project reference, selected/required/optional profiles, per-scenario result, provenance, adapter, command_ref, timing, evidence refs, evidence completeness, blockers, completeness summary, verification summary, timestamps.

`submit_authorized` is **absent**. Test does not own a Submit authorization field. Structural Review and Change Record are not produced.

## Completed report integrity

`load_completed_report()` is the single coherent completed-report reader. `is_completed_pass_report()` and `list_completed_reports()` use the same path.

Blocked invocations use one effective `ScenarioResult` list for `analyze()`, `_build_report()`, and failure rendering. If the contract contains known profiles, the completed blocked report contains those profiles with their actual `NOT_RUN` / `BLOCKED` state. `completeness.required` cannot name a profile that is absent from `profiles`.

`validate_report()` fail-closes unless `profiles` is a list of mappings, `completeness` and `verification` are mappings, and `candidate_match` plus `test_pass` / `test_complete` on both summaries are real booleans. Completeness id collections (`required`, `optional`, `selected`, `executed`, `terminal_usable`, `missing_required`, `blocked_required`) must exist and be lists of nonempty strings. Required numeric completeness fields (`required_total`, `optional_total`, and the required counters) must exist as integers, not bools. Required boolean completeness fields (`candidate_match`, `evidence_complete`, `batch_evidence_complete`, `test_pass`, `test_complete`, `required_set_authoritative`) must exist as strict booleans. Absence is not treated as zero or false. Malformed persisted fields return INCOMPLETE; they do not raise.

`required_total` / `optional_total` must equal those list lengths. Required counters must match required profile results. `required_set_authoritative` is mandatory even when `test_complete` is false. `coverage_complete` may be true when that authority is true, the candidate matches, required coverage evidence is complete, and every required profile is terminal usable (`PASS` or `FAIL`). A required FAIL may still yield `coverage_complete=true` and `test_pass=false`, but it cannot yield `test_complete=true`. An optional FAIL may yield `test_pass=false` while still allowing `test_complete=true` when every required obligation is satisfactorily complete.

Top-level `candidate_match` and `completeness.candidate_match` must be identical booleans. `batch_evidence_complete` must equal `all(evidence_complete)` over `result != NOT_RUN` profiles. `completeness.evidence_complete` must match required-coverage evidence from those profile rows. `test_pass=true` requires a nonempty executed PASS batch with complete batch evidence.

Every profile `id` is a unique nonempty string and `profile.required` is a strict boolean. A required profile must appear exactly once in `completeness.required` and not in `optional`. An optional profile must appear exactly once in `completeness.optional` and not in `required`. A profile cannot belong to both sets or to neither. Duplicate profile ids are invalid.

Every Evidence Ref must carry `ref_id`, `report_id`, and `candidate_digest` bound to the report. Locally `resolvable: true` refs also require a nonempty digest that matches the stored artifact.

P6 also owns the locator-only reference used by Task Books and Change Records.
`TestEngine.build_evidence_refs()` mints portable `test-runs/<run-id>/...`
locators only from a validated completed report.
`TestEngine.resolve_evidence()` returns the original Evidence item plus
terminal profile accounting. Before durable finalization it reloads the owning
runtime report and validates local Evidence Ref digests. A valid P6 durable
capsule is independently sufficient for historical resolution, even when a
stale/corrupt runtime run remains; `load_completed_report()` stays runtime-only
and never accepts the capsule as repair. Report-fragment locators preserve
result-bearing HUMAN, CI, and EXTERNAL Evidence without converting it to
`command_result`.

An active `PREPARED` materialization is a fail-closed durability barrier.
While it holds a locator, `resolve_evidence()` returns healthy runtime truth
with `resolution_source=runtime`; if runtime truth is unavailable or corrupt,
resolution blocks for P8 durability reconciliation rather than describing the
candidate-only capsule as durable. P6 never inspects Git history or Change
Record durability to cross this barrier.

A completed report is usable only when:

- publication is complete (`incomplete/run.yaml` is gone)
- `report_status` is `COMPLETED`
- `report.report_id` matches the requested run directory identity
- schema validation succeeds
- locally resolvable Evidence Refs (`resolvable=true`) still resolve and their integrity digest matches
- `verification.test_pass` == `completeness.test_pass`
- `verification.test_complete` == `completeness.test_complete`
- those values are consistent with profile results, `candidate_match`, required/selected/optional identities, evidence completeness, and required-set authority
- Evidence Ref `report_id` and `candidate_digest` bind to the report
- evidence ids and ref ids are unique

Missing or corrupt required local refs make the report unusable as a completed verification report. Network/external evidence is not fetched. External refs with `resolvable=false` remain represented truthfully and are governed by supplied-evidence usability policy.

A profile `FAIL` with persisted `verification.test_pass: true` is rejected. Internally contradictory reports do not load as completed. A coherent completed PASS report still loads.

## TEST_PASS, coverage_complete, and test_complete

These summaries are independent. `test_pass` is not derived from coverage.
`coverage_complete` is not Foundation `TEST_COMPLETE`.

`TEST_PASS` (`completeness.test_pass`) answers: did the actually selected/executed accepted verification batch pass?

It may be true only when:

- the batch contains at least one actually executed/accepted result;
- every batch member is usable PASS;
- no selected member is FAIL or BLOCKED/unresolved;
- candidate pre/post matches;
- required evidence for executed batch members is complete;
- no batch-level infrastructure/contract blocker invalidates execution.

Required tests outside the selected batch may remain `NOT_RUN`. Those make `test_complete = false` and must not automatically make `test_pass = false`. Every `NOT_RUN` entry records `not_run_reason`.

P6 `coverage_complete` answers: did every required Test Contract entry and
every explicitly selected optional profile reach a terminal usable result, and
is the required set authoritative?

- `required_set_authoritative` is true;
- candidate identity is current;
- every required test has a terminal usable result (`PASS` or `FAIL`);
- no required test is `BLOCKED` or `NOT_RUN`;
- every explicitly selected optional profile has a terminal usable result;
- required and selected-optional evidence is present.

A required or selected-optional terminal FAIL counts as terminal usable.
Infrastructure `BLOCKED` and `NOT_RUN` do not. An unselected optional
`NOT_RUN` is outside selected coverage and does not make coverage incomplete.

P6 `test_complete` answers: has the required verification obligation been
satisfactorily completed for this candidate? It requires complete required
coverage and `required_fail == 0`; selected optional status does not become a
required obligation. A required FAIL cannot yield `test_complete`. Unknown
required policy cannot yield `test_complete` merely because observed tests
passed.

Authoritative verified zero-required-tests with no executed tests: `test_pass = false`, `coverage_complete = true`, `test_complete = true`.

INFERRED, observed-undeclared, or otherwise non-authoritative empty required set: `test_complete = false`.

Candidate mismatch: both false.

This P6 `test_complete` field is the current Test completeness result consumed by P8 S5. It is not `SUBMIT_AUTHORIZED`.

Truth table (P6 support-artifact fields):

| Situation | test_pass | coverage_complete | test_complete |
| --- | --- | --- | --- |
| selected required PASS + other required NOT_RUN | true | false | false |
| full required PASS | true | true | true |
| required PASS + required FAIL, full coverage | false | true | false |
| required BLOCKED | false | false | false |
| authoritative verified zero-required-tests | false | true | true |
| observed tests PASS, required policy UNKNOWN | true | false | false |
| INFERRED empty required set | false | false | false |
| candidate mismatch / stale run | false | false | false |

## Failure vs infrastructure blocker

A correctly executed failing command is scenario `FAIL`, Skill outcome `COMPLETED`, and a report is published. That is not a Test Skill crash.

Missing command, unsupported adapter, missing or non-project-bound working directory, malformed/UNKNOWN/CONFLICTING/INFERRED authority, missing required evidence, provenance mismatch, or candidate change is `BLOCKED` and cannot become PASS.

## Support-artifact publication

Location:

```text
.scaffold/runtime/test-runs/<testrun-...>/
├── incomplete/run.yaml     # non-authoritative while running
├── report.yaml             # atomically published completed report LAST
├── summary.md              # human rendering only
└── evidence/               # referenced blobs
```

Run id: `testrun-<UTC timestamp>-<8 lowercase hex>`. The unique suffix is newly generated per invocation (`secrets.token_hex(4)`). It is not derived from candidate identity. Same-candidate runs in the same second receive distinct ids.

Publication protocol:

1. create run incomplete area
2. execute / ingest
3. persist required evidence blobs/references
4. write human summary
5. build final report
6. validate final report (schema + semantic consistency)
7. atomically publish `report.yaml` LAST
8. remove incomplete markers

Before final completed publication, `load_completed_report()` must not return a completed report. Presence of `report.yaml` alone is not enough: if `incomplete/run.yaml` still exists, or the report fails schema/integrity validation, the reader fail-closes.

`is_completed_pass_report()` uses the same coherent completed-publication invariant plus `test_pass`.

If interruption occurs after evidence or summary but before final report publication, no COMPLETED report is usable. After atomic publication, report-referenced required artifacts already exist.

There is no P2 lifecycle or recovery state machine for Test. Stale incomplete runtime directories are non-authoritative. A safe fresh rerun is sufficient.

Completed `report.yaml` survives ordinary process restart on the same host. It is **not** a fourth canonical development record. Canonical records remain Task Book, Develop Session, and Change Record.

## Runtime support-artifact cleanup

P2 requires `.scaffold/runtime` to remain temporary local. P6 provides explicit bounded cleanup only.

```text
cleanup_test_run(root, run_id)
    remove .scaffold/runtime/test-runs/<exact-run-id>/
    only when run_id is one legal Test-run directory name
    and no PREPARED durable materialization holds that run

cleanup_incomplete_test_runs(root)
    remove abandoned incomplete Test-run directories only
```

`cleanup_test_run()` refuses `"."`, `".."`, empty, absolute, or multi-component identities and deletes nothing for invalid input. It cannot broaden into the `test-runs/` container. After S10, cleanup may delete a temporary run because referenced Evidence resolves from its deterministic metadata capsule and optional raw-byte sidecar under an already `GENERATED` `.scaffold/ext/test/evidence/` target. Fresh Adoption registers that area as GENERATED; Bootstrap does not create the directory. Only Change-Record-referenced locators are materialized.

Cleanup is local housekeeping. It is not a Test mode, not Submit, not Develop, and not a canonical record lifecycle.

Completed reports are **not** automatically deleted because a newer run exists. Completed support artifacts may still be needed by the caller or later Submit during the local workflow.

## no-SCM

Test runs without Git. Candidate identity is the conservative workspace fingerprint. No invented SHA.

## v1 selective reuse

Inspected conceptually from Architecture/Constitution capability-class B. No v1 tree is vendored.

Reused as concepts, reimplemented under v2: Contract/profile, Target Adapter boundary, Evidence, Evidence Ref, Analysis.

Rejected: v1 Game Legibility product identity, Repair loop, old record taxonomy, v1 lifecycle authority, CI/network harnesses, wholesale Test subsystem copy.

## Scenario-Aware Verification supporting plans

Scenario-Aware Verification belongs to Test. It is not a fifth Skill, not a
fourth canonical development record, and not a replacement for Test Profile or
Task Book.

Supporting layout:

```text
.scaffold/runtime/test-plans/<plan_id>/plan.yaml
.scaffold/runtime/test-plans/heads/<task_id>/<requirement_id>/head.yaml
```

Plans are `supporting: true` / `canonical: false`. A fresh Test Agent
reconstructs scenario and proof obligations from the current head/locator.
Required proof obligations are SATISFIED only by sufficient current Evidence.
Association (`po_id` / `covers`) is not coverage. An explicit suite/regression
strategy may use bound-profile PASS. State/trace presence, log text, file
artifacts, and visual checkpoints do not by themselves prove a structural PO.
Caller `adequacy.status` is not authority; engine-derived adequacy feeds
`test_complete`. Optional Evidence `role` and `retention_class` are defined in
[PC_SCF_H2_BOUNDED_VERIFICATION.md](PC_SCF_H2_BOUNDED_VERIFICATION.md).
A required
`INSUFFICIENT_OBSERVABILITY` obligation cannot yield requirement PASS; Test
returns the existing Test→Develop observability handoff and does not edit
product source. Profile `exit_code` 0 alone is not requirement PASS.

Plans bind `task_id`, `task_revision` (historical), `task_contract_digest`
(currentness for new plans), `requirement_id`, and profile. An optional
`candidate_digest` is revalidated before execution. New-format plans stay
current across completion-only Task revision changes. Legacy plans without
`task_contract_digest` still require exact `task_revision`. Missing head,
contract mismatch, or candidate mismatch fails closed.

This is an unreleased `test@2.0.1` candidate extension. Released `test@2.0.0`
is not mutated. SKILL_CONTRACT would require a version bump for a released
identity; this working-tree candidate is the same in-place pattern used by
P10 on `understand@2.1.0`.

## P7 / P8 boundaries

P6 does not implement Develop, Repair, Task completion, isolated worktrees, Submit S1–S12, Structural Review, Knowledge Consistency, `SUBMIT_AUTHORIZED`, Repository Sync, Change Record finalization, Commit, or Push.
