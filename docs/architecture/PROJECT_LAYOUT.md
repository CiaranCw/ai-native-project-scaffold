# Project Layout

This document is the P2 **normalized contract view** of an Active host. Rules: [../contracts/PROJECT_CONTRACT.md](../contracts/PROJECT_CONTRACT.md). Product rules: [../contracts/CONSTITUTION.md](../contracts/CONSTITUTION.md).

It is **not** permission to relocate business code or existing docs. Canonical entries MAY **reference** physical authorities that already exist.

This distribution repository does **not** contain a live host tree.

---

## Canonical normalized tree

```text
<ProjectRoot>/
│
├── AGENTS.md                     Layer 1 — thin router
│                                 GENERATED | MANAGED | HUMAN_OWNED+bridge
│
├── docs/project/                 Layer 2 — canonical knowledge entries
│   ├── overview.md               REQUIRED
│   ├── architecture.md           CONDITIONAL (applicability in project.yaml)
        │   ├── development.md            CONDITIONAL
        │   ├── testing.md                CONDITIONAL
│   └── modules/                  CONDITIONAL; one entry per important module
│
├── .scaffold/                    Layer 3 — machine index / state
│   ├── project.yaml
│   ├── modules.yaml
│   ├── commands.yaml
│   ├── tests.yaml
│   ├── skills.lock               contents: P4
│   ├── tasks/                    schema: P3
│   ├── changes/                  schema: P3
│   ├── runtime/                  LOCAL / TEMPORARY / ignored
│   │   └── local/                machine paths only; not secrets
│   └── ext/<namespace>/          OPTIONAL domain extras
│
├── CLAUDE.md / Cursor rules / …  thin bridges only
│
└── existing project files…       unchanged unless an approved Plan says so
```

---

## Authority by fact type

```text
 Physical workspace / SCM reality
   files that exist, real diff, actual tree
          │
          │  mismatch is a CONFLICT
          │  (not silent overwrite, not Agent memory)
          │
     ┌────┴─────┐
     ▼          ▼
 Layer 2      Layer 3
 docs         .scaffold
 declared     machine index
 meaning      status / maps
     │          │
     └────┬─────┘
          ▼
       Layer 1
       AGENTS.md
       routes; does not invent
       repository truth
          ▲
          │ pointer only
   thin client files
```

AGENTS does **not** derive physical reality. It tells the Agent where declared meaning and machine indexes live, then the Agent still inspects the real tree.

---

## AGENTS routing

```text
New Agent (no chat)
        │
        ▼
    AGENTS.md
        │
        ├─ identity + status + hard constraints
        ├─ → docs/project/overview.md
        ├─ → docs/project/* or referenced existing docs
        ├─ → .scaffold/project.yaml (lifecycle, maintenance, version, baseline, applicability)
        ├─ → .scaffold/modules.yaml
        ├─ → when to Understand / Develop / Test / Submit
        └─ → Refresh if structure drifted; Compatibility if lock drifted
```

Keep AGENTS short. Load module docs only when that module is in scope (progressive disclosure).

---

## docs/project progressive disclosure

```text
overview.md          always first (explains; not machine SSOT)
        │
        ├─ architecture.md if project.yaml says present / referenced
        │     (physical file MAY live outside docs/project/)
        ├─ development.md  if applicable
        ├─ testing.md  ↔  explains tests.yaml (does not copy it)
        └─ modules/<id>  loaded when working that area
                  │
                  └── physical file MAY live outside docs/project/
```

---

## `.scaffold` relationships

```text
project.yaml     identity, lifecycle + maintenance conditions,
                 contract version, last-understood baseline,
                 ownership registry (canonical),
                 knowledge-domain applicability
       │
       ├─ modules.yaml    paths + knowledge entry + source vs generated
       │                  (evidence-derived facts keep P1 confidence)
       ├─ commands.yaml   declared ops + VERIFIED/INFERRED/UNKNOWN/CONFLICTING
       ├─ tests.yaml      observed systems + declared required-test policy
       │                  (no result history)                 → P6 executes
       ├─ skills.lock     expected versions                   → P4 defines
       ├─ tasks/          Task Books                          → P3
       ├─ changes/        Change Records: candidate before Commit;
       │                  as-built after successful Commit    → P3
       ├─ ext/<ns>/       optional domain metadata
       └─ runtime/        NOT knowledge
              ├─ sessions / caches
              └─ local/   machine-only paths
```

---

## Durable vs runtime

```text
 SHARED / DURABLE                         LOCAL / TEMPORARY
 AGENTS, docs/project                     .scaffold/runtime/**
 .scaffold/*.yaml, skills.lock            including local/
 .scaffold/tasks/, changes/               Adoption/Develop sessions
 tracked ext/                             caches

 Agents MUST NOT treat runtime as handoff truth.
```

---

## Shared vs machine-local paths

```text
 Shared metadata                         runtime/local/
  relative to project root                C:\Users\...\SDK
  portable separator `/`                  machine absolute
  placeholders                            ignored; not secrets
```

---

## Ownership decision

```text
Artifact in project.yaml ownership registry?
        │
        ├─ GENERATED → Scaffold MAY regenerate per Contract
        ├─ MANAGED   → only inside named bounded regions
        ├─ HUMAN_OWNED → read/reference; no overwrite without instruction
        └─ missing / markers corrupt / overlap
                 → CONFLICTING
                 → MUST NOT guess
                 → Refresh / human

Pointer/reference is not a fourth mode.
Referencing a physical file does not transfer ownership.
```

---

## Freshness / Refresh loop

```text
Repository / workspace changes
        │
        ▼
Freshness check
 (baseline, path existence, links, index vs tree)
        │
        ├─ still valid → continue (lifecycle unchanged)
        └─ stale
              ▼
         ACTIVE + NEEDS_REFRESH
              ▼
         Understand Refresh (P5)
              ▼
         Project Contract current
```

Version/lock difference is **not** automatically NEEDS_MIGRATION.
Compatibility evaluation (P4/P5) decides whether migration is required.

No implementation in P2.

---

## Client thin bridges

```text
 Canonical knowledge (docs + .scaffold)
              │
              ▼
         AGENTS.md
              ▲
    ┌─────────┼─────────┐
    │         │         │
 CLAUDE    Cursor     future
 thin      thin       thin
```

If a client requires a file copy: **one-way generate** from canonical source.

---

## Existing-doc authority

```text
 Canonical entry                    Physical authority
 docs/project/architecture.md  -->  docs/engine/architecture.md
 (entry has its own ownership)      (keeps its own ownership; not copied)
```

Single Source of Truth over forced relocation.

---

## Extensions

```text
.scaffold/ext/<namespace>/     YES
.scaffold/random-engine.yaml   NO
```

---

## Who implements later

| Need | Phase |
| --- | --- |
| Record schemas in tasks/changes/runtime | P3 |
| Lock file grammar | P4 |
| Write/update this tree on a host | P5 |
| Run tests.yaml | P6 |
