# Adoption / Bootstrap Contract

This document is the P1 contract for **first-time entry** of an ordinary project into AI-Native Project Scaffold v2.0.

It does **not** implement Bootstrap, Understand, CLI, schemas, or SCM recipes. Those belong to later phases.

**Normative words:** MUST, MUST NOT, SHOULD, MAY.

**Authority:** [CONSTITUTION.md](CONSTITUTION.md) wins if this contract conflicts with it. Structure and loops: [../architecture/ADOPTION_FLOW.md](../architecture/ADOPTION_FLOW.md).

---

## 1. Scope

This contract answers: how does Scaffold **safely attach** to an ordinary existing project for the first time?

It covers Preflight through Activate and Cleanup, including resume, idempotence, partial/broken state, empty/mature/dirty/no-SCM hosts, and conceptual unadoption.

It does **not** cover Develop, Test, Submit, Skill packaging, or final project-side file trees.

Adoption / Bootstrap is **not** a fifth Skill. It is Understand’s first-entry path:

```text
Understand
├── Adoption / Bootstrap + Full
├── Refresh
└── Compatibility
```

---

## 2. Terms

| Term | Meaning |
| --- | --- |
| **Host project** | The ordinary project being attached. |
| **Distribution** | Canonical Scaffold product source/release. MUST NOT be copied wholesale (docs, tests, research, caches) into the host. A bounded project-local consumer installation of runtime + four Skill packages is the supported product subset. |
| **Adoption Baseline** | Evidence of the host’s real state **before** Scaffold mutation. |
| **Adoption Plan** | Explicit, reviewable description of intended first-attach mutations and preservations. |
| **Adoption Session** | Temporary resume/recovery artifact. **Not** a canonical development record. |
| **Apply** | Minimal approved project-side integration only. |
| **Understand Full** | Knowledge-producing normalize step after Apply. Implemented in **P5**. |
| **Active** | Activation Validation has passed. Files existing is **not** sufficient. |
| **Plan candidate** | A specific Adoption Plan version that a human approved or rejected. |

Canonical development records remain only: Task Book, Develop Session, Change Record (Constitution §7).

---

## 3. Preconditions

Adoption MAY start on:

- an empty or new directory
- a mature existing project
- a dirty working tree
- a host with no SCM
- a host that already has AI client files

Adoption MUST NOT assume Git, Perforce, a clean tree, an existing commit, one IDE, one engine, or one language.

Adoption MUST NOT require the developer to commit, stash, reset, or discard existing work merely to attach Scaffold.

---

## 4. Conceptual host states

These are **semantics**, not stored enums (P2/P3 own persistence):

| State | Meaning |
| --- | --- |
| **NOT ADOPTED** | No completed activation. Absence or presence of stray files is not decisive by itself. |
| **ADOPTION IN PROGRESS / INTERRUPTED** | Apply or later steps started; activation has not passed. |
| **ACTIVE** | Activation Validation passed. Normal four-Skill lifecycle applies. |
| **NEEDS RECOVERY / RE-PLANNING** | Partial or inconsistent Scaffold traces exist; continuing blindly is unsafe. |

“Scaffold-like files exist” MUST NOT be treated as ACTIVE.

---

## 5. Adoption Baseline

Before any host mutation, Adoption MUST establish an **Adoption Baseline**.

The baseline’s purpose is later verification that adoption did **not** silently destroy, overwrite, or misattribute pre-existing work.

The baseline SHOULD conceptually account for, where available:

- project root
- SCM type and current revision / stream / workspace
- tracked state
- untracked / new files
- pre-existing modifications
- relevant host files that Apply might later touch
- existing or partial Scaffold traces

Exact hashing, snapshot format, and storage are **P2/P3/P5**. P1 freezes the invariant:

**Pre-existing work MUST be preserved.**  
Adoption mutations MUST remain distinguishable from the baseline.  
Activation MUST fail if that invariant cannot be shown.

---

## 6. Lifecycle (normative order)

```text
Ordinary Project
  → B1 Preflight                 (observe only)
  → B2 Read-Only Discovery       (observe only)
  → B3 Adoption Plan
  → B4 Exact-plan apply           (plan-candidate-bound)
  → B5 Minimal Adoption Apply    (first allowed mutation)
  → B6 Understand Full / Normalize
  → B7 Activation Validation
  → B8 Activate
  → B9 Cleanup Temporary Adoption State
```

