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
         │ stages complete + acceptance met
         │ + final required tests satisfy acceptance
         ▼
 READY_FOR_REVIEW              ← Develop MUST stop here
         │                     ← TEST_PASS MUST NOT auto-start Submit
         │                     ← failed required tests MUST NOT arrive here
         ▼
      Submit                   ← only Skill that may Commit / Push
         │
         ├─ S1 Intake
         ├─ S2 Delta Classification
         ├─ S3 Structural Review      ← real diff, not agent memory
         ├─ S4 Knowledge Consistency
         ├─ S5 Test Completeness      ← TEST_COMPLETE for this candidate
         │         │
         │         ▼
         │  READY_FOR_HUMAN_APPROVAL  ← still not Commit
         ├─ S6 Human Approval         ← candidate-bound; Commit ≠ Push
         ├─ S7 Repository Sync
         ├─ S8 if candidate changed → S3/S4/S5 → S6 (Candidate B)
         ├─ S9 Finalize Records       ← Change Record for this candidate
         ├─ S10 Commit                ← requires candidate-bound authorization
         ├─ S11 Optional Push         ← extra authorization
         └─ S12 Cleanup               ← Develop Session after successful Commit
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
                    Submit re-reads SCM   │
                    Submit MAY call Test  │
                    Submit MAY require    │
                    Understand Refresh    │
```

| From | To | Why |
| --- | --- | --- |
| Understand | all others | Authority map, commands, tests, constraints, freshness |
| Develop | Test | Stage validation and Task final tests |
| Develop | — | Stops at READY_FOR_REVIEW; **no Commit** |
| Test | caller | Scoped evidence; **never** “you may submit” |
| Submit | real tree | Sole authority for “what changed” |
| Submit | Test | Completeness / re-test after sync |
| Submit | Understand | Refresh when knowledge is stale |
| Submit | SCM | Commit / optional Push after human gate |

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
        ▼
   Final Tests (Test Skill, scope = Task Final Test)
        │
        ├─ required tests fail / acceptance unmet
        │     → remain in Develop ↔ Test
        │
        └─ stages complete
           + stage acceptance satisfied
           + final required tests satisfy defined acceptance
                │
                ▼
           READY_FOR_REVIEW
                │
                ×  MUST NOT Commit
                ▼
           human starts Submit (separate Skill)
```

MUST NOT mark READY_FOR_REVIEW merely because final tests ran.

Task Book is the **plan**. It is not proof of the final committed tree. Submit may discover undeclared files; those still count.

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
successful Commit → clean up session (P3 defines how)
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
    do AGENTS / architecture / module docs / metadata /
    Test Matrix still match the tree?
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
    candidate-bound; Commit token ≠ Push token
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
S9 Finalize Change Record     ← candidate record; included in the Commit
S10 Commit
S11 Optional Push             ← separate authorization
S12 Cleanup                   ← Develop Session after successful Commit
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
S9 finalize Change Record     ← describes this candidate; not yet as-built
        │
        ▼
S10 Commit
        │
        ├─ failure → MUST NOT treat that record as submitted history
        └─ success → that Change Record becomes long-term as-built
                     → S11 Optional Push
                     → S12 Cleanup
        │
        ×  not “Agent memory of the session”
        ×  MUST NOT create the Change Record after Commit
```

P3 defines draft / final state mechanics.

| After successful Commit | Fate |
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
| **P8** | Submit Skill | Diff, reviews, human gate, sync, commit |
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
