# AI-Native Project Scaffold

Portable project-development scaffold for AI-collaborative work. Import it into an existing project so a new Agent can **understand, develop, test, submit, and hand off** without depending on chat history.

This is **not** a game-test framework. Game projects are the primary research subject. The top-level architecture MUST NOT bind to a game engine, SCM, IDE, Agent client, or model vendor.

## Status

**P0 — CLOSED / BASELINED** at `6ea16e343fdd4324983786186b17b2d59b059fb7`.

**P1 — CLOSED / BASELINED** at `3944e932c9a1d40a78402fc1d244c6a3d99e09f9`.

**P2 — CLOSED / BASELINED** at `59d0765de9552569d6aa92e58517b32143c27289`.

**P3 — Records Contract** (current design phase; not closed).

There is no Skill runtime, CLI, schema package, or adoption tooling in this repository yet. Do not treat this tree as an installable product.

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
10. [docs/decisions/0001-v2-clean-restart.md](docs/decisions/0001-v2-clean-restart.md) — why v2 is a clean restart

If these documents conflict, **Constitution wins**. Runtime, CLI, validators, and live host `.scaffold/` records are out of scope for P3.

## Historical v1

`ai-native-game-scaffold` **v1.0.1** is **FROZEN, READ-ONLY REFERENCE**.

- v1 is a Game Legibility / Test Runtime historical baseline.
- v2 does **not** continue that repository.
- Do **not** copy the v1 tree into v2.
- Later phases MAY selectively reuse qualified v1 capabilities after inspect → qualify → map → migrate → revalidate. See Architecture.

## Allowed at P3

- Read P0/P1/P2 baselines plus the two P3 records documents.
- Human review of P3.
- After P3 human review passes, an approved P3 baseline commit exists, and the working tree is clean: start **P4** (Skill Contract & Versioning).

## Forbidden at P3

- Implement Skills, runtime, CLI, Python packages, JSON Schema, or validators.
- Create live host `AGENTS.md`, `docs/project/`, or `.scaffold/` **in this distribution repository** (including `tasks/`, `changes/`, `runtime/`).
- Create `skills/`, `src/`, `runtime/`, `bootstrap/`, `contracts/schemas/`, `examples/`, `tests/`, or `tools/`.
- Copy or vendor the v1 source tree.
- Modify `ai-native-game-scaffold`.
- Invent a fifth top-level Skill or a fourth canonical development record.
- Treat Test PASS as permission to commit or push.
- Auto-commit or auto-push.
- Start P4 before P3 is baselined.

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
| **P3** | Records Contract — current |
| P4 | Skill Contract & Versioning |
| P5 | Understand Skill |
| P6 | Test Skill |
| P7 | Develop Skill |
| P8 | Submit Skill |
| P9 | Repair Migration (into Develop Repair Mode) |
| P10 | Incremental Understanding / Multi-Agent |
| P11 | Cross-Project E2E |
| P12 | Independent Audit / v2.0 Release |

## Next

**P4 — Skill Contract & Versioning.**

P4 MUST NOT start until P3 human review has passed **and** an approved P3 baseline commit exists with a clean working tree.