**No host mutation** MAY occur before B2, B3, and explicit B4 approval of the planned mutations.

The approved Adoption Plan defines the authorized **Adoption Mutation Envelope**. Every host mutation during first-time adoption — **B5 through B6, until B8** — MUST stay inside the currently approved Plan candidate.

If the Plan **materially** changes, or the host **materially** changes in a way that invalidates Plan assumptions or the real mutation candidate, **after B4 and before B8**, previous approval is void. Adoption MUST re-discover / re-plan / re-approve **before** applying the new mutation.

Purely observational discoveries that do **not** change the authorized envelope MUST NOT require re-approval.

---

## 7. B1 — Preflight

Preflight MUST establish the real starting state. It is observational.

Where applicable it MUST attempt to detect:

- project root
- empty vs existing project
- SCM type (or none)
- current revision / baseline
- current branch / stream / workspace concept
- existing working-tree modifications
- untracked / new files
- nested repositories / workspaces
- existing Scaffold presence
- partial or interrupted adoption

Preflight MUST NOT: reset, clean, stash, discard, force-sync, overwrite, auto-commit, or auto-push.

---

## 8. B2 — Read-only Discovery

Discovery MUST be evidence-based. Unknown facts MUST remain unknown.

Discovery MUST NOT invent build commands, architecture, modules, test coverage, ownership, paths, or authority relationships.

Inspect where applicable:

| Area | Look for evidence of |
| --- | --- |
| **Identity** | Name, purpose, type, major stack |
| **Structure** | Top-level dirs, source / asset / generated roots, config, likely modules, entry points |
| **Build / run** | Build, launch, package, development commands |
| **Test** | Unit / integration / smoke / engine / project scripts / CI / test docs |
| **Documentation** | README, architecture, design, development, onboarding, module, operations docs |
| **AI / Agent** | `AGENTS.md`, `CLAUDE.md`, Cursor rules, Skills, Hooks, MCP configs, AI docs, other client entries |
| **SCM / collaboration** | Workspace model, ignore rules, contribution / branch-stream conventions |
| **Local environment** | Machine-local config, absolute local paths, local build settings, ignored env files, secret/credential **references** |

Secret **values** MUST NOT be copied into shared project knowledge even if discovered. See §27.

### Read-only verification

B1 and B2 are **operationally read-only**.

Before B4, Discovery MAY:

- read project files
- inspect repository / workspace state
- inspect configuration
- discover **declared** build / run / test commands
- perform checks that are demonstrably observational and non-mutating

Discovery MUST NOT execute a command merely to obtain **VERIFIED** status if that command MAY mutate host state.

Conceptual examples of potentially mutating work (not a command blacklist): builds; test runs that generate outputs; package commands; generators; formatters; migrations; launch commands that write state.

If a verification MAY change host state, it MUST NOT run during read-only Discovery. The fact MUST remain **INFERRED** or **UNKNOWN** until a later authorized verification point.

**VERIFIED** does **not** mean the Agent was allowed to run any command it wanted.

---

## 9. Fact confidence

**UNKNOWN is not FALSE.**

| Class | Meaning |
| --- | --- |
| **VERIFIED** | Directly supported by project evidence, or successfully checked by a **non-mutating** observation. |
| **INFERRED** | Reasonable structural conclusion, not yet verified. |
| **UNKNOWN** | Not determined. |
| **CONFLICTING** | Available project authorities disagree. |

A host MAY activate with non-critical UNKNOWNs. It MUST NOT activate with unresolved **critical** facts (see §17).

Do not encode these classes as a P2 YAML schema here.

---

## 10. Existing AI infrastructure

Adoption MUST assume the host MAY already contain AI infrastructure.

Adoption MUST NOT blindly replace `AGENTS.md`, `CLAUDE.md`, Cursor rules, Skills, Hooks, MCP configs, AI docs, or other client entries.

Discovery MUST classify, where possible:

- apparent authority
- duplicated content
- client-specific content
- machine-local content
- stale or conflicting content
- integration risk

Scaffold **integrates**. It does not assume a blank AI environment.

