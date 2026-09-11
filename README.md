# AI-Native Project Scaffold

Portable project-development scaffold for AI-collaborative work. Import it into
an existing project so a new Agent can **understand, develop, test, submit, and
hand off** without depending on chat history.

This is **not** a game-test framework. Game projects are the primary research
subject. The Core architecture is **not** bound to a game engine, SCM, IDE,
Agent client, or model vendor.

Cursor is currently a **supported project-local client adapter**. Project Import
installs Cursor Skill adapters plus first-use rule/hook enforcement into the
**host** project. Those adapters are not canonical top-level Skills. Clients
without an equivalent enforcement adapter do not have the same hard first-use
enforcement.

This Distribution checkout has no live consumer installation and no live
adopted-host `.scaffold/project.yaml` or `.scaffold/skills.lock` at the
repository root. That is a Distribution/host distinction, not a claim that the
product has no Cursor integration.

## Quick Start

```text
git clone <Scaffold repository>
cd <Scaffold repository>
python src/scaffold_consumer.py import-project --host <project>
```

Then open the imported project in Cursor and give the Agent a normal business
request. No Scaffold-specific task prompt is required.

`--host .` is supported. Details:
[docs/QUICK_START.md](docs/QUICK_START.md) and
[docs/CONSUMER_INSTALLATION.md](docs/CONSUMER_INSTALLATION.md).

## First use: import is not Adoption

`import-project` installs the project-local Scaffold surface. It does **not**
Adopt the project.

For a fresh project, successful import leaves the host **NOT_ADOPTED**.

On first normal work:

1. the Agent discovers Scaffold;
2. Understand bootstrap runs;
3. **NEEDS_HUMAN** when approval is required;
4. the human approves the exact Adoption Plan;
5. Adoption completes;
6. ordinary Develop / Test / Submit work can proceed.

The user's ordinary business request is **not** Adoption approval.

See [docs/architecture/ADOPTION_FLOW.md](docs/architecture/ADOPTION_FLOW.md),
[docs/contracts/ADOPTION_CONTRACT.md](docs/contracts/ADOPTION_CONTRACT.md),
and [docs/implementation/FIRST_USE_ENFORCEMENT_DESIGN.md](docs/implementation/FIRST_USE_ENFORCEMENT_DESIGN.md).

## Current status

Published GitHub `main` RC:
`80c421e56bb1d6ef3239d5186957a6c66a411db9`.

Current `main` contains an **RC-level installable/importable product**. This
repository does **not** claim a formal v2.0 release. There is no formal release
tag.

| Work | Current state |
| --- | --- |
| P0–P4 Foundation | CLOSED / BASELINED |
| FA-1 | PASS / CLOSED |
| P5 Understand, P6 Test, P7 Develop, P8 Submit | CLOSED / BASELINED / REMOTELY PUBLISHED |
| FA-2 | PASS / CLOSED |
| P9 Repair/Migration | PASS / CLOSED |
| P10 Incremental Understanding / Multi-Agent | PASS / CLOSED |
| DIVE | PASS / CLOSED |
| Consumer Installation | PASS / CLOSED |
| PC-CONSUMER-001 first-use lifecycle enforcement | PASS / CLOSED |
| Project Import / Team Onboarding | PASS / CLOSED |
| Agent3 / fresh Consumer behavioral pilot | **NOT STARTED** |

## Current product surface

- **Understand / Develop / Test / Submit** — exactly four canonical Skills
- **project-local Consumer Installation** — managed runtime and packages in the host
- **one-command Project Import** — `import-project`; not a Skill
- **first-use lifecycle enforcement** — Cursor rule/hook adapter; not a Skill
- **Repair/Migration** — Develop mode; not a fifth Skill
- **Incremental Understanding / Multi-Agent**
- **no auto-commit / no auto-push**

## Four Skills

| Skill | Question it answers |
| --- | --- |
| **Understand** | What is this project, and how should a new Agent maintain it? |
| **Develop** | How should the current task be completed under project rules? |
| **Test** | What was actually verified for the given scope, and with what result? |
| **Submit** | Does the **real** working tree meet submission conditions? |

Bootstrap / Adoption, Refresh, Compatibility, Repair, Stage Validation,
Structural Review, Project Import, and the first-use hook/rule are **not**
top-level Skills. Their homes are defined in the Constitution.

## Authority

Read in this order:

