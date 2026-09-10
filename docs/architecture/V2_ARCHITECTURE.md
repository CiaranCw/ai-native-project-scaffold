# v2 Top-Level Architecture

This document explains **how the frozen Constitution parts relate**. Rules live in [../contracts/CONSTITUTION.md](../contracts/CONSTITUTION.md). This file is maps, lifecycles, and boundaries — not a second constitution.

P0 freezes architecture **shape**. It does not freeze schemas, APIs, Skill file trees, or runtime.

---

## Two layers

```text
┌─────────────────────────────────────────────────────────────┐
│  Distribution Layer  (this repository)                       │
│  Product definition, later Skill packs, contracts, tools     │
│  Not the host game / app                                     │
└────────────────────────────┬────────────────────────────────┘
                             │ adopt (P1+)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Adopted Project Layer  (host repository)                    │
│  Layer 1  AGENTS.md          router                          │
│  Layer 2  docs/project/      human knowledge                 │
│  Layer 3  .scaffold/         machine state                   │
│  Thin client entries (Claude / Cursor / future)              │
│  Business code remains the host’s — scaffold is not a        │
│  mandatory business runtime                                  │
└─────────────────────────────────────────────────────────────┘
```

A new Agent working **on this distribution repo** during P0 starts at [../../README.md](../../README.md), then Constitution, then this file.

A new Agent working **on an adopted host** (after P2+) starts at that host’s `AGENTS.md`. That file does not exist in this distribution tree at P0; it is a host-project artifact.

---

## End-to-end lifecycle

```text
Ordinary project
        │
        ▼
Adoption / Bootstrap          ← not a Skill; first-attach path of Understand
        │
        ▼
Understand Full
        │
        ▼
Scaffold-managed project
        │
        ▼
Task Book                     ← “what we intend to do”
        │
        ▼
   ┌────────────┐     invoke      ┌────────────┐
   │  Develop   │ ◄─────────────► │    Test    │
   │ D1 Prepare │                 │ native +   │
   │ D2 Implement│                │ advanced   │
   │ D3 Validate│                 └────────────┘
   └─────┬──────┘
         │ stages complete + candidate-bound Stage
         │ completion decisions SATISFIED/current
         │ + final required tests satisfy acceptance
         │ + Task Completion Decision SATISFIED/current
         ▼
 READY_FOR_REVIEW              ← Develop MUST stop here
         │                     ← TEST_PASS MUST NOT auto-start Submit
         │                     ← failed required tests MUST NOT arrive here
         ▼
      Submit                   ← only Skill that may durably finalize / Push
         │
         ├─ S1 Intake
         ├─ S2 Delta Classification
         ├─ S3 Structural Review      ← real diff, not agent memory
         ├─ S4 Knowledge Consistency
         ├─ S5 Test Completeness      ← TEST_COMPLETE for this candidate
         │         │
         │         ▼
         │  READY_FOR_HUMAN_APPROVAL  ← still not S10-authorized
         ├─ S6 Human Approval         ← SUBMIT_AUTHORIZED for S10; Push separate
         ├─ S7 Repository Sync
         ├─ S8 if candidate changed → S3/S4/S5 → S6 (Candidate B)
         ├─ S9 Finalize Bundle        ← Change Record + permitted support
         ├─ S10 Commit / Durable Finalization
         │                            ← SUBMIT_AUTHORIZED; SCM Commit or no-SCM
         │                               atomic/conflict-detectable publication
         ├─ S11 Optional Push / N/A   ← extra authorization if push-capable SCM
         └─ S12 Cleanup               ← Develop Session after successful S10
                │
                ▼
         Understand Refresh if knowledge drifted
                │
                ▼
         Next development round
```

Submit MUST accept work that **never** used Develop (human-only or tool-only diffs). In that case there is no Task Book / Session to consult; S2 still classifies against the real tree.

---

## Four-Skill interaction

```text
                    Understand
                 Full / Refresh
                 / Compatibility
                         │
                         │ writes/maintains
                         ▼
              Project knowledge (3 layers)
                         │
            ┌────────────┼────────────────┐
            ▼            ▼                ▼
        Develop        Test            Submit
            │            ▲                │
            └────────────┘                │
         Develop invokes Test             │
         for stage / final tests          │
                                          │
                    Submit re-reads real │
                    project/SCM if any   │
                    Submit MAY call Test  │
                    Submit MAY require    │
                    Understand Refresh    │
```