If a client entry already exists, the Plan MUST name a **client-entry integration strategy** (a separate dimension from B3 action classes):

| Strategy | Meaning |
| --- | --- |
| **PRESERVE** | Leave the file untouched. |
| **MANAGED_UPDATE** | Change only an approved managed region / field. |
| **THIN_BRIDGE** | Keep the existing client-specific entry as a thin routing bridge to canonical project knowledge; it MUST NOT become another authority. |
| **DEFER** | Human must resolve authority first. |

**THIN_BRIDGE is not a sixth generic B3 action class.** It describes the intended client-entry role. Realization MUST use only approved generic actions — typically a **MANAGED_UPDATE** of the existing entry, and/or **PRESERVE** of that file plus **CREATE** / **MANAGED_UPDATE** of canonical authority elsewhere.

MUST NOT silently replace the full existing client file.

---

## 11. Single Source of Truth

If several files already contain the same project knowledge, Adoption MUST NOT add another hand-maintained duplicate.

The Plan SHOULD identify:

- proposed authority
- thin client entry points
- duplicated information
- one-way-generation candidates
- unresolved authority conflicts

Target shape (P0):

```text
authoritative project knowledge
            ↓
   ┌────────┼─────────┐
   ▼        ▼         ▼
 AGENTS   Claude    Cursor   …future
 thin     thin      thin
```

Generation tooling is **not** P1.

---

## 12. Shared vs machine-local state

| Shared project knowledge MAY | Shared project knowledge MUST NOT |
| --- | --- |
| Architecture, modules, portable commands, placeholders, workflow rules, testing expectations, constraints | Secrets, credentials, tokens, sensitive local state |

Absolute local paths SHOULD NOT become canonical shared authority when a portable representation is possible.

Machine-local values MUST use a local / ignored mechanism. Exact location is **P2**.

---

## 13. B3 — Adoption Plan

Discovery MUST produce an Adoption Plan **before** mutation.

### Starting state

The Plan MUST summarize: project identity; SCM state (or none); Adoption Baseline; existing dirty work; existing / partial Scaffold state.

### Discovered knowledge

The Plan MUST summarize evidenced structure / modules, build / run / test evidence, documentation, AI infrastructure, and unresolved facts — each with a confidence class where stated.

### Proposed actions

Each planned **mutation or preservation** MUST use exactly one of these **generic action classes** (not P2 schema fields). There is no sixth class:

| Class | Meaning |
| --- | --- |
| **CREATE** | New Scaffold-managed artifact. |
| **MANAGED_UPDATE** | Modify only an explicitly controlled region / field. |
| **PRESERVE** | Existing artifact stays untouched. |
| **LOCAL_ONLY** | Machine-specific integration / state; not shared authority. |
| **DEFER** | Insufficient evidence, non-critical, or postponed. |

Client-entry **strategies** (`PRESERVE` / `MANAGED_UPDATE` / `THIN_BRIDGE` / `DEFER`) are recorded separately. See §10. A `THIN_BRIDGE` strategy MUST still be expressed in the Plan as one or more of the five generic classes above.

The Plan MUST also list:

- predicted files / areas that may be touched
- files / areas that will be preserved
- UNKNOWNs and CONFLICTING facts
- source-of-truth and ownership collisions
- local / shared boundary risks
- expected activation checks
- activation blockers
- relevant adoption risks

---

## 14. B4 — Exact-plan apply

No host mutation in first-time adoption (B5 or B6) MUST start until an **exact
Adoption Plan** has been previewed and then applied. Preview is not apply.

Default: **preview only**.

The applied Plan is the **Adoption Mutation Envelope**. Apply authorizes only
the mutations in that candidate — through Apply **and** first-adoption
Understand Full — until Activate.

A general instruction such as “Adopt this project” or “Run Day-1 Bootstrap”
authorizes the Agent to **enter** the Bootstrap workflow, produce a preview,
and then apply that exact Plan when machine/project preconditions still hold.
It is **not** Auto-Adoption outside this explicit lifecycle route. `--approved
--plan-digest` is the compatibility spelling of that apply request. It has no
Git Commit or Git Push meaning.

