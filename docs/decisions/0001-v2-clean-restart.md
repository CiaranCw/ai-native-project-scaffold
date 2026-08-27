# ADR 0001 — v2 clean restart in a sibling repository

Status: Accepted for P0 (product/repository strategy). Not a release approval.

## Context

`ai-native-game-scaffold` **v1.0.1** is a frozen thin baseline. Its product identity was:

1. **Project Legibility** — a new Agent can find authority, commands, and constraints, then run verification.
2. **Game Legibility** — a test run becomes a structured Evidence Bundle, not only an exit code.

v1 Core (Harness / Analysis / Repair), contracts, and the in-process runner are built around that identity. The repository is a **Game Legibility / Test Runtime** historical baseline, not a general project-development scaffold.

v2.0 changes the product definition.

v2 is a **portable project-development scaffold** that can be imported into an existing project so AI can continuously understand, develop, test, submit, and hand off. Game projects remain the primary research subject, but the top level MUST NOT be a game-test framework and MUST NOT bind to an engine, SCM, IDE, or Agent vendor.

Continuing to grow v1 `main` would mix two products in one history: a sealed test-runtime tree and a new four-Skill scaffold (Understand / Develop / Test / Submit, human submission gate, Task Book / Session / Change Record). Selective reuse of v1 is still valuable — especially Test runtime and Repair mechanics — but reuse MUST be explicit, not “keep editing the old tree until it looks like v2.”

## Decision

**Clean restart, selective reuse**, in a **new sibling repository**:

- New repo: `ai-native-project-scaffold` (this repository). It is the only **ACTIVE DEVELOPMENT** tree for v2.0.
- **Clean restart:** v2 does not copy the v1 file tree, Python package, CLI, examples, or `runs/` / `analyses/` / `repairs/` layout as the v2 skeleton.
- **v1 frozen:** `ai-native-game-scaffold` v1.0.1 remains **READ-ONLY REFERENCE**. Do not extend that repo. Do not modify it from v2 work.
- **Selective reuse only:** a v1 capability may enter v2 only after inspect → qualify → map to a v2 responsibility → migrate → revalidate under v2. P0 performs **no** migration.

Primary likely mappings (not a migration checklist to execute now):

- v1 Contracts / Scenario / Adapter / Harness / Evidence / Analysis → **Test Skill** (advanced capability)
- v1 Repair qualification / policy / isolated worktree / regression / fresh verification → **Develop Repair Mode** (P9)

## Alternatives considered

### A. Continue v1 `main`

Keep using `ai-native-game-scaffold` as the v2 implementation repo.

Rejected: v2’s top-level object is no longer “thin test runtime + repair loop.” Folding four Skills, adoption of dirty existing projects, Submit-as-authority, and human commit control into v1 `src/scaffold/` would either:

- silently redefine a frozen 1.0.1 baseline, or
- leave v1’s Game Legibility Core as the apparent product, which is the wrong v2 identity.

v1.0.1 would stop being a stable reference.

### B. Create a `v2` branch in the v1 repository

Same Git remote; new branch; maybe a monorepo later.

Rejected: branch isolation does not isolate **product history or default clone identity**. Contributors cloning the game-scaffold repo still land in a test-runtime tree. Clean-restart discipline (“do not copy the old tree”) is harder to enforce when the old tree is the same project. v1 tags and v2 work would share issue/PR/release namespace.

### C. Clean sibling repository (chosen)

New repo, new history, v1 left frozen at v1.0.1.

Chosen because:

- v2 can state a new product without rewriting v1 docs or Core nouns.
- v1 remains a readable, versioned asset library.
- Default clone of each repo matches that repo’s job.
- Migration must be a conscious qualify step, which matches “repository truth” and “do not silently inherit.”

Cost: two repositories exist for a while; Agents MUST be told which tree is active ([README](../../README.md) / [Constitution](../contracts/CONSTITUTION.md)).

## Consequences

- v2 has an independent Git history. There is no requirement that v2 commits fast-forward from v1.0.1.
- v1 remains the reference for Game Legibility / Test Runtime and Repair mechanics until a later phase qualifies pieces.
- Until P6/P9, v2 will **not** contain the v1 runner. That is intentional.
- Any v1 file that appears in v2 MUST be explainable by a later phase’s qualify record — not by P0.
- This ADR does not authorize implementing Skills, schemas, or CLI.

## Validation (no v1 pollution)

Confirm, at P0 and whenever this decision is checked:

1. Working tree is `ai-native-project-scaffold`, remote matching the v2 GitHub repo.
2. P0 adds only the four constitution documents listed in the P0 spec (`README.md`, `docs/contracts/CONSTITUTION.md`, `docs/architecture/V2_ARCHITECTURE.md`, this ADR).
3. `ai-native-game-scaffold` is not modified (no commits, no file writes from v2 P0 work).
4. v2 P0 does not contain `src/`, `skills/`, `examples/`, `contracts/schemas/`, or copied v1 `runs/` layouts.

If any of (2)–(4) fail, P0 is polluted and MUST be corrected before human review.