| From | To | Why |
| --- | --- | --- |
| Understand | all others | Authority map, commands, tests, constraints, freshness |
| Develop | Test | Stage validation and Task final tests |
| Develop | — | Stops at READY_FOR_REVIEW; **no S10 durable finalization / Commit** |
| Test | caller | Scoped evidence; **never** “you may submit” |
| Submit | real tree | Sole authority for “what changed” |
| Submit | Test | Completeness / re-test after sync |
| Submit | Understand | Refresh when knowledge is stale |
| Submit | finalization capability | SCM Commit or no-SCM durable finalization after `SUBMIT_AUTHORIZED`; optional Push separately authorized |

---

## Adoption path (not a fifth Skill)

Constraints (normative text: Constitution §3):

```text
read-only discovery
    → adoption plan
    → apply minimal scaffold integration
    → Understand Full
    → validation
    → activate
```

Architecture implication: Adoption is a **mode of first contact**, executed with Understand Full as the knowledge-producing step. Failure MUST be resumable. Integration MUST be reversible. Dirty trees are in-scope. Existing user docs are inputs, not trash.

P1 owns the contract. This diagram MUST NOT be implemented at P0.

---

## Task lifecycle

```text
create / accept Task Book
        │
        ▼
   for each Stage:
        D1 Prepare  →  D2 Implement  →  D3 Validate (Test)
        │
        │  D1: upstream-currentness; safe sync if permitted;
        │      MUST NOT destroy dirty work; Refresh if sync
        │      materially changes project facts
        │  stage TEST_PASS ≠ task done
        │  Stage Completion Decision:
        │      SATISFIED | UNSATISFIED | UNKNOWN
        │      bound to the actual candidate
        │  Entering COMPLETE requires current SATISFIED;
        │  later stale COMPLETE records historical progress only
        ▼
   Final Tests (Test Skill, scope = Task Final Test)
        │
        ├─ required tests fail / acceptance unmet
        │     → remain in Develop ↔ Test
        │
        └─ stages complete
           + every Stage completion decision SATISFIED/current
           + final required tests satisfy defined acceptance
           + Task Completion Decision SATISFIED/current
                │
                ▼
           READY_FOR_REVIEW
                │
                ×  MUST NOT perform S10 / Commit
                ▼
           human starts Submit (separate Skill)
```

MUST NOT mark READY_FOR_REVIEW merely because final tests ran.

A READY repair is not an implicit status reversal. Submit may route repair
only with a current `submit_to_develop` handoff carrying deterministically
mapped `target_stage_ids`. P7, not P8, uses Task CAS to atomically reopen the
Task and those exact Stages. After C1 → C2 repair, stale target and non-target
Stage decisions cannot restore READY; every decision relied upon for READY
and the Task Completion Decision must be `SATISFIED` and current for C2. A
stale `COMPLETE` Stage may remain structurally complete during revalidation,
but cannot support READY until its decision is current. No first/last/all-Stage
fallback and no new Stage state is introduced.

### One candidate authority without Task self-reference

```text
                         P6 SINGLE CANDIDATE PROJECTION
 source/business/project/config bytes ───────────────┐
                                                     ├─► candidate_digest C
 Task substantive authority projection ─────────────┘
   goal / acceptance / scope / baseline
   Stage plan / requirement IDs / execution bindings

 Task control plane (current Task lifecycle/result bytes)
   revision / updated_at / statuses / Session links
   result locators/outcomes / Stage+Task decisions
                  └─ candidate-neutral when substantive projection is unchanged
                     because of their content class, not writer provenance
                     still visible in the complete physical Diff
                     candidate-equivalent != publication-authorized
```

P6 owns this single semantic projection for Git and no-SCM. It is
content-deterministic from currently observed authoritative content, not a
publication-provenance oracle. It is not an exclusion of `.scaffold/tasks/**`:
Task creation/removal and substantive Task authority changes alter C. All
non-Task content retains ordinary candidate effect. Malformed or
lifecycle-illegal Task content fails closed under Task schema and lifecycle
authority. The complete Task file change remains in Git/no-SCM physical
observation and Submit-S2/S3 review. Authorized Scaffold Task mutation still
requires P3 expected-revision CAS. candidate-equivalent !=
publication-authorized.

Consequently:

```text
Test Evidence(C)
  → Task Book stores Evidence locator + Decision(C) + COMPLETE/READY
  → observe_candidate == C                # no self-staleness
                                      # remaining on C does not prove CAS

source/project/substantive Task mutation
  → observe_candidate == C2
  → Evidence(C), Decision(C), review(C), authorization(C) are stale
```

