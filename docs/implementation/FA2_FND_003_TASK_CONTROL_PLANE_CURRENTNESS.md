# FA2-FND-003 — Task Control-Plane Candidate Currentness and Explicit Test Binding

Status: candidate Foundation amendment; requires independent re-audit.

This amendment resolves two Foundation gaps found while reviewing FA-2 Batch
5. It does not resume Batch-5 runtime implementation, fix B5-C03, close
C-MAJ-009/C-MAJ-015, start Batch 6/P9, or modify DIVE.

## Gap A: candidate self-reference

P6 is the accepted candidate authority. Before this amendment, the runtime
candidate projection included Task Book bytes while FA2-FND-002 required a
Completion Decision inside that same Task Book to equal the actual candidate.
The sequence was impossible:

```text
observe C
→ build Decision(C)
→ publish Decision(C) into Task Book
→ Task bytes change
→ observe C2
→ Decision(C) is immediately stale
```

The same cycle affected Stage completion, Task Completion Decision, READY,
repair reopen, revalidation, and P6 Evidence cited by those publications.
Repeatedly rewriting a digest would repeat the self-reference.

## Selected single-authority candidate model

P6 continues to own exactly one public `candidate_digest`. Its projection
hashes all substantive project content plus a semantic projection of Task
authority. It does not hash volatile Task control-plane fields as
unclassified bytes.

Candidate-significant Task authority includes:

- Task identity/creation identity, title, goal, acceptance, baseline, scope
- Stage identity, goal, and acceptance
- planned Stage/final requirement identities
- explicit requirement-to-Test-profile execution bindings
- other facts that change what work or verification is required

Bounded candidate-neutral control-plane facts include:

- revision/update metadata
- Task/Stage lifecycle status
- Develop Session links and concise result/progress summaries
- result-side Evidence locators and observed outcomes
- Stage and Task Completion Decisions, including bounded supersedes

Neutrality applies whenever the **current** Task content's substantive
projection is unchanged. It is a content-class property of those fields, not
proof that a particular process wrote them. Mixed or substantive Task mutation
is candidate-changing. Malformed or lifecycle-illegal Task content fails
closed under Task schema and lifecycle authority.

P6 `candidate_digest` is content-deterministic. Identical currently observed
Task bytes contribute the same candidate identity regardless of writer or
publication path. The digest is not a publication-provenance oracle.

This remains one candidate authority. A semantic per-path digest is merely an
input to P6's one projection, like existing file digests; it is not a durable
second candidate identity and is never caller-defined.

## FND3-R01: candidate identity vs publication authority

Candidate semantic identity and Task publication authority are different
questions.

- P6 `candidate_digest` answers: what substantive project/Task candidate exists
  now?
- P3/P7 expected-revision CAS answers: was this Task mutation legally published
  through the canonical mutation workflow?

State A (P7 CAS) and State B (direct write) that produce identical final Task
bytes X are indistinguishable to `observe_candidate`. Mutation provenance is
historical/process information, not content-semantic candidate input.
Therefore P6 MUST NOT compute A→C and B→C2 from final repository state alone.

**candidate-equivalent != publication-authorized.** Every authorized semantic
Task mutation performed by Scaffold still MUST use expected revision N plus
atomic conditional publication to N+1. A direct/manual/non-CAS write of
identical control-plane bytes is not converted into an authorized P7
publication merely because those bytes are candidate-neutral. Candidate
neutrality is not proof that the write was authorized.

This correction does not add cryptographic signing, a provenance ledger, another
canonical record, or a second candidate digest. Those facts are not required
for the current product contract: current content plus separate P3 CAS and
Task/lifecycle validation already answer the two questions.

## Why this is bounded

The model is not “ignore `.scaffold/tasks/**`.” Task creation/removal and
changes to goal, acceptance, scope, baseline, Stages, requirement plans, or
execution bindings change candidate identity. All non-Task source, business,
project, configuration, and authority content keeps its ordinary effect.

Control-plane neutrality is not write permission, Diff exclusion, ownership
permission, provenance proof, or Task lifecycle validation. P7 remains the
authorized Scaffold Task writer through CAS. An unexpected direct edit does
not gain lifecycle authority merely because it is candidate-equivalent.
The complete physical Task Book bytes remain visible in Git status/Diff or
no-SCM inventory and can be classified by Submit as unexpected/unattributed.
Schema, transition, Decision, Evidence, and revision rules still fail closed.

