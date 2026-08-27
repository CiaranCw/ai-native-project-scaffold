# Adoption Flow

This document shows **how** first-time adoption moves. Normative rules live in [../contracts/ADOPTION_CONTRACT.md](../contracts/ADOPTION_CONTRACT.md). P0 product rules: [../contracts/CONSTITUTION.md](../contracts/CONSTITUTION.md).

P1 freezes flow shape. It does not freeze schemas, CLI, or runtime.

---

## Not a fifth Skill

```text
Understand
├── Adoption / Bootstrap + Full     ← this document
├── Refresh
└── Compatibility

Develop / Test / Submit stay independent.
```

---

## Two layers

```text
┌──────────────────────────────────────────────────────────┐
│  Scaffold Distribution                                   │
│  Skills, contracts, later runtime, migrations, tools     │
│  MUST NOT be vendored wholesale into each host           │
└────────────────────────────┬─────────────────────────────┘
                             │ adopt
                             ▼
┌──────────────────────────────────────────────────────────┐
│  Adopted Project                                         │
│  own knowledge + minimal metadata + client thin entries  │
│  business code stays the host’s                          │
└──────────────────────────────────────────────────────────┘
```

---

## Shared vs machine-local

```text
        Discovery facts
              │
              ▼
     ┌────────┴────────┐
     ▼                 ▼
 Shared knowledge    Machine-local state
 portable cmds       absolute paths
 architecture        credentials / tokens
 modules / rules     ignored env / secrets
        │                 │
        ▼                 ▼
 host knowledge       local / ignored
 layers (P2)          mechanism (P2)
```

UNKNOWN facts stay UNKNOWN. They are not written as false commands or invented modules.

---

## Main sequence

```text
Ordinary project
        │
        ▼
 B1 Preflight                 observe only
        │                     SCM? dirty? empty? partial Scaffold?
        ▼
 B2 Read-Only Discovery       evidence only; non-mutating checks
        │                     VERIFIED / INFERRED / UNKNOWN / CONFLICTING
        │                     no build/test/generate just to verify
        ▼
 B3 Adoption Plan             generic actions only:
        │                     CREATE / MANAGED_UPDATE / PRESERVE
        │                     LOCAL_ONLY / DEFER
        ▼
 B4 Human Plan Approval       default = not authorized
        │                     plan-candidate-bound
        │                     envelope = B5 + B6 until B8
        ▼
 B5 Minimal Apply             first allowed mutation
        │                     inside approved envelope
        ▼
 B6 Understand Full           normalize knowledge (P5)
        │                     still inside approved envelope
        ▼
 B7 Activation Validation     files exist ≠ Active
        │                     all B5/B6 mutations vs Plan
        │                     unresolved critical fact = FAIL
        │
        ▼
 B8 Activate
        │
        ▼
 B9 Cleanup Adoption Session
        │
        ▼
 Normal lifecycle:
 Understand Refresh / Compatibility
 Develop ↔ Test → Submit
```

No mutation before B2 + B3 + B4.
B5 and B6 mutations MUST stay inside the approved envelope.

---

## Approval and re-plan loops

```text
          B3 Plan candidate
                 │
                 ▼
          B4 Human review
           /           \
     reject             approve
       │                  │
       ▼                  ▼
  no Apply          host still same?
                    /            \
                  yes            material change
                   │                  │
                   ▼                  ▼
                 B5 Apply      approval void
                               re-discover → new Plan → B4

B6 needs a mutation outside the envelope
        → STOP (do not apply it)
        → new Plan candidate
        → previous B4 invalid
        → human re-approval
        → continue

Human changes requested scope
        → new Plan candidate
        → previous B4 invalid

Material host change after B4, before B8
        → re-evaluate Plan / approval
        → re-discover / re-plan / re-approve if invalidated
```

---

## Interrupt / fail / already-active

```text
Apply started, then interrupted
        │
        ▼
 keep Adoption Session
        │
        ▼
 resume: baseline + Plan + host still valid?
        /                    \
      yes                     no
       │                      │
       ▼                      ▼
  continue safely      re-discover → re-plan → B4

B7 fails
        │
        ▼
 MUST NOT Activate
        │
        ▼
 correct adoption state and/or re-plan → B4 if Plan changes
        │
        ▼
 B7 again

Already ACTIVE
        │
        ×  MUST NOT Bootstrap as new
        ▼
 Understand Refresh
 or Understand Compatibility
```

---

## Conceptual host states

```text
 NOT ADOPTED
      │
      │ Apply starts
      ▼
 IN PROGRESS / INTERRUPTED ──validation fail──► NEEDS RECOVERY / RE-PLAN
      │
      │ B7 pass
      ▼
 ACTIVE ──unadopt (conceptual)──► NOT ADOPTED
                                 (business project still runnable)
```

Stray Scaffold-like files do **not** skip to ACTIVE.

---

## Client-entry strategies (not a sixth action class)

```text
 Existing AGENTS / CLAUDE / Cursor / other
                    │
                    ▼
              inspect (B2)
                    │
     ┌──────────────┼──────────────┬─────────────┐
     ▼              ▼              ▼             ▼
 PRESERVE    MANAGED_UPDATE   THIN_BRIDGE      DEFER
 strategy    strategy         strategy         strategy
 keep file   managed region   thin route to    human
                              canonical        resolves
                              knowledge
```

THIN_BRIDGE is a **strategy**. Realization uses only B3 generic classes
(usually MANAGED_UPDATE, or PRESERVE + CREATE/MANAGED_UPDATE of authority).

MUST NOT silent full-file replace. One knowledge authority; thin clients only.

---

## Unadopt (conceptual)

```text
 ACTIVE
   │
   ▼
 identify GENERATED artifacts
 identify MANAGED regions
 identify thin bridges
 identify local Scaffold state
   │
   ▼
 remove Scaffold integration
 preserve HUMAN_OWNED
 preserve business code
 preserve independently valuable user docs
   │
   ▼
 host still builds / runs / develops
```

No unadopt implementation in P1.

---

## Who implements later

| Question | Not this file |
| --- | --- |
| Where do files live? | P2 |
| Session / record schemas | P3 |
| Skill package and lock | P4 |
| Running Bootstrap / Full / Refresh / Compatibility | P5 |
