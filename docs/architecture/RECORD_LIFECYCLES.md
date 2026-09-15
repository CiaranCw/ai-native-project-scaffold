# Record Lifecycles

This document visualizes the P3 Records Contract. Rules live in [../contracts/RECORDS_CONTRACT.md](../contracts/RECORDS_CONTRACT.md). Product rules: [../contracts/CONSTITUTION.md](../contracts/CONSTITUTION.md).

It does **not** implement Develop, Submit, Test, or live host `.scaffold/` trees.

**Name note:** Submit pipeline stages are **Submit-S1 … Submit-S12**. Develop working-tree snapshots are **Session-S0**, **Session-S1**, and Submit-observed **Observed-S2**.

This distribution repository does **not** contain live Task Books, Change Records, or Sessions.

---

## Four authorities (do not collapse)

```text
 Task Book              Develop Session           Change Record           Repository
 intent / progress      one execution’s           durable submitted       physical Diff
                        observed transition       summary                 and tree

  “what we meant        “what this Develop        “what the candidate     “what files
   to do”                run observed”             actually contained”     actually changed”

        × not final Diff     × not repository truth    × not the SCM patch
        × not as-built       × not human proof         × not Task intent
```

A later Agent with no chat MUST still be able to answer all four questions. Session files are **optional assistance** and are **deleted** after successful Submit-S10 durable finalization.

---

## Canonical storage (host, not this repo)

```text
.scaffold/
├── tasks/<task-id>.yaml                         SHARED / DURABLE / GENERATED
├── changes/<change-id>.yaml                     SHARED / DURABLE / GENERATED
│                                                (candidate before S10;
│                                                 same staged/normalized bytes
│                                                 or finalized logical content
│                                                 becomes as-built after success)
└── runtime/                                     LOCAL / TEMPORARY
    ├── develop-sessions/<dev-id>/
    │   ├── session.yaml                         overlays + coverage
    │   ├── files.yaml                           Develop-touched only
    │   └── patches/                             optional; no secrets
    ├── adoption-sessions/<adopt-id>/
    │   └── session.yaml                         delete after activation
    └── understand-assessments/
        ├── <ka-id>/
        │   └── assessment.yaml                   S4 supporting artifact;
        │                                        not a canonical record
        └── heads/<binding-digest>/
            └── head.yaml                        current Assessment authority
                                                 for one (candidate, impact) binding
    ├── repair-state/<task-id>.yaml              supporting Repair recovery;
                                                 not a canonical record
    ├── migration-executions/<mig-id>/           P5 operational artifact;
    │   ├── execution.yaml                       not a canonical record
    │   └── plan.yaml
    ├── understand-currentness/                  supporting incremental
        ├── <uc-id>/snapshot.yaml                understanding currentness;
        ├── heads/project/head.yaml              not a canonical record
        ├── completions/<rc-id>/                 refresh-completion receipts;
        │   ├── completion.yaml                  supporting, not canonical
        │   └── result.yaml
        └── handoff.yaml                         derived summary only
    └── test-plans/                              supporting Scenario-Aware
        ├── <plan_id>/plan.yaml                  Verification plans;
        └── heads/<task-id>/<requirement-id>/    Test-owned, not canonical
            head.yaml
```

Do not add another `.scaffold/` root namespace. Do not create these directories in this distribution repository.

---

## Task lifecycle

