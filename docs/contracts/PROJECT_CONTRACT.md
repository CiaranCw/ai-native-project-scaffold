# Project Contract

This document is the P2 contract for the **persistent shape** of an Active Scaffold-managed host project.

It does **not** implement Understand, validators, YAML parsers, Skill runtime, or record schemas.

**Normative words:** MUST, MUST NOT, SHOULD, MAY.

**Authority:** [CONSTITUTION.md](CONSTITUTION.md) wins on product rules. First-attach rules: [ADOPTION_CONTRACT.md](ADOPTION_CONTRACT.md). Layout diagrams: [../architecture/PROJECT_LAYOUT.md](../architecture/PROJECT_LAYOUT.md).

P2 freezes **project-side structure and authority**. Exact YAML/JSON fields, filenames inside reserved directories, and runtime behavior belong to later phases unless this contract names a path.

---

## 1. Scope

This contract answers: after adoption, what does a correctly Scaffold-managed project look like, and where does authoritative knowledge / state live?

It covers the three layers (`AGENTS.md`, `docs/project/`, `.scaffold/`), ownership, fact-type authority, freshness, multi-client entries, extensions, and path/text portability.

It does **not** cover Task Book / Develop Session / Change Record schemas (P3), Skill packaging or `skills.lock` contents (P4), Understand execution (P5), Test runtime (P6), Develop (P7), or Submit (P8).

This **distribution** repository MUST NOT contain a live host `.scaffold/`, host `AGENTS.md`, or host `docs/project/` as P2 artifacts. Those belong on adopted hosts. Trees in this document are the **normalized contract view**.

---

## 2. Definitions

| Term | Meaning |
| --- | --- |
| **Host** | An ordinary project after (or during) adoption. |
| **Canonical knowledge entry** | The stable name an Agent looks up (e.g. `docs/project/architecture.md`). |
| **Physical document location** | Where that knowledge actually lives (may be an older path the entry **references**). |
| **Declared command** | A named operation recorded in commands metadata. |
| **Validated execution** | Evidence that a declared command was actually run and observed. Distinct from declaration. |
| **Adoption Mutation Envelope** | P1: authorized first-attach mutations. P2 assumes activation already happened or is in progress. |
| **Ownership registry** | Machine-readable coverage of each shared durable Scaffold-touched artifact and, for MANAGED files, each controlled region. Every artifact has one of GENERATED / MANAGED / HUMAN_OWNED. Ownership controls mutation; it does not declare authority. |

Canonical development records remain Task Book, Develop Session, Change Record. Adoption Session remains a temporary non-canonical artifact (P1 / P3).

---

## 3. Normalized project model

An **Active** host MUST present three conceptual layers. They MUST NOT be three hand-maintained copies of the same facts.

```text
Layer 1  AGENTS.md          thin Agent router
Layer 2  docs/project/      human-readable knowledge (+ references)
Layer 3  .scaffold/         machine-readable index and durable/temporary state
```

Natural-language docs **explain**. Machine-readable files **index and check**. AGENTS **routes**. Repository / workspace **physical reality** is authority for what files and diffs actually exist (Constitution: repository truth overrides Agent memory).

---

## 4. Canonical `.scaffold/` layout

P2 **accepts** this core layout. Do not add unnamespaced files at `.scaffold/` root.

```text
.scaffold/
├── project.yaml      project-level metadata
├── modules.yaml      module/domain index
├── commands.yaml     named operations
├── tests.yaml        testing index / contract
├── skills.lock       expected Scaffold/Skill versions (contents: P4)
├── install/          MANAGED project-local consumer installation (not Adoption)
├── tasks/            Task Books (schema: P3)
├── changes/          Change Records (schema: P3)
├── runtime/          local temporary state (not project knowledge)
└── ext/              OPTIONAL namespaced extensions
```

`ext/` is the only justified extra top-level directory: it keeps domain metadata off the core root. It is **optional / reserved**, not required for empty hosts. See “Extensions / namespacing”.

---

## 5. Layer 1 — `AGENTS.md`

`AGENTS.md` is the canonical top-level AI/Agent **entry router**. It MUST stay concise. It MUST NOT become the encyclopedia.

### Required information contract

The file (or an approved managed region / thin bridge that fulfills the same role) MUST make all of the following discoverable **by value or by pointer**, not by inventing a frozen prose template:

