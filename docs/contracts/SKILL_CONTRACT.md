# Skill Contract

This document is the P4 contract for **Skill identity**, **package format**, **versioning**, **`skills.lock`**, **compatibility evaluation**, **Skill routing**, **Project Rule loading**, and **client-neutral exposure**.

It does **not** implement Understand, Develop, Test, Submit, a resolver, a migration engine, or live host `.scaffold/skills.lock`.

**Normative words:** MUST, MUST NOT, SHOULD, MAY.

**Authority:** [CONSTITUTION.md](CONSTITUTION.md) wins on product rules. Host shape: [PROJECT_CONTRACT.md](PROJECT_CONTRACT.md). Records: [RECORDS_CONTRACT.md](RECORDS_CONTRACT.md). Adoption: [ADOPTION_CONTRACT.md](ADOPTION_CONTRACT.md). Routing diagrams: [../architecture/SKILL_ROUTING_AND_VERSIONING.md](../architecture/SKILL_ROUTING_AND_VERSIONING.md).

P4 MUST NOT silently redefine P0–P3. It fills the reserved `.scaffold/skills.lock` contents and the Skill-package / Rule-loading protocol that P0–P2 deferred.

This **distribution** repository MUST NOT contain live `skills/` packages or a host `.scaffold/skills.lock` as P4 artifacts. YAML blocks labeled **CONTRACT EXAMPLE — NOT RELEASE DATA** are illustrative only.

---

## 1. Scope

This contract answers: how are the four Scaffold Skills packaged, discovered, routed, versioned, locked, checked for compatibility, and exposed consistently to different Agent clients **without** duplicating project knowledge or silently changing workflow semantics?

It covers:

- canonical Skill ids and modes
- Skill vs Mode vs Project Rule
- Distribution packages vs host lock
- manifests, immutability, and version dimensions
- routing and nested invocation
- permission non-escalation
- ephemeral invocation / generic result
- `skills.lock` exact-expectation semantics
- compatibility results and migration protocol
- Compatibility Preflight (not a fifth Skill)
- Project Rule resolution
- client integration modes

It does **not** cover Skill business workflows (P5–P8), Test Evidence schema (P6), or live package/lock files.

---

## 2. Definitions

| Term | Meaning |
| --- | --- |
| **Skill** | A complete lifecycle-capable workflow with a stable `skill_id`. Exactly four exist. |
| **Mode** | A named operational path **inside** one Skill. Not independently versioned. Not a Skill package. |
| **Project Rule** | A project-local constraint or instruction for some scope. Not a workflow orchestrator. |
| **Distribution** | This scaffold product: Skill packages, contracts, later runtime. |
| **Host** | An adopted project. Holds `AGENTS.md`, knowledge, `.scaffold/skills.lock`. |
| **Canonical package** | The Distribution-side Skill package identified by `skill_id` + `skill_version`. |
| **Lock** | `.scaffold/skills.lock` — exact **expected** Skill identities/versions for this host. |
| **Actual package** | The package the local Distribution Resolver found and would execute. |
| **Selected Distribution Release** | The exact, explicitly identifiable Distribution instance/release and its coherent exact core-package set selected to perform first attachment before host lock authority exists. |
| **Pre-Adoption Bootstrap Preflight** | Distribution-anchored Compatibility Preflight context used only for legitimate first attachment before host Scaffold identity/lock exists. |
| **Host Compatibility Preflight** | Host-anchored Compatibility Preflight context that evaluates established host metadata/lock against actual manifests. |
| **Compatibility Preflight** | One Distribution support layer that selects the applicable preflight context and establishes safe resolution **before** a Skill starts. Not a fifth Skill. |
| **REVIEWED CANDIDATE DIFF** | P3 term. Submit’s reviewed change-set. Unchanged here. |

---

## 3. Exactly four Skills

Canonical `skill_id` values are **exactly**:

| `skill_id` | Human name | Question |
| --- | --- | --- |
| `understand` | Understand | What is this project, and how should a new Agent maintain it? |
| `develop` | Develop | How should the current task be completed under project rules? |
| `test` | Test | What was actually verified for the given scope, and with what result? |
| `submit` | Submit | Does the **real** working tree meet submission conditions? |

MUST NOT invent a fifth top-level Skill. MUST NOT rename a Skill because its version changed (`understand-skill-v2`, `scaffold-develop`, `submit-new` are forbidden identities).

---

## 4. Skill vs Mode vs Rule

### Skill

Owns a workflow. MAY accept structured context, invoke **allowed** subordinate Skills, and produce a structured result.

### Mode

Named path inside one Skill. MUST NOT become an independently versioned package.

| Skill | Modes (frozen homes) |
| --- | --- |
| Understand | `bootstrap` (Adoption / Bootstrap), `full`, `refresh`, `compatibility` |
| Develop | `normal_task`, `repair` |
| Test | Scoped verification only at P4. Additional Test modes, if any, are **P6**. They MUST NOT become top-level Skills. |
| Submit | No extra top-level Skill modes. Submit-S1…S12 remain **internal stages** (P0/P3). |

The following remain modes / internal workflows — **not** Skills:

| Name | Home |
| --- | --- |
| Adoption / Bootstrap | Understand `bootstrap` |
| Full / Refresh / Compatibility | Understand modes |
| Repair | Develop `repair` |
| Stage Validation | Develop → Test |
| Structural Review | Submit internal |
| Knowledge Consistency | Submit internal |
| Test Completeness | Submit internal |

### Project Rule

A project-local constraint. Examples: generated files must not be hand-edited; module X requires test suite Y; a directory requires a formatting workflow.

A Rule MUST NOT impersonate a Skill. A Rule MUST NOT grant Commit / Push / submission authorization.

---

## 5. Distribution vs host

Preserve P2.

```text
Scaffold Distribution
├── four Skill packages
├── framework contracts
├── compatibility protocol
└── later runtime / tooling

Adopted Project
├── AGENTS.md
├── docs/project/
├── .scaffold/skills.lock     expected Skill-set
└── thin / derived client integrations
```

Canonical Skill packages belong to the **Distribution**. A normal adopted host MUST NOT vendor a complete copy of all Skill implementation/instructions.

`skills.lock` locks **canonical** package identities. It MUST NOT lock Cursor / Claude / Codex adapter versions.

---

## 6. Canonical package layout

Distribution-side only. **Do not create these directories in this design task.**

```text
skills/<skill-id>/
├── skill.yaml
├── SKILL.md
└── references/          OPTIONAL
```

Required packages:

```text
skills/understand/
skills/develop/
skills/test/
skills/submit/
```

| Path | Role |
| --- | --- |
| `skill.yaml` | Machine identity, versions, modes, capabilities, compatibility declarations |
| `SKILL.md` | Canonical **normative** Agent-readable workflow/instruction entry |
| `references/` | OPTIONAL progressive-disclosure support. MUST NOT be a second identity authority |

---

## 7. Package authority

| File | Authority |
| --- | --- |
| `skill.yaml` | Machine identity / compatibility / declared capability metadata |
| `SKILL.md` | Normative workflow/instruction authority |
| `references/` | Supporting detail only |

If `skill.yaml` and `SKILL.md` **materially contradict** each other, the package is **INVALID** (package/input validity — **not** a sixth compatibility result). MUST NOT silently pick the convenient file. MUST NOT execute that identity as a valid released package. MUST NOT produce `EXACT` or `COMPATIBLE` for it.

---

## 8. Manifest contract

`skill.yaml` MUST be capable of representing:

| Concept | Purpose |
| --- | --- |
| `skill_id` | Exactly one of `understand` \| `develop` \| `test` \| `submit` |
| `skill_version` | Released Skill identity version (`MAJOR.MINOR.PATCH`) |
| `package_format_version` | How this package tree is interpreted |
| `entry` | Path to the instruction entry, normally `SKILL.md` |
| `modes` | Supported modes for this Skill |
| `contracts` | Framework/contract generations this package knows how to operate against |
| `provides` | Stable capability ids this Skill offers |
| `requires` | Capability **prerequisites** for safe operation/resolution. NOT invocation permission, NOT a new routing edge, NOT permission escalation |
| `runtime` | OPTIONAL client/runtime requirements (non-authoritative; not permissions) |

MUST NOT include: project-specific module data, Task Book content, secrets, chat history, model identity, user identity, or submission permission.

MUST NOT define a large package-manager schema. Exact key grammar is illustrative; the **capabilities** above are required.

No field such as `can_commit` / `submit_authorized` MAY serve as human authorization.

---

## 9. Skill ids

Core `skill_id` values are stable public identifiers. Version changes belong in `skill_version` only.

---

## 10. Semantic versioning

`skill_version` uses `MAJOR.MINOR.PATCH` **semantics**:

| Component | Meaning |
| --- | --- |
| **MAJOR** | Incompatible public Skill contract/workflow change. MAY require Compatibility evaluation or host migration. |
| **MINOR** | Backward-compatible capability/workflow extension. |
| **PATCH** | Backward-compatible correction / clarification / bug fix. |

The version number **alone** MUST NOT be the full compatibility algorithm.

- A different MAJOR MAY have an explicit migration path — or be `INCOMPATIBLE`.
- A MINOR/PATCH difference MUST NOT be silently treated as an **EXACT** lock match.
- MUST NOT say “major mismatch always migration” or “patch mismatch always safe.”

---

## 11. Released package immutability

Once a Skill package version is **released**, the meaning of:

```text
<skill_id>@<skill_version>
```

MUST be **immutable**.

The same id+version MUST NOT later contain materially different normative Skill behavior. If normative behavior changes, `skill_version` MUST change.

Development / unreleased packages MAY exist. They MUST NOT masquerade as the same released identity.