```text
 create Task Book
   goal       = what we want
   acceptance = how we know the whole Task is done
        │
        ▼
     DRAFT
        │  accepted as the active plan
        ▼
   IN_PROGRESS
        │
        │   for each Stage:
        │     PENDING → IN_PROGRESS ⇄ Test
        │                      │
        │                      ├─ required tests FAIL → stay non-complete
        │                      ├─ acceptance decision UNKNOWN/UNSATISFIED
        │                      │     → stay non-complete
        │                      └─ candidate-bound completion decision SATISFIED
        │                         + required tests meet defined acceptance
        │                         + no required-test blocker
        │                                → Stage COMPLETE
        ▼
 TASK_COMPLETE (derived: all required stages COMPLETE)
        │
        ×  structural status aggregation only
        ×  not current-candidate Stage or Task acceptance
        ×  not TEST_COMPLETE
        ×  not submit authorization
        ▼
   Task-level final required tests
        │
        ├─ FAIL / acceptance unmet → remain IN_PROGRESS (Develop ↔ Test)
        │
        └─ stages COMPLETE
           + every Stage completion decision current for candidate
           + final required tests satisfy defined acceptance
           + Task Completion Decision SATISFIED/current for candidate
           + no required blocker
                ▼
         READY_FOR_REVIEW          ← Develop MUST stop here
                │                     MUST NOT perform S10 / Commit
                │                     MUST NOT mark this merely because tests ran
                │                     structured Task decision; no acceptance_met boolean
                ▼
             Submit (separate Skill)
                │
                │  S3–S6 review the REVIEWED CANDIDATE DIFF
                │  Task Book MUST NOT be mutated at S9
                ▼
         Submit-S9 deterministic Finalization Bundle
         (Change Record + referenced support; not a Task Book edit)
                │
                ▼
         Submit-S10 Commit / Durable Finalization
                │
                ├─ FAIL / INTERRUPT → Task Book still live
                │         status is NOT “submitted history”
                │
                └─ SUCCESS → Task Book historical / generally immutable
                             (contextual: durable Change Record lists this task
                              AND authoritative S10 success evidence
                              establishes that durable record)
                             MUST NOT rewrite the plan to absorb unplanned Diff
```

Lightweight tasks use **the same schema** with **one** Stage.

No Task Book: Submit still starts; **TASK_COMPLETE = NOT APPLICABLE**. Do not invent a fake Task Book.

### Candidate currentness across Task publication

```text
P6 candidate C
   = source/business/project/config physical content
   + semantic substantive Task authority projection
       (goal, acceptance, scope, baseline, Stage/requirement plan,
        explicit requirement→profile execution bindings)

current Task control-plane facts
   revision / updated_at / statuses / Session links
   Evidence locators/outcomes / completion decisions
        │
        ├─ complete Task Book byte change remains in real Diff
        └─ substantive projection unchanged → P6 candidate remains C
           (content-deterministic; not writer-path knowledge)

source/project/substantive Task change → P6 candidate C2
        └─ old C Evidence/decisions/review/authorization stale
```

This is one P6-owned candidate projection, not a P7 digest and not a blanket
`.scaffold/tasks/**` exclusion. Creating/removing a Task, changing intent or
requirements, or mixing such changes into progress publication is
candidate-significant. Malformed or lifecycle-illegal Task content gains no
lifecycle authority. A non-CAS write of identical control-plane bytes remains
candidate-equivalent and is still not publication-authorized.
**candidate-equivalent != publication-authorized.** Git/no-SCM physical
observation and Submit review still see every changed Task byte.

### Planned requirement execution binding

```text
Task required_tests entry (durable)
  requirement_id = task-required/check-save
  execution_binding.profile_id = unit-save-check
        │
        ▼
Develop→Test: exact R→P mapping; select P
        │
        ▼
P6 public locator L; resolver(L).profile_id = P
        │
        ▼
P7 attaches L to R only because current Task authority says R→P
```

No explicit binding means no fresh-execution attachment by equal names, list
position, or guessing. A mismatched producing profile cannot satisfy R.
Project-required profiles remain separate from Task requirement identities.
An existing legitimate HUMAN/CI/EXTERNAL P6 locator may be cited directly.

```text
 READY_FOR_REVIEW
      │
      │ valid current submit_to_develop handoff
      │ + explicit deterministically mapped target_stage_ids
      │ + Task expected-revision / atomic conditional publication
      ▼
 IN_PROGRESS
      └─ exact target Stages COMPLETE → IN_PROGRESS
         old SATISFIED decisions → superseded / UNKNOWN for repair

 C1 → repair mutation → C2
      └─ target and non-target Stage decisions relied upon for READY
         must be SATISFIED and current for C2 before READY returns
         + Task Completion Decision must be SATISFIED/current for C2

 READY_FOR_REVIEW + no valid Stage-targeted repair handoff
      → no reopen; no first/last/all-Stage guess

 CANCELED  → explicit; Sessions not silently deleted
```

---

## Develop Session lifecycle