1. Project identity (name / what this host is)
2. Current high-level Scaffold / project state (route to `project.yaml`; see “Project lifecycle and maintenance conditions”)
3. Global hard constraints
4. Where Layer 2 knowledge starts (`docs/project/` and any canonical entries)
5. Where Layer 3 lives (`.scaffold/`)
6. How to find module knowledge (index + per-module entries)
7. When to use Understand / Develop / Test / Submit
8. What to read before changing a named module / area
9. What to do when structure changes (Understand Refresh)
10. What to do when Skill / contract versions change (Understand Compatibility; P4)
11. How a new important module / area is registered (update index + knowledge entry; do not copy the world)

AGENTS MUST point at details. It MUST NOT duplicate architecture, module maps, handbooks, or testing strategy.

### Ownership of AGENTS.md

Scaffold MUST NOT require owning the whole file.

| Situation | Allowed |
| --- | --- |
| New / empty / approved generated router | **GENERATED** whole file |
| Existing file, approved integration region | **MANAGED** region only |
| Existing file remains human text | **HUMAN_OWNED** plus approved **THIN_BRIDGE** / pointer (P1 client-entry strategy) |

MUST NOT silently replace a HUMAN_OWNED `AGENTS.md`.

---

## 6. Layer 2 — `docs/project/`

`docs/project/` is the canonical **detailed** human+AI knowledge **namespace**. It is a lookup layer, not a demand to relocate every existing doc.

### Stable core

```text
docs/project/
├── overview.md
├── architecture.md
├── development.md
├── testing.md
└── modules/
```

### Required vs optional vs conditionally required

| Path | Class | Rule |
| --- | --- | --- |
| `docs/project/` | **REQUIRED** (Active) | Canonical knowledge namespace. |
| `overview.md` | **REQUIRED** | Stable start. MAY be short. MUST NOT invent architecture. |
| `architecture.md` | **CONDITIONALLY REQUIRED** | Required when architecture is established **or** an existing architecture authority is indexed. Empty/early hosts MAY omit it when `project.yaml` records the domain as not established / not applicable. |
| `development.md` | **CONDITIONALLY REQUIRED** | Required when workflow / env / local rules exist or are indexed. |
| `testing.md` | **CONDITIONALLY REQUIRED** | Required when tests exist or `tests.yaml` records profiles. If none, `project.yaml` records not applicable; do not invent a test system. |
| `modules/` | **CONDITIONALLY REQUIRED** | Required when ≥1 **important** module exists. |

### Conditional-entry applicability

`.scaffold/project.yaml` is the canonical **machine-readable** authority for whether a normalized knowledge domain/entry is:

- present
- referenced elsewhere
- not established / not applicable

Exact fields are **not** frozen.

`AGENTS.md` MUST **route** the Agent to that state or knowledge entry. It MUST NOT become an independent competing state store.

`overview.md` MAY explain the situation in human-readable form. It MUST NOT be a second machine-readable applicability authority.

MUST NOT maintain the same applicability fact by hand in AGENTS, overview, and `project.yaml`.

Agents MUST NOT hunt randomly when a domain is recorded as not established.

These files are **canonical entries**. They MAY be short pointers to existing physical docs. They MUST NOT copy those docs. A pointer/reference is **not** an ownership mode. The entry still has exactly one of GENERATED / MANAGED / HUMAN_OWNED. **Reference does not transfer ownership:** pointing at `docs/engine/architecture.md` does not make that physical target Scaffold-owned.

### Entry responsibilities

