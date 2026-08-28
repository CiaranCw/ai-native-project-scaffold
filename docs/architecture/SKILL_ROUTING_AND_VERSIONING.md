# Skill Routing and Versioning

This document visualizes the P4 Skill Contract. Rules live in [../contracts/SKILL_CONTRACT.md](../contracts/SKILL_CONTRACT.md). Product rules: [../contracts/CONSTITUTION.md](../contracts/CONSTITUTION.md). Host lock path: [../contracts/PROJECT_CONTRACT.md](../contracts/PROJECT_CONTRACT.md).

It does **not** implement Skills, a resolver, client plugins, or live `skills/` / `.scaffold/skills.lock`.

This distribution repository does **not** contain Skill packages or a host lock.

---

## Top-level routing

```text
 User intent
        │
        ▼
    AGENTS.md          portable entry router (P2)
        │
        ▼
 Skill Resolver / Compatibility Preflight
   (Distribution support layer — NOT a fifth Skill)
   reads project.yaml + skills.lock
   inspects available manifests
        │
        ├─ package/input INVALID → BLOCK (not a compatibility result)
        │     (intrinsic declaration / release defects only)
        │
        └─ VALID package
              │
              ▼
         current resolver / environment
         can satisfy declared format + capabilities?
              │
              ├─ EXACT / COMPATIBLE → requested Skill may start
              ├─ MIGRATION_REQUIRED → Compatibility / migration path
              │    ACTIVE host: NEEDS_MIGRATION semantically applies
              ├─ INCOMPATIBLE       → BLOCK
              │    (includes known-unsatisfied VALID requires,
              │     or well-formed format this resolver cannot use)
              └─ UNKNOWN            → BLOCK (do not guess)
              × current-environment miss ≠ rewrite package INVALID
        │
        ▼
 understand | develop | test | submit
```

One user sentence → **one** top-level Skill. Nested Skills are invocations, not co-owners.

```text
 “Implement this and test it.”
        → Develop  (may invoke Test)

 “Review, run final tests, and commit.”
        → Submit   (may use Test / Understand)

 “Adopt this project.”
        → Understand / bootstrap

 “Repair this failed change.”
        → Develop / repair
```

---

## Modes (not extra Skills)

```text
 Understand
 ├─ bootstrap      Adoption / first attach
 ├─ full
 ├─ refresh
 └─ compatibility

 Develop
 ├─ normal_task
 └─ repair         ← not a fifth Skill

 Test
 └─ scoped verification   (further modes: P6)

 Submit
 └─ internal stages S1–S12 only
    Structural Review / Knowledge Consistency /
    Test Completeness stay inside Submit
```

```text
 Skill   = complete workflow
 Mode    = path inside one Skill
 Rule    = project-local constraint
           (not a Skill, not Commit permission)
```

---

## Distribution vs host

```text
 DISTRIBUTION                         HOST
 skills/understand/                   AGENTS.md
 skills/develop/                      docs/project/
 skills/test/                         .scaffold/skills.lock
 skills/submit/                       thin / derived client files
 contracts + later tooling

 Host MUST NOT normally vendor
 complete Skill implementations.
```

---

## Package authority

```text
 skill.yaml     machine identity / compatibility
 SKILL.md       normative workflow
 references/    support only

 material contradiction → INVALID package
 (validity layer — not a 6th compatibility result)
 (do not pick a convenient file; cannot be EXACT)
```

Released identity `<skill_id>@<skill_version>` is **immutable**.

---

## Distinct version dimensions

```text
 skill_version              Skill identity (semver semantics)
 package_format_version     how the package tree is read
 lock_format_version        how skills.lock is read
 Project Contract version   project.yaml          (P2)
 record schema_version      Task/Change/Session   (P3)
 product / release version  Distribution product
 client adapter version     NOT locked
```

MUST NOT treat these as one number.

---

## Develop / Test loop

```text
 Develop
    │
    ▼
   Test ── FAIL ──► Develop ──► Test ── PASS ──► continue
    │
    ×  not a DevelopTest Skill
    ×  TEST_PASS ≠ TASK_COMPLETE
    ×  TEST_PASS ≠ READY_FOR_REVIEW
    ×  TEST_PASS ≠ SUBMIT_AUTHORIZED
    ×  Test MUST NOT edit source
    ×  Test MUST NOT perform S10 / Commit
```

---

## Submit dependencies