## Git and no-SCM

On Git, P6 retains revision, branch, dirty path/status, rename/deletion, and
other physical observations. The Task path contributes its semantic
substantive projection to candidate identity, while `git diff` retains all
bytes.

On no-SCM, inventory retains file path, existence/type, and physical
observation. The same Task projection contributes to the one candidate digest.
Other files remain byte-significant.

Thus a source change after Test yields C2 and stales Evidence(C). A Task-only
control-plane update whose current substantive projection is unchanged keeps C
and does not stale Evidence(C) solely because progress authority was recorded.
Remaining on C does not prove the write was CAS-authorized.

## P6/P7/P8 currentness

P6 `report_usable_for` still compares the report's candidate binding to the
fresh P6 candidate. The equality remains meaningful because current
control-plane bytes with an unchanged substantive projection leave that
candidate unchanged.

P7 stores Stage/Task decisions for C. After those current control-plane bytes
exist, fresh P6 observation remains C; the decisions are representable and
current. Remaining on C does not prove the write used P3 CAS. Any
substantive mutation produces C2 and FA2-FND-002 stale-decision rules apply.

P8 never trusts a caller digest. It re-observes through P6 and separately reads
the real Diff. Candidate-neutral Task progress does not disappear from review.

## Relation to FA2-FND-001

This model is independent of, and narrowly consistent with, the reviewed
candidate C / S9 finalization candidate F model. FA2-FND-001 permits only the
deterministic Finalization Bundle after S6. FA2-FND-003 defines how P6 projects
Task control-plane progress before/during candidate currentness. It does not
add to the S9 bundle or exempt arbitrary S9 mutation.

## Gap B: explicit requirement execution binding

Closed C-MAJ-017 established that Task requirement proof is:

```text
requirement_id + evidence_ref.locator → P6 resolver → current terminal Evidence
```

It also established that equal `requirement_id` and P6 `profile_id` strings do
not create an association. Batch-5 runtime attempted exactly that forbidden
join.

The missing Foundation fact was how a **fresh** selected profile execution is
authorized to populate a Task requirement's locator.

## Selected binding model

The Task planned reference owns a durable explicit mapping:

```yaml
required_tests:
  - requirement_id: task-required/check-save
    execution_binding:
      kind: test_profile
      profile_id: unit-save-check
```

The Task planning authority declares that executable profile P is the planned
producer for requirement R. Because this changes the required verification
plan, the binding is candidate-significant.

P7 derives an ephemeral Develop→Test mapping from current Task authority:

```text
requirement_bindings:
  - requirement_id: task-required/check-save
    profile_id: unit-save-check
selected: [unit-save-check]
```

P6 executes the profile. Its report and public locator resolution preserve the
producing profile identity. P6 does not assert that the profile satisfies the
Task requirement. P7 attaches the locator only after checking:

```text
Task R explicitly binds P
+ resolved locator was produced by P
→ locator may be attached to R
```

Equal names, list order, a sole selected profile, or caller prose prove
nothing. Missing or mismatched binding leaves the requirement unresolved.

The association and proof are recoverable without chat: the Task stores R→P
and then the exact P6 locator. Raw Test Report mappings never become Task
authority.

## Manual, HUMAN, CI, and EXTERNAL Evidence

An automated local profile binding is optional. Existing legitimate P6 HUMAN,
CI, or EXTERNAL Evidence may satisfy a requirement through an explicit opaque
locator under existing candidate/provenance rules. The producing Evidence need
not be assigned a fake local profile equal to the requirement.

## Preserved boundaries

- exactly three canonical development records
- exactly four top-level Skills
- unchanged Task, Stage, and Session states
- P3 owns durable Task requirement/binding semantics
- P6 owns candidate, execution, Evidence, and locators
- P7 owns lifecycle, Task CAS, and execution routing
- P8 owns review/repair routing and still reads the real Diff
- no S13, new permission, Commit/Push escalation, or `skills.lock` change

## Acceptance cases

FND3-E01 through FND3-E10 and FND3-R01 are normative in Records Contract §39.
Static tests pin their presence and cross-contract alignment; they do not
prove Batch-5 runtime. FND3-E01, FND3-E04, and FND3-E05 keep their product
intent: completion publication does not self-stale, READY publication is
representable, and the real Diff remains complete. They do not imply that P6
candidate identity can prove a historical CAS write.