This is what makes `skills.lock` meaningful.

---

## 12. Package format version

`package_format_version` is distinct from all of:

| Dimension | Owner |
| --- | --- |
| `skill_version` | This package’s Skill identity |
| `package_format_version` | How the package tree is parsed |
| Project Contract version | `project.yaml` (P2) |
| Per-kind record `schema_version` | Task Book, Develop Session, Change Record, Adoption Session each self-describe (P3). Not one global number |
| `lock_format_version` | `skills.lock` grammar |
| Scaffold product / release version | Distribution product, if any |

MUST NOT conflate these dimensions. MUST NOT store a second hand-maintained copy of the Project Contract version in the lock when `project.yaml` already owns it.

---

## 13. Capabilities and compatibility declarations

A manifest MUST be able to state which framework contracts / capabilities it can operate against. Compatibility evaluation MAY consider:

- Project Contract generation (from `project.yaml`)
- **per-kind** record schema capabilities / generations the Skill can safely interpret (P3 kinds remain distinct)
- Skill `package_format_version`
- required core Skill capabilities (`requires`)
- required runtime / client capabilities

MUST NOT hardcode compatibility solely as “major versions equal.”

P4 freezes the **protocol**. It does not freeze every future compatibility matrix.

A Skill MAY be compatible with Project Contract generation A but not B. A Skill MAY safely interpret Task Book schema generation X but not Change Record generation Y. Evaluation MUST use declared contract capabilities, not only Skill-to-Skill version numbers.

MUST NOT collapse Task Book, Develop Session, Change Record, and Adoption Session into one global `records_schema_version`.

A Skill manifest MUST be able to declare which **relevant** record-type schema capabilities / generations it can safely interpret. Exact YAML grammar is **not** frozen. A Skill NEED NOT declare a record kind it never consumes, unless its workflow requires that kind.

This is capability/compatibility declaration only. It does **not** modify P3 record schemas.

P2/P3 version definitions are unchanged.

---

## 14. Skill dependencies

Packages MAY declare dependencies on **stable capabilities** provided by another core Skill.

`requires` means: **package/capability prerequisite** for the workflow/package to safely execute.

`requires` does **not** mean:

- permission to invoke another Skill
- permission to perform that Skill’s mutations
- permission escalation
- a new routing edge
- proof that another Skill MUST always be invoked at Skill startup

The manifest states required **capability availability**. Runtime invocation **timing** remains P5–P8 workflow behavior.

Capability prerequisite and runtime invocation are **related but distinct**. The Skill Contract **routing graph** remains authoritative for who may invoke whom.

Two questions MUST stay separate:

| Question | Failure means |
| --- | --- |
| **Dependency declaration validity** — is this `requires` entry itself legal? (valid capability id; not an invocation permission; no forbidden routing edge; no intrinsic circular core dependency **declaration**) | Package is **INVALID** |
| **Dependency satisfaction** — can **this** Distribution/environment actually provide that valid required capability? | Package remains **VALID**. Known unsatisfied requirement → `INCOMPATIBLE` or an explicit resolution blocker. Cannot safely determine satisfaction → `UNKNOWN` / blocker. MUST NOT guess. |

Examples:

- Develop MAY route/invoke Test because the **framework** allows it — not because `requires: test.execution` grants permission.
- Submit MAY use Test / Understand because the **framework** allows it.
- A manifest MUST NOT create `Test → Develop` source-edit authority merely by declaring `requires: develop.repair`.

| Guidance | Rule |
| --- | --- |
| Describe | required **capability** |
| MUST NOT describe | a random local filesystem path |
| MUST NOT | invent circular **core** dependency chains |
| MUST NOT | declare a dependency that creates a forbidden route |
| SHOULD | avoid unnecessary package coupling |

Dependency declarations MUST be compatible with the framework routing/call boundaries.

If a core package **declares** an impossible, cyclic, or forbidden dependency that contradicts this Skill Contract: the package is **INVALID** (validity layer). It MUST NOT enter compatibility evaluation as a valid released identity.

A **VALID** package whose current environment cannot satisfy a legal `requires` entry is **not** INVALID. That is resolution / compatibility, not package identity.

Conceptual examples (not a closed catalog):

- Develop `requires`: Test execution capability (prerequisite metadata; invocation is still the routing graph)
- Submit `requires`: Test capability; Understand Refresh capability; Understand Compatibility capability

Understand MUST NOT require Develop or Submit to exist in order to interpret a host.

---

## 15. Routing

Normal top-level ownership:

| Skill | Owns |
| --- | --- |
| **Understand** | Bootstrap / Adoption, Full, Refresh, Compatibility |
| **Develop** | Task implementation, stage implementation, Repair. MAY invoke Test for required validation. |
| **Test** | Verification execution and evidence/result reporting |
| **Submit** | Independent final review, real Diff intake, Structural Review, Knowledge Consistency, Test Completeness, human authorization gate, Change Record finalization, SCM Commit or no-SCM durable finalization, optional Push |

Test MUST NOT silently enter Develop. Test MUST NOT authorize submission.

Submit MAY invoke/use Understand Refresh or Compatibility, and Test, where its own lifecycle requires them.

P4 MUST NOT add a Submit stage.

### 15.1 AGENTS decision logic (conceptual)

`AGENTS.md` is the portable entry router (P2). Compound phrasing does **not** create extra Skills.

| User intent (examples) | Route |
| --- | --- |
| Understand or normalize this project | Understand (`full` or as needed) |
| Adopt this project | Understand `bootstrap` |
| Update stale knowledge | Understand `refresh` |
| Check Skill compatibility | Understand `compatibility` |
| Implement this Task | Develop `normal_task` |
| Repair a failed/reviewed implementation | Develop `repair` |
| Only run/verify tests | Test |
| Review and submit this candidate | Submit |
| Commit this approved candidate | Submit |

“Implement this and test it.” → **Develop** (invokes Test).  
“Review this, run whatever final tests are needed, and commit.” → **Submit** (uses Test and/or Understand as required).

MUST NOT route one user sentence into several independent top-level Agents that each assume authority.

---

## 16. Nested invocation

### 16.1 Develop ↔ Test

```text
Develop → Test → FAIL → Develop → Test → PASS → continue
```

This remains **two Skills**, not a `DevelopTest` Skill.

Test results alone MUST NOT grant `TASK_COMPLETE`, `READY_FOR_REVIEW`, or `SUBMIT_AUTHORIZED` (P0/P3).

Develop owns the distinct P3 Stage Completion Decisions and Task Completion
Decision. They may reference P6 public Evidence but MUST NOT forge Test
Evidence or treat `TEST_PASS` as either acceptance decision. Each decision
and every resulting Task/Stage transition uses the canonical Task Book
conditional-publication path.

Task planned `requirement_id` and P6 Test `profile_id` are distinct
identities. For a fresh executable profile to supply Evidence automatically,
current Task authority MUST contain an explicit durable execution binding:

```text
Task requirement R → P6 Test profile P
```

Develop derives the nested invocation from that binding and carries explicit
`requirement_id`→`profile_id` pairs plus selected profile IDs. Test executes
profiles and returns public locator output whose resolution preserves each
producing `profile_id`; Test does not decide that P satisfies R. Develop may
attach a locator to R only when R's current binding names that resolved
profile. Equal strings, list order, a sole selected result, or caller prose
MUST NOT create the association. Without an explicit binding, fresh execution
does not authorize automatic Task locator attachment.

The binding is durably recoverable from the Task Book and is substantive Task
authority. Changing it changes the P6 candidate. Result-side locator and
observed-outcome publication is bounded Task control-plane progress. When the
current Task's substantive projection is unchanged, those result fields are
candidate-neutral. Authorized Scaffold publication of them still MUST use Task
CAS. **candidate-equivalent != publication-authorized.** Legitimate HUMAN, CI,
or EXTERNAL P6 Evidence may instead be cited by its explicit opaque locator
without an automated profile binding.

### 16.2 Submit MUST NOT become Develop

If Submit discovers an implementation defect, missing required project change, or substantive repair requirement:

- Submit MUST NOT silently edit business/source content by switching itself into Develop
- Submit blocks / returns a **repair handoff** with one or more explicit
  `target_stage_ids` when the blocker deterministically maps to current Task
  Stage authority
- Develop (or Develop `repair`) → Test → Submit **re-enters** with a **new** candidate

P8 implements this. P4 freezes the routing boundary.

If Submit cannot deterministically map the blocker to a Stage, it MUST return
an unresolved repair route rather than guess the first, last, or all Stages.
For a READY Task, only a current, Task-bound, Stage-targeted
`submit_to_develop` handoff permits P7 to atomically reopen the Task and exact
target Stages. P8 does not write the Task Book.

### 16.3 Submit → Understand

Submit MAY require Understand `refresh` when knowledge, authority links, or structure are stale.

Submit MAY require Understand `compatibility` when Skill/contract compatibility is uncertain.

After a material project/candidate change, Submit returns through the existing S3/S4/S5/S6 loop (P0). No new Submit stage.

### 16.4 Handoff content

Cross-Skill handoff MUST carry only needed engineering state. MUST NOT copy entire chat context as the handoff contract.

| From → To | Carries (conceptually) |
| --- | --- |
| Develop → Test | Explicit Task `requirement_id`→Test `profile_id` execution bindings, selected profile IDs, and candidate / worktree context |
| Test → Develop | Producing profile identity + public Evidence locator references + result / failure / blocker |
| Develop → Submit | READY_FOR_REVIEW Task + current candidate context |
| Submit → Understand | Freshness / compatibility scope |
| Submit → Develop | Repair requirement as **HANDOFF**: Task and candidate binding, blockers, explicit `target_stage_ids`, optional P6 Evidence refs, and non-escalating bounded capabilities |