```text
 Submit
 ├─ may use Understand refresh / compatibility
 ├─ may use Test
 └─ MUST NOT silently become Develop

 source defect / missing required change
        │
        ▼
 repair HANDOFF → Develop (normal_task or repair)
        │
        ▼
 Test as needed
        │
        ▼
 Submit again on a NEW candidate
        │
        × previous S6 authorization does not transfer (P0)
```

After material knowledge/candidate change: existing S3/S4/S5/S6 loop. No new Submit stage.

---

## Permission non-escalation

```text
 caller authority
        │
        ▼
 nested Skill
        │
        × does not inherit Commit / Push
        × does not inherit submit authorization
        × Develop→Test does not grant Test source edits
        × Submit→Understand does not grant Understand Commit

 skill.yaml / skills.lock
        × cannot store can_commit / submit_authorized
          as human permission
        × requires: = capability prerequisite
          NOT invocation permission
          NOT a new routing edge
          NOT “always invoke that Skill at startup”
          NOT “current environment miss = package INVALID”
```

---

## Lock resolution

```text
 .scaffold/skills.lock
   exact expected versions
   of understand / develop / test / submit
        +
 available Distribution manifests
        │
        ▼
 package / input validity   (intrinsic declaration / release)
        ├─ INVALID → blocker (not EXACT / not COMPATIBLE)
        └─ VALID
              │
              ▼
         current resolver / environment
         capability + format satisfaction
              │
              ▼
         Compatibility evaluation
         (reproducible from explicit lock + host +
          package + contract + capability inputs;
          lock is expectation, not a transcript)
              │
              ├─ EXACT                 VALID + lock match + checks pass
              ├─ COMPATIBLE            VALID + differs; safe; NOT exact
              ├─ MIGRATION_REQUIRED    VALID; host representation must change
              │                         ACTIVE → NEEDS_MIGRATION applies
              ├─ INCOMPATIBLE          VALID; known unsafe
              │                         (incl. unsatisfied valid requires)
              └─ UNKNOWN               VALID; cannot tell — do not guess
         × unsatisfied current capability ≠ package INVALID
         × unsupported local format ≠ automatically package INVALID
```

```text
 version difference
        ≠
 automatic NEEDS_MIGRATION

 difference → evaluate first
 same version strings ≠ automatically EXACT
```

---

## Compatible substitution vs lock

```text
 lock:    understand 2.0.0
 actual:  understand 2.0.1   (COMPATIBLE)
        │
        ├─ MAY execute
        ├─ MUST report actual 2.0.1
        ├─ MUST NOT report EXACT
        ├─ MUST NOT rewrite skills.lock
        └─ durable outputs MUST NOT claim 2.0.0 ran

 user later explicitly updates lock
        → lock update (reviewable)
        → still not migration unless evaluation says so
```

---

## Migration flow

```text
 difference detected
        │
        ▼
 compatibility evaluation
        │
        ├─ NO migration needed
        │     execute if EXACT / COMPATIBLE
        │     update lock only if explicitly requested
        │
        └─ YES  MIGRATION_REQUIRED
              │  ACTIVE host: NEEDS_MIGRATION semantically applies
              ▼
           migration plan
           (bounded, source/target known,
            intended mutations listed;
            bound to plan identity + source host
            + source lock + record/metadata generation
            + target intent + mutation envelope)
              │
              ▼
           human approval of THAT PLAN
           (source-state-bound)
              │
              ├─ before Apply, plan / host / lock /
              │  contract assumptions / envelope
              │  materially change
              │     → previous approval INVALID
              │     → re-evaluate compatibility
              │     → update/regenerate plan
              │     → explicit human re-approval
              │
              ▼
           PREPARED
           revalidate binding + current plan approval
              │
              ▼
           APPLYING
           checkpoint approved actions + expected state
              │
              ▼
           VALIDATING
              │
              ├─ success → COMPLETED
              └─ interruption / uncertainty / divergence
                   → RECOVERY_REQUIRED
                   → observe host + checkpoints + approved envelope
                   → expected prefix MAY resume
                   → unexpected divergence requires
                     re-evaluation + updated plan + human re-approval
              │
              ▼
           normal Submit for persistent finalized changes
              │
              × newer package existence is not approval
              × plan approval ≠ P8 SUBMIT_AUTHORIZED
              × MUST NOT silently rewrite P3 historical Change Records
```

