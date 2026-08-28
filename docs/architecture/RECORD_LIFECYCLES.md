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

A later Agent with no chat MUST still be able to answer all four questions. Session files are **optional assistance** and are **deleted** after successful Commit.

---

## Canonical storage (host, not this repo)

```text
.scaffold/
├── tasks/<task-id>.yaml                         SHARED / DURABLE / GENERATED
├── changes/<change-id>.yaml                     SHARED / DURABLE / GENERATED
│                                                (candidate before Commit;
│                                                 same staged/normalized bytes
│                                                 become as-built after success)
└── runtime/                                     LOCAL / TEMPORARY
    ├── develop-sessions/<dev-id>/
    │   ├── session.yaml                         overlays + coverage
    │   ├── files.yaml                           Develop-touched only
    │   └── patches/                             optional; no secrets
    └── adoption-sessions/<adopt-id>/
        └── session.yaml                         delete after activation
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
        │                      └─ acceptance + required tests meet
        │                         defined acceptance + no required-test blocker
        │                                → Stage COMPLETE
        ▼
 TASK_COMPLETE (derived: all required stages COMPLETE)
        │
        ×  not TEST_COMPLETE
        ×  not submit authorization
        ▼
   Task-level final required tests
        │
        ├─ FAIL / acceptance unmet → remain IN_PROGRESS (Develop ↔ Test)
        │
        └─ stages COMPLETE
           + final required tests satisfy defined acceptance
           + declared Task-level acceptance satisfied
                ▼
         READY_FOR_REVIEW          ← Develop MUST stop here
                │                     MUST NOT Commit
                │                     MUST NOT mark this merely because tests ran
                │                     no acceptance_met boolean
                ▼
             Submit (separate Skill)
                │
                │  S3–S6 review the REVIEWED CANDIDATE DIFF
                │  Task Book MUST NOT be mutated at S9
                ▼
         Submit-S9 Change Record only
         (deterministic artifact; not a Task Book edit)
                │
                ▼
         Submit-S10 Commit
                │
                ├─ FAIL → Task Book still live
                │         status is NOT “submitted history”
                │
                └─ SUCCESS → Task Book historical / generally immutable
                             (contextual: durable Change Record lists this task
                              AND repository history contains that record)
                             MUST NOT rewrite the plan to absorb unplanned Diff
```

Lightweight tasks use **the same schema** with **one** Stage.

No Task Book: Submit still starts; **TASK_COMPLETE = NOT APPLICABLE**. Do not invent a fake Task Book.

```text
 READY_FOR_REVIEW ──(more Develop before durable Change Record)──► IN_PROGRESS
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
        │                                   (no trustworthy Session-S1)
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
 successful authorized Commit
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
 S0 dirty, never touched, S2 ≠ S0      → not pure PREEXISTING → UNATTRIBUTED
                                        (or another provable class)
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
 Submit-S9  write/replace ONLY
 .scaffold/changes/<change-id>.yaml
        │
        │  path_summary describes REVIEWED CANDIDATE DIFF
        │  MUST NOT list/count this Change Record file itself
        │
        ▼
 COMMIT CANDIDATE TREE
   = reviewed candidate
   + deterministic S9 Change Record artifact
        │
        ×  MUST NOT wait until after Commit to create the file
        ×  MUST NOT store this Commit’s SHA inside the file
        ×  MUST NOT persist submitted: true
        ×  MUST NOT persist submit_authorized: true as permission
        ×  MUST NOT mutate Task Books at S9
        ×  any other S9 mutation is NOT silently review-exempt
        ▼
 Submit-S10 Commit attempt
        │
        ├─ FAIL ──► still a candidate
        │           MUST NOT call it submitted history
        │           unchanged staged/normalized record → retry
        │           material reviewed-diff change → regenerate first
        │
        └─ SUCCESS ► staged/normalized record bytes
                     become durable as-built
                     (working-tree CRLF/LF MAY differ from the blob)
                     SCM history binds Commit ↔ record
                     full Commit Diff INCLUDES the Change Record file
                     Submit-S11 optional Push (separate auth)
                     Submit-S12 MUST clean completed SEALED Sessions
```

```text
 Uncommitted / not in successful Commit     = candidate Change Record
 Same staged/normalized bytes in a
 successful Commit                          = durable as-built Change Record
```

No second Commit solely to flip a status field. No post-Commit record rewrite to become “submitted.”

---

## Task Book vs Change Record (after success)

```text
 Historical Task Book              Durable Change Record           Repository
 remaining intent & stages         compact as-built summary        exact Commit Diff
 Session IDs if present:           of REVIEWED CANDIDATE DIFF      (includes Change
  advisory / non-required          provenance COUNTS not            Record artifact)
  (no S9 mutation required)        Session directories
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
 Submit-S9 writes Change Record only
   durable provenance → Change Record summary
        │
        ▼
 Submit-S12 MUST delete completed SEALED Session directories
        │
        ▼
 Historical Task Book already understandable without runtime/
```

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

## Cleanup summary

```text
                    after successful
                    authorized Commit
                    + durable Change Record

 Develop Sessions   ──► Submit-S12 MUST delete corresponding
                         completed SEALED Session directories
                         OPEN: never silent-delete; surface conflicts
                         cleanup failure: report + retry;
                         do not invalidate the Commit
 Task Book          ──► historical; stop mutating
                         (no S9 mutation)
 Change Record      ──► keep (already in the Commit)
 Adoption Session   ──► delete on activation success (different lifecycle)
 Push               ──► not required for Develop Session cleanup
```

Draft/canceled Task Books with no durable history: explicit user/project action only. Committed Change Records: no routine deletion.

---

## Concurrency (Task Book)

```text
 Agent A reads revision N
 Agent B writes revision N+1
 Agent A writes expecting N
        │
        ▼
 MUST NOT overwrite
 re-read → reconcile → increment
```

No lock service. Develop Sessions use distinct IDs per execution.

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
 durable association to SCM history MAY be limited  → P8
```

---

## What later phases own (not drawn as runtime here)

```text
 P4  skills.lock / compatibility
 P5  Understand + Adoption Session use
 P6  Evidence schema / test execution
 P7  creating Task Books & sealing Sessions
 P8  Observed-S2, classification execution,
     reviews, human gate, Commit/Push, cleanup
```

This file is maps only. If it conflicts with [../contracts/RECORDS_CONTRACT.md](../contracts/RECORDS_CONTRACT.md), the Records Contract wins; if both conflict with the Constitution, the Constitution wins.