Candidate identity remains P6-owned. P7 and P8 consume P6's single
content-deterministic semantic candidate projection; neither may invent a
digest or trust a caller-provided identity. When current Task control-plane
bytes leave the substantive Task authority projection unchanged, P6 candidate
identity remains the same regardless of which process wrote those bytes. A
source, project, configuration, or substantive Task authority mutation still
changes the candidate. The complete real Diff remains visible to Submit in
either case. Authorized Task publication still requires P3 CAS.

---

## 17. Permission non-escalation

A child Skill invocation MUST NOT gain permissions merely because the caller has more authority.

| Invocation | MUST NOT imply |
| --- | --- |
| Develop → Test | Test may modify source |
| Submit → Test | Test may perform S10 durable finalization / Commit |
| Submit → Understand Refresh | Understand has generic Commit permission |

Human submission authorization remains owned by Submit / P8 and is **candidate-bound**. Skill routing MUST NOT escalate permission.

Neither `skill.yaml` nor `skills.lock` MAY grant Commit, Push, Adoption approval, or submission approval.

---

## 18. Invocation context and generic result

### 18.1 Ephemeral invocation context

P4 defines a **non-durable** invocation context. It is **not** a canonical development record (P3 taxonomy unchanged).

A Skill execution MUST be able to know / report:

- resolved `skill_id` and `skill_version` **actually used**
- selected mode
- host / project identity
- relevant baseline / candidate identity
- caller Skill if nested
- allowed operation context
- result / outcome
- blockers
- durable artifact / evidence references where applicable

MUST NOT persist chain-of-thought, full prompts, or chat logs as Skill state.

### 18.2 Generic result

Every Skill MUST be capable of returning a concise portable result containing:

- `skill_id` / `skill_version` actually used
- mode
- outcome
- relevant project / candidate baseline
- mutations performed or `none` (summary)
- produced / updated artifact references
- evidence / test references where relevant
- blockers / unresolved conflicts
- recommended next route
- if actual ≠ lock: an explicit **compatible-difference** (or other compatibility result) — MUST NOT report EXACT

Generic outcomes MAY include: `COMPLETED` | `BLOCKED` | `FAILED` | `NEEDS_HUMAN`.

Skills NEED NOT share identical detailed business fields (those are P5–P8).

---

## 19. `skills.lock`

P2 reserved `.scaffold/skills.lock`. P4 freezes it as:

**shared, durable, canonical expected Skill-set lock** for this host.

It MUST lock the four core Skill identities **explicitly**.

MUST NOT contain: absolute local installation paths, credentials, runtime Session data, human submit permission, chat/model data.

Do **not** create this file in this distribution repository.

### 19.1 Established-host discovery / resolution

```text
Host skills.lock
  → expected Skill identity / exact version
  → Distribution Resolver (actual available packages)
  → package manifest
  → Compatibility Evaluation
  → execute  or  block / Compatibility
```

This is the normal **Host Compatibility Preflight** model after host lock authority exists. Legitimate first attachment before `project.yaml` / `skills.lock` exists uses §27 **Pre-Adoption Bootstrap Preflight**, not a fabricated host lock.

Project-local installation is documented in [../CONSUMER_INSTALLATION.md](../CONSUMER_INSTALLATION.md). `.scaffold/install/install.yaml` is pre-Adoption product provenance and MUST NOT replace `skills.lock`.

### 19.2 Minimum lock model

Capable of representing:

| Concept | Purpose |
| --- | --- |
| `lock_format_version` | How this lock file is interpreted |
| four core `skill_id` entries | MUST all be present on an Active host |
| exact expected `skill_version` per Skill | Not a range |
| optional expected `package_format_version` | Format compatibility hint |
| optional distribution / source **identity** | Reproducible resolution — **not** a machine-local path |

MUST NOT duplicate the Project Contract version already owned by `project.yaml`. Host Compatibility Preflight **reads** `project.yaml` instead.

---

## 20. Lock ownership

`.scaffold/skills.lock` is a **GENERATED** durable Scaffold artifact.

It changes only through an explicit Compatibility / lock-update workflow.

Human approval of that workflow MUST NOT convert the whole file to HUMAN_OWNED.

The P2 ownership registry MUST be capable of covering `.scaffold/skills.lock` as GENERATED. P4 does **not** freeze per-file vs namespace/pattern representation. Exact `project.yaml` grammar remains P2. **This file does not edit P2.**

P2’s table allowed “GENERATED or MANAGED” as a reservation. P4 specializes the reserved artifact’s mode to **GENERATED**. That is not a fourth ownership mode.

---

## 21. Exact expectation semantics

For each core Skill, the lock records an **EXACT** expected `skill_version`.

```text
understand: 2.0.0     ← exact
understand: ">=2"     ← forbidden as the lock value
```

Compatibility MAY allow execution using a **different** actual version (`COMPATIBLE`). That does **not** make the lock an exact match and MUST NOT be reported as `EXACT`.

---

## 22. Compatibility result model

### 22.1 Package / input validity (not a sixth result)

**INVALID is not a sixth compatibility result.**

Freeze a pre-compatibility validity layer:

```text
PACKAGE / INPUT VALIDITY
  → VALID
  or
  → INVALID
```

Only a **VALID** resolved package MAY enter the normal five-result compatibility evaluation.

```text
package declaration / release validity
        │
        ├─ INVALID → validity blocker
        │            MUST NOT produce EXACT or COMPATIBLE
        │            MUST NOT execute as the claimed
        │            valid released identity
        │
        └─ VALID
              │
              ▼
         current resolver / environment
         capability evaluation
              │
              ▼
         compatibility evaluation
              │
              ▼
         EXACT | COMPATIBLE | MIGRATION_REQUIRED
         | INCOMPATIBLE | UNKNOWN
```

INVALID covers **intrinsic / static** correctness of the claimed package/release. Examples:

- malformed required manifest syntax/data
- invalid core `skill_id`
- malformed semantic `skill_version`
- malformed / impossible `package_format_version` **declaration**
- required `entry` missing **from the package**
- declared mode incompatible with the Skill identity
- material `skill.yaml` / `SKILL.md` contradiction
- positively detected mutation of an immutable released identity
- malformed capability declaration
- dependency declaration that creates a **forbidden** routing relation
- intrinsically circular core dependency **declaration**
- otherwise structurally impossible package declaration

A package MUST NOT become intrinsically INVALID merely because the **current** Distribution / runtime cannot satisfy a valid declared prerequisite.

- Well-formed `package_format_version` that **this** resolver does not support → package MAY remain VALID; current Distribution cannot safely execute it → `INCOMPATIBLE` / `UNKNOWN` / distribution blocker as appropriate. Not automatically INVALID.
- Valid `requires` whose capability is missing **here** → package remains VALID; unsatisfied prerequisite → `INCOMPATIBLE` or explicit resolution blocker. Cannot determine satisfaction → `UNKNOWN` / blocker.

Do **not** add `DEPENDENCY_MISSING` or `FORMAT_UNSUPPORTED` as compatibility-result values. They MAY be blocker **reasons**, not new result classes.

P4 does **not** implement a concrete package-format negotiation algorithm.

Matching id/version **strings** MUST NOT force `EXACT`. Same version ≠ automatically `EXACT`.

If package/release identity validity itself cannot safely be established where the Distribution requires such identity verification: MUST NOT guess. Surface a blocker, or `UNKNOWN` **after** a VALID package is in evaluation, as appropriate. MUST NOT call the package `EXACT` merely because id/version strings match.

A GENERATED DERIVED COPY of an INVALID canonical package does **not** make that package VALID. Canonical package validity/identity still comes first.

### 22.2 The five compatibility results

Frozen compatibility results remain **exactly these five**:

| Result | Meaning |
| --- | --- |
| **EXACT** | Resolved package is **VALID**; expected id/version **matches** the lock; **and** required compatibility checks pass |
| **COMPATIBLE** | Resolved package is **VALID**; actual version **differs** from the lock; evaluation from **explicit inputs** establishes safe operation **without** host migration; difference MUST be surfaced; lock unchanged unless explicitly updated |
| **MIGRATION_REQUIRED** | Resolved package is **VALID**; evaluation determines the host’s persistent Scaffold-managed representation must change before normal operation can safely proceed. For an **ACTIVE** host this **semantically applies** P2 `NEEDS_MIGRATION`. P5 owns operational persistence of that maintenance condition. |
| **INCOMPATIBLE** | Resolved package is **VALID**; known unsafe / unsupported combination. No currently valid normal execution path. |
| **UNKNOWN** | Resolved package is **VALID**, but compatibility cannot be established safely. MUST NOT guess. |

P4 MUST NOT add `INVALID` to this enum. P4 MUST NOT add P2 lifecycle states.

For an **ACTIVE** host: compatibility result `MIGRATION_REQUIRED` → P2 `NEEDS_MIGRATION` **semantically applies**. P5 owns writing/updating that condition. This phase does not implement P5.

For a host that is **not** ACTIVE (e.g. ADOPTING / RECOVERY_REQUIRED), the corresponding lifecycle / recovery flow MAY govern instead of the ACTIVE maintenance condition.

`NEEDS_MIGRATION` is produced **only after** evaluation yields `MIGRATION_REQUIRED`. Mere version difference MUST NOT create it.

---

## 23. Compatible substitution

A `COMPATIBLE` result MAY allow execution using a non-exact local Skill version.

If so:

- actual version MUST be surfaced in the Skill result
- MUST NOT be reported as `EXACT`
- lock MUST remain unchanged unless an **explicit** lock update is performed
- durable outputs MUST NOT pretend the locked version actually ran
- the compatibility decision MUST be reproducible from the **explicit evaluation inputs** used for that decision