If the Plan **materially** changes before B8, the previous apply request is
**invalid**. The Agent MUST preview and apply the new candidate before any
mutation that is outside the old envelope.

If the host **materially** changes after preview and before B8 in a way that
invalidates Plan assumptions or the real candidate, apply is **invalid**.
Adoption MUST re-discover, re-plan, and apply the current Plan.

Observational discoveries that do not change the envelope MUST NOT require
re-preview.

MUST NOT design concrete authorization field names here.

Human approval is **not** an Adoption predicate. Core MUST NOT require a
trusted grant, approval_origin, or human-confirmation perimeter. If machine
preconditions fail, Adoption MUST stop fail-closed (`BLOCKED` / re-plan), not
wait for a human Approve click.

Adoption MUST NOT auto-commit or auto-push. Git Commit and Git Push remain
later, separately instructed actions.

---

## 15. B5 — Minimal Apply

After exact-plan apply, Apply MAY perform only the minimum host-side integration required for Understand Full and later Scaffold operation, and only inside the **Adoption Mutation Envelope**.

Apply MUST NOT:

- implement business features
- perform unrelated refactors or architecture cleanup
- migrate assets
- reorganize the host merely for Scaffold convenience
- rewrite SCM history
- auto-commit or auto-push
- fully replace HUMAN_OWNED documents
- vendor the entire Distribution tree into the host

**Minimal integration, not project reconstruction.**

---

## 16. Ownership

| Mode | Rule |
| --- | --- |
| **GENERATED** | Scaffold owns the entire artifact. |
| **MANAGED** | Scaffold MAY change only explicitly managed regions / fields. |
| **HUMAN_OWNED** | Scaffold MAY read. MUST NOT overwrite without explicit human instruction. |

Marker syntax and storage are **P2**. Existing human content MUST be preserved.

---

## 17. B6 — Handoff to Understand Full

| Adoption | Understand Full |
| --- | --- |
| Safely connect the host to Scaffold | Actually understand and normalize the host |

After minimal Apply, control MUST pass to Understand Full. Adoption MUST NOT collapse that job into Apply.

Understand Full later builds project knowledge, module map, commands, testing knowledge, workflow rules, documentation authority, and the normalized project contract. **P5** implements it.

Understand Full MUST NOT bypass Adoption Plan identity and envelope binding.

If B6 discovers that normalization requires a new file, an existing-file modification, a materially different ownership treatment, a different client-entry strategy, or any other material mutation **outside** the current envelope:

1. STOP before applying that new mutation
2. update / rebuild the Adoption Plan
3. invalidate the previous apply request
4. preview and apply the current Plan
5. continue only inside the new envelope

---

## 18. B7 — Activation Validation

A host MUST NOT become Active merely because files were written.

Activation Validation MUST establish at least:

| ID | Invariant |
| --- | --- |
| A | Pre-existing work is preserved (baseline holds). |
| B | No unapproved project area was modified. |
| C | No blocking ownership collision remains. |
| D | A project-knowledge authority can be identified. |
| E | Client-entry integration is coherent enough to continue. |
| F | Shared vs local boundary is not knowingly violated. |
| G | No known credential / token / secret was written into shared Scaffold knowledge. |
| H | Generated / Managed / Human-Owned duties are unambiguous enough to continue. |
| I | No unresolved **CRITICAL** UNKNOWN / CONFLICTING fact remains. |
| J | **All** adoption-phase mutations (B5 and B6, not Apply alone) remain inside the current approved Plan. |
| K | If any adoption-phase mutation would have diverged materially, a new Plan was human-approved **before** that mutation. |
| L | Adoption did not silently change business behavior. |
| M | The host can determine how future Scaffold work should enter. |

Activation is **not** perfect understanding. It MUST NOT require every command, module, test, or architecture detail to be known.

Activation **does** mean: the host can enter the normal Scaffold lifecycle without hidden adoption assumptions.

Any unresolved **critical** UNKNOWN / CONFLICTING fact:

- B7 **FAIL**
- MUST NOT Activate

No waiver mechanism is defined in P1.

### Critical vs non-critical facts

**Critical** (MUST **block** activation until resolved in a new approved Plan). Listing a critical collision as DEFER does **not** clear the blocker. P1 MUST NOT invent a silent waiver:

- unresolved authority collision for project knowledge or existing `AGENTS.md` / equivalent router
- HUMAN_OWNED overwrite would be required to continue
- baseline / pre-existing-work preservation cannot be shown
- unapproved mutation detected
- known secret in shared knowledge
- shared / local boundary knowingly violated
- material Plan / adoption-mutation divergence without re-approval

**Non-critical** (MUST NOT by themselves block activation):

- unknown release / packaging command
- incomplete module map
- missing architecture essay
- absent test system on an empty or early project
- no SCM, unless a later project policy explicitly requires one

---

## 19. B8 — Active

Only after B7 passes MAY the host be **Active** (Scaffold-managed).

Persistence of that fact is **P2**.

Once Active, Bootstrap MUST NOT run again as if the host were new. Normal routes are Understand Refresh, Understand Compatibility, Develop, Test, and Submit.

---

## 20. B9 — Cleanup

After successful activation, temporary Adoption Session state MUST be cleaned (mechanism is **P3/P5**).

Long-term project knowledge MUST remain only in the authorized knowledge layers (P0 / P2).

---

## 21. Interrupted adoption / resume

Once Apply begins, a temporary Adoption Session MAY retain: original baseline, approved Plan identity, completed steps, applied actions, pending validation, interruption state.

Storage is **P3/P5**.

On resume, Adoption MUST verify that:

- original baseline assumptions still hold
- the host has not materially diverged
- the approved Plan is still applicable
- Plan approval is still valid

If any check fails: re-discover → re-plan → re-approve.

MUST NOT blindly restart and overwrite prior adoption or host work.

---

## 22. Idempotence

Adoption SHOULD be operationally idempotent.

Re-running Adoption against an **Active** host MUST NOT:

- duplicate client entry files
- duplicate managed blocks
- create parallel project knowledge
- copy another Distribution runtime
- reset already-normalized knowledge

Route to Understand Refresh or Understand Compatibility according to the reason.

---

## 23. Partial / broken adoption

If Scaffold-like artifacts exist but activation never passed, the host is **IN PROGRESS / INTERRUPTED** or **NEEDS RECOVERY / RE-PLANNING**, not Active.

Recovery MUST inspect baseline, Plan, and actual tree; then resume or re-plan. MUST NOT treat leftover files as success.

---

## 24. Empty project

Discovery MAY find little or nothing. Adoption MUST NOT invent a fake architecture.

Acceptable initial facts include: purpose from developer input; implementation not started; modules not established; build / test UNKNOWN or absent.

Normalized knowledge MUST be allowed to grow later via Understand Refresh.

---

## 25. Mature project

Prefer **discover → preserve → index → normalize** over **rewrite → reorganize → replace**.

Scaffold is a governance / development framework, not a forced repository restructuring tool.

---

## 26. Dirty-work project

If uncommitted / unsubmitted host work exists:

- record it in the Adoption Baseline
- preserve it
- distinguish later Apply mutations from that pre-existing delta
- MUST NOT require commit / stash / reset
- expose risks in the Plan
- validate preservation before Activate

---

## 27. No-SCM project

A host without Git / Perforce / other SCM MAY still be adopted.

SCM-dependent later capabilities MAY be unavailable or degraded until SCM is configured.

Adoption MUST NOT fail solely because no SCM exists, unless a later project policy explicitly requires one.

Submit behavior for no-SCM hosts is later-phase work.

---

## 28. Distribution vs adopted project

| Distribution | Adopted host |
| --- | --- |
| Skills, reusable contracts, later runtime, migrations, reusable tools | Own project knowledge; project rules / config; minimal metadata / reference; project-specific tests / adapters when needed; client integration |

Adoption MUST NOT copy the entire Distribution implementation into the host. The scaffold MUST NOT become a mandatory business-runtime dependency.

---

## 29. Reversible adoption

Adoption MUST be reversible in principle. Removing Scaffold MUST NOT destroy normal business behavior.

Conceptual unadopt MUST consider: generated artifacts; managed regions; thin client bridges; local Scaffold state; HUMAN_OWNED material; project docs that gained independent value.

MUST NOT delete business code, unrelated user docs, or operational necessities.

Unadopt tooling is **not** P1.

---

## 30. Adoption Session lifecycle