```text
 Develop starts
        │
        ▼
 Session-S0
   baseline identity
 + workspace overlay vs baseline
   (dirty / modified / deleted / untracked)
   coverage: complete | partial | unavailable
 + files.yaml before-digest of Develop-touched paths
   (captured BEFORE first mutation)
        │
        × overlay membership ≠ Develop attribution
        ▼
      OPEN  ──────────────────────────────► ABORTED
        │                                   (no trustworthy Session-S1;
        │                                    not acceptance of current bytes;
        │                                    observed_success remains attribution,
        │                                    not DEVELOP_KNOWN;
        │                                    unexplained drift remains durable)
        │ Develop work (may invoke Test)
        ▼
 Session-S1
   end-of-session workspace overlay
   (same baseline; same coverage class)
 + files.yaml after kind/digest/metadata
   optional safe text patch
        │
        ▼
     SEALED   ← SHOULD be immutable
        │
        │ retained while Submit incomplete or blocked
        │ OPEN Sessions MUST NOT be silently deleted
        ▼
 Submit observes Observed-S2 (fresh; not stored as Session truth)
        │
        ▼
 successful authorized S10 durable finalization
 + durable Change Record
        │
        ▼
 Submit-S12 MUST delete corresponding
 completed SEALED Session directories
        │
        × Push is NOT required
        × no Session status named SUBMITTED
        × OPEN conflict → surface; do not pretend cleanup succeeded
```

```text
 Repository / Observed-S2
        wins over
 Session memory / Session-S1
        wins over
 Agent chat
```

---

## Multiple Sessions (composition)

```text
 Session 1 SEALED S1 after-state  ==  Session 2 before-state   → chain OK
 Session 1 SEALED S1 after-state  ≠   Session 2 before-state   → GAP
                                                              → not DEVELOP_KNOWN
                                                              → MIXED_CHANGE if Develop touched the path

 Latest SEALED S1  vs  Observed-S2
        │
        ├─ equal + chain + not preexisting dirty → DEVELOP_KNOWN possible
        └─ differ → MIXED_CHANGE
```

Order Sessions by `created_at`, then `record_id`.

---

## Submit provenance (advisory)

```text
 SEALED Sessions
   (S0/S1 workspace overlays + Develop-touched files.yaml)
 + Observed-S2 actual Diff
                        │
                        ▼
              classify each changed path
                        │
        ┌───────────────┼───────────────────────────────┐
        ▼               ▼               ▼               ▼
 MIXED_CHANGE   PREEXISTING     POST_DEVELOP      DEVELOP_KNOWN
 (highest         _CHANGE        _ADDITIONAL       (full Session
  review)         (S2 still      (S1 overlay       coverage)
                  equals S0)      proves still
                                  baseline at
                                  Develop end)
        │
        └──────────────► UNATTRIBUTED (fallback; not an error)

 Precedence (first logical match wins):
   1 MIXED_CHANGE
   2 PREEXISTING_CHANGE
   3 POST_DEVELOP_ADDITIONAL
   4 DEVELOP_KNOWN
   5 UNATTRIBUTED

 Dirty then Develop-touched            → MIXED_CHANGE
 Develop-touched then S2 ≠ S1          → MIXED_CHANGE (not POST)
 S0 dirty, never touched, S2 = S0      → PREEXISTING_CHANGE
                                        only if no durable unexplained-drift
                                        fact contradicts the inference
 S0 dirty, never touched, S2 ≠ S0      → not pure PREEXISTING → UNATTRIBUTED
                                        (or another provable class)
 durable unexplained fact vs later
 Session overlays                      → MUST NOT become inherited_baseline
                                        merely because the earlier Session
                                        was aborted or cleaned up
 not dirty, never touched,
 S1 overlay shows baseline-equivalent,
 S2 shows the change                   → POST_DEVELOP_ADDITIONAL
 “not in S0 and exists at S2” alone    → NOT enough for POST
 S1 coverage partial/unavailable       → UNATTRIBUTED
 timestamps / mtimes alone             → MUST NOT prove POST
 No Session / cannot tell              → UNATTRIBUTED

 × no HUMAN_CHANGE class
 × classes do not override the actual Diff
 × DEVELOP_KNOWN is not a review skip
```

