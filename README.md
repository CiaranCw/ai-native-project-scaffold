# AI-Native Project Scaffold

Portable project-development scaffold for AI-collaborative work. Import it into an existing project so a new Agent can **understand, develop, test, submit, and hand off** without depending on chat history.

This is **not** a game-test framework. Game projects are the primary research subject. The top-level architecture MUST NOT bind to a game engine, SCM, IDE, Agent client, or model vendor.

## Status

**P0 — CLOSED / BASELINED** at `6ea16e343fdd4324983786186b17b2d59b059fb7`.

**P1 — CLOSED / BASELINED** at `3944e932c9a1d40a78402fc1d244c6a3d99e09f9`.

**P2 — CLOSED / BASELINED** at `59d0765de9552569d6aa92e58517b32143c27289`.

**P3 — CLOSED / BASELINED** at `6a0091de9c4575e607bd8687744ee154cea7226c`.

**P4 — CLOSED / BASELINED** at `56c7bdb3fa1e193b6fc54693ca635fa3c86e5f77`.

**FA-1 — PASS / CLOSED** at `2bf5a9a96acca45ccc919dd542bc914420674316`. Independent re-audit of the current P0–P4 Foundation passed. All blocking findings are closed.

**P5 — CLOSED / BASELINED / REMOTELY PUBLISHED.** Understand implementation passed final design, source, and local test review. Git history and `origin/main` are authoritative for the exact P5 baseline commit identity.

**P6 — CLOSED / BASELINED / REMOTELY PUBLISHED.** Test implementation passed final design, source, and local test review. Git history and `origin/main` are authoritative for the exact P6 baseline commit identity.

**P7 — CLOSED / BASELINED / REMOTELY PUBLISHED.** Develop implementation passed final design, source, and local test review. Git history and `origin/main` are authoritative for the exact P7 baseline commit identity.

**P8 — CLOSED / BASELINED / REMOTELY PUBLISHED.** Submit implementation passed final source and test review. Git history and `origin/main` are authoritative for the exact P8 baseline commit identity.

This tree is not an installable product release. Remote publication of P8 does not start FA-2 or P9.

## Authority

Read in this order:

1. This README (entry only)
2. [docs/contracts/CONSTITUTION.md](docs/contracts/CONSTITUTION.md) — highest in-repo rules
3. [docs/architecture/V2_ARCHITECTURE.md](docs/architecture/V2_ARCHITECTURE.md) — v2 structure and data flow
4. [docs/contracts/ADOPTION_CONTRACT.md](docs/contracts/ADOPTION_CONTRACT.md) — first-attach contract (P1)
5. [docs/architecture/ADOPTION_FLOW.md](docs/architecture/ADOPTION_FLOW.md) — first-attach flow (P1)
6. [docs/contracts/PROJECT_CONTRACT.md](docs/contracts/PROJECT_CONTRACT.md) — active host structure (P2)
7. [docs/architecture/PROJECT_LAYOUT.md](docs/architecture/PROJECT_LAYOUT.md) — active host layout (P2)
8. [docs/contracts/RECORDS_CONTRACT.md](docs/contracts/RECORDS_CONTRACT.md) — development records (P3)
9. [docs/architecture/RECORD_LIFECYCLES.md](docs/architecture/RECORD_LIFECYCLES.md) — record lifecycles (P3)
10. [docs/contracts/SKILL_CONTRACT.md](docs/contracts/SKILL_CONTRACT.md) — Skill packages, lock, compatibility (P4)
11. [docs/architecture/SKILL_ROUTING_AND_VERSIONING.md](docs/architecture/SKILL_ROUTING_AND_VERSIONING.md) — routing and versioning (P4)
12. [docs/decisions/0001-v2-clean-restart.md](docs/decisions/0001-v2-clean-restart.md) — why v2 is a clean restart

If these documents conflict, **Constitution wins**. P5 implementation notes: [docs/implementation/P5_UNDERSTAND.md](docs/implementation/P5_UNDERSTAND.md). P6 implementation notes: [docs/implementation/P6_TEST.md](docs/implementation/P6_TEST.md). P7 implementation notes: [docs/implementation/P7_DEVELOP.md](docs/implementation/P7_DEVELOP.md). P8 implementation notes: [docs/implementation/P8_SUBMIT.md](docs/implementation/P8_SUBMIT.md). This distribution repository must not contain a live adopted-host `.scaffold/project.yaml` or `.scaffold/skills.lock`.

## Historical v1

`ai-native-game-scaffold` **v1.0.1** is **FROZEN, READ-ONLY REFERENCE**.

- v1 is a Game Legibility / Test Runtime historical baseline.
- v2 does **not** continue that repository.
- Do **not** copy the v1 tree into v2.
- Later phases MAY selectively reuse qualified v1 capabilities after inspect → qualify → map → migrate → revalidate. See Architecture.

## Current

P0–P4 Foundation is independently audited and closed. P5 Understand, P6 Test, P7 Develop, and P8 Submit are **CLOSED / BASELINED / REMOTELY PUBLISHED**. FA-2 is the next mandatory gate and is not started. P9 is not started.

Current tree (P8 baseline, not a v2.0 release):

- Understand package at `skills/understand/`
- Test package at `skills/test/`
- Develop package at `skills/develop/`
- Submit package at `skills/submit/`
- P5 runtime at `src/scaffold_p5/`
- P6 runtime at `src/scaffold_p6/`
- P7 runtime at `src/scaffold_p7/`
- P8 runtime at `src/scaffold_p8/`
- ordinary local P5/P6/P7/P8 tests and non-authoritative fixtures at `tests/`
- no live adopted-host `.scaffold/` lock/project state at the distribution repository root
- no Claude / Cursor / Codex client configs
- no v1 source tree and no fifth top-level Skill
- no auto-commit or auto-push

## Four Skills (names only)

| Skill | Question it answers |
| --- | --- |
| **Understand** | What is this project, and how should a new Agent maintain it? |
| **Develop** | How should the current task be completed under project rules? |
| **Test** | What was actually verified for the given scope, and with what result? |
| **Submit** | Does the **real** working tree meet submission conditions? |

Bootstrap / Adoption, Refresh, Compatibility, Repair, Stage Validation, and Structural Review are **not** top-level Skills. Their homes are defined in the Constitution.

## Phase map

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
| P9 | Repair Migration (into Develop Repair Mode) |
| P10 | Incremental Understanding / Multi-Agent |
| P11 | Cross-Project E2E |
| P12 | Independent Audit / v2.0 Release |

## Next

**FA-2 — next mandatory gate, not started**

P9 is not started.

This repository does **not** claim v2.0 release. FA-2 and P9–P12 remain future work.