Adoption Session is temporary. Purpose: first-attach safety and interruption recovery — **not** development handoff.

| Event | Session fate |
| --- | --- |
| Adoption starts | MAY exist |
| Activation succeeds | MUST be cleaned |
| Blocked / interrupted | Retain enough to resume |
| Abandoned | Explicit cleanup MAY remove it |

Directory and schema are **P3/P5**.

---

## 31. Security / privacy boundary

Adoption MAY inspect environment and config. It MUST NOT normalize secrets into shared project knowledge.

- Credentials are not project documentation.
- Tokens are not shared Scaffold metadata.
- Machine-local secrets remain local.
- Ignored files MUST NOT be blindly copied into project knowledge.
- Generated docs MUST avoid embedding sensitive local values.

This is a data-boundary rule, not a security-test framework. P1 MUST NOT add adversarial, fuzz, injection, traversal, exploit, or network-probing mechanisms.

---

## 32. Normative case outcomes

| Case | Safe behavior |
| --- | --- |
| **A** Empty new project | Discover little; do not invent architecture; Plan says UNKNOWNs; after approval, minimal Apply + Full; non-critical UNKNOWNs MAY activate. |
| **B** Clean mature project | Discover / preserve / index / normalize; no forced restructure. |
| **C** Dirty mature project | Baseline records dirty work; preserve it; no commit required; Apply mutations distinguishable; preservation required for Activate. |
| **D** Existing client entries | Inspect; choose a **strategy** (PRESERVE / MANAGED_UPDATE / THIN_BRIDGE / DEFER); realize it only via the five generic action classes; never silent full replace. |
| **E** Conflicting duplicate knowledge | CONFLICTING; Plan names proposed authority; unresolved **critical** authority collision **blocks** Activate. |
| **F** Interrupted after partial Apply | Resume from session; verify baseline / plan / host; else re-plan / re-approve; no blind restart. |
| **G** Rerun on Active host | No second Bootstrap; route Refresh or Compatibility; no duplicate entries / knowledge / runtime. |
| **H** No SCM | Adoption MAY proceed; SCM features degraded; no fail-for-no-SCM unless policy requires SCM. |
| **I** Local absolute paths / local config | LOCAL_ONLY / portable placeholders; MUST NOT promote secrets or needless absolute paths to shared authority. |
| **J** Human rejects Plan | B5/B6 MUST NOT mutate; host stays NOT ADOPTED (or prior state); approval remains false. |
| **K** Human changes requested scope before mutation | Produce a new Plan candidate; old approval void; wait for new B4. |
| **L** Host changes after Plan approval, before B8 | If Plan assumptions or the candidate are invalidated: approval void; re-discover / re-plan / re-approve. |
| **M** Validation finds unapproved B5 or B6 mutation | MUST NOT Activate; recovery / re-plan; unapproved envelope breach is a blocker. |
| **N** Critical UNKNOWN / CONFLICTING remains | B7 FAIL; MUST NOT Activate. |
| **O** Non-critical fact remains UNKNOWN | MAY Activate. UNKNOWN ≠ FALSE. |
| **P** Later stop using Scaffold | Conceptual unadopt: remove generated / managed / local Scaffold traces; preserve HUMAN_OWNED and business code. |

---

## 33. Non-goals

P1 MUST NOT define: final host tree; final `.scaffold` layout; final AGENTS template; concrete YAML schemas; ownership-marker syntax; local-env filename; Task Book / Develop Session / Change Record / Test Matrix schemas; Skill package format; routing implementation; CLI; Python classes; Git or Perforce command recipes; hooks; migrations; Bootstrap / Understand / Test runtime implementations; Game Legibility migration; auto-commit; auto-push.

---

## 34. Deferred responsibilities

| Phase | Owns |
| --- | --- |
| **P2** Project Contract | Host directory structure; AGENTS structure; `.scaffold` layout; metadata locations; ownership representation; shared / local persistence |
| **P3** Records Contract | Task Book, Develop Session, Change Record schemas; temporary persistence including Adoption Session |
| **P4** Skill Contract | Skill package, routing, Rules, version lock, compatibility protocol |
| **P5** Understand | Bootstrap execution, Full, Refresh, Compatibility |
