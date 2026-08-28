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
 read-only preflight context classification
   (Distribution support layer — NOT a fifth Skill)
        │
        ├─ legitimate first attachment
        │  NOT_ADOPTED + no host identity/lock + no recovery evidence
        │       │
        │       ▼
        │  PRE-ADOPTION BOOTSTRAP PREFLIGHT
        │  selected exact Distribution release
        │  release-pinned Understand = actual bootstrap package
        │  validates identity/integrity before Skill execution
        │       │
        │       ├─ exact + safe → Understand / bootstrap
        │       └─ mismatch → BLOCK / explicit coherent release selection
        │
        ├─ established/prior host identity/metadata
        │       │
        │       ▼
        │     AGENTS.md
        │       │
        │       ▼
        │  HOST COMPATIBILITY PREFLIGHT / RECOVERY
        │       │
        │       ├─ complete authoritative skills.lock
        │       │    → project.yaml + lock + actual packages
        │       │    → normal five-result evaluation
        │       │
        │       ├─ current interrupted initial Adoption
        │       │  before complete lock
        │       │    → bounded approved Plan/Session recovery rule
        │       │
        │       └─ no safe authority → BLOCK / P1 recovery
        │
        └─ partial/conflicting/uncertain Scaffold footprint
                → ADOPTING / RECOVERY_REQUIRED / UNKNOWN /
                  CONFLICTING or BLOCK under P1/P2
                × missing lock alone does not mean bootstrap
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
 requested entry
        │
        ▼
 read-only context classification
        │
        ├─ legitimate NOT_ADOPTED first attachment
        │  no established host identity / project.yaml / skills.lock
        │  no recovery evidence
        │       │
        │       ▼
        │  PRE-ADOPTION BOOTSTRAP PREFLIGHT
        │       authority: explicitly Selected Distribution Release
        │       establish:
        │         exact Distribution release identity
        │         release-pinned Understand package identity
        │         = actual resolved bootstrap Understand
        │         = intended initial lock Understand
        │         actual Understand id/version (surface it)
        │         package VALIDITY / immutable release identity
        │         bootstrap mode
        │         interpretable package format
        │         bootstrap runtime/client/dependency capabilities
        │       × no host lock required
        │       × no invented EXACT lock comparison
        │       × no pre-lock COMPATIBLE substitution
        │       × no “whatever/latest installed Understand”
        │       mismatch/ambiguity → BLOCK / explicit coherent
        │                            release-package selection
        │       safe → Understand bootstrap (P1 workflow)
        │
        ├─ established/prior Scaffold host
        │       │
        │       ▼
        │  HOST COMPATIBILITY PREFLIGHT / RECOVERY
        │       │
        │       ├─ complete authoritative host lock
        │       │     authority: project.yaml + skills.lock
        │       │                + actual local packages
        │       │     VALID package → EXACT | COMPATIBLE |
        │       │                     MIGRATION_REQUIRED |
        │       │                     INCOMPATIBLE | UNKNOWN
        │       │
        │       ├─ current interrupted initial Adoption
        │       │  before complete authoritative lock
        │       │     require:
        │       │       recoverable Session → applicable approved Plan
        │       │       observed expected approved host prefix/checkpoint
        │       │       exact Selected Release still resolvable
        │       │       release-pinned U = actual recovery U
        │       │     temporary authority:
        │       │       same Plan's Selected Release/package facts
        │       │     × partial lock is not authority
        │       │     × no installed-package inference/substitution
        │       │     → P1/P5 decides safe remaining recovery work
        │       │
        │       └─ missing/incomplete lock without valid current
        │          initial-Adoption Plan/Session binding
        │             → consistency/recovery blocker
        │             × do not regenerate from installed packages
        │             × historical Plan is not a magic lock
        │
        └─ partial/prior/conflicting footprint or cannot tell
                × MUST NOT fall back to bootstrap
                → existing P1/P2 recovery/conflict/block semantics
```

Pre-Adoption Bootstrap Preflight and Host Compatibility Preflight are two contexts of one support layer. They are not Skills, lifecycle states, or compatibility-result values.

```text
Selected Distribution Release R
  → coherent release set pins Understand U
  → Bootstrap Preflight establishes actual bootstrap Understand = U
      by package/release identity and integrity, not strings alone
  → B3 Plan binds:
      R pinned Understand U
      = actual bootstrap Understand U
      = intended initial lock Understand U
      + develop/test/submit from the same coherent release set
  → P1 human approval
  → approved Apply creates project.yaml and ultimately establishes
    complete coherent skills.lock
  → skills.lock becomes durable expected-version authority
  → later Agent reads lock and uses Host Compatibility Preflight

actual bootstrap Understand ≠ release-pinned Understand
  → BLOCK before bootstrap
  → select/resolve a coherent release that pins the intended package
  → rerun Bootstrap Preflight

× no chat-memory dependency
× R does not remain a competing durable host version authority
```

```text
interrupted initial Adoption after host identity, before complete lock
  → Host Compatibility / recovery path (NOT a third context)
  → current Adoption Session identifies same approved Plan
  → revalidate Plan identity + approval applicability + observed host
  → expected approved prefix/checkpoint
      + exact Selected Release R still resolvable
      + release-pinned Understand U = actual recovery Understand U
        → bounded Plan-derived package resolution
        → P1/P5 may decide whether approved remaining work resumes
  → partial/malformed/incomplete lock is recovery evidence, NOT authority
  → complete coherent four-Skill lock established
        → lock authority begins; temporary recovery anchor expires

missing binding / unexpected divergence / exact R or U unavailable
  → BLOCK / P1 recovery, re-plan, and re-approval as applicable

previously ACTIVE host later loses lock
  → established-host consistency/recovery
  × MUST NOT revive historical Adoption Plan as expected-version authority
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
 selected bootstrap Distribution release identity
 does not depend on SCM in the ordinary host
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