This control-plane rule is separate from FA2-FND-001 C/F: C/F permits only
the deterministic S9 Finalization Bundle after review; it does not define
Task lifecycle currentness and receives no broader exception.

### Explicit requirement-to-profile execution binding

```text
Task Book (durable planned authority)
  requirement_id: task-required/check-save
  execution_binding:
    kind: test_profile
    profile_id: unit-save-check
         │
         ▼
Develop→Test carries exact R→P + selects P
         │
         ▼
P6 executes P and returns locator L
P6 resolver(L) preserves producing profile_id P
         │
         ▼
P7 may attach L only to requirement R bound to P
```

`requirement_id` is not `profile_id`; equal spelling proves nothing. Missing
or mismatched binding remains unresolved and is never guessed from position or
a sole result. Project-required profile obligations remain separate. HUMAN,
CI, and EXTERNAL P6 Evidence may directly satisfy a Task requirement through
an explicit locator without an automated profile binding.

Task Book is the **plan**. It is not proof of the final durably finalized result. Submit may discover undeclared files; those still count.

The development / handoff lifecycle has exactly three **canonical development records**: Task Book, Develop Session, Change Record. Other artifacts (Test Report / Evidence, Adoption Session, migration or analysis artifacts) MAY exist only with a different purpose, authority, lifecycle, and retention. MUST NOT duplicate those three with scratchpad / work-log / handoff-log / session-history / changelog copies.

---

## Develop Session lifecycle

```text
Develop starts → snapshot S0 (real tree)
        │
        │  session notes what Develop explicitly did
        ▼
Develop ends  → S1
        │
        │  other actors MAY edit the tree
        ▼
Submit starts → S2 (real tree wins)
        │
        ├─ DEVELOP_KNOWN
        ├─ POST_DEVELOP_ADDITIONAL
        ├─ MIXED_CHANGE
        └─ PREEXISTING_CHANGE
        │
        ×  no HUMAN_CHANGE class
        ▼
successful S10 durable finalization → clean up session (P3 defines how)
```

If Submit never succeeds, **P3** MUST define retention / expiry for abandoned sessions. P0 only forbids unbounded accumulation.

Session is a **lens** on the diff. The diff is the fact.

---

## Submit review pipeline

S2 classification is assistance. S3–S5 always run against **current real diff**.

```text
S2 classes
    │
    ▼
S3 Structural Review
    files, modules, add/delete, interfaces, deps,
    commands, config formats, test methods, layout,
    undeclared vs Task Book, unknown vs Session
    │
    ▼
S4 Knowledge Consistency
    current-head Understand Knowledge Assessment
    for knowledge-relevant S3 impacts; lexical
    token presence is not SATISFIED; superseded
    locators and mutated bytes are not SATISFIED;
    stale docs are a defect
    │
    ▼
S5 Test Completeness
    required set := f(Task Book, real diff, Test Matrix, project rules)
    extra human edits (e.g. Save) still require Save tests
    TEST_COMPLETE = terminal results + complete coverage
                    + no unresolved required-test blocker
    executing a failing required test ≠ TEST_COMPLETE
    │
    ▼
S6 Human Approval of Candidate A
    authorization = false by default
    SUBMIT_AUTHORIZED = candidate-bound S10 authorization
    for SCM Commit, this is Commit authorization
    no second COMMIT_AUTHORIZED gate; Push remains separate
    │
    ▼
S7 Repository Sync
    │
    ├─ candidate unchanged → S6 for A remains valid
    └─ candidate changed
            → Candidate A authorization void
            → S8 re-diff / re-test as needed
            → S3 / S4 / S5 as needed
            → S6 for Candidate B
    │
    ▼
S9 Finalize Bundle            ← Change Record + permitted referenced support
S10 Commit / Durable Finalization
    SCM: exact bundle in Commit
    no SCM: P8 atomic/conflict-detectable durable publication
S11 Optional Push / N/A       ← separate authorization when capability exists
S12 Cleanup                   ← Develop Session after successful S10
```

`DEVELOP_KNOWN` still receives S3–S5. It is not a fast-pass.

If S7/S8 changes the candidate, previous S6 authorization is invalid. This is a loop (`S8 → S3/S4/S5 → S6`), not a thirteenth stage. Authorization from another Submit attempt is never reusable.

---

## Change Record lifecycle