Advisory review attention order: MIXED → POST → PREEXISTING → UNATTRIBUTED → DEVELOP_KNOWN. **All** actual Diff still requires appropriate review (P8).

---

## Change Record publication

```text
 REVIEWED CANDIDATE DIFF
   (real project/change-set through S3/S4/S5/S6,
    and S8 loop if needed)
        │
        ▼
 Submit-S9 Finalization Bundle
   exact .scaffold/changes/<change-id>.yaml
   + zero or more deterministic support artifacts
     required by its durable opaque references
        │
        │  path_summary describes REVIEWED CANDIDATE DIFF
        │  MUST NOT list/count this Change Record file itself
        │  support content derives only from pre-S6 validated
        │  authority/Evidence and adds no business intent
        │
        ▼
 S10 FINALIZATION CANDIDATE
   = reviewed candidate
   + exact deterministic S9 Finalization Bundle
        │
        ×  MUST NOT wait until after S10 to create the record
        ×  MUST NOT store this Commit’s SHA inside the file
        ×  MUST NOT persist submitted: true
        ×  MUST NOT persist submit_authorized: true as permission
        ×  MUST NOT mutate Task Books at S9
        ×  any mutation outside the permitted bundle is
           NOT silently review-exempt
        ▼
 Submit-S10 Commit / Durable Finalization attempt
        │
        ├─ FAIL / INTERRUPT ──► still a candidate
        │           MUST NOT call it submitted history
        │           support artifacts require cleanup/recovery
        │           MUST NOT clean completed Sessions as submitted
        │           unchanged finalized bundle → retry
        │           material reviewed-diff change → regenerate first
        │
        └─ SUCCESS ► same S9-finalized bundle
                     becomes durable as-built + referenced support
                     SCM: exact staged/normalized bundle in Commit
                     no SCM: P8 atomic/conflict-detectable durable publication
                     success distinguishable after restart
                     Submit-S11 optional Push / N/A (separate auth if present)
                     Submit-S12 MUST clean completed SEALED Sessions
```

```text
 S9-finalized / no successful S10            = candidate Change Record
 Same logical content in successful S10      = durable as-built Change Record
```

No second operation solely to flip a status field. No post-S10 record rewrite to become “submitted.” No-SCM finalization MUST NOT pretend an SCM Commit occurred.

---

## Task Book vs Change Record (after success)

```text
 Historical Task Book              Durable Change Record           Finalized reality
 remaining intent & stages         compact as-built summary        exact S10 result
 Session IDs if present:           of REVIEWED CANDIDATE DIFF      (SCM Commit or
  advisory / non-required          provenance COUNTS not            no-SCM publication
  (no S9 mutation required)        Session directories              includes record)
                                   task_book_ids → Task(s)

 MUST NOT copy Session hashes/patches into the Task Book.
 MUST NOT rewrite the Task Book to pretend extra Diff was always planned.
 MUST NOT add a Task → Change back-reference.
```

---

## Session IDs on the Task Book

```text
 Active Task Book
   develop_session_ids  →  always operational / advisory
                           never required to interpret the Task
                           MAY become non-resolvable after cleanup
        │
        │  optional compact/remove only BEFORE S3–S6 + S6 auth
        │
        ×  Submit-S9 MUST NOT mutate the Task Book
        │    (no compaction, no Change back-reference,
        │     no cosmetic cleanup)
        ▼
 Submit-S9 writes no Task mutation;
   Finalization Bundle contains the Change Record
   and only permitted referenced support artifacts
   durable provenance → Change Record summary
        │
        ▼
 Submit-S12 MUST delete completed SEALED Session directories
        │
        ▼
 Historical Task Book already understandable without runtime/
```

Submit-S12 MUST NOT erase durable unexplained truth living outside ephemeral
Session runtime (`.scaffold/ext/develop/unexplained.yaml`).

---

## Adoption Session lifecycle

```text
 Adoption starts
        │
        ▼
 temporary Adoption Session
   id, baseline, plan identity/digest,
   completed steps, applied mutations,
   pending validation, OPEN|BLOCKED|INTERRUPTED
        │
        ├─ interrupted / blocked → retain → resume
        │     P5 MUST revalidate plan identity, host, approval
        │     observed_approved ≠ standing permission
        │
        ├─ abandoned → explicit cleanup MAY delete
        │
        └─ activation success → DELETE Session
              (no persisted ACTIVATED record)

 MUST NOT silently delete recoverable adoption state.
 MUST NOT become a fourth canonical development record.
```