| Entry | Holds | MUST NOT |
| --- | --- | --- |
| **overview.md** | Purpose, high-level status, major tech, map of where to go next | Full module or architecture dump |
| **architecture.md** | Boundaries, major components, relationships, constraints | Entire module handbooks |
| **development.md** | Workflow, env expectations, local rules, generated vs source boundaries, SCM workflow **references** | Secrets, machine-absolute paths as shared authority |
| **testing.md** | Human meaning of test systems, strategy, profiles, limits, how to read `tests.yaml` | Test Skill runtime, Evidence schemas |
| **modules/** | Progressive per-module authority | A forced 4/5-file kit per module |

Every **important** module MUST have one clear authoritative knowledge entry. A simple module MAY be one file. A complex module MAY use several files. Physical location MAY be outside `docs/project/` if the canonical entry **references** it.

Existing excellent docs (e.g. `docs/engine/architecture.md`) SHOULD remain canonical **content**. Scaffold SHOULD index/reference them rather than duplicate.

---

## 7. Layer 3 — `.scaffold/`

`.scaffold/` is the machine-readable contract/state root. It indexes; it MUST NOT become a second architecture essay.

Semantic files (`*.yaml`, `skills.lock`) are **shared durable** unless stated otherwise. `runtime/` is **local temporary**.

Exact YAML keys are **not** frozen here. Each file MUST be capable of representing the responsibilities below.

---

## 8. Canonical path table

| Path | Purpose | Req | Shared | Durable | Typical ownership | Authority role | Later schema |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `AGENTS.md` | Agent router | Required (role) | Shared | Durable | GENERATED, MANAGED, or HUMAN_OWNED | Routing; not encyclopedia | P5 maintains |
| `docs/project/` | Knowledge namespace | Required (Active) | Shared | Durable | N/A (container) | Human-readable namespace | P5 |
| `docs/project/overview.md` | Project start | Required | Shared | Durable | GENERATED, MANAGED, or HUMAN_OWNED | High-level map | P5 |
| `docs/project/architecture.md` | Architecture entry | Conditional | Shared | Durable | GENERATED, MANAGED, or HUMAN_OWNED | Declared architecture entry | P5 |
| `docs/project/development.md` | Dev workflow entry | Conditional | Shared | Durable | GENERATED, MANAGED, or HUMAN_OWNED | Declared workflow entry | P5 |
| `docs/project/testing.md` | Testing explanation | Conditional | Shared | Durable | GENERATED, MANAGED, or HUMAN_OWNED | Declared testing meaning | P5 / P6 interprets |
| `docs/project/modules/` | Module knowledge | Conditional | Shared | Durable | N/A (container); files inside use one of the three modes | Per-module meaning | P5 |
| `.scaffold/` | Machine root | Required (Active) | Mixed | Mixed | N/A (container) | Index/state root | P2+ |
| `.scaffold/project.yaml` | Project metadata + ownership registry | Required (Active) | Shared | Durable | GENERATED or MANAGED | Machine project-level facts | refine later; not P3 records |
| `.scaffold/modules.yaml` | Module index | Required (Active) | Shared | Durable | GENERATED or MANAGED | Machine module map | P5 |
| `.scaffold/commands.yaml` | Command registry | Required (Active) | Shared | Durable | GENERATED or MANAGED | Declared operations + confidence | P5; execution later |
| `.scaffold/tests.yaml` | Testing index | Required (Active) | Shared | Durable | GENERATED or MANAGED | Observed systems + declared policy | **P6** semantics |
| `.scaffold/skills.lock` | Version lock | Required (Active) | Shared | Durable | GENERATED or MANAGED | Expected versions | **P4** contents |
| `.scaffold/tasks/` | Task Books | Reserved | Shared | Durable | Deferred to P3; MUST stay compatible with the three modes | Task intent/progress | **P3** |
| `.scaffold/changes/` | Change Records | Reserved | Shared | Durable | Deferred to P3; MUST stay compatible with the three modes | Candidate before S10; as-built after successful S10 durable finalization | **P3** |
| `.scaffold/runtime/` | Temporary local state | Reserved | **Local** | **Temporary** | N/A (local temporary; not knowledge-ownership) | Non-authoritative | P3/P5/P7 |
| `.scaffold/runtime/local/` | Machine-local values | Optional | **Local** | Temporary / machine | N/A (local temporary) | Non-shared paths/overrides | P5 |
| `.scaffold/ext/` | Namespaced extensions | Optional / reserved | Shared if used | Durable if tracked | GENERATED or MANAGED | Domain extras; not core | later domain phases |
| Client bridge / derived copy / managed client region | Client integration | Conditional | Shared | Durable | GENERATED, MANAGED, or HUMAN_OWNED | Normally non-authoritative routing/compatibility artifact | P5/P4 |

Active hosts MAY have empty `tasks/` and `changes/` directories. They MUST NOT put Task/Change **schemas** in `project.yaml`.

A later phase MAY place a deterministic support-artifact representation under
`.scaffold/ext/<namespace>/` when that phase owns the artifact schema and a
durable Change Record must retain a resolvable opaque reference to it. Such use
is shared and durable when tracked, remains non-core, and MUST satisfy the
ownership registry. It MUST NOT redefine `runtime/` as durable, add an
unnamespaced `.scaffold/` root, or create another canonical development record.
FA2-FND-005 places host-level unexplained-drift support under
`.scaffold/ext/develop/`. That file is Session-independent durable truth, not
a Task Book, Develop Session, or Change Record.

---

## 9. Shared vs local, durable vs temporary

| Class | Examples | Agent rule |
| --- | --- | --- |
| **Shared / durable** | AGENTS, `docs/project/`, `project.yaml`, `modules.yaml`, `commands.yaml`, `tests.yaml`, `skills.lock`, `tasks/`, `changes/`, tracked `ext/` | Handoff knowledge. MAY be in SCM. |
| **Local / temporary** | `.scaffold/runtime/` including sessions, caches, `runtime/local/` | MUST NOT treat as long-term authority. MUST normally be SCM-ignored. MUST expire (P1/P3). |

HUMAN_OWNED docs elsewhere remain shared if the project already tracks them. Scaffold MUST NOT force them into `.scaffold/`.

---

## 10. Ownership model

P1 modes remain the **only** three: **GENERATED**, **MANAGED**, **HUMAN_OWNED**.

Pointer / reference is **not** a fourth mode. A canonical entry that points at existing physical authority still has exactly one of the three modes (for example a GENERATED thin pointer, a MANAGED pointer region, or a HUMAN_OWNED file containing an approved pointer).

**Authority and ownership are independent dimensions.** Authority answers whether an artifact is a source of truth. Ownership answers how Scaffold may create, manage, update, or remove an artifact or bounded region. A non-authoritative artifact MAY still be Scaffold-owned; an ownership mode MUST NOT imply authority.

**Reference does not transfer ownership.** If `docs/project/architecture.md` references `docs/engine/architecture.md`, Scaffold ownership of the entry does **not** make the physical target Scaffold-owned. The target retains its own ownership. The registry covers artifacts Scaffold may actually touch. Merely referenced HUMAN_OWNED authorities do not become writable.

**Canonical registry location:** `.scaffold/project.yaml`.

MUST NOT add `.scaffold/ownership.yaml` or another `.scaffold/` root file for ownership.

The registry MUST be capable of identifying every **shared durable Scaffold-touched artifact**, whether authoritative or non-authoritative, and assigning **exactly one** whole-artifact mode: GENERATED, MANAGED, or HUMAN_OWNED.

For MANAGED artifacts, the registry MUST also be able to identify the approved managed-region ids whose actual boundaries are represented by managed markers.

Coverage includes, where Scaffold durably creates or manages them: authoritative generated artifacts, thin client bridges, generated derived client copies, managed regions inside existing client files, and other durable compatibility artifacts. Ordinary local ephemeral `.scaffold/runtime/` state does **not** require durable registry entries.

Exact field grammar is later work.

**Chosen representation (combination):**

1. **Central ownership registry in `project.yaml`:** every shared durable Scaffold-touched path → one whole-artifact mode, regardless of authority role.
2. **Embedded managed regions** (only for MANAGED files): explicit begin/end bounds with a unique id.

Whole-file GENERATED: Scaffold MAY regenerate the artifact per Contract.  
Whole-file HUMAN_OWNED: Scaffold MAY read/reference; MUST NOT overwrite without explicit human instruction.  
MANAGED: Scaffold MUST NOT edit outside approved regions.

Registry and markers MUST agree. If markers are missing, corrupt, overlapping, or ids collide: **CONFLICTING**. MUST NOT guess. Human resolution or Understand Refresh.

### Managed regions

A managed region MUST be: explicitly bounded; uniquely identifiable; non-overlapping; safely replaceable; distinguishable from human text.

Illustrative bound (not a required comment language for every file type):

```text
<!-- scaffold:managed id="unique-id" -->
…generated or managed payload…
<!-- /scaffold:managed id="unique-id" -->
```

Equivalent paired markers MAY be used in other comment syntaxes if the Plan/registry names them. P5 implements editing. P2 does not.

---

## 11. Authority by fact type

MUST NOT use a naïve global rule such as “YAML always wins” or “code always wins.”

| Fact type | Authority |
| --- | --- |
| **Physical reality** | Actual workspace: files that exist, real diff, current tree |
| **Declared rules / intent** | Project Contract + canonical docs: workflow, constraints, ownership, declared architecture, required process |
| **Machine-readable index** | `.scaffold` files **within this contract** (identity, indexes, declared commands, lock presence, status) |

If they **disagree**, that is a **knowledge consistency conflict**. MUST NOT silently pick the convenient side. MUST surface as conflict → Understand Refresh and/or human resolution; later Submit Knowledge Consistency (P8).

“Repository truth overrides Agent memory” does **not** mean “ignore declared project rules.” Memory loses. Rules vs reality is a **detected mismatch**, not a license to overwrite either.

---

## Fact confidence and declared policy

P1 confidence classes apply to **evidence-derived** facts in normalized metadata:

**VERIFIED** / **INFERRED** / **UNKNOWN** / **CONFLICTING**

When machine metadata records an evidence-derived fact whose certainty matters, the relevant file MUST be capable of preserving that confidence. This applies where relevant across `project.yaml`, `modules.yaml`, `commands.yaml`, and `tests.yaml`.

MUST NOT require a confidence field on every scalar. Exact YAML grammar is not frozen.

Examples of evidence-derived facts: detected module path; detected test-system availability; detected SCM availability; detected command; detected generated/source classification.

An **INFERRED** discovery MUST NOT silently become **VERIFIED** merely because it was written into `.scaffold`.

**Observed / evidence-derived fact** MAY use the four P1 confidence classes.

**Declared rule / required workflow / normative policy** MUST have an authoritative declared source or an explicit approved project-governance origin. A normative project rule MUST NOT become authoritative merely because an Agent **INFERRED** it.

---

## 12. `project.yaml` semantics

Project-level only. Canonical location of the **ownership registry**. MUST be capable of representing:

- project identity
- adoption / management **lifecycle** (see “Project lifecycle and maintenance conditions”)
- zero or more **maintenance conditions** (same section)
- **Project Contract version** (not Skill versions)
- portable project-root / context identity
- pointers to Layer 1/2 authorities
- last-understood **baseline** (see “Last-understood baseline”), SCM-agnostic
- ownership registry (in this file, not a pointer to another root file)
- knowledge-domain applicability (present / referenced elsewhere / not established)
- capability / availability (e.g. SCM none / degraded), with confidence when evidence-derived

MUST NOT contain: Task Book bodies, Change Record bodies, Skill implementations, test **result** history.

A truly **NOT_ADOPTED** host MUST NOT be required to persist `NOT_ADOPTED` in `project.yaml`, because that file may not exist yet. That state is normally inferred externally.

---

## 13. `modules.yaml` semantics

Machine **index**, not a second architecture.md.

MUST map module identities to: paths/areas; human knowledge **entry** (canonical and/or physical); source vs generated classification; optional relationships; optional rule/test **references**. Evidence-derived detections (path exists, generated vs source) MUST be able to keep P1 confidence.

MUST remain compact and reference-oriented. Design prose belongs in docs.

---

## 14. `commands.yaml` semantics

Canonical named operations (build, run, test, lint, format, package, project workflows).

Command **availability / detection** is an evidence-derived fact and MUST be able to keep P1 confidence (see “Fact confidence and declared policy”).

MUST distinguish **declared** vs **validated execution**. VERIFIED MUST NOT mean “looks plausible.” VERIFIED for a command that mutates the host MUST come from an authorized later verification point, not read-only Discovery (P1).

Portable: project-relative; no needless machine-absolute paths. Exact run/result semantics are later.

---

## 15. `tests.yaml` semantics

Machine testing **index/contract**.

- **Observed facts:** known test-system / profile **availability** MAY use P1 confidence.
- **Declared policy:** module/area → **REQUIRED** test relationships MUST come from an authoritative declared source or approved governance. MUST NOT become required merely because an Agent INFERRED them.

Human meaning lives in `docs/project/testing.md` (or its referenced physical doc). The two MUST NOT be hand-duplicated; docs explain, YAML indexes.

**P6** owns execution, Test Matrix behavior, Evidence. This file MUST NOT define Test runtime. MUST NOT store test **result** history.

---

## 16. `skills.lock` reservation

Location: `.scaffold/skills.lock`. Shared and durable. Declares expected Scaffold / Skill versions so silent upgrades do not happen.

**P4** owns file contents, compatibility, migration. P2 MUST NOT specify lock grammar.

---

## 17. `tasks/`, `changes/`, `runtime/` reservations

| Path | Role | Owner of schema |
| --- | --- | --- |
| `tasks/` | Canonical Task Books; shared durable | **P3** |
| `changes/` | Canonical Change Record namespace. During Submit a finalized **candidate** MAY exist here **before** S10. After S10 durable finalization **succeeds**, that same logical record content becomes durable as-built history. If S10 fails or is interrupted, it MUST NOT be described as successfully submitted history. Candidate/final representation is **P3**. | **P3** |
| `runtime/` | Temporary local: Adoption Session, Develop Session, caches, `local/` | **P3/P5/P7**; not knowledge |

`runtime/` MUST NOT be canonical project knowledge, MUST NOT be required durable handoff, MUST normally be SCM-ignored, MUST have cleanup.

---

## 18. Path portability

- Project-internal paths in **shared** metadata SHOULD be project-root relative.
- Absolute machine paths SHOULD stay in `runtime/local/`.
- Shared references MUST NOT depend on one developer’s drive letter.
- Path identity MUST be unambiguous; preserve repository case where it matters.
- Shared machine-readable paths SHOULD use `/` as the portable separator.
- MUST NOT rewrite business-project path strings inside HUMAN_OWNED source.

---

## 19. Line-ending / text policy

Non-destructive:

- Scaffold-generated **shared** text SHOULD follow the host’s existing repository text policy when one exists.
- If none, Scaffold-owned shared text SHOULD use stable LF.
- MUST NOT rewrite HUMAN_OWNED files **only** to normalize line endings.
- Line-ending-only churn MUST NOT be treated as semantic project change.

P2 does **not** add `.gitattributes` or conversion tools.

---

## 20. Machine-local configuration

Reserved: `.scaffold/runtime/local/` (ignored).

MAY hold: SDK/engine install path, local workspace, cache, personal tool path, temporary overrides.

MUST NOT hold secrets, tokens, credentials. Those stay outside project knowledge.

MUST NOT create a second **shared** authority for the same facts. Shared metadata uses placeholders / relative paths.

---

## 21. Knowledge freshness

Facts go stale when paths, modules, commands, tests, architecture, client links, or ownership change.

Freshness MUST be machine-checkable where practical. Conceptual anchors:

- last-understood baseline (see “Last-understood baseline”)
- referenced path existence
- authority link validity
- module index vs tree
- command/test verification state vs declaration

**P5** owns Refresh behavior. P2 only requires the contract to **support** these checks.

---

## 22. Last-understood baseline

`project.yaml` MUST be capable of recording the workspace baseline against which knowledge was last understood or refreshed.

MUST NOT assume Git SHA only. MAY be: Git revision; Perforce changelist; other project-defined baseline; **unavailable / no-SCM**.

---

## 23. Conflicts

Examples: `modules.yaml` points at a deleted path; commands.yaml vs current config; AGENTS link missing; architecture.md describes a removed subsystem; client file duplicates stale knowledge.

MUST NOT silently fabricate reconciliation. The mismatch is a detectable inconsistency: candidate Understand Refresh; human resolution when **which authority** is itself ambiguous.

---

## 24. Multi-client entries

`AGENTS.md` is the primary portable router.

`CLAUDE.md`, Cursor rules, Codex config, future clients MUST be **thin**: tool wiring, rare client constraints, pointer to AGENTS / canonical knowledge.

They MUST NOT be independent encyclopedias. If a client format technically requires a copy: one source is canonical; copies MUST be one-way derived/generated, not hand-synced. When Scaffold durably creates or manages a bridge, derived copy, or client-file region, the ownership registry MUST cover that artifact or region even though it remains non-authoritative.

Client-entry **strategies** remain P1: PRESERVE / MANAGED_UPDATE / THIN_BRIDGE / DEFER. Generic Plan actions remain the five P1 classes.

---

## 25. Project Rules

Skills ≠ Rules (Constitution). P2 only **indexes** rule authority.

`modules.yaml` / docs MAY **reference** project-local Rules (path or future Rule id). **P4** owns package format and loading.

P2 MUST NOT invent a tree of Rule files or a Rule runtime.

---

## 26. Extensions / namespacing

Domain extras (engine, assets, deploy, analysis) MUST live under `.scaffold/ext/<namespace>/` (or a pointer from that namespace).

MUST NOT: overload core file meanings; create competing authorities; replace core semantics; drop arbitrary files on `.scaffold/` root.

A P6-owned deterministic Test Evidence support representation MAY use this
boundary when required solely to keep a durable Change Record's public P6
locator resolvable after normal runtime expiry. Foundation does not freeze the
namespace spelling or physical Evidence schema. P6 owns that representation;
P8 may request materialization through validated opaque references and may
include the resulting artifacts in the permitted S9 Finalization Bundle.

Only the minimal material required for P6 resolution may be retained. The
artifact MUST preserve P6-required candidate binding, provenance, and
integrity; MUST be covered as Scaffold-written by the existing GENERATED or
MANAGED ownership semantics; and MUST NOT grant Test any Commit or Submit
authority. This permission is not a global candidate-identity exclusion for
`.scaffold/ext/`.

No extension runtime in P2.

---

## 27. Module expansion

When an important module appears, update: module index, knowledge entry, related rule/test references, architecture **references** if needed.

MUST NOT require editing every project file. Indexes and pointers keep fan-out small. **P5** Refresh uses this.

---

## 28. Generated content

Modules/project metadata SHOULD classify **source/authoritative** vs **generated/derived** areas (build/, Intermediate/, dist/, generated code, derived assets, temp reports).

Understand MUST NOT infer architecture primarily from stale generated output when authoritative source exists. No engine-specific folder lists in P2.

---

## 29. Monorepo / multi-root

MUST NOT assume one source dir, language, or module tree.

One host Contract MAY index several major modules/domains/roots. Nested **independent** products MAY have their own Contract. P2 does **not** design workspace federation.

---

## 30. Empty / early project

An adopted empty host MUST still satisfy this Contract’s **required** paths (overview + `.scaffold` core files, possibly sparse).

Valid facts: no modules; commands none or UNKNOWN; tests none; architecture not established. MUST NOT invent content. Structure MAY exist before rich knowledge.

---

## 31. Mature project

Prefer **index / reference** existing authority over copy / rewrite / reorganize. Scaffold makes the host **legible**, not a new repo layout.

---

## 32. No-SCM project

Status MUST be able to say SCM unavailable / not configured. MUST NOT invent Git/P4 state. Freshness MAY be partial / UNKNOWN. Submit-S10 still requires durable finalization, but MUST NOT pretend an SCM Commit occurred; **P8** owns the atomic/conflict-detectable no-SCM finalization mechanism.

---

## 33. Project lifecycle and maintenance conditions

These are **two dimensions**. They MUST NOT be a single exclusive status enum.

`project.yaml` MUST be capable of representing the lifecycle **plus** zero or more applicable maintenance conditions. Exact YAML field names are **not** frozen.

### A. Adoption / management lifecycle

| State | Meaning |
| --- | --- |
| **NOT_ADOPTED** | Scaffold activation has never completed. Files alone are not enough. Normally **inferred externally**. MUST NOT require persisting this value in `project.yaml` on a host that has no such file yet. |
| **ADOPTING** | First-time adoption is underway; persistent Scaffold metadata MAY already exist. |
| **ACTIVE** | Activation Validation passed. |
| **RECOVERY_REQUIRED** | Partial/broken Scaffold state is unsafe to continue blindly. |

Mapping from P1 names: in-progress/interrupted → **ADOPTING**; needs recovery/re-planning → **RECOVERY_REQUIRED**.

An interrupted or uncertain migration after persistent mutation begins also uses **RECOVERY_REQUIRED** when coherent safe completion cannot be proven. Such a host MUST NOT return to normal ACTIVE use merely because some planned actions ran; P4 defines migration execution/recovery semantics and P5 applies them.

### B. Maintenance conditions

These are **not** replacements for ACTIVE. An **ACTIVE** host MAY simultaneously carry **NEEDS_REFRESH** and/or **NEEDS_MIGRATION**.

| Condition | Meaning |
| --- | --- |
| **NEEDS_REFRESH** | Knowledge is likely stale vs reality. Understand Refresh (P5) applies. Lifecycle MAY remain ACTIVE. |
| **NEEDS_MIGRATION** | A **compatibility evaluation** (P4/P5) has determined that the active project requires migration before normal use can safely continue. |

Mere Skill / lock / local version **difference** MUST NOT automatically set **NEEDS_MIGRATION**.

Correct flow:

```text
version/lock difference detected
  → Compatibility evaluation (P4/P5)
  → compatible: migration not required
  → compatibility logic determines migration required: NEEDS_MIGRATION
```

P2 MUST NOT invent the P4 compatibility algorithm. `skills.lock` remains path/role only.

MUST NOT explode into dozens of states or conditions. Detailed Refresh/Compatibility transitions: **P5/P4**.

---

## 34. Project Contract version

Active hosts MUST record the Project Contract version they conform to. This is **not** individual Skill versions (`skills.lock` / P4).

Compatibility MUST NOT be assumed silently. Detailed protocol: **P4**.

---

## 35. Cross-phase responsibilities

| Phase | Owns |
| --- | --- |
| **P3** | Task Book, Develop Session, Change Record schemas; IDs; Adoption/Develop session persistence |
| **P4** | Skill package, Rule load/route, `skills.lock` contents, compatibility, migration |
| **P5** | Creating/updating these artifacts in practice; Full / Refresh / Compatibility; freshness maintenance |
| **P6** | `tests.yaml` **execution**, Test Matrix, native tests, Evidence, and owned deterministic materialization/resolution of minimal durable Test support artifacts |
| **P7** | Task-driven edits; Develop Session |
| **P8** | Diff-derived consistency and test completeness; `SUBMIT_AUTHORIZED`; final Change Record and Finalization Bundle orchestration; SCM Commit or no-SCM durable finalization; optional Push |

---

## 36. Normative case outcomes

| Case | Behavior |
| --- | --- |
| **A** Empty adopted project | Required sparse core; `project.yaml` records domains not established; overview MAY explain; no invented modules/commands/tests. |
| **B** Mature docs outside `docs/project/` | Canonical entries **point**; do not copy; physical target keeps its own ownership. |
| **C** Human-owned AGENTS.md | MANAGED region or THIN_BRIDGE; no full-file replace. |
| **D** Generated AGENTS.md | GENERATED whole file; stays thin; points at docs + `.scaffold`. |
| **E** CLAUDE/Cursor duplicate architecture | Thin them; one canonical doc/index; one-way generate if a copy is required. |
| **F** Windows absolute paths | Shared metadata relative + `/`; absolutes only in `runtime/local/`. |
| **G** CRLF vs LF | Not semantic change; do not rewrite HUMAN_OWNED solely for EOL; Scaffold-owned shared text follows policy or LF. |
| **H** Module renamed | Update index + knowledge entry + links; Refresh; do not leave stale paths as VERIFIED. |
| **I** Module deleted, `modules.yaml` stale | CONFLICT; lifecycle MAY stay ACTIVE with **NEEDS_REFRESH**; MUST NOT silently drop or keep as truth. |
| **J** New important module | Add index + authority entry + test/rule refs as needed; not a full-tree rewrite. |
| **K** Build command changes | Update `commands.yaml` confidence; docs if declared workflow changed; conflict if they disagree. |
| **L** Testing strategy changes | Update declared policy in `tests.yaml` + testing entry; not twin essays. Availability stays an observed fact. |
| **M** No tests yet | `project.yaml` applicability + `tests.yaml` records none; testing.md optional; UNKNOWN/absent is allowed. |
| **N** No SCM | Lifecycle remains valid (MAY be ADOPTING / ACTIVE / RECOVERY_REQUIRED). SCM state and SCM-backed last-understood baseline MAY be unavailable / not configured. MUST NOT invent Git / Perforce / other SCM revision. Project Contract / adoption remains valid. |
| **O** Monorepo | One Contract MAY index multiple roots; optional nested contracts; no federation product. |
| **P** Generated dirs look like source | Classify generated vs source (with confidence); do not treat generated as architecture authority. |
| **Q** Managed markers missing/corrupt | CONFLICTING; no guess; no edit of that region; Refresh / human. |
| **R** HUMAN_OWNED doc vs YAML | Conflict; do not silently overwrite either; Refresh / human. |
| **S** Stale client entry | Thin-bridge/freshness failure; Refresh; do not let client file become a second architecture. |
| **T** Old `runtime/` data | Temporary; expire/cleanup; never treat as handoff knowledge. |
| **U** Domain extension | `.scaffold/ext/<namespace>/` only; core files unchanged. |
| **V** `skills.lock` present, P4 undefined | Location reserved; MUST NOT invent compatibility; **NEEDS_MIGRATION** only after a compatibility evaluation determines migration is required. |
| **W** Repo moved far past last-understood baseline | Lifecycle MAY stay **ACTIVE** with **NEEDS_REFRESH**; Understand Refresh before treating indexes as current. |

---

## 37. Non-goals

P2 MUST NOT: write `.scaffold/` or host `AGENTS.md` into **this** distribution repo; ship an AGENTS generator; YAML/JSON Schema validators; CLI; Python packages; Skill runtime; Task/Change/Session field schemas; Test/Repair/Submit implementations; Git/P4 integration code; hooks; migration engine; extension runtime; client generators; line-ending converters.