```text
final reviewed candidate
+ final test status
+ final Structural Review
+ final knowledge-update status
        │
        ▼
S9 finalize bundle            ← Change Record + deterministic referenced support
        │                        all candidate-only before S10
        │
        ▼
S10 Commit / Durable Finalization
        │
        ├─ failure/interruption → MUST NOT treat record/support as durable history
        │                        candidate support requires cleanup/recovery
        │                        MUST NOT clean Sessions as submitted
        └─ success → Change Record becomes long-term as-built
                     referenced support becomes durable/resolvable
                     using the same S9-finalized logical bundle
                     → S11 Optional Push / N/A
                     → S12 Cleanup
        │
        ×  not “Agent memory of the session”
        ×  MUST NOT create the Change Record after S10
```

P3 defines draft / final state mechanics.

On an SCM host, S10 success is the Commit containing the exact S9 Finalization
Bundle. On a no-SCM host, P8 defines a recoverable atomic or
conflict-detectable durable finalization/publication for the same logical
bundle whose success is distinguishable after restart. A no-SCM path MUST NOT
pretend a Commit occurred. Neither path rewrites the finalized bundle after
S10.

| After successful S10 durable finalization | Fate |
| --- | --- |
| Develop Session | Clean up (S12) |
| Task Book | Completed / historical |
| Change Record | Keep (finalized at S9; as-built after S10) |

---

## Understand Refresh feedback

```text
Develop or Submit detects:
  new module, deleted module, interface/command/layout change,
  stale AGENTS or module docs, Skill/contract version drift
        │
        ▼
Understand Refresh  or  Understand Compatibility
        │
        ▼
updated Layer 1–3 knowledge
        │
        ▼
later Agents load the new map (no chat required)
```

Refresh is an Understand **mode**, not a Skill. Compatibility failure MUST NOT be papered over by silently running newer Skills (Constitution §12).

---

## Client entries (future)

```text
                 Project Knowledge
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   AGENTS thin     Claude thin     Cursor thin   …future
   (router)        (pointer)       (pointer)
```

Each thin entry: where authority lives; rare client-only config; tool wiring. No duplicated project encyclopedia.

---

## Phase map

| Phase | Name | P0 boundary |
| --- | --- | --- |
| **P0** | Constitution | This freeze. No runtime. |
| **P1** | Adoption / Bootstrap Contract | First attach; dirty tree; resume; revert |
| **P2** | Project Contract | `AGENTS.md` / `docs/project/` / `.scaffold/` fields |
| **P3** | Records Contract | Task Book / Session / Change Record schemas |
| **P4** | Skill Contract & Versioning | Skill/Rule format, routing, lockfile |
| **P5** | Understand Skill | Full / Refresh / Compatibility |
| **P6** | Test Skill | Native tests + v1 test-runtime reuse |
| **P7** | Develop Skill | Staged tasks + Develop Session |
| **P8** | Submit Skill | Diff, reviews, human gate, sync, SCM Commit or no-SCM durable finalization |
| **P9** | Repair Migration | v1 Repair → Develop Repair Mode |
| **P10** | Incremental Understanding / Multi-Agent | Change-driven refresh, handoff, clients |
| **P11** | Cross-Project E2E | Multiple structurally different hosts |
| **P12** | Independent Audit / v2.0 Release | Freeze official v2.0 baseline |

P1 MUST NOT start until a human closes P0.

---

## v1 selective reuse (position only)

`ai-native-game-scaffold` v1.0.1 is **FROZEN READ-ONLY**. Decision record: [../decisions/0001-v2-clean-restart.md](../decisions/0001-v2-clean-restart.md).

v1 solved **Project Legibility** (thin) and **Game Legibility** (Evidence-centric test runtime), with Repair as a bounded test→repair loop. That **product identity does not continue**. v2’s product is the four-Skill project scaffold. v1 becomes a **qualified asset library** for later phases.

| v1 area | Likely v2 home | P0 |
| --- | --- | --- |
| Contracts / Scenario / Target Adapter / Harness / Evidence / Evidence Ref / Analysis | Test Skill — capability class B | Do not copy |
| Repair qualification, policy, isolated worktree, regression, fresh verification | Develop Repair Mode | Do not copy; P9 migrates |

Reuse gate (every candidate):

```text
inspect → qualify → map to a v2 responsibility → migrate selected pieces → revalidate under v2
```

MUST NOT vendor the v1 tree into this repository “for convenience.”

---

## Boundary reminder

This file MUST NOT be used as an excuse to add `skills/`, `src/`, `runtime/`, schemas, CLI, or examples at P0. Those trees are later phases.