1. This README (entry only)
2. [docs/contracts/CONSTITUTION.md](docs/contracts/CONSTITUTION.md) — highest in-repo rules
3. [docs/architecture/V2_ARCHITECTURE.md](docs/architecture/V2_ARCHITECTURE.md) — v2 structure and data flow
4. [docs/QUICK_START.md](docs/QUICK_START.md) — onboarding
5. [docs/CONSUMER_INSTALLATION.md](docs/CONSUMER_INSTALLATION.md) — project-local installation and import
6. [docs/contracts/ADOPTION_CONTRACT.md](docs/contracts/ADOPTION_CONTRACT.md) — first-attach contract
7. [docs/architecture/ADOPTION_FLOW.md](docs/architecture/ADOPTION_FLOW.md) — first-attach flow
8. [docs/implementation/FIRST_USE_ENFORCEMENT_DESIGN.md](docs/implementation/FIRST_USE_ENFORCEMENT_DESIGN.md) — first-use enforcement
9. [docs/contracts/PROJECT_CONTRACT.md](docs/contracts/PROJECT_CONTRACT.md) — active host structure
10. [docs/contracts/SKILL_CONTRACT.md](docs/contracts/SKILL_CONTRACT.md) — Skill packages, lock, compatibility

Further layout, records, routing, and implementation notes:

- [docs/architecture/PROJECT_LAYOUT.md](docs/architecture/PROJECT_LAYOUT.md)
- [docs/contracts/RECORDS_CONTRACT.md](docs/contracts/RECORDS_CONTRACT.md)
- [docs/architecture/RECORD_LIFECYCLES.md](docs/architecture/RECORD_LIFECYCLES.md)
- [docs/architecture/SKILL_ROUTING_AND_VERSIONING.md](docs/architecture/SKILL_ROUTING_AND_VERSIONING.md)
- [docs/decisions/0001-v2-clean-restart.md](docs/decisions/0001-v2-clean-restart.md)
- [docs/implementation/FIRST_USE_WALKTHROUGH.md](docs/implementation/FIRST_USE_WALKTHROUGH.md)
- [docs/implementation/CONSUMER_INSTALLATION_DESIGN.md](docs/implementation/CONSUMER_INSTALLATION_DESIGN.md)
- [docs/implementation/P5_UNDERSTAND.md](docs/implementation/P5_UNDERSTAND.md)
- [docs/implementation/P6_TEST.md](docs/implementation/P6_TEST.md)
- [docs/implementation/P7_DEVELOP.md](docs/implementation/P7_DEVELOP.md)
- [docs/implementation/P8_SUBMIT.md](docs/implementation/P8_SUBMIT.md)
- [docs/implementation/P9_REPAIR_MIGRATION.md](docs/implementation/P9_REPAIR_MIGRATION.md)
- [docs/implementation/P10_INCREMENTAL_MULTIAGENT.md](docs/implementation/P10_INCREMENTAL_MULTIAGENT.md)

If these documents conflict, **Constitution wins**.

## Historical context

`ai-native-game-scaffold` **v1.0.1** is **FROZEN, READ-ONLY REFERENCE**.

- v1 is a Game Legibility / Test Runtime historical baseline.
- v2 does **not** continue that repository.
- Do **not** copy the v1 tree into v2.
- Later phases MAY selectively reuse qualified v1 capabilities after
  inspect → qualify → map → migrate → revalidate. See Architecture.

Historical DIVE Day-1 correction notes:
[docs/implementation/DIVE_PILOT_CORRECTION_01.md](docs/implementation/DIVE_PILOT_CORRECTION_01.md).
Those notes are not current status. DIVE is PASS / CLOSED.

| Phase | Focus |
| --- | --- |
| **P0** | Constitution — CLOSED / BASELINED |
| **P1** | Adoption / Bootstrap Contract — CLOSED / BASELINED |
| **P2** | Project Contract — CLOSED / BASELINED |
| **P3** | Records Contract — CLOSED / BASELINED |
| **P4** | Skill Contract & Versioning — CLOSED / BASELINED |
| **FA-1** | Foundation Architecture Audit — PASS / CLOSED |
| **P5** | Understand Skill — CLOSED / BASELINED / REMOTELY PUBLISHED |
| **P6** | Test Skill — CLOSED / BASELINED / REMOTELY PUBLISHED |
| **P7** | Develop Skill — CLOSED / BASELINED / REMOTELY PUBLISHED |
| **P8** | Submit Skill — CLOSED / BASELINED / REMOTELY PUBLISHED |
| **P9** | Repair Migration — PASS / CLOSED |
| **P10** | Incremental Understanding / Multi-Agent — PASS / CLOSED |
| P11 | Cross-Project E2E |
| P12 | Independent Audit / v2.0 Release |

## Next

Published RC3, Project Import, and first-use enforcement already exist on
`main`.

The next real validation is a **new** fresh Consumer workspace and an Agent3
behavioral pilot.

Agent3 has **not** started. This repository does **not** claim v2.0 released,
production/general availability, or a formal release tag.