LOCAL / TEMPORARY / DELETE AFTER SUCCESSFUL ACTIVATION.

---

## Migration Execution lifecycle (bounded operational artifact)

```text
 PREPARED
   bound to plan + source host + source lock
   + relevant generations + target intent + mutation envelope
   × not persisted approval
   │ revalidate binding + current approval before first mutation
   ▼
 APPLYING
   persistent mutation begun
   checkpoints: completed / remaining / expected observed state
   rollback/recovery only where defined; no universal rollback
   │
   ▼
 VALIDATING
   actions ran; host is NOT yet successfully migrated
   │
   ├─ required validation succeeds ───────────────► COMPLETED
   │                                                update/clear applicable
   │                                                P2 maintenance/recovery state
   │
   └─ interruption / uncertainty / divergence ───► RECOVERY_REQUIRED
                                                    observe actual host
                                                    + read checkpoints
                                                    + compare approved envelope
                                                          │
                   provable expected prefix/checkpoint ────┤ resume MAY proceed
                   unexpected/material divergence ─────────┤ approval inapplicable
                                                          │ re-evaluate, new plan,
                                                          │ human re-approval
                                                          ▼
                                                        ABORTED only if
                                                        no mutation occurred OR
                                                        coherent safe reversion proven
```

Expected approved Apply checkpoints do not themselves invalidate plan approval. Unknown partial mutation MUST remain RECOVERY_REQUIRED, never ABORTED. The artifact survives while needed for recovery and is not a fourth canonical development record or a Change Record replacement.

---

## Cleanup summary

```text
                    after successful
                    authorized S10 durable finalization
                    + durable Change Record

 Develop Sessions   ──► Submit-S12 MUST delete corresponding
                         completed SEALED Session directories
                         OPEN: never silent-delete; surface conflicts
                         cleanup failure: report + retry;
                         do not invalidate the durable finalization
 Task Book          ──► historical; stop mutating
                         (no S9 mutation)
 Change Record      ──► keep (already durably finalized)
 Adoption Session   ──► delete on activation success (different lifecycle)
 Push               ──► not required for Develop Session cleanup
```

Draft/canceled Task Books with no durable history: explicit user/project action only. Durably finalized Change Records: no routine deletion.

---

## Concurrency (Task Book)

```text
 Agent A reads revision N        Agent B reads revision N
             │                                │
             └──── atomic conditional publication ────┘
                              │
                    only one may publish N+1
                              │
                    other writer gets conflict/block
                              │
                    re-read → reconcile/re-plan
                              │
                    retry as a new mutation
```

Plain read N → re-read N → write N+1 is insufficient without atomic conditional publication or safe serialization. P3 does not require a central/distributed lock service and does not freeze or forbid a particular safe mechanism; implementations may use CAS, local/per-record locking, serialization, transactions, centralized or distributed coordination where appropriate, or equivalent conflict-producing publication. If safety cannot be established, mutation blocks.

---

## No-SCM

```text
 baseline.kind: none | unavailable
        │
        × do not invent SHA / changelist
        │
        ▼
 Session digests still compare local files
 Change Record still summarizes the candidate
 Submit-S10 uses P8 atomic/conflict-detectable durable finalization
 success is distinguishable after restart
 failure/interruption creates no submitted history or Session cleanup
 S11 Push is N/A
 × do not pretend Commit occurred
```

---

## What later phases own (not drawn as runtime here)

```text
 P4  skills.lock / compatibility
 P5  Understand + Adoption Session use
 P6  Evidence schema / test execution
 P7  creating Task Books & sealing Sessions
 P8  Observed-S2, classification execution,
     reviews, SUBMIT_AUTHORIZED, SCM Commit or
     no-SCM durable finalization, optional Push, cleanup
```

This file is maps only. For record representation/lifecycle topics, [../contracts/RECORDS_CONTRACT.md](../contracts/RECORDS_CONTRACT.md) governs this visualization; Adoption behavior remains owned by P1. Product-wide conflicts remain governed by the Constitution.