Those inputs include, as applicable:

- locked expected skill id/version
- actual resolved package identity/version
- valid package manifest / release identity
- Project Contract state / version / capabilities
- relevant **per-kind** Record schema capabilities
- required dependency capability results
- package format support
- required runtime / client capability facts

MUST NOT require chat history or Agent memory. MUST NOT store all of these inside `skills.lock`. The lock remains the **expected Skill lock**, not an execution transcript.

Compatibility evaluation is context-sensitive but reproducible from explicit engineering inputs.

P4 does **not** require human confirmation for every PATCH difference. Projects / runtime policy MAY be stricter later.

**Silent identity substitution is forbidden.**

---

## 24. Version difference ≠ migration

Preserve P2 exactly:

```text
lock / version difference
  → evaluate compatibility
       EXACT              → normal
       COMPATIBLE         → MAY proceed under policy; difference remains explicit
       MIGRATION_REQUIRED → ACTIVE host: NEEDS_MIGRATION semantically applies
                            (P5 persists the condition)
                            non-ACTIVE: lifecycle / recovery flow MAY govern
       INCOMPATIBLE       → block normal Skill execution
       UNKNOWN            → block unsafe execution / require resolution
```

Mere difference MUST NOT automatically mean `NEEDS_MIGRATION`. Only evaluated `MIGRATION_REQUIRED` creates that semantic condition.

---

## 25. Migration semantics

**Migration** ≠ installing another local package.

Migration means the **host’s persistent Scaffold-managed representation** must change because the new framework/Skill generation cannot safely use the old representation unchanged.

Later it MAY involve: project metadata, managed entries, record conversion strategy, client bridges, other Scaffold-controlled artifacts.

P4 defines the protocol. **P5** Understand Compatibility **executes** it.

### 25.1 Safety

Migration MUST NOT be silently applied merely because a newer Skill package exists.

A migration path MUST be:

- explicitly identified
- bounded
- reviewable
- based on known source/target contract versions
- capable of reporting intended persistent mutations
- blocked if prerequisites are unknown

Actual host mutation requires **explicit human approval of the migration plan** before application.

**Migration Plan Approval** is bound to:

- the specific migration plan identity / content
- source host Project Contract / Scaffold state
- source `skills.lock` expectation
- relevant source record / metadata generation
- target compatibility / migration intent
- approved persistent mutation envelope

Exact storage/schema is **not** P4.

If **before the first migration mutation** any of the following materially change:

- the migration plan
- host persistent Scaffold state
- `skills.lock`
- source / target contract assumptions
- the migration mutation envelope

then previous Migration Plan Approval is **invalid**.

Required flow:

```text
re-evaluate compatibility
  → update / regenerate migration plan
  → explicit human re-approval
  → apply later in P5 Understand Compatibility
```

Pure observational information that does **not** alter plan applicability or the mutation envelope MUST NOT automatically require re-approval.

Migration Plan Approval is **not** P8 `SUBMIT_AUTHORIZED`. Persistent migration changes still require normal Submit and candidate-bound S10 authorization before durable submission finalization.

### 25.2 Migration execution and interruption

P5 MUST execute an approved migration through this minimal lifecycle:

```text
PREPARED → APPLYING → VALIDATING → COMPLETED
PREPARED → ABORTED
APPLYING / VALIDATING → RECOVERY_REQUIRED
RECOVERY_REQUIRED → deterministic resume or proven-safe ABORTED
```

This lifecycle is not a fifth Skill and does not create a fourth canonical development record. P3 defines minimum representation obligations for a bounded operational Migration Execution artifact/session; P5 owns its concrete schema, persistence, checkpoints, and runtime.

| State | Meaning |
| --- | --- |
| **PREPARED** | Execution context is bound to plan identity/content, source host state/fingerprint, source `skills.lock`, relevant record/metadata generation, target intent, and approved mutation envelope. PREPARED is not persisted human permission. Before first mutation, P5 MUST revalidate those bindings and establish valid current Migration Plan Approval. |
| **APPLYING** | Persistent mutation has begun. Execution state records which approved actions/checkpoints completed, which remain, expected observed state for recovery, and rollback/recovery information where defined. Universal rollback is **not** required. |
| **VALIDATING** | Approved mutation actions ran, but required post-apply validation has not yet established a coherent successfully migrated host. Normal operation MUST NOT treat migration as complete. |
| **COMPLETED** | Migration actions and required validation succeeded. P5 may then update or clear applicable P2 `NEEDS_MIGRATION` / `RECOVERY_REQUIRED` state and clean temporary execution state according to its lifecycle. |
| **RECOVERY_REQUIRED** | Persistent mutation may be partial/uncertain, actual host state diverged unexpectedly, validation cannot establish coherence, or restart cannot safely determine how to resume. A host in this condition MUST NOT return to normal ACTIVE use blindly. |
| **ABORTED** | Valid only if no persistent migration mutation occurred, or all applied mutations were proven safely reverted/neutralized and the host is coherent. Unknown partial mutation is RECOVERY_REQUIRED, never ABORTED. |

Recovery MUST observe the actual host, read execution checkpoints, and compare both against the approved mutation envelope.

- If observed state is a provable expected prefix/checkpoint of the approved plan, P5 MAY deterministically resume under the approved recovery protocol.
- Approved Apply actions moving the host through expected checkpoints inside the mutation envelope do **not** by themselves invalidate approval applicability.
- If material unexpected divergence exists, or remaining mutations/assumptions would leave the approved envelope, the prior approval is no longer applicable. Re-evaluate compatibility, update/regenerate the plan, and obtain human re-approval before further mutation.

Interruption after persistent mutation begins MUST enter RECOVERY_REQUIRED unless deterministic safe completion or a coherent safely reverted state can be proven. Execution/checkpoint state MUST NOT be cleaned while needed to reason about uncertain partial mutation.

### 25.3 Records

If a new Skill generation cannot safely interpret old Task / Change / Session schema: it MUST NOT silently rewrite those records.

Evaluation MAY return `MIGRATION_REQUIRED`.

A later migration plan MUST respect P3: durable historical Change Records MUST NOT normally be rewritten. Prefer new reader compatibility, corrective metadata, or a forward conversion strategy. P4 does **not** implement historical migration.

---

## 26. Lock update vs project migration

| Action | Meaning |
| --- | --- |
| **Lock update** | Explicit project decision to change exact expected Skill versions. Host representation otherwise usable. |
| **Project migration** | Host persistent Scaffold-managed representation must change. |

Example: Skill `2.0.0` → `2.0.1` is `COMPATIBLE` and needs no host representation change. An explicit decision MAY update `skills.lock`. That is a **lock update**, not project migration.

`NEEDS_MIGRATION` MUST NOT be used for a simple intentional lock refresh when no host migration is required.

A proposed lock update MUST make visible: old expected versions, new expected versions, compatibility result, whether project migration is required, and why. MUST NOT hide a Skill upgrade inside unrelated business changes. It MAY later be submitted together, but the version change MUST remain visible.

A lock mutation is a real project change. It MUST go through Understand Compatibility / the change workflow and later normal Submit review. MUST NOT silently rewrite the lock because a newer version is available or happened to execute successfully.

---

## 27. Compatibility Preflight (support layer)

There is a bootstrap problem: a Skill MUST NOT blindly run before compatibility is known.

**Skill Resolver / Compatibility Preflight** is a **Distribution support layer**. It is **not** a fifth Skill.

It supports exactly two **resolution contexts**, not two Skills, workflows, compatibility enums, or lifecycle states:

| Context | Authority anchor | Applies when |
| --- | --- | --- |
| **Pre-Adoption Bootstrap Preflight** | Explicitly Selected Distribution Release | Legitimate first attachment before host Scaffold identity and lock authority exist |
| **Host Compatibility Preflight** | Complete authoritative host `skills.lock` expectations with `project.yaml`, or the bounded Plan-derived recovery anchor in §27.5.1, resolved against actual local Distribution packages | Host Scaffold metadata/lock exists or prior Scaffold identity/state means normal host/recovery reasoning applies |

Context selection MUST use read-only evidence and P1/P2 lifecycle semantics. It MUST NOT mutate the project or pre-create host metadata merely to make preflight succeed.

### 27.1 Pre-Adoption Bootstrap Preflight

This narrow context is allowed only when read-only first-contact classification can establish:

```text
ordinary project
+ legitimate NOT_ADOPTED condition
+ no established Scaffold host identity
+ no evidence requiring Adoption recovery
```

P4 does not redefine P1 B1/B2 Discovery or P2 lifecycle semantics. The support layer establishes only enough read-only context to choose the safe preflight path; Understand `bootstrap` then owns the P1 Adoption workflow.

In this context, absence of `.scaffold/project.yaml` and `.scaffold/skills.lock` is expected. It MUST NOT automatically mean corruption, `INCOMPATIBLE`, package `INVALID`, or missing-lock recovery for an ACTIVE host. The absence is acceptable only because durable host authority has not yet been established.

Before host lock authority exists, bootstrap resolution MUST be anchored to an exact, explicitly identifiable **Selected Distribution Release**. The invoked Distribution instance MUST expose an unambiguous release identity and a coherent exact core-package set. Resolution MUST NOT mean “use whatever Understand package happens to be installed” or silently select the newest available package.

If multiple possible releases/packages exist and the invoked Distribution release cannot be uniquely determined: MUST NOT guess. **BLOCK** and require explicit release resolution/selection.

Before Understand `bootstrap` may execute, the actual resolved bootstrap Understand package MUST be established as the **exact Understand package pinned by that Selected Distribution Release’s coherent core-package set**. This exact identity relation includes, as applicable under the existing package/release rules:

- `skill_id` is `understand`
- actual `skill_version` equals the release-pinned Understand version
- actual package/release identity corresponds to that released package member
- immutable package/release identity and integrity checks pass

Matching `skill_id` and `skill_version` strings alone MUST NOT establish this relation when released-package identity or integrity cannot be established. A mutated or otherwise INVALID package does not become the release-pinned package merely because those strings match.

If the actual resolved bootstrap Understand does not exactly match the release-pinned Understand identity: **BLOCK before Understand bootstrap executes** and require explicit release/package resolution. Pre-Adoption Bootstrap Preflight MUST NOT use the established-host `COMPATIBLE` substitution model, silently execute or substitute the alternative package, or treat the mismatch as `EXACT`, `COMPATIBLE`, or a new compatibility-result value.

If a different Understand package is intended, a coherent Distribution Release/core-package set that pins that exact intended package MUST be explicitly selected/resolved, then Pre-Adoption Bootstrap Preflight MUST be rerun. P4 does not freeze how releases are installed, acquired, or selected.

Pre-Adoption Bootstrap Preflight MUST at minimum establish:

- Selected Distribution Release identity
- the Selected Distribution Release’s pinned Understand package identity/version
- actual Understand package identity and `skill_version`, and its exact identity binding to that release-pinned package
- intrinsic package validity (`VALID` / `INVALID`)
- immutable release identity/integrity as applicable
- Understand declares/supports `bootstrap`
- package format is interpretable by the selected/current Distribution
- required bootstrap runtime/client capabilities are satisfied
- bootstrap-required dependency capabilities are resolvable
- actual Understand version is surfaced

It MUST NOT require a host `project.yaml` or `skills.lock` that legitimately does not yet exist. It MUST NOT report `EXACT` from a lock comparison when no initial host lock exists. Pre-Adoption Bootstrap Preflight is a resolution context, not a sixth compatibility result.

### 27.2 Missing metadata is not a bootstrap signal

MUST NOT define:

```text
skills.lock missing → bootstrap
```

Missing/incomplete metadata may instead indicate interrupted Adoption, partial adoption, a corrupted previously ACTIVE host, `RECOVERY_REQUIRED`, or conflicting Scaffold footprint.

If prior Scaffold identity, partial durable state, or conflicting/insufficient evidence makes legitimate first attachment unsafe to establish, preflight MUST NOT silently downgrade to bootstrap. It MUST block or use existing `ADOPTING`, `RECOVERY_REQUIRED`, `UNKNOWN`, `CONFLICTING`, and recovery semantics according to P1/P2 authority. P4 adds no lifecycle state.

### 27.3 Initial Adoption Plan and lock intent

P4 specializes the package/version portion of the existing P1 B3 Adoption Plan. The Plan MUST bind, directly or by stable exact reference:

- Selected Distribution Release identity
- actual bootstrap Understand package identity/version
- target Project Contract generation/intent as applicable
- exact intended initial four-core-Skill set
- exact intended initial `.scaffold/skills.lock` values
- mutation envelope that creates/normalizes host metadata and the initial lock

These are not independent arbitrary facts. For Understand, the Plan MUST preserve one coherent identity relation:

```text
Selected Distribution Release pinned Understand
= actual resolved bootstrap Understand
= initial skills.lock expected Understand
```

The intended `develop`, `test`, and `submit` lock entries MUST come from the same coherent Selected Distribution Release/core-package set. The Plan MUST NOT combine a release-pinned Understand with a different actual bootstrap Understand or a mixed-release initial package set.

The Plan remains subject to existing P1 Human Plan Approval. No host metadata or initial lock may be created before P1’s approved mutation stage merely to satisfy preflight.

The initial `skills.lock` MUST contain exact expected versions for **all four** core Skills (`understand`, `develop`, `test`, `submit`) derived from the one coherent Selected Distribution Release/core-package set used for Adoption. Its expected Understand identity/version MUST equal both the release-pinned and actual resolved bootstrap Understand identity/version. Executing only Understand during bootstrap does not permit an Understand-only lock. Mixed-release package sets, version ranges, machine-local paths, secrets, and permission bits remain forbidden.

If, before Apply, the Selected Distribution Release identity, its release-pinned Understand identity, actual bootstrap Understand identity/version, intended core Skill set, initial lock content, target contract generation, or approved mutation envelope materially changes—or if the required release/actual/lock identity binding otherwise no longer holds—existing Adoption Plan Approval MUST NOT silently carry over. Re-resolve/re-discover/re-evaluate as needed, update/regenerate the Plan, and obtain human re-approval under P1. No new permission type is created.

### 27.4 Authority handoff

```text
legitimate first attachment before host identity/recovery evidence
  → bootstrap resolution authority = Selected Distribution Release

host identity/recovery evidence exists before complete initial lock
  → Host Compatibility / recovery path
  → same applicable approved Plan's Selected Distribution Release
     MAY serve only as the bounded §27.5.1 recovery anchor

approved Adoption completely and coherently establishes initial skills.lock
  → normal resolution authority = durable host metadata/lock
  → actual local Distribution packages are evaluated against that lock
```

The authority handoff occurs only when the complete coherent initial `skills.lock` has been durably established according to the approved Adoption. No lock, two-of-four entries, malformed/incomplete initial lock, or interrupted publication is normal expected-version authority.

After that complete establishment, `skills.lock` is the durable expected-version source of truth. The bootstrap-selected release and any Plan-bound recovery use MUST expire as resolution authority and MUST NOT remain a second durable host version authority. If release identity is retained as source/provenance inside the lock or historical Adoption evidence, it MUST NOT compete with the lock’s exact expected Skill entries.

A later Agent with no chat history reads the durable host lock and runs Host Compatibility Preflight. It does not require the adopting Agent’s memory to determine expected versions.

### 27.5 Host Compatibility Preflight

For established/adopted hosts, normal lock-based behavior is unchanged. Preflight MAY:

- read `project.yaml`
- read `skills.lock`
- inspect available Skill manifests
- decide **intrinsic package/input validity** (`VALID` / `INVALID`)
- for VALID packages only: evaluate whether the **current** resolver/environment can satisfy declared format and capability prerequisites
- compare package / contract compatibility **only for VALID packages**
- decide whether a requested Skill may start

An `INVALID` package is a validity blocker. It MUST NOT be scored `EXACT` or `COMPATIBLE`.

A VALID package whose current environment cannot satisfy a legal prerequisite MUST NOT be rewritten as INVALID. Use `INCOMPATIBLE`, `UNKNOWN`, or an explicit resolution/distribution blocker as appropriate. MUST NOT guess.

When compatibility **work** itself is required: route to Understand `compatibility` **if** the available Understand package declares it can safely interpret the **current host generation**.

If even that cannot be established: **BLOCK** and require a compatible Distribution / explicit migration path.

#### 27.5.1 Interrupted initial-Adoption recovery before complete lock

An interrupted first Adoption in which host identity or other prior Scaffold state already exists belongs to the **Host Compatibility Preflight / recovery path**, under P2 `ADOPTING` / `RECOVERY_REQUIRED` semantics as the evidence requires. It is not legitimate fresh attachment and MUST NOT reuse Pre-Adoption Bootstrap Preflight. This is a narrow resolution rule inside the existing Host context, not a third Preflight context, lifecycle state, compatibility result, record, or approval type.

Before a complete authoritative initial `skills.lock` exists, the same revalidated approved Adoption Plan’s Selected Distribution Release MAY temporarily anchor package resolution solely to continue that same initial Adoption. This bounded anchor MAY be used only when P1/P2/P3 facts and actual host observation establish all of the following:

- the host is in the current initial Adoption execution/recovery path, not a completed `ACTIVE` host
- a recoverable current Adoption Session exists and identifies the applicable Adoption Plan
- the Plan identity/content is recoverable
- P1 revalidation establishes that the Plan had valid Human Plan Approval and that approval remains applicable; a persisted observed-approval field alone is not permission
- the Plan still binds the exact Selected Distribution Release, exact release-pinned Understand, coherent exact four-Skill core set, exact intended initial `skills.lock`, target contract intent as applicable, and approved mutation envelope
- observed durable host state is a provable expected prefix/checkpoint of that envelope, or another state P1 recovery can safely reason about without changing approved intent
- the exact Selected Distribution Release and pinned package identities remain resolvable
- the actual Understand needed for recovery satisfies the R4 exact identity relation: release-pinned Understand = actual resolved recovery Understand, including applicable package/release identity and integrity

If any required fact cannot be established: MUST NOT guess. BLOCK or return to P1 recovery/re-planning and human re-approval as applicable. There is no pre-lock `COMPATIBLE` substitution, latest-installed fallback, or same-version-string shortcut.

When valid, this package-resolution authority is **Plan-bound, execution-bound, recovery-only, and non-reusable outside that Adoption**. It is not durable host expected-version authority, human permission, or a compatibility-result value. Preflight revalidation and package resolution remain read-only: they do not publish the lock, replay an action, or mutate the host. P4 authorizes only bounded package resolution; P1/P5 remain responsible for whether and how approved remaining work may resume. P4 does not decide replay, idempotence, rollback, retry, checkpoint storage, or concrete resume behavior. P3 remains authority for Adoption Session representation and retention.

An absent, partial, malformed, incomplete, or not-yet-authoritatively-published initial lock is recovery evidence, not normal Host Compatibility expected-version authority. MUST NOT perform ordinary lock-based compatibility against it. The intended complete lock comes from the applicable approved Plan; it MUST NOT be inferred or regenerated from whatever packages are installed. Completing the Plan’s already-approved outstanding initial-lock action is not regeneration from installed packages, and the package environment MUST NOT redefine the intended lock.

