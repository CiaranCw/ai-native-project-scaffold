# FA2-FND-002 — Stage/Task Completion Decisions and Repair Stage Reopening

Status: candidate Foundation amendment; requires independent re-audit.

This post-FA-1 and post-FA2-FND-001 amendment resolves the two Foundation
gaps that correctly stopped FA-2 Batch 5. It does not implement C-MAJ-009 or
C-MAJ-015, does not revise FA2-FND-001, and does not claim Batch 5 closure.

## Why Batch 5 stopped

The Records Contract required implementation/acceptance satisfaction before
Stage `COMPLETE`, but represented Stage acceptance only as human-readable
intent. P6 could prove candidate-bound Test/Evidence truth; P7 had no frozen,
reconstructable representation of its acceptance decision. Inferring
completion from source writes or `TEST_PASS` would collapse distinct truths.

Separately, the Foundation allowed a READY Task to return to `IN_PROGRESS`
when work continued, but a Submit repair handoff did not identify which
`COMPLETE` Stage was affected. P7 could not choose the first, last, or all
Stages without inventing authority.

## Affected authority

- Constitution §6: aligns D3, READY, and bounded repair non-escalation.
- Records Contract §§8.4, 10, 11, 31, and §39 scenarios: owns the durable
  decision, candidate currentness, target-stage reopen, and CAS semantics.
- Skill Contract §16: freezes the Stage-targeted `submit_to_develop` routing
  boundary and preserves P6/P7/P8 ownership.
- Current lifecycle architecture diagrams visualize those amended rules.

The Project Contract is unchanged because no project structure, ownership
mode, or ownership boundary changes.

## Stage Completion Decision

The Stage's `acceptance` text remains human-readable intent, not a DSL. The
Task Book contains the current structured `completion_decision` for that
Stage:

```yaml
completion_decision:
  stage_id: stage-1
  candidate_digest: sha256:<candidate>
  outcome: SATISFIED  # SATISFIED | UNSATISFIED | UNKNOWN
  basis:
    - kind: test_evidence
      summary: Required behavior was verified for this candidate.
      evidence_ref: { locator: "<opaque-p6-locator>" }
  rationale: Current authoritative facts satisfy the Stage criterion.
```

The decision names the target Stage, evaluated candidate, bounded outcome,
authoritative basis, relevant P6 Evidence locators, and concise rationale.
`UNKNOWN` is distinct from `UNSATISFIED`. Neither allows `COMPLETE`.

P7 owns this lifecycle decision and Task publication. P6 exclusively owns
Test execution, Evidence schema/truth, integrity, and locator resolution.
Human or subjective acceptance remains `UNKNOWN` until an existing legitimate
human-observation Evidence/control path supplies cited authority. Hidden chat
memory is not a basis.

## Task Completion Decision

Focused Foundation review found that Task-level `acceptance` had the same
residual gap: READY publication alone was being treated as P7's assertion
without reconstructable candidate-bound authority. The Task Book therefore
also contains a distinct `task_completion_decision` with:

- `candidate_digest`
- the same `SATISFIED` / `UNSATISFIED` / `UNKNOWN` outcome enum
- bounded authoritative `basis`
- concise reconstructable `rationale`
- optional bounded `supersedes` summary

It may reference repository/Task facts, current Stage decisions, final P6
Evidence, and legitimate human-observation Evidence. It may not rely on hidden
chat, raw Test Reports, uncited user statements, successful writes, or
`TEST_PASS` alone. A C1 Task decision cannot support READY on C2.

## Completion and READY

`IN_PROGRESS` → `COMPLETE` requires a current-candidate `SATISFIED` decision,
satisfied required Stage Test obligations, and no unresolved required-test
blocker. Source-write success, `TEST_PASS`, and `TEST_COMPLETE` are each
insufficient by themselves.

READY additionally requires every Stage to be `COMPLETE`, every Stage decision
relied upon for READY to be `SATISFIED` and current for the actual candidate,
current/satisfied final Task verification, and a Task Completion Decision that
is `SATISFIED` and current for that candidate. If the Task decision is
`UNKNOWN`, READY is forbidden even when every Stage decision and final Test
is satisfied.
READY remains Develop-owned and grants no Submit authorization, Commit, or
Push.

## Revalidation and repair

Entering `COMPLETE` requires §8.4 conditions to hold for the actual candidate
at publication. Thereafter the status records validly established completion;
it does not promise that its decision remains current for every later
candidate. A `COMPLETE` Stage may remain `COMPLETE` while P7 publishes a
replacement `SATISFIED` decision for C2 through Task CAS. Its stale C1
decision is historical progress only and cannot support READY meanwhile. If
C2 evaluation is `UNSATISFIED` or `UNKNOWN`, P7 moves the Stage to
`IN_PROGRESS`, or to existing `BLOCKED` semantics only for an
external/human/policy stop. No `REVALIDATING` state is added.

For READY repair, `submit_to_develop` must carry a nonempty,
deterministically mapped `target_stage_ids` list in addition to Task,
candidate, blocker, optional Evidence, and bounded capability data. If P8
cannot map a blocker to current Task Stage authority, it returns unresolved
routing and guesses nothing.

Given a valid current handoff, P7 atomically publishes through expected
revision:

```text
Task READY_FOR_REVIEW → IN_PROGRESS
target Stages COMPLETE → IN_PROGRESS
old target decisions → superseded and replaced by UNKNOWN repair decisions
old Task decision → superseded and replaced by UNKNOWN repair decision
```

The superseded summary records the prior candidate, outcome, and concise
rationale without creating another canonical record. Non-target Stages need not
be blindly reopened, but before READY returns on C2 every Stage decision
relied upon for READY and the Task Completion Decision must be
`SATISFIED` and current for C2.

## Preserved invariants

- exactly three canonical development records
- exactly four top-level Skills
- Task states: DRAFT, IN_PROGRESS, READY_FOR_REVIEW, CANCELED
- Stage states: PENDING, IN_PROGRESS, BLOCKED, COMPLETE
- Task Book expected-revision atomic conditional publication
- P6 Evidence authority; no second P7 Evidence system
- P7 Task mutation and repair execution
- P8 review/routing without Task writes
- no S13, new submission permission, Commit/Push escalation, or global human gate
- Develop Session remains OPEN, SEALED, or ABORTED and advisory

## Foundation acceptance cases

FND2-E01 through FND2-E12 are normative scenarios in Records Contract §39.
They cover normal completion, PASS/acceptance separation, required failure,
stale decisions, subjective acceptance, READY, valid and invalid targeted
repair, C1→C2 invalidation, non-target currentness, and taxonomy/authority.

## Downstream work and re-audit

FA-2 Batch 5 must be re-planned and implemented against this amended
authority. Runtime work may add Task schema validation and P7/P8 protocol
support only after independent re-audit accepts the amendment. Re-audit must
verify decision reconstructability, P6 locator ownership, candidate
currentness, deterministic Stage targeting, atomic reopen, non-target
revalidation, CAS conflict behavior, and permission non-escalation.

Batch 6, P9, DIVE, unrelated FA-2 findings, and runtime Batch-5 closure remain
outside this amendment.