`ABORTED` is valid only before persistent mutation or after proven coherent safe reversion/neutralization; unknown partial mutation remains `RECOVERY_REQUIRED`. Expected approved Apply checkpoints do not themselves invalidate approval applicability. Universal rollback is not required. Migration Execution is a bounded operational artifact, not a fifth Skill or fourth canonical development record.

Installing a local package ≠ migrating the host.

---

## Compatibility Preflight

```text
 requested Skill
        │
        ▼
 Preflight (not a Skill)
        │
        ├─ lock missing / incomplete / malformed
        │     MUST NOT invent pins from whatever is installed
        │     → Understand compatibility / recovery if that
        │       Understand package can interpret this host generation
        │     else BLOCK
        │
        ├─ package missing / INVALID / self-contradictory
        │     VALIDITY BLOCK — not a compatibility result
        │     MUST NOT score EXACT or COMPATIBLE
        │     no generic-chat substitute
        │
        └─ VALID package
              current environment may still fail to satisfy
              a legal requires / package-format capability
              → INCOMPATIBLE / UNKNOWN / distribution blocker
              → MUST NOT rewrite the package as INVALID
              EXACT / COMPATIBLE → start Skill
              otherwise as above
```

---

## Multi-client model

```text
 Canonical Distribution Skill
        │
        ├── NATIVE LOAD           preferred
        ├── THIN BRIDGE           points at AGENTS + resolver
        └── GENERATED DERIVED COPY
              one-way, regenerable,
              source skill_id + skill_version
              stale MUST be detectable
              NOT authority
              still ownership-registered when durably Scaffold-generated
              does not make an INVALID package VALID

 All clients
        │
        ▼
 same AGENTS
 same skills.lock
 same Project Rules
 same records
```

Authority and ownership are independent: durable Scaffold-created thin bridges, generated copies, and managed client regions remain non-authoritative but are covered by P2 ownership registration as GENERATED or MANAGED as applicable.

```text
 Agent A (Cursor, Dist 2.0.x)     Agent B (Claude, Dist 2.1.y)
        │                                │
        └──────── same host lock ────────┘
                         │
              each resolves own packages
              each evaluates compatibility
              each reports actual versions
              execute only if allowed
```

---

## Rule loading

```text
 Global rules
 +
 scope / module / test rules in scope
        │
        ▼
 load relevant only
        │
        ▼
 Skill workflow
        │
        ├─ Rule vs Rule conflict, authority unclear
        │     → MUST NOT guess → Refresh / human
        ├─ Rule vs Constitution / Contracts
        │     → CONFLICT; framework wins
        └─ human asks to change a Rule
              → surface governance mutation
              → old Rule still exists until reviewed
```

No mandatory `docs/project/rules/`. No second global Rule state file. Rules are not Skills.

---

## Generic Skill result (shape only)

```text
 skill_id + skill_version actually used
 mode
 outcome: COMPLETED | BLOCKED | FAILED | NEEDS_HUMAN
 baseline / candidate identity
 mutations: summary or none
 artifact / evidence refs
 blockers
 next route
 if actual ≠ lock: compatibility difference (not EXACT)
```

Ephemeral. Not a P3 canonical record. No chat / chain-of-thought storage.

---

## No-SCM

```text
 skills.lock + manifests + evaluation
        │
        × do not require Git tags
        × do not invent SHAs as Skill ids
        │
        ▼
 resolution still works
 skills.lock remains a persistent host artifact
 even without SCM
 a lock update is still a project mutation
 P8 owns concrete submission / finalization
 SCM history / Commit exist only when SCM exists
 no SCM: S10 uses atomic/conflict-detectable durable publication
 success distinguishable after restart
 failure/interruption creates no false submitted history
 S11 Push is N/A
 MUST NOT pretend an SCM Commit occurred
```

---

## What later phases own (not drawn as runtime)

```text
 P5  Bootstrap / Full / Refresh / Compatibility execution
     migration application
 P6  Test execution / Evidence
 P7  Develop + Repair + Sessions
 P8  Submit reviews, SUBMIT_AUTHORIZED, Change Record,
     SCM Commit or no-SCM durable finalization, optional Push
```

This file is maps only. If it conflicts with [../contracts/SKILL_CONTRACT.md](../contracts/SKILL_CONTRACT.md), the Skill Contract wins; if both conflict with the Constitution, the Constitution wins.