Expected approved progress alone does not invalidate Plan Approval applicability. Material unexpected divergence, a changed Plan/envelope/identity binding, or work outside the approved envelope requires re-discovery/re-evaluation as needed, an updated/regenerated Plan, and P1 human re-approval. No new permission is created.

The bounded recovery anchor MUST cease when the complete coherent initial lock becomes authoritative, Adoption is abandoned/aborted under P1, the Plan is replaced, approval is no longer applicable, observed state materially diverges, exact release/package resolution fails, or recovery requires a revised Plan and approval.

A historical Adoption Plan MUST NOT be revived as a magic lock for an `ACTIVE` host that later loses or corrupts its previously authoritative lock. That remains established-host consistency/recovery behavior. The bounded rule applies only to the same interrupted initial Adoption whose complete initial lock was never successfully established and whose current Session/Plan/recovery binding proves that fact.

The rule MUST work without host SCM. Recovery authority derives from durable Scaffold state, the Adoption Plan/Session binding, actual host observation, and Distribution-owned release identity—not Git history, tags, SHAs, or remote branches.

A later Agent with no chat history can recover the expected release, exact U/D/T/S set, recovery Understand, and intended complete lock only from those revalidated durable/session/Plan facts. If that Agent cannot recover the binding or resolve the exact release-pinned package, it MUST BLOCK rather than substitute its own local package set.

Compatibility Preflight MUST NOT perform project development in either context.

---

## 28. Missing / invalid package or lock

If an expected Skill cannot be found, has a malformed manifest, has invalid package structure, contradicts its own `SKILL.md`, or has other **INVALID** validity failures:

- that is a **package/input validity** blocker, not a fifth/sixth compatibility result
- MUST NOT produce `EXACT` or `COMPATIBLE`
- MUST NOT execute as the claimed valid released identity
- MUST NOT silently replace with generic chat behavior, another Skill, or a client-specific stale copy

If a **VALID** package cannot establish supported contract compatibility: evaluate to `INCOMPATIBLE` or `UNKNOWN` as appropriate. MUST NOT guess.

An ACTIVE or previously established host whose `skills.lock` is missing, malformed, incomplete, or lacks one of the four core Skill entries has a Scaffold consistency problem.

MUST NOT silently regenerate the lock from whatever is installed and continue as though nothing happened.

Route to Understand Compatibility / recovery planning **where safely possible** (P5 owns operational repair). Otherwise BLOCK.

This established-host rule MUST NOT be applied to legitimate first attachment merely because no initial host lock exists. Conversely, missing lock alone MUST NOT select bootstrap; §27 context classification governs.

For the same currently interrupted initial Adoption, §27.5.1 MAY provide bounded Plan-derived package resolution when all recovery conditions hold. The missing/incomplete lock itself supplies no expected-version authority. If those conditions do not hold—including when a previously `ACTIVE` host later loses its lock—BLOCK or use P1/established-host recovery; MUST NOT reconstruct authority from installed packages or a historical Adoption Plan.

---

## 29. Project Rules

P4 owns Rule **loading / routing** semantics. It does **not** create a second Rule database or require `docs/project/rules/`.

Rules MAY already live in: `docs/project/` content; existing HUMAN_OWNED docs; dedicated Rule files a project chooses; module knowledge entries.

References MAY be indexed by `modules.yaml`, project docs, or other P2-approved pointers. MUST NOT create another global project state file.

A dedicated rules directory MAY exist. It is **not** mandatory.

### 29.1 Rule reference

A usable Rule reference MUST make discoverable:

- stable authority source / path / reference
- applicability scope
- normative rule content
- module / domain association when relevant

A Rule SHOULD have a stable name/id when referenced from multiple places. Exact YAML schema is **not** frozen.

### 29.2 Scope / progressive disclosure

Load Rules according to work scope. MUST NOT load every project Rule into every Agent context merely because it exists.

| Kind | When |
| --- | --- |
| Global | All relevant Skills for that host |
| Module / path | When that module/path is in scope |
| Test-specific | When Test / Develop / Submit scope requires it |

### 29.3 Authority / conflicts

MUST NOT define “most specific file always wins.”

Framework Contract invariants remain authoritative (Constitution, Project Contract, Records Contract, this Skill Contract).

Valid Project Rules MAY specialize generic Skill behavior **within** allowed framework bounds.

If a Project Rule contradicts a higher framework invariant: that is a **CONFLICT**. MUST NOT silently override the framework.

If two applicable Project Rules conflict and authority cannot be determined: MUST NOT guess. Surface conflict → Understand Refresh / human resolution as appropriate.

### 29.4 Current human instruction vs Rule

A current human instruction MAY intentionally request a Rule change. That is **not** permission to silently ignore the existing Rule.

The Skill MUST surface that a rule/governance change is being requested. The change is a project mutation subject to normal review. MUST NOT pretend the old Rule never existed.

### 29.5 Skills MUST NOT hardcode project Rules

Generic Skill packages MUST NOT hardcode project-specific module structure, test-suite names, local paths, engine rules, or business policy.

Skill package = workflow logic. Project = project-specific facts/Rules.

---

## 30. Client-neutral authority

Canonical Skill authority MUST NOT belong to Cursor, Claude, Codex, or any other individual client.

Canonical authority is the **Scaffold Distribution package**. Clients are consumers / adapters.

Claude-specific, Cursor-specific, or Codex-specific copies MUST NOT become independent Skill authorities.

`skills.lock` targets canonical packages, **not** client adapter versions. One project Skill expectation remains client-neutral.

---

## 31. Client integration modes

At least these three:

| Mode | Meaning |
| --- | --- |
| **NATIVE LOAD** | Client directly loads the canonical Skill package. **Preferred.** |
| **THIN BRIDGE** | Client-specific project/config file points at AGENTS + the canonical Skill resolver/authority. Aligns with P1 `THIN_BRIDGE` strategy. |
| **GENERATED DERIVED COPY** | Only when a client **technically requires** local copied instructions. |

Authority and ownership remain independent (P2). A durable Scaffold-created thin bridge, generated derived copy, or Scaffold-managed region in an existing client file MUST be covered by the P2 ownership registry even though it remains non-authoritative. Whole generated copies use **GENERATED**; Scaffold-controlled regions use **MANAGED**; preserved files with no Scaffold-controlled mutation remain **HUMAN_OWNED**. No fourth mode is introduced.

### 31.1 Generated derived copy

The copy MUST be: derived one-way, non-authoritative, regenerable, source-identifiable. MUST NOT be hand-maintained as an independent Skill.

It SHOULD identify conceptually: source `skill_id`, source `skill_version`, and generation/adapter version where useful.

This metadata is for **synchronization**, not authorship credit. MUST NOT require user-visible AI attribution.

If the source Skill version changes, a stale derived copy MUST be detectable.

A derived copy does **not** make an INVALID canonical package VALID. Canonical package validity / identity still comes first.

P4 does **not** design exact client file syntax.

Different clients MUST resolve the same: AGENTS authority, `skills.lock` expectation, canonical Skill ids, Project Rules, project records. They MAY use different adapters. They MUST NOT develop separate project truths.

Two Agents with different locally installed Distribution versions each: read the **same** lock → resolve **own** available packages → run Compatibility evaluation → report **actual** Skill versions → execute only if allowed.

---

## 32. Actual version reporting

Every Skill execution MUST be able to report the actual `skill_id` and `skill_version` that executed.

If actual ≠ lock, the result MUST make the compatibility difference visible.

This supports reproducibility and multi-Agent debugging without storing chat history.

---

## 33. No-SCM

Skill resolution and version compatibility MUST NOT require Git / Perforce.

`skills.lock` remains usable on no-SCM hosts. It is still a **persistent host artifact** even without SCM.

A Selected Distribution Release identity used for Pre-Adoption Bootstrap Preflight MUST NOT depend on SCM being present in the ordinary host. A Distribution MAY expose its own stable release identity independently of host SCM.

A lock update is still a project mutation. P8 owns the concrete submission/finalization mechanism. SCM-dependent history / Commit capabilities exist **only when SCM exists**. On a no-SCM host, Submit-S10 instead uses P8’s atomic or conflict-detectable durable finalization/publication operation; P4 freezes only that success is recoverably distinguishable after restart, failure/interruption creates no false submitted history, no Git/SCM Commit is pretended, and Submit-S11 Push is N/A.

MUST NOT invent Git tags as mandatory Skill identities.

Skill id/version **resolution** MUST NOT require Git.

---

## 34. Integrity principle

Version identity MUST NOT be trivially spoofable by mutable content.

A resolved Skill package SHOULD support integrity verification against its distributed/released identity.

P4 does **not** freeze a canonical hash algorithm.

At minimum: the same released `skill_id`+`skill_version` with **materially different normative content** is **INVALID** (validity layer). It MUST NOT evaluate as `EXACT` or `COMPATIBLE`.

Future Distribution implementation MAY use package digest, signed release metadata, or immutable artifact identity without changing Project Contract semantics.

---

## 35. Package self-check

Separate **intrinsic validity** from **current-environment satisfaction**. Failure of the latter MUST NOT rewrite package identity as INVALID.

### 35.1 Static / intrinsic validity checks

These ask whether the **package/declaration itself** is legal:

- valid core `skill_id`
- valid semantic `skill_version`
- well-formed / possible `package_format_version` **declaration** (malformed or impossible → INVALID)
- required `entry` exists **in the package**
- declared modes consistent with that Skill identity
- `requires` entries are legal capability-prerequisite **declarations** (not invocation permission)
- no forbidden routing edges in the dependency **declaration**
- no intrinsic circular core dependency **declaration**
- no material `skill.yaml` / `SKILL.md` contradiction
- no positively detected mutation of a claimed released identity
- no otherwise structurally impossible declaration

Failure → **INVALID** package (validity blocker), not a compatibility-result value.

### 35.2 Resolution / compatibility checks (after VALID)

These ask whether **this** Distribution / runtime can use that VALID package:

- required capability **currently** resolvable / satisfied
- package format **supported by the current** Distribution / resolver
- required runtime / client capabilities **currently** satisfied

Failure of these MUST NOT mark the package INVALID.

- Known unsatisfied valid requirement → `INCOMPATIBLE` or an explicit resolution blocker
- Cannot safely determine satisfaction → `UNKNOWN` / blocker
- MUST NOT guess

“Required dependencies / capabilities resolvable” is **not** a universal INVALID-package criterion.

P4 defines the requirements. Implementation/testing is later.

### 35.3 Environment-satisfaction examples

| Case | Package identity | Current environment | Outcome |
| --- | --- | --- | --- |
| Well-formed Develop `requires: test.execution`; Test capability unavailable here | **VALID** | dependency unsatisfied | Block normal Develop via resolution/compatibility. **Not** package INVALID. |
| Well-formed `package_format_version` unsupported by this resolver | **VALID** | format not supported here | Compatibility / distribution blocker. **Not** automatically package INVALID. |
| Manifest declares a forbidden or intrinsically cyclic dependency graph | **INVALID** | (does not reach compatibility) | Validity blocker. |

---

## 36. Cross-phase responsibilities

| Phase | Owns |
| --- | --- |
| **P4** (this contract) | Package, routing, version, lock, compatibility protocol, Rule loading semantics, client-exposure rules |
| **P5** | Understand workflows: Bootstrap, Full, Refresh, Compatibility **execution**, migration **application**, knowledge updates |
| **P6** | Test Skill workflow, execution, Evidence, native tests, Game Legibility runtime |
| **P7** | Develop Skill, Task execution, Develop Sessions, Repair |
| **P8** | Submit Skill, Observed-S2, reviews, Test Completeness, candidate-bound human authorization, Change Record, SCM Commit or no-SCM durable finalization, optional Push |

P4 MUST NOT implement those workflows.

---

## 37. Non-goals

P4 MUST NOT implement:

- live `skills/` packages or host `.scaffold/skills.lock` in this repository
- Skill runtime, resolver code, compatibility engine, migration engine
- client plugins or Claude / Cursor / Codex config
- YAML parser, Rule parser, Rule index schema
- Test / Develop / Submit runtime
- AGENTS generator, client-copy generator, integrity signing system

---

## 38. Contract examples

All blocks below are **CONTRACT EXAMPLE — NOT RELEASE DATA**. They MUST NOT be treated as released versions or copied into live `skills/` / `.scaffold/` in this repository.

### 38.1 Understand manifest

```yaml
# CONTRACT EXAMPLE — NOT RELEASE DATA
skill_id: understand
skill_version: 2.0.0
package_format_version: "1"
entry: SKILL.md
modes: [bootstrap, full, refresh, compatibility]
contracts:
  project_contract: ["2"]
  # per-kind record capabilities — not one global records_schema
  record_schemas:
    adoption_session: ["1"]
    change_record: ["1"]
provides:
  - understand.bootstrap
  - understand.full
  - understand.refresh
  - understand.compatibility
requires: []
runtime: {}
```

### 38.2 Develop manifest

```yaml
# CONTRACT EXAMPLE — NOT RELEASE DATA
skill_id: develop
skill_version: 2.0.0
package_format_version: "1"
entry: SKILL.md
modes: [normal_task, repair]
contracts:
  project_contract: ["2"]
  # per-kind record capabilities — not one global records_schema
  record_schemas:
    task_book: ["1"]
    develop_session: ["1"]
provides:
  - develop.implement
  - develop.repair
# capability prerequisite only — does NOT grant Test invocation permission
requires:
  - test.execution
runtime: {}
```

### 38.3 `skills.lock`

```yaml
# CONTRACT EXAMPLE — NOT RELEASE DATA
# Conceptual host file: .scaffold/skills.lock
lock_format_version: "1"
skills:
  understand:
    version: 2.0.0
  develop:
    version: 2.0.0
  test:
    version: 2.0.0
  submit:
    version: 2.0.0
# optional reproducible source identity — not a machine-local path
distribution:
  identity: ai-native-project-scaffold
```

Exact expected versions. These numbers are **hypothetical**.

---

## 39. Version compatibility examples

| Locked | Actual | Declared situation | Result |
| --- | --- | --- | --- |
| 2.0.0 | 2.0.0 | Package **VALID** and checks pass | **EXACT** |
| 2.0.0 | 2.0.0 | Package **INVALID** (malformed / mutated identity / contradiction) | **validity blocker** — not EXACT, not a sixth compatibility result |
| 2.0.0 | 2.0.1 | VALID; explicit inputs establish safe operation; no host migration | **COMPATIBLE** (not EXACT) |
| 2.0.0 | 2.1.0 | VALID; capabilities/contracts compatible | **COMPATIBLE** *possible* — only if evaluation says so |
| 2.0.0 | 3.0.0 | VALID; host migration explicitly required | **MIGRATION_REQUIRED** (ACTIVE → NEEDS_MIGRATION semantics) |
| any | VALID | Compatibility cannot be established | **UNKNOWN** |
| any | VALID | Known unsupported combination | **INCOMPATIBLE** |

MUST NOT infer the table from major/minor/patch numbers alone. Same version strings MUST NOT force `EXACT`.

---

## 40. Acceptance scenarios

Contract-level behavior. No fixtures.

| Case | Behavior |
| --- | --- |
| **A** All four locked versions exactly available | Each package VALID; Preflight → EXACT for each. Normal Skill start. Lock unchanged. |
| **B** One PATCH differs, declared compatible | COMPATIBLE. MAY execute. Difference surfaced. Not reported EXACT. Lock unchanged. |
| **C** One MINOR differs, capability checks pass | COMPATIBLE *if* evaluation agrees; else not guessed. Surfaced. Lock unchanged. |
| **D** MAJOR differs, migration required | Package VALID → MIGRATION_REQUIRED. ACTIVE host: NEEDS_MIGRATION semantically applies (P5 persists). Plan + host-state-bound approval before apply. Material pre-apply change invalidates approval. Expected approved Apply checkpoints do not. Interrupted partial Apply uses Migration Execution recovery semantics. |
| **E** Version differs, known incompatible | INCOMPATIBLE. Block normal execution. No silent substitute Skill. |
| **F** Compatibility cannot be determined | UNKNOWN. Block unsafe execution. Do not guess. |
| **G** Expected Skill package missing | Blocker. MUST NOT use generic chat or another Skill as equivalent. |
| **H** Manifest malformed | Package/input **INVALID**. Validity blocker. MUST NOT produce EXACT or COMPATIBLE. MUST NOT execute as the claimed released identity. |
| **I** `skill.yaml` contradicts `SKILL.md` | Package **INVALID**. Validity blocker. Do not pick a side. Not a compatibility-result value. |
| **J** Same released id+version, normative content changed | Package **INVALID** (mutated immutable identity). MUST NOT execute as that release. MUST NOT call EXACT merely because strings match. |
| **K** Active project has no `skills.lock` | Consistency problem. MUST NOT regenerate from installed packages and continue. Route Compatibility / recovery if safe; else BLOCK. |
| **L** Lock lacks Test | Incomplete lock. Same as K/L class: MUST NOT invent the missing pin. Recovery / Compatibility; else BLOCK. |
| **M** Compatible local version executes | COMPATIBLE path. Lock **not** rewritten. Result reports actual version. |
| **N** User explicitly chooses to update the lock | Lock update workflow. Visible old/new/result/migration-needed. Later Submit reviews the change. |
| **O** Lock update requires no project migration | Lock update only. MUST NOT set NEEDS_MIGRATION. |
| **P** Skill upgrade requires Project Contract migration | VALID package → MIGRATION_REQUIRED. ACTIVE → NEEDS_MIGRATION semantics. Plan/source-state/envelope-bound approval; re-evaluate/re-approve for material unexpected divergence. Approved expected checkpoints retain applicability. P5 applies through PREPARED/APPLYING/VALIDATING/COMPLETED or recovery. Plan approval ≠ Submit authorization. |
| **Q** Skill cannot interpret current Record schema | MUST NOT silently rewrite records. MIGRATION_REQUIRED (or INCOMPATIBLE/UNKNOWN if no path). P3 history rules stand. |
| **R** Cursor natively loads Skill package | NATIVE LOAD. Canonical package remains authority. |
| **S** Claude requires a thin bridge | THIN BRIDGE to AGENTS + canonical resolver. Bridge is not a second Skill. |
| **T** Client requires generated copied instructions | GENERATED DERIVED COPY. One-way, regenerable, source id+version identifiable. Non-authoritative. |
| **U** Generated copy stale after Skill upgrade | Stale MUST be detectable. MUST NOT treat copy as current Skill authority. Regenerate or block on contradiction. |
| **V** Two clients, different local Scaffold versions | Same lock + Rules + records. Each resolves own packages, evaluates, reports actual versions, executes only if allowed. |
| **W** Global project Rule applies | Loaded for relevant Skills. Does not become a Skill. |
| **X** Module-specific Rule | Loaded only when that module/path is in scope. Progressive disclosure. |
| **Y** Two applicable Rules conflict | MUST NOT guess. Surface CONFLICT → Refresh / human. |
| **Z** Project Rule contradicts Constitution | CONFLICT. Framework wins. MUST NOT silently override Constitution. |
| **AA** Human asks to change a Project Rule | Surface requested governance change. Existing Rule remains until the mutation is reviewed. Not silent ignore. |
| **AB** Develop invokes Test | Allowed. Test does not gain source-edit or submit permission. |
| **AC** Test fails, returns to Develop | Two-Skill loop. FAIL ≠ TASK_COMPLETE / READY_FOR_REVIEW / SUBMIT_AUTHORIZED. |
| **AD** Submit needs final Test | Submit may use Test. Test still cannot authorize submission. |
| **AE** Submit detects stale knowledge | Require / invoke Understand `refresh`. Then existing S3–S6 loop if the candidate/knowledge changed. No new Submit stage. |
| **AF** Submit detects source defect needing repair | Handoff to Develop. Submit MUST NOT silently become Develop. New candidate required. |
| **AG** Repair | Develop `repair` mode. Not a fifth Skill. |
| **AH** Adoption | Understand `bootstrap`. Not a fifth Skill. |
| **AI** No-SCM project | Lock + manifests + evaluation still work. Lock remains a persistent host artifact without SCM. P8 owns atomic/conflict-detectable durable S10 finalization; no SCM Commit is invented. Success survives restart; failure does not create submitted history. |
| **AJ** Actual compatible version ≠ lock | COMPATIBLE. Surfaced. Lock unchanged unless explicit update. Durable outputs MUST NOT claim the locked version ran. |
| **AK** Client adapter duplicates stale architecture/Rules | Adapter is not authority. Detectable staleness / knowledge conflict. Thin or regenerate. MUST NOT fork project truth. |
| **AL** Skill tries to persist `submit_authorized: true` | Forbidden in package, lock, and records (P3). Not authorization. |
| **AM** Unknown client supports only generated text imports | GENERATED DERIVED COPY rules apply. Source identity required. Still not authority. |
| **AN** Skill version change during an active Task | No silent lock rewrite. Task Book not silently rewritten. Compatibility still applies; MIGRATION_REQUIRED may block; COMPATIBLE MAY continue with surfaced difference. |
| **AO** Compatibility succeeds; user does not want lock update | COMPATIBLE execution MAY proceed under policy. Lock stays. Difference remains explicit. MUST NOT rewrite the lock anyway. |
| **AP** Migration interrupted during Apply | Retain bounded execution checkpoints. If safe completion is uncertain, use RECOVERY_REQUIRED. Resume only from a provable expected approved checkpoint; unexpected divergence invalidates approval applicability. ABORTED requires no mutation or proven coherent reversion. |
| **AQ** Legitimate ordinary project has no Scaffold metadata | Read-only context establishes NOT_ADOPTED with no recovery evidence. Use Distribution-anchored Pre-Adoption Bootstrap Preflight; absence of `project.yaml` / `skills.lock` is expected and is not a compatibility result. |
| **AR** Missing lock but prior Scaffold footprint exists | MUST NOT infer bootstrap. Use P1/P2 ADOPTING / RECOVERY_REQUIRED / UNKNOWN / CONFLICTING or block semantics as evidence requires. |
| **AS** Multiple Distribution releases are available | Selected Distribution Release must be uniquely identifiable. If invocation does not determine it, BLOCK; MUST NOT choose latest/whatever-installed Understand. |
| **AT** Initial Adoption Plan approved | Plan binds one coherent relation among selected-release-pinned Understand, actual bootstrap Understand, and intended lock Understand, plus target contract intent, the same-release four-Skill lock, and mutation envelope. Material pre-Apply identity/source/lock change requires updated Plan and human re-approval. |
| **AU** Initial host lock is created | Only inside the approved Adoption mutation stage. Its Understand entry equals the release-pinned and actual bootstrap Understand; all four exact versions come from the coherent selected release set. No ranges, paths, or permissions. |
| **AV** Later Agent enters with another local Distribution | Reads durable host lock and runs Host Compatibility Preflight against actual packages. Bootstrap release is not a second durable version authority; no prior chat is required. |
| **AW** Selected release pins U1; resolver provides that exact released U1 package | Exact bootstrap identity binding is established; if all other bootstrap checks pass, Understand bootstrap may proceed. |
| **AX** Selected release pins U1; resolver provides U2 | BLOCK before Understand bootstrap. No pre-lock `COMPATIBLE` substitution and no Adoption Plan based on mismatched identities. |
| **AY** Selected release pins U1; user intends U2 | MUST NOT combine that release set with U2. Explicitly select/resolve a coherent release set that pins U2, rerun Pre-Adoption Bootstrap Preflight, and proceed only after exact identity binding is established. |
| **AZ** Approved Plan bound release/U1; actual package changes to U2 before Apply | Prior Plan Approval MUST NOT silently carry over. Re-resolve/re-evaluate, update or regenerate the Plan, and obtain human re-approval under P1. |
| **BA** Package claims the same `understand` id/version but released identity/integrity cannot be established | Strings alone are insufficient. BLOCK / resolve; MUST NOT treat the package as the exact release-pinned member. |
| **BB** After Adoption, host lock expects U1 and explicit host evaluation finds local U1.1 compatible | Normal Host Compatibility Preflight MAY return `COMPATIBLE`; the pre-adoption exact-binding rule does not remove established-host compatible substitution. |
| **BC** Initial Adoption completes with coherent U1/D1/T1/S1 lock | Complete lock becomes durable expected-version authority; temporary bootstrap/Plan resolution authority expires. |
| **BD** Current approved initial Adoption is interrupted after `project.yaml` but before lock | Host Compatibility/recovery revalidates current Session, Plan, approval applicability, expected host prefix, exact release R, and exact U1. If all hold, Plan-bound R may temporarily resolve U1 for P1/P5 recovery. |
| **BE** Current interrupted initial Adoption has only two lock entries | Partial lock is not authority and MUST NOT enter ordinary lock comparison. Use the bounded Plan recovery anchor only if every condition holds. |
| **BF** Host identity exists but recoverable Session/Plan binding is absent | MUST NOT fresh-bootstrap, infer a release/lock, or guess. BLOCK / P1 recovery. |
| **BG** Applicable Plan binds R/U1 but recovering Agent has only U2 | No pre-lock `COMPATIBLE` substitution. BLOCK pending exact R/U1 resolution. |
| **BH** Interruption follows a provable approved `project.yaml` creation step | Expected approved progress alone does not invalidate Plan Approval applicability. |
| **BI** Durable Scaffold mutation outside the approved envelope appears | Prior approval MUST NOT silently carry over. Re-discover/re-evaluate, update/regenerate Plan, and obtain P1 human re-approval. |
| **BJ** Previously completed `ACTIVE` host later loses its lock | Historical Adoption Plan MUST NOT become expected-version authority. Use established-host consistency/recovery behavior. |
| **BK** Recovery completes coherent four-Skill initial lock | Lock becomes durable expected-version authority; bounded recovery anchor ceases; later entry uses normal Host Compatibility Preflight. |

---

## 41. Invariant checklist

| ID | Invariant |
| --- | --- |
| A | Exactly four top-level Skills |
| B | Modes are not extra Skills |
| C | Repair is Develop mode |
| D | Adoption is Understand mode |
| E | Structural Review remains Submit internal |
| F | Canonical Skill authority is client-neutral |
| G | Skill packages live in Distribution, not normally the host |
| H | Package has manifest + `SKILL.md` |
| I | `skill_id` is stable across versions |
| J | Released id+version is immutable |
| K | Skill version ≠ package format version |
| L | `skills.lock` contains exact expected versions |
| M | Lock mismatch ≠ automatic migration |
| N | EXACT ≠ COMPATIBLE |
| O | COMPATIBLE difference is surfaced |
| P | MIGRATION_REQUIRED only after evaluation |
| Q | INCOMPATIBLE / UNKNOWN never silently execute unsafe workflow |
| R | Compatible execution does not silently rewrite the lock |
| S | Lock update ≠ project migration |
| T | `skills.lock` cannot grant Commit/Push authorization |
| U | Nested invocation cannot escalate permission |
| V | Submit does not silently become Develop |
| W | Develop may invoke Test |
| X | Submit may use Test / Understand |
| Y | Test cannot authorize submission |
| Z | Project Rules are not Skills |
| AA | Rules load progressively by scope |
| AB | Rule conflicts do not silently override Contracts |
| AC | Client copies are derived, not authority |
| AD | Different clients resolve the same project authority |
| AE | Actual executed Skill version is reportable |
| AF | No-SCM Skill resolution works |
| AG | Missing/malformed lock or package blocks guessing |
| AH | Migration execution has recoverable PREPARED/APPLYING/VALIDATING/COMPLETED/RECOVERY_REQUIRED/ABORTED semantics |
| AI | Compatibility Preflight has Distribution-anchored pre-adoption and host-lock-anchored contexts without becoming another Skill |
| AJ | Missing lock alone never implies bootstrap |
| AK | Bootstrap resolution uses a uniquely identifiable Selected Distribution Release and surfaces actual Understand version |
| AL | Initial Adoption Plan binds selected release and exact four-Skill lock intent under P1 approval |
| AM | Initial lock becomes the durable expected-version SSOT; bootstrap source does not remain a competing authority |
| AN | Pre-adoption actual Understand exactly matches the Selected Distribution Release’s pinned Understand package identity before bootstrap executes |
| AO | Initial lock Understand equals release-pinned and actual bootstrap Understand; all four entries derive from one coherent release set |
| AP | Interrupted initial Adoption uses only a current applicable Plan/Session-bound recovery anchor inside Host Compatibility Preflight |
| AQ | Partial initial lock is recovery evidence, not normal host authority; complete coherent publication triggers handoff |
| AR | Plan-bound recovery authority expires and cannot be revived from historical Adoption for a later damaged ACTIVE host |
