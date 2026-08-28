# Records Contract

This document is the P3 contract for **development-record kinds**, **identifiers**, **schemas**, **lifecycles**, **provenance classes**, and **retention**.

It does **not** implement Develop, Submit, Test, YAML parsers, validators, hashing tools, or live host `.scaffold/` trees.

**Normative words:** MUST, MUST NOT, SHOULD, MAY.

**Authority order for this phase:** [CONSTITUTION.md](CONSTITUTION.md) → this Records Contract together with [PROJECT_CONTRACT.md](PROJECT_CONTRACT.md) → [ADOPTION_CONTRACT.md](ADOPTION_CONTRACT.md) → [../architecture/V2_ARCHITECTURE.md](../architecture/V2_ARCHITECTURE.md) → [../architecture/PROJECT_LAYOUT.md](../architecture/PROJECT_LAYOUT.md) → [../architecture/ADOPTION_FLOW.md](../architecture/ADOPTION_FLOW.md) → [../architecture/RECORD_LIFECYCLES.md](../architecture/RECORD_LIFECYCLES.md) → ADR → README. Constitution wins on product rules. This contract MUST NOT silently redefine P0/P1/P2.

P3 freezes **how Scaffold records intent, temporary Develop provenance, and durable submitted facts**. Runtime behavior belongs to later phases unless this contract names a required invariant.

This **distribution** repository MUST NOT contain live host `.scaffold/tasks/`, `.scaffold/changes/`, or `.scaffold/runtime/` as P3 artifacts. YAML blocks labeled **CONTRACT EXAMPLE** are illustrative only.

Related diagrams: [../architecture/RECORD_LIFECYCLES.md](../architecture/RECORD_LIFECYCLES.md).

---

## 1. Scope

This contract answers: how does Scaffold record development intent, temporary Develop provenance, and final submitted facts **without** creating duplicate memory systems?

It covers:

- the three canonical development record kinds
- storage locations under the P2-reserved `.scaffold/` namespaces
- identifiers and common metadata
- Task Book / Develop Session / Change Record responsibilities
- Session-S0 / Session-S1 / Observed-S2
- advisory provenance classes
- candidate vs durable Change Record publication
- Adoption Session persistence (temporary, not a fourth development record)
- compaction, cleanup, concurrency, no-SCM, ownership, and retention

It does **not** cover Skill packaging (`skills.lock` contents), Understand execution, Test Evidence schema, Develop runtime, or Submit pipeline implementation.

---

## 2. Record taxonomy

There are exactly **three canonical development record** kinds:

| Kind | Answers | Authority |
| --- | --- | --- |
| **Task Book** | What are we trying to do, how is it divided, and where are we now? | Development **plan / progress**. NOT final submitted truth. NOT the physical Diff. |
| **Develop Session** | What state transition was explicitly observed during **one** Develop execution? | **Temporary advisory provenance**. NOT repository truth. NOT human-authorship proof. |
| **Change Record** | What actually ended up in the final submission candidate and became durable after successful Commit? | Durable **submitted-change summary** derived from **real** final repository state. The repository / SCM remains authority for the physical Diff. |

MUST NOT introduce another record that duplicates the lifecycle or duty of these three. MUST NOT create parallel work-log, handoff-log, scratchpad, session-history, developer-diary, or mega-CHANGELOG copies of the same development facts.

Other artifacts MAY exist when they have a clearly different purpose, authority, lifecycle, and retention. They are **not** a fourth canonical development record:

| Artifact | Why it is distinct |
| --- | --- |
| **Adoption Session** | First-attach resume/recovery only. Temporary. P1 authority. |
| **Test Report / Evidence** | What a specified test scope actually verified. P6 schema. |
| External CI result | External verification input. Not development plan or as-built summary. |
| Analysis / migration artifact | Bounded later-phase work. Must not clone Task/Session/Change duties. |

The four questions a later Agent MUST be able to answer without chat history:

```text
What did we intend to do?                         → Task Book
What did this Develop execution observe/change?   → Develop Session
What actually ended up in the submitted result?   → Change Record
What physically changed?                          → repository / workspace reality
```

Those four authorities MUST NOT be collapsed into one file.

---

## 3. Canonical storage

P3 fills filenames **inside** P2-reserved directories. It MUST NOT add another `.scaffold/` root namespace.

| Record | Canonical location | Shared | Durable |
| --- | --- | --- | --- |
| Task Book | `.scaffold/tasks/<task-id>.yaml` | YES | YES |
| Change Record | `.scaffold/changes/<change-id>.yaml` | YES | YES after successful Commit; candidate before Commit (same path) |
| Develop Session | `.scaffold/runtime/develop-sessions/<develop-session-id>/` | NO — local | NO — temporary |
| Adoption Session | `.scaffold/runtime/adoption-sessions/<adoption-session-id>/` | NO — local | NO — temporary |

Develop Session directory (host, not this distribution repo):

```text
.scaffold/runtime/develop-sessions/<develop-session-id>/
├── session.yaml          REQUIRED (metadata + S0/S1 workspace overlays)
├── files.yaml            REQUIRED once any Develop-touched path is tracked
└── patches/              OPTIONAL
    └── <patch-file-id>.patch
```

Adoption Session directory:

```text
.scaffold/runtime/adoption-sessions/<adoption-session-id>/
└── session.yaml          REQUIRED
```

`runtime/` remains **local / temporary / non-authoritative** and SHOULD normally be SCM-ignored (P2). Sessions MUST NOT be treated as handoff knowledge.

This distribution repository MUST NOT create these directories.

---

## 4. Name disambiguation

P0 uses **S1–S12** for Submit stages and **S0/S1/S2** for Develop working-tree snapshots. P3 writes them as:

| Term in this contract | Meaning |
| --- | --- |
| **Session-S0** | Working tree / workspace state at **Develop Session start** |
| **Session-S1** | Sealed working tree / workspace state at **Develop Session end** |
| **Observed-S2** | **Fresh** real working tree / workspace state observed by **Submit** |
| **Submit-S1 … Submit-S12** | Frozen Submit pipeline stages (Constitution §10) |
| **Submit-S2** | Delta Classification. It **uses** Observed-S2; it is not itself a stored snapshot. |

Observed-S2 is **not** stored as permanent Develop Session truth. Submit MUST observe it fresh. Repository truth overrides Session memory.

---

## 5. Common metadata and versioning

Every durable YAML record, and every Session `session.yaml`, MUST be self-describing.

Minimum header:

| Field | Required | Notes |
| --- | --- | --- |
| `record_type` | MUST | `task_book` \| `change_record` \| `develop_session` \| `adoption_session` |
| `schema_version` | MUST | Explicit string for **this record kind**. Not Project Contract version, not Skill version, not Scaffold package version. |
| `record_id` | MUST | Stable ID (see §6). Immutable after creation. |
| `created_at` | MUST | Timezone-aware RFC3339. UTC SHOULD be used for persisted machine records. |
| `updated_at` | MUST on mutable records | Task Book while live; candidate Change Record if regenerated; Session while OPEN. Omit or freeze after immutability. |

Initial `schema_version` for all four kinds defined here: `"1"`.

P4 owns broader compatibility. P3 only requires that record versions exist and are explicit. MUST NOT bind a record `schema_version` blindly to Project Contract version, Skill version, or package version.

MUST NOT store in canonical records:

- AI model name
- chat id
- chain-of-thought
- full prompt
- conversation transcript
- token logs
- hidden reasoning
- model scratchpad

Timestamps help ordering. They MUST NOT alone prove authorship, repository ancestry, authority, or causal ownership. SCM / baselines / digests / actual state remain stronger evidence.

---

## 6. ID and naming contract

One ID family is frozen for all four kinds.

### 6.1 Shape

```text
<kind>-<utc-compact>-<token>
```

| Kind prefix | Record |
| --- | --- |
| `task` | Task Book |
| `change` | Change Record |
| `dev` | Develop Session |
| `adopt` | Adoption Session |

- Kind prefix MUST be lowercase (`task` / `change` / `dev` / `adopt`).
- `<utc-compact>` MUST be UTC `YYYYMMDDThhmmssZ` (example: `20260827T120501Z`). Literal separators `T` and `Z` MUST be uppercase. MUST NOT embed a local timezone.
- `<token>` MUST be exactly **8 lowercase hexadecimal** characters (`[0-9a-f]{8}`).
- The whole ID MUST match: `^(task|change|dev|adopt)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$`
- The complete ID MUST use exactly the canonical case defined by that regex. Implementations MUST NOT arbitrarily case-fold IDs.
- IDs MUST be filename-safe: no spaces, no path separators, no `<>:"/\|?*`.
- Human `title` / `goal` MUST remain separate fields. MUST NOT encode the title into the ID.

Example: `task-20260827T120501Z-a1b2c3d4`

### 6.2 Stability and collision

- An ID is **stable once created**. MUST NOT rename a record to “fix” the timestamp or title.
- IDs MUST be collision-resistant enough for multi-Agent use: the creator MUST NOT reuse an ID that already exists in that kind’s namespace.
- On collision, generate a **new token** (and MAY refresh the UTC timestamp). MUST NOT mutate another Agent’s record to steal its ID.
- IDs MUST NOT be derived from a **final Git commit SHA** (or any SCM revision of the Commit that will contain the record).
- IDs MUST NOT require SCM to exist.

Time-sortability: the UTC timestamp prefix SHOULD order IDs chronologically. Equal timestamps are disambiguated by `token`, then by full ID string.

### 6.3 Filenames

| Kind | Path |
| --- | --- |
| Task Book | `.scaffold/tasks/<task-id>.yaml` |
| Change Record | `.scaffold/changes/<change-id>.yaml` |
| Develop Session | `.scaffold/runtime/develop-sessions/<dev-id>/` |
| Adoption Session | `.scaffold/runtime/adoption-sessions/<adopt-id>/` |

The filename / directory name MUST equal `record_id` exactly, including the canonical `T` / `Z` case.

Optional Develop patch files inside a Session:

- `patches/<patch-file-id>.patch`
- `<patch-file-id>` MUST be 16 lowercase hex characters = first 16 hex chars of SHA-256 of the UTF-8 project-relative path.
- MUST NOT use the raw path as a filename (Windows). MUST NOT use an SCM revision as `patch-file-id`.

---

## 7. Task Book role

Canonical: `.scaffold/tasks/<task-id>.yaml`

Shared: **YES**. Durable: **YES**. Mutable during an active task: **YES**. After successful submission represented by a durable Change Record: **historical / generally immutable**.

Task Book is the **plan and progress** record.

MUST NOT attempt to explain the final physical Diff. That belongs to Change Record + repository reality.

MUST NOT be treated as proof that no other final changes exist.

If actual changes exceed Task Book scope: the Task Book MUST NOT be silently rewritten merely to make history look tidy. Submit still derives final truth from the real Diff. P8 decides how extra changes are resolved/reviewed.

---

## 8. Task Book schema

A Task Book MUST be capable of representing the fields below. Illustrative names are contract-level. P7/P8 implement read/write. This is **not** a JSON Schema and MUST NOT be split into a separate schema file.

### 8.1 Required capability

| Concept | Purpose |
| --- | --- |
| `record_type`, `schema_version`, `record_id`, `created_at`, `updated_at` | Common header |
| `record_revision` | Stale-write guard (§31) |
| `title` | Short label, separate from ID |
| `goal` | This round’s full goal — **what we want** |
| `acceptance` | Final Task-level acceptance condition — **how we know the whole Task is done**. MUST NOT store a redundant `acceptance_met` boolean. `READY_FOR_REVIEW` itself asserts that this declared acceptance is satisfied. |
| `baseline` | Repository/workspace baseline **against which the task was planned** (SCM-agnostic; not proof of a clean tree) |
| `scope` | Declared intent: modules, paths/areas, include, exclude, concise notes |
| `stages` | One or more stages; lightweight tasks use **exactly one** |
| `final_tests` | Planned task-level required tests (references, not Evidence bodies) |
| `status` | `DRAFT` \| `IN_PROGRESS` \| `READY_FOR_REVIEW` \| `CANCELED` |
| `develop_session_ids` | Operational / advisory Session links. Non-authoritative; **not required** for interpretation; MAY become non-resolvable after runtime cleanup |
| `result_notes` | Optional concise progress notes |

Durable association is one-way: **Change Record → Task Book(s)** via `task_book_ids`. The Task Book MUST NOT store a Change Record back-reference.

MUST NOT embed: full Git/SCM diff, file copies, large logs, Test Evidence bodies, chat transcripts, Agent reasoning, Develop Session hashes, or Develop Session patches.

`goal` and Task-level `acceptance` MUST remain distinct. For a lightweight one-stage task, Task-level `acceptance` MAY be one concise sentence and MAY intentionally align with the single Stage `acceptance`. Stage `acceptance` remains the per-stage condition (§8.4).

### 8.2 Baseline

`baseline` MAY be:

| `kind` | `value` |
| --- | --- |
| `git` | revision string as known **before** this task’s plan |
| `perforce` | changelist / depot baseline as known |
| `project` | project-defined baseline identifier |
| `none` | no SCM / no baseline object |
| `unavailable` | SCM or baseline cannot be honestly stated |

MUST NOT invent a SHA or changelist. Existing dirty work belongs to Session-S0, **not** duplicated as a second dirty-file catalog in the Task Book.

This baseline is **planning context**. It is not proof the working tree was clean.

### 8.3 Scope

Declared intent only. MAY include modules, paths/areas, explicit inclusions, explicit exclusions, concise notes.

Scope MUST NOT be treated as proof that no other final changes exist.

### 8.4 Stages

The **same** Task Book schema is used for simple and multi-stage work. A simple task MUST remain lightweight by using **exactly one concise Stage**. MUST NOT invent a second mini-task schema.

Each Stage MUST be capable of:

| Concept | Purpose |
| --- | --- |
| `stage_id` | Unique within the Task Book. Recommended: `stage-1`, `stage-2`, … |
| `goal` | Stage goal |
| `acceptance` | Acceptance condition |
| `status` | See §9 |
| `required_tests` | Planned test **references** for this stage |
| `result_summary` | Concise outcome when available |
| `evidence_refs` | Opaque locators; P6 owns Evidence |

A Stage MUST NOT become `COMPLETE` merely because its tests **executed**.

Normal `COMPLETE` requires **all** of:

1. implementation / acceptance condition satisfied
2. required Stage tests satisfy their **defined acceptance requirements**
3. no unresolved required-test blocker for that Stage

If required tests fail: the Stage remains non-complete. Develop ↔ Test continues. Typical status remains `IN_PROGRESS`. `BLOCKED` is for an external/human/policy stop, not the ordinary fail-and-fix loop.

### 8.5 Planned tests vs TEST_COMPLETE

Task Book test requirements are **planned requirements**.

They MUST NOT claim to be the final authority for **TEST_COMPLETE**.

Submit later calculates required testing from:

```text
actual Diff + tests.yaml + Task Book + project policy
```

Unplanned / manual / external changes in the real Diff still count. If the developer extra-edited a module omitted from the Task Book, that module’s required tests remain required (Constitution / later P6+P8). P3 only freezes: planned ≠ complete.

### 8.6 Test references

P3 MUST NOT define Test Report / Evidence schema. P6 owns that.

Task Book and Change Record MAY reference Test Evidence with an **opaque locator**:

```yaml
# CONTRACT EXAMPLE fragment
required_tests:
  - requirement_id: "stage-1/config-parse"
    evidence_ref:
      locator: "opaque-p6-locator"
    observed_outcome: PASS
```

`observed_outcome` when present MUST be one of: `PASS` | `FAIL` | `NOT_EXECUTED` | `UNKNOWN`.

MUST NOT copy full logs, screenshots, Evidence Bundles, or CI output into Task Book or Change Record.

`WAIVED` / exception mechanics are **P8**. P3 MUST NOT invent a waiver that grants TEST_COMPLETE.

---

## 9. Stage statuses

Frozen Stage states (exactly these four):

| Status | Meaning |
| --- | --- |
| `PENDING` | Not started |
| `IN_PROGRESS` | Implementation and/or Develop ↔ Test underway |
| `BLOCKED` | Cannot continue without external/human/policy resolution beyond the ordinary test-fail-fix loop |
| `COMPLETE` | §8.4 completion conditions hold |

MUST NOT explode into dozens of Stage states.

---

## 10. Task statuses

Frozen Task Book `status` values (exactly these four):

| Status | Meaning |
| --- | --- |
| `DRAFT` | Created; not yet accepted as the active development plan |
| `IN_PROGRESS` | Development is underway |
| `READY_FOR_REVIEW` | Develop’s terminal success state for this Task Book (§11) |
| `CANCELED` | Explicitly abandoned; not submitted |

MUST NOT persist `SUBMITTED` (or equivalent) as a Task status that would be written **before** Commit and could lie if Commit fails.

Successful submission is established through **Change Record + repository history**, not by pre-writing submitted into the Task Book.

If work continues after `READY_FOR_REVIEW` and before a durable Change Record exists, `status` MUST return to `IN_PROGRESS` until §11 holds again.

`CANCELED` is explicit. Canceled tasks MUST NOT be treated as READY_FOR_REVIEW. Associated OPEN Sessions MUST NOT be silently deleted; see §28.

---

## 11. TASK_COMPLETE and READY_FOR_REVIEW

**TASK_COMPLETE** is a **derived** condition. It MUST NOT be stored as a fifth Task status.

For a standard Task Book:

```text
TASK_COMPLETE  =  all required Task stages are COMPLETE
```

TASK_COMPLETE alone does **not** imply: final task-level tests accepted; TEST_COMPLETE; Structural Review pass; submission authorization; Commit readiness.

**READY_FOR_REVIEW** (persisted Task `status`) requires:

```text
all stages COMPLETE
+ task-level final required tests satisfy their defined acceptance conditions
+ the Task Book’s declared Task-level acceptance is satisfied
```

MUST NOT mark `READY_FOR_REVIEW` merely because final tests **ran**. MUST NOT persist a separate `acceptance_met` flag; `READY_FOR_REVIEW` itself asserts that the declared Task-level `acceptance` is satisfied.

READY_FOR_REVIEW is **not** submit authorization and MUST NOT start Commit / Push (Constitution).

---

## 12. Lightweight task behavior

Typo / small-config work uses the **same** schema:

- one Stage
- short goal
- Task-level `acceptance` (MAY be one concise sentence; MAY match the single Stage `acceptance`)
- small scope
- minimal test requirement (MAY be a single planned check or an explicit “none required by task plan” note **as planned intent only**)

Even when the Task Book plans no tests, Submit’s TEST_COMPLETE is still computed from the **actual Diff** + `tests.yaml` + policy. A lightweight plan MUST NOT skip Submit completeness.

---

## 13. No-task Submit semantics

Submit MUST support human-only, tool-created, external-Agent, and mixed changes that have **no** Task Book.

Absence of a Task Book MUST NOT prevent Submit from starting.

When no Task Book governs the submission candidate:

```text
TASK_COMPLETE = NOT APPLICABLE
```

MUST NOT create a fake completed Task Book. MUST NOT automatically synthesize historical planning that never existed.

P8 owns how the final Submit gate evaluates the no-task case. This contract does **not** alter the Constitution.

---

## 14. Develop Session role

Canonical: `.scaffold/runtime/develop-sessions/<develop-session-id>/`

Develop Session is **LOCAL**, **TEMPORARY**, and **ADVISORY**.

It records **one** Develop execution’s observed state transition.

MUST NOT claim “this file was written by a human.”
MUST NOT claim “everything outside this Session is human work.”
MUST NOT override repository reality.

```text
REPOSITORY TRUTH OVERRIDES SESSION MEMORY.
```

Observed-S2 wins over Session-S1. Physical Diff wins over both.

---

## 15. Develop Session lifecycle

Frozen Session states:

| Status | Meaning |
| --- | --- |
| `OPEN` | Develop execution is still active. Session-S0 exists; Session-S1 is not sealed. |
| `SEALED` | Session-S1 has been captured; session evidence is closed. SHOULD be immutable. |
| `ABORTED` | No trustworthy complete Session-S1 exists. |

```text
OPEN → SEALED
OPEN → ABORTED
```

MUST NOT create `SUBMITTED` as a Session state. Successful Commit causes **cleanup**, not another durable Session transition.

A SEALED session remains locally available until successful Submit cleanup (or explicit cancel/stale cleanup). It MUST NOT be silently deleted while Submit is incomplete or blocked.

ABORTED sessions MUST NOT be used as DEVELOP_KNOWN evidence. They MAY remain until explicit cleanup so the abort is inspectable.

---

## 16. Session-S0 / Session-S1 / Observed-S2

Two evidence kinds MUST stay distinct:

| Kind | Answers | Must not be treated as |
| --- | --- | --- |
| **Workspace boundary overlay** | Which paths already differed from the Session baseline at a Session boundary? | Proof that Develop produced those paths |
| **Develop-touched manifest** (`files.yaml`) | Which paths did this Develop execution explicitly touch? | A whole-workspace inventory |

**Boundary observation ≠ Develop attribution.** An ambient overlay change MUST NOT be treated as if Develop produced it.

MUST NOT snapshot the whole project. Overlays record only paths that **differ from the Session baseline**, where the host can honestly observe them.

### 16.1 Session-S0 (start)

Develop MUST NOT assume a clean tree.

Session-S0 MUST preserve:

1. repository/workspace **baseline identity** at Session start (SCM-agnostic; `none` / `unavailable` allowed)
2. a compact **Session-S0 workspace overlay** relative to that baseline, covering dirty / modified / deleted / untracked paths already present at Develop start, **where the host can honestly observe them**
3. **before-state** of every path the Session **later** modifies, captured **before** the first Session mutation of that path (in `files.yaml`, not by treating overlay membership as a Develop touch)

Each recorded overlay path MUST be capable of preserving: `path`; kind/existence; digest when applicable and safe.

The overlay MUST also record whether coverage is: `complete` | `partial` | `unavailable`.

Exact YAML field names are not frozen. The capability MUST exist.

### 16.2 Session-S1 (seal)

Session-S1 MUST capture a compact **end-of-session workspace overlay** relative to the **same** Session baseline, where available, with the same per-path capability and the same coverage class (`complete` | `partial` | `unavailable`).

Purpose: answer “Had this **non-Develop-touched** path already changed by Session-S1?”

Separately, for each path **Develop explicitly touched**, Session-S1 / `files.yaml` MUST record:

- after existence / status
- after digest where applicable
- relevant metadata (kind, text vs binary when known)
- optional text patch when safe and manageable
- relevant Stage id(s) when a Task Book exists
- `was_preexisting_dirty`

### 16.3 Observed-S2 (Submit)

Observed-S2 is the **real current** repository/worktree state observed by Submit.

It is **not** stored as permanent Develop Session truth. Submit observes it **fresh**. Observed-S2 wins.

---

## 17. Digests, manifest, and patches

### 17.1 Digest

Portable per-file comparison MUST work without SCM.

Frozen digest:

- algorithm: **SHA-256 of raw file bytes**
- representation: `sha256:` + 64 lowercase hex characters

MUST NOT hash the entire repository tree. MUST NOT require storing file contents.

Line-ending-only changes MAY change the raw digest. P2 still says EOL-only churn is not automatically **semantic** project change. Provenance compares **bytes**. Semantic-vs-EOL policy remains P2/P8; P3 does not treat digest equality as a style waiver.

### 17.2 Path kind

Each tracked path MUST be able to distinguish:

| `kind` | Meaning |
| --- | --- |
| `missing` | Not present |
| `regular_file` | Ordinary file |
| `symlink` | Symlink or equivalent |
| `other` | Special / unknown filesystem object |

For `symlink`, record the target string as metadata. Digest the **target string** (UTF-8 bytes), not the referent file body. MUST NOT follow a symlink into a secret-bearing file in order to hash contents.

`content_class` when known: `text` | `binary` | `unknown`.

### 17.3 Session change manifest (`files.yaml`)

`files.yaml` remains the **Develop-touched** manifest only. Workspace-overlay paths that Develop did not touch MUST NOT be copied here as if Develop produced them.

For every Develop-touched path, the Session MUST be capable of recording:

| Concept | Purpose |
| --- | --- |
| `path` | Project-root relative; portable `/`; preserve repository case |
| `before_kind` / `after_kind` | Existence/kind |
| `before_digest` / `after_digest` | When applicable |
| `change_kind` | `created` \| `modified` \| `deleted` \| `type_changed` |
| `was_preexisting_dirty` | Path already dirty/untracked at Session-S0 **before** this Session’s first mutation |
| `patch_ref` | Optional relative patch file |
| `stage_ids` | Relevant Stage(s), if a Task Book exists |

MUST NOT store huge file bodies in the manifest.

### 17.4 Optional patches

For manageable **non-sensitive text**, a Session-S0 → Session-S1 patch MAY be retained **locally**.

For binary, large, sensitive, or secret-bearing files: hashes + metadata only. MUST NOT store the body.

What is “large” is a later implementation threshold (P7). This contract only requires: bodies are optional and MUST be omitted when unsafe or unmanageable.

### 17.5 Sensitive content

Temporary patches MUST NOT become a secret archive.

If a touched file **may** contain credentials, tokens, private keys, or sensitive machine-local values: MUST NOT store a content patch. Record only safe metadata / digest where appropriate.

P3 is not a secrets-management framework. Detection heuristics are P7/P8. The invariant is: **when in doubt, do not store content**.

### 17.6 No chain-of-thought

Develop Session MUST NOT persist chain-of-thought, hidden reasoning, complete chat transcript, full prompts, model scratchpad, or token logs.

---

## 18. Multiple Session composition

A Task MAY involve multiple Develop Sessions. While active, the Task Book MAY list relevant Session IDs.

Composition MUST be deterministic:

1. Order Sessions by `created_at`, then by `record_id`.
2. For a path touched by multiple Sessions, a **continuous Develop provenance chain** requires: previous relevant Session-S1 after-state **equals** next relevant Session’s before-state for that path.
3. If an unexplained gap exists, the path **cannot** be `DEVELOP_KNOWN`.
4. The **latest relevant SEALED** Session-S1 is compared against Submit Observed-S2.

OPEN or ABORTED Sessions MUST NOT complete a DEVELOP_KNOWN chain.

If Develop later edits a path that was already dirty at the **first** covered mutation: `was_preexisting_dirty` remains true for provenance. The path MUST NOT become `DEVELOP_KNOWN` merely because a Session touched it.

---

## 19. Provenance classifications

These classes are **advisory**. They classify final changed paths relative to Session evidence. They MUST NOT override the actual Diff. They MUST NOT be used as `HUMAN_CHANGE`. Classification MUST be conservative: if timing or continuity cannot be proven, use `UNATTRIBUTED`.

P0 remains authoritative. P3 only makes the advisory mechanics precise (see §37).

| Class | Meaning (P3) |
| --- | --- |
| `DEVELOP_KNOWN` | Develop Session evidence **fully covers** the observed transition. NOT “AI owns this file forever.” |
| `MIXED_CHANGE` | Develop touched the path **and** the final transition is **not** purely covered by Develop evidence. |
| `PREEXISTING_CHANGE` | Honest **unchanged** pre-Develop dirty state still present at Observed-S2. NOT “the developer definitely wrote it.” |
| `POST_DEVELOP_ADDITIONAL` | Proven additional change **after** Develop end, with Session-S1 boundary evidence. NOT “human change.” |
| `UNATTRIBUTED` | Provenance cannot be safely established (including typical human-only Submit with no Session). NOT an error. |

### 19.1 DEVELOP_KNOWN

A final changed path MAY be `DEVELOP_KNOWN` only when **all** hold:

- one or more valid **SEALED** Develop Sessions explicitly cover its transition
- it was **not** already dirty before the first covered Develop mutation
- relevant Session transitions form a continuous chain (§18)
- latest sealed Develop after-state **equals** Observed-S2 (digest + kind)
- there is no unexplained state gap

### 19.2 MIXED_CHANGE

Use `MIXED_CHANGE` when Develop touched the path and any of:

- the path was already dirty before Develop, then Develop edited it
- Develop changed it, then it changed again after Session-S1 (Observed-S2 ≠ Session-S1)
- multiple Develop Sessions have an unexplained gap
- final Observed-S2 differs from latest sealed Session-S1

If Develop **did** touch the same path and it changed again: `MIXED_CHANGE`, **not** `POST_DEVELOP_ADDITIONAL`.

MUST NOT claim the extra portion is definitely human-authored.

`MIXED_CHANGE` is highest review priority.

### 19.3 PREEXISTING_CHANGE

`PREEXISTING_CHANGE` MAY be used only when **all** hold:

- the path was recorded as pre-existing dirty in the Session-S0 workspace overlay
- Develop never touched it
- sufficient boundary/digest evidence shows the final relevant Observed-S2 state is **still the same** pre-existing state, with **no unexplained later mutation**

If the Session-S0 pre-existing state and Observed-S2 **differ**, and no Develop Session covered the transition: MUST NOT call it pure `PREEXISTING_CHANGE`. Use another **provable** class or `UNATTRIBUTED`.

If Develop **also** touched it: `MIXED_CHANGE`, not `PREEXISTING_CHANGE`.

### 19.4 POST_DEVELOP_ADDITIONAL

`POST_DEVELOP_ADDITIONAL` MAY be used only when evidence establishes **all** of:

- the path was not pre-existing dirty
- Develop did not touch it
- Session-S1 **workspace overlay** evidence shows it was still baseline-equivalent / absent / unchanged at Develop end
- Observed-S2 shows the additional change

MUST NOT infer `POST_DEVELOP_ADDITIONAL` merely from “not in Session-S0 and exists at Observed-S2”.

If Session-S1 boundary coverage is `partial` or `unavailable` and timing cannot be safely established: `UNATTRIBUTED`.

Timestamps / mtimes alone MUST NOT prove POST timing.

If no relevant Develop window exists at all (no Sessions), do **not** force this class; use `UNATTRIBUTED`.

### 19.5 UNATTRIBUTED

Use when:

- no relevant Develop Session exists
- Session data is incomplete
- baseline or overlay evidence is insufficient
- Session-S1 overlay coverage is `partial` / `unavailable` and POST/PREEXISTING timing cannot be proven
- provenance cannot safely be established

Human-only Submit commonly begins here. Submit MUST still review the actual Diff. `UNATTRIBUTED` remains the honest fallback.

---

## 20. Classification precedence

For each path in the **actual** final Diff, apply definitions logically, then resolve with this precedence (first match wins):

1. `MIXED_CHANGE`
2. `PREEXISTING_CHANGE`
3. `POST_DEVELOP_ADDITIONAL`
4. `DEVELOP_KNOWN`
5. `UNATTRIBUTED` (fallback)

Label-order MUST NOT override the definitions. In particular:

- dirty then Develop-touched → `MIXED_CHANGE`
- Develop-touched and Observed-S2 ≠ Session-S1 → `MIXED_CHANGE`
- S0 dirty, never Develop-touched, S2 still equals that S0 state → `PREEXISTING_CHANGE` possible
- not dirty at S0, never Develop-touched, S1 overlay shows still baseline-equivalent, S2 shows the change → `POST_DEVELOP_ADDITIONAL` possible
- insufficient overlay/timing evidence → `UNATTRIBUTED`

Advisory Submit review priority (all actual Diff still requires appropriate review; P8 implements):

1. `MIXED_CHANGE`
2. `POST_DEVELOP_ADDITIONAL`
3. `PREEXISTING_CHANGE`
4. `UNATTRIBUTED`
5. `DEVELOP_KNOWN`

`DEVELOP_KNOWN` MUST NOT skip Structural Review / Knowledge Consistency / Test Completeness.

P8 owns classification **execution**. P3 freezes the classes, definitions, and precedence.

---

## 21. Change Record role

Canonical: `.scaffold/changes/<change-id>.yaml`

Shared: **YES**. Durable after successful Commit: **YES**.

Generated/finalized by Submit from:

```text
REVIEWED CANDIDATE DIFF
+ final review
+ final test evidence
+ knowledge consistency state
```

MUST NOT be generated merely from Agent memory, Task Book claims, or Develop Session claims.

Repository/SCM remains authority for the exact physical Diff, including the Change Record artifact in the Commit. Change Record is a **compact durable summary**, not a second diff store.

---

## 22. Change Record schema

A Change Record MUST be capable of representing:

| Concept | Purpose |
| --- | --- |
| `record_type`, `schema_version`, `record_id`, `created_at` | Header. `updated_at` only while still a **candidate** being regenerated. |
| `summary` | Concise human summary |
| `base` | Final **pre-Commit** parent/baseline (known before Commit; SCM-agnostic) |
| `affected` | Modules / areas |
| `path_summary` | Changed-path summary (exact or grouped) |
| `structural_summary` | Structural change summary |
| `knowledge_updates` | Documentation / knowledge updates |
| `verification` | Test/verification summary + opaque evidence references |
| `understand_involvement` | Refresh / Compatibility involvement if relevant |
| `task_book_ids` | Zero or more Task Book IDs |
| `provenance` | Compact class counts / notes — **not** Session internals |
| `limitations` | Important unresolved facts if Submit policy allows recording them |

MUST NOT embed: full diff, full logs, full Test Evidence, Develop Session hashes, Develop Session patches, chat transcripts, or the **final Commit SHA of the Commit that contains this record**.

MUST NOT persist `submit_authorized: true` (or equivalent) as a reusable permission bit.

MUST NOT persist `status: submitted` (or equivalent) before Commit.

`tests: pass` (or similar) inside a Change Record MUST NOT automatically authorize submission. The record stores final facts. It does not grant permission. TEST_COMPLETE remains a Submit-S5 judgment (P8).

### 22.1 Path scale

For normal changes, exact relevant paths MAY be listed.

For very large or generated changes, MAY use path groups/prefixes, counts, affected modules, and concise generated-change summaries.

```yaml
# CONTRACT EXAMPLE fragment
path_summary:
  representation: grouped
  total_changed_paths: 420
  groups:
    - prefix: generated/proto/
      count: 400
      note: generated stubs
    - prefix: src/save/
      count: 20
      note: listed exactly in paths
  paths:
    - path: src/save/Save.cpp
      change: modified
```

MUST NOT create megabyte-scale Change Records merely to duplicate Git/Perforce.

`path_summary` describes the **REVIEWED CANDIDATE DIFF** (§23). It MUST NOT recursively count or list its own `.scaffold/changes/<change-id>.yaml` as part of the change set it summarizes. The complete Commit Diff still includes that artifact; repository/SCM remains authority for that full Diff.

### 22.2 Tasks

A Change Record MAY reference **zero, one, or many** Task Books (human-only work, one planned task, or a deliberately grouped candidate).

MUST NOT require a Task Book.

A Task Book SHOULD normally be finalized by **no more than one** durable Change Record.

A Task Book already represented by a successful submitted Change Record MUST NOT be silently reused for new development. New work SHOULD create a new Task Book.

### 22.3 Provenance summary

Durable compact provenance MAY include:

- number of relevant Develop Sessions (count / existence — **not** required resolvable IDs)
- path counts / summaries by provenance class
- presence of MIXED / POST / PREEXISTING / UNATTRIBUTED changes

MUST NOT copy local Session internals. MUST NOT require deleted Session directories to understand the Change Record.

---

## 23. Change Record timing

Preserve P0/P2 exactly. Do **not** add a Submit stage. Distinguish:

| Term | Meaning |
| --- | --- |
| **REVIEWED CANDIDATE DIFF** | The real project/change-set reviewed through Submit-S3/S4/S5/S6 (and the Submit-S8 loop if needed). This is the **input** to Submit-S9. |
| **COMMIT CANDIDATE TREE** | That reviewed candidate **plus** the deterministic Submit-S9 Change Record artifact. |

```text
REVIEWED CANDIDATE DIFF
  → Submit-S9 finalize Change Record into .scaffold/changes/
  → COMMIT CANDIDATE TREE = reviewed candidate + that artifact
  → Submit-S10 Commit
```

MUST NOT create the Change Record **after** Commit.

The Change Record `path_summary` describes the **REVIEWED CANDIDATE DIFF**. It MUST NOT recursively include itself.

Any Submit-S9 mutation **other than** that expected deterministic Change Record finalization is **not** silently exempt from candidate-bound review. Submit-S9 MUST NOT mutate Task Books (see §28.3).

If the reviewed candidate **materially** changes before retry (including after Submit-S7/S8 sync): the Change Record MUST be regenerated or revalidated **before** the next Commit attempt. A Change Record describing Candidate A MUST NOT be committed with Candidate B.

If only the Commit attempt failed and the candidate record representation is unchanged: the same candidate record MAY be retried.

---

## 24. Candidate vs durable semantics

Publication is **contextual**. There is no second Commit solely to flip a status field.

| Context | Meaning |
| --- | --- |
| Record exists in the working tree / index and is **not** in a successful Commit | **Candidate** Change Record |
| **Same bytes** are contained in a **successful** Commit | **Durable as-built** Change Record |

**“Same bytes”** means the exact Change Record content representation **selected/staged for the SCM commit after** repository-configured normalization / clean filtering (P2 already recognizes CRLF/LF and repository text policy).

It does **not** require raw Windows working-tree bytes to equal the committed blob bytes when the SCM normally normalizes text.

| Host | Candidate identity |
| --- | --- |
| SCM with text normalization / clean filtering | Staged representation after that filtering |
| SCM without such filtering | The finalized serialized record bytes |
| No SCM | The project-defined finalized record representation (P8) |

The candidate Change Record MUST NOT be rewritten after Commit merely to become “submitted.” MUST NOT invent a second post-Commit record mutation. This contract does **not** design Git-specific runtime filtering.

If Commit fails: the record remains an uncommitted candidate. MUST NOT be described as successfully submitted history.

This avoids lying if Commit fails, avoids a self-referential Commit SHA, and avoids a second mutation after Commit.

No-SCM: do not invent a revision. “Durable” then means P8’s project-defined successful finalization of that candidate (P8 owns limitations). Session cleanup follows that successful durable finalization, not Push, and not an invented SHA.

---

## 25. No final Commit SHA

The Change Record MUST NOT contain the final Commit SHA (or equivalent SCM identifier) of the **Commit that contains that Change Record**.

Reason: self-reference / circular finalization.

Git/SCM history associates the record with the Commit.

The record MAY contain the final candidate’s **base / parent** baseline, because that is known before Commit.

MUST NOT invent a post-Commit second mutation merely to insert the Commit SHA.

---

## 26. Change Record immutability

Once a Change Record is contained in a successful durable Commit, it SHOULD be treated as historical / immutable.

Future corrections SHOULD normally create a **new change** and/or a **new corrective Change Record**, rather than rewriting old submitted history.

History rewriting remains explicit exceptional human/SCM action, not normal Scaffold behavior.

Candidate files MAY be replaced before a successful Commit.

---

## 27. Human authorization is not a record permission bit

`SUBMIT_AUTHORIZED` requires **current explicit** human authorization of **this** reviewed candidate (Constitution).

P3 MUST NOT create a reusable YAML boolean such as `submit_authorized: true` that an Agent can persist and later reuse as authority to Commit.

A record MAY later retain a **non-authoritative historical statement** that human authorization occurred, if P8 needs an audit note. That statement MUST NEVER grant future authorization.

The same principle applies to Adoption Plan approval snapshots (P1): persisted history ≠ active permission.

---

## 28. Task / Session cleanup and historical Task Books

### 28.1 Develop Session cleanup

Constitution: after successful Commit, the Develop Session **MUST** be cleaned up. P3 does not weaken that.

```text
Develop starts            → Session OPEN (Session-S0)
Develop ends normally     → SEALED (Session-S1)
Submit incomplete/blocked → retain
Successful authorized Commit
  + durable Change Record established
                          → Submit-S12 MUST clean corresponding
                            completed SEALED Develop Sessions
Push                      → NOT required for cleanup
```

In this storage model, cleanup means **deleting** the corresponding local Session directories.

OPEN Sessions MUST NOT be silently deleted. If an OPEN Session unexpectedly conflicts with finalization, surface it for P8 / human handling rather than pretending cleanup succeeded.

If mandatory post-Commit cleanup fails because of a local operational error: report the cleanup failure and retry cleanup. MUST NOT rewrite or invalidate the successful Commit solely for that reason.

If the task is **CANCELED**: explicit cleanup MAY remove Sessions. That is not the successful-Commit rule.

A stale detector MAY **prompt** cleanup of stale/ABORTED Sessions. MUST NOT silently delete an **OPEN** Session. Temporary memory MUST NOT accumulate unboundedly (Constitution principle 10).

ABORTED Sessions MAY be removed by explicit cleanup or stale prompt; they MUST NOT be treated as DEVELOP_KNOWN evidence while they remain.

### 28.2 Task Book after successful submission

After a successful Commit represented by a Change Record:

- the Task Book becomes **historical task evidence**
- it SHOULD normally stop mutating
- lasting role: what was intended, how work was staged, what task-level acceptance was reached
- Change Record describes what actually shipped in the **REVIEWED CANDIDATE DIFF**
- repository history describes the exact physical Commit Diff (including the Change Record artifact)

MUST NOT rewrite the Task Book to pretend unplanned final changes were always part of the original plan.

Historicity is **contextual**: a Task Book is historical when a **durable as-built** Change Record lists its `record_id` **and** repository history contains that durable Change Record. Until that Commit succeeds, `READY_FOR_REVIEW` is **not** submitted history.

No Task-side Change Record back-reference is required or permitted as a contract field.

### 28.3 Session IDs on the Task Book (no Submit-S9 mutation)

`develop_session_ids` MAY remain on an active Task Book. They MUST always be:

- operational / advisory
- non-authoritative
- **not required** for interpretation
- allowed to become non-resolvable after runtime cleanup

After successful Commit, a historical Task Book MUST already be understandable without `runtime/`. Durable provenance lives in the Change Record as a compact summary. MUST NOT copy Session hashes or patches into the Task Book.

If P8 chooses to remove or compact operational Session IDs, that mutation MUST occur **before** the candidate is finalized through Submit-S3 / S4 / S5 / S6 review and human authorization.

Submit-S9 MUST NOT mutate the Task Book merely for:

- Session reference compaction
- a Change Record back-reference
- cosmetic historical cleanup

This preserves candidate-bound human authorization.

P8 implements cleanup and any pre-review compaction. P3 defines the invariant.

---

## 29. Adoption Session persistence

Canonical: `.scaffold/runtime/adoption-sessions/<adoption-session-id>/session.yaml`

LOCAL, TEMPORARY. **Not** a canonical development record. MUST NOT duplicate full project knowledge. MUST NOT turn the Adoption Plan into a permanent fourth development record.

MUST be capable of preserving only what is needed for safe resume (P1):

- adoption session id
- starting Adoption Baseline
- current plan identity / digest / reference
- completed adoption steps
- applied mutation summary
- pending validation
- lifecycle state
- timestamps

Frozen Adoption Session states:

| Status | Meaning |
| --- | --- |
| `OPEN` | Adoption in progress |
| `BLOCKED` | Cannot proceed; retain for resume / human |
| `INTERRUPTED` | Unexpected stop; retain for resume |

There is **no** persisted `ACTIVATED` success state: successful activation **deletes** the Session.

### 29.1 Authorization snapshot

The Session MAY remember which Plan candidate was **observed as approved**, for resume/revalidation only.

A persisted local field MUST NOT be treated as permanent human permission.

On resume, P5 MUST revalidate: Plan identity, host state, approval applicability. P1 remains authoritative. If checks fail: re-discover → re-plan → re-approve.

### 29.2 Adoption cleanup

| Event | Fate |
| --- | --- |
| Successful activation | Corresponding Adoption Session → cleanup |
| Blocked / interrupted | Retain enough to resume |
| Abandoned | Explicit cleanup MAY remove it |

MUST NOT silently delete an active/recoverable adoption state.

---

## 30. Historical-reference behavior

| From | To | Survival |
| --- | --- | --- |
| Task Book → Develop Session | Temporary operational / advisory | MUST NOT be required for interpretation, including after Session cleanup |
| Change Record → Task Book | Durable (the only durable association direction) | Task IDs remain; Task files remain historical |
| Change Record → Test Evidence | Durable / externally resolvable as P6 defines | Opaque locator; P6 resolution |
| Change Record → Develop Session | MUST NOT require Session survival | Compact summary only |

Cross-record references MUST be stable, explicit, and non-circular where practical.

Change Record MUST NOT require Develop Session directories to survive.

Task Book MUST NOT require deleted Sessions to survive after submission.

A later Agent with only committed `tasks/` + `changes/` + repository history MUST be able to interpret intent vs as-built **without** `runtime/`.

---

## 31. Concurrency / `record_revision`

Task Book is a **shared mutable** record during development. Multiple Agents MAY interact with it.

Lightweight stale-write guard:

- Task Book contains a monotonically increasing integer `record_revision` (start at `1`).
- Every semantic mutation: re-read the current Task Book; verify the expected revision; write the update; increment `record_revision`.
- A stale Agent MUST NOT blindly overwrite a newer revision.

MUST NOT build locking infrastructure. MUST NOT assume one Agent.

Develop Session is local / session-specific (one execution). Concurrent Develop executions SHOULD use **distinct** Session IDs.

Change Record is finalized once per candidate. Regenerating a candidate replaces candidate bytes; it is not a shared live merge.

---

## 32. No-SCM

All records MUST function without Git/Perforce.

Where SCM baseline is unavailable, record honestly:

```yaml
baseline:
  kind: none        # or unavailable
  value: null
```

MUST NOT invent SHA/changelist.

Develop Session file digests still permit local provenance assistance.

Change Record remains valid, though exact repository-history association MAY be limited.

P8 owns no-SCM Submit limitations. P3 MUST NOT pretend a Commit SHA exists.

Session cleanup still requires **successful authorized durable finalization** of the Change Record as defined by P8 for that host — not Push, and not an invented revision.

---

## 33. Ownership

P2 left detailed Task/Change ownership to P3. P2’s three modes remain the **only** three: GENERATED, MANAGED, HUMAN_OWNED. MUST NOT invent a fourth P2 ownership mode.

| Record | Ownership |
| --- | --- |
| **Task Books** | **GENERATED** durable record artifacts. Mutable according to the Task lifecycle; that does not change the ownership mode. |
| **Change Records** | **GENERATED** durable record artifacts finalized by Submit. Immutable after successful Commit; that does not change the ownership mode. |
| **Develop Sessions** | LOCAL / TEMPORARY / non-authoritative. Not durable knowledge entries. |
| **Adoption Sessions** | LOCAL / TEMPORARY / non-authoritative. Not durable knowledge entries. |

Human-approved mutation of a Task Book through the record workflow MUST NOT convert the whole file to HUMAN_OWNED.

The P2 ownership registry in `.scaffold/project.yaml` MUST cover the canonical durable namespaces:

- `.scaffold/tasks/<task-id>.yaml`
- `.scaffold/changes/<change-id>.yaml`

as **GENERATED**.

P3 MUST NOT freeze whether that registry represents coverage **per file** or through a **namespace/pattern** rule. Exact `project.yaml` grammar remains deferred.

Runtime Sessions MUST NOT be registered as durable knowledge authority.

---

## 34. Deletion and retention

| Record | Deletion |
| --- | --- |
| Durable committed Change Records | MUST NOT be routinely deleted |
| Historical Task Books represented by committed changes | SHOULD NOT be routinely deleted |
| Temporary runtime Sessions | Cleaned by lifecycle rules (§28, §29) |
| Draft / canceled Task Books with no durable historical value | MAY be removed only through **explicit** project/user action |

MUST NOT silently clean history. MUST NOT accumulate unbounded session logs (Constitution principle 10). Stale OPEN Sessions: prompt, do not silent-delete.

---

## 35. Cross-phase responsibilities

| Phase | Owns |
| --- | --- |
| **P3** (this contract) | Data/lifecycle contracts: schemas, IDs, states, provenance classes, cleanup invariants, candidate/durable publication |
| **P4** | Skill package, Skill routing, Rule loading, `skills.lock` contents, compatibility/migration protocol |
| **P5** | Adoption execution, Understand Full / Refresh / Compatibility, Adoption Session **operational use** |
| **P6** | Test Report/Evidence schema, test execution, Test Matrix, evidence storage/resolution, native tests, Game Legibility runtime |
| **P7** | Task-driven Develop behavior; creating/updating Task Books in practice; creating/sealing Develop Sessions; Repair Mode |
| **P8** | Observed-S2; provenance classification **execution**; Structural Review; Knowledge Consistency; Test Completeness; human authorization; Change Record finalization; Commit/Push; Session cleanup |

P3 MUST NOT implement those runtimes.

---

## 36. Non-goals

P3 MUST NOT implement:

- actual host `.scaffold` directories in this distribution repository
- YAML parser / JSON Schema / validators / CLI / Python runtime
- Git or Perforce integration
- Test Evidence schema or Test runner
- Develop runtime or Submit runtime
- automatic cleanup code, hashing implementation, or patch generator
- locks / database / agent-memory service / changelog generator

---

## 37. P3 specialization of P0 advisory provenance semantics

P0 remains authoritative. Constitution §7 says Submit **MAY** classify paths using the four named classes and forbids `HUMAN_CHANGE`. It does **not** state that the list is exhaustive, and it requires Submit to work with no Session.

P3 only makes those advisory mechanics precise:

1. **`UNATTRIBUTED`** is the honest fallback when Session/baseline/overlay evidence cannot safely establish a tighter class (including human-only Submit).
2. **`MIXED_CHANGE`** includes “already dirty, then Develop edited” and “Session gap,” as well as Develop-touched paths whose Observed-S2 diverges from Session-S1, so they are not mislabeled `DEVELOP_KNOWN` or `PREEXISTING_CHANGE`.
3. **`PREEXISTING_CHANGE`** and **`POST_DEVELOP_ADDITIONAL`** require the Session boundary-overlay evidence in §16 and §19. Insufficient evidence → `UNATTRIBUTED`.
4. Task “completed / historical” after success is **contextual** (durable Change Record listing the Task Book + repository history), not a pre-Commit `SUBMITTED` field.

Do not silently patch P0 documents. If an implementer believes a later runtime conflicts with Constitution, stop and raise a human design question.

---

## 38. Illustrative YAML examples

All blocks below are **CONTRACT EXAMPLE**, not live host data. They MUST NOT be copied into this distribution repo as `.scaffold/` files.

### 38.1 Standard Task Book (multi-stage)

```yaml
# CONTRACT EXAMPLE — not live host data
record_type: task_book
schema_version: "1"
record_id: task-20260827T120501Z-a1b2c3d4
record_revision: 4
created_at: 2026-08-27T12:05:01Z
updated_at: 2026-08-27T16:40:00Z
title: Save checksum header
goal: Add a checksum to the Save file header and keep load compatible.
acceptance: New saves include a checksum; load rejects a corrupt checksum; Save module knowledge names the field.
baseline:
  kind: git
  value: 3944e932c9a1d40a78402fc1d244c6a3d99e09f9
scope:
  modules: [save]
  paths: [src/save/]
  exclude: [src/save/legacy/]
  notes: Do not migrate old slots in this task.
status: IN_PROGRESS
stages:
  - stage_id: stage-1
    goal: Write checksum on save.
    acceptance: New saves include a checksum field.
    status: COMPLETE
    required_tests:
      - requirement_id: save/write-checksum
        evidence_ref: { locator: "opaque-p6-locator-1" }
        observed_outcome: PASS
    result_summary: Header writer emits checksum.
  - stage_id: stage-2
    goal: Verify checksum on load.
    acceptance: Corrupt checksum fails load with a defined error.
    status: IN_PROGRESS
    required_tests:
      - requirement_id: save/load-checksum
        evidence_ref: { locator: "opaque-p6-locator-2" }
        observed_outcome: FAIL
    result_summary: Waiting on load-path fix.
  - stage_id: stage-3
    goal: Docs for the header field.
    acceptance: Save module knowledge names the field.
    status: PENDING
    required_tests: []
final_tests:
  - requirement_id: save/task-final
    evidence_ref: { locator: "opaque-p6-locator-final" }
    observed_outcome: NOT_EXECUTED
develop_session_ids:
  - dev-20260827T121000Z-11aa22bb
result_notes: Stage-2 load path still failing required test.
```

### 38.2 Lightweight Task Book (same schema, one stage)

```yaml
# CONTRACT EXAMPLE — not live host data
record_type: task_book
schema_version: "1"
record_id: task-20260827T130000Z-deadbeef
record_revision: 2
created_at: 2026-08-27T13:00:00Z
updated_at: 2026-08-27T13:12:00Z
title: Fix config typo
goal: Correct the display-name typo in config/app.yaml.
acceptance: Display name reads correctly.
baseline:
  kind: git
  value: 3944e932c9a1d40a78402fc1d244c6a3d99e09f9
scope:
  paths: [config/app.yaml]
status: READY_FOR_REVIEW
stages:
  - stage_id: stage-1
    goal: Fix the typo.
    acceptance: Display name reads correctly.
    status: COMPLETE
    required_tests:
      - requirement_id: config/app-yaml-parse
        evidence_ref: { locator: "opaque-p6-locator-3" }
        observed_outcome: PASS
    result_summary: Typo corrected; parse check passed.
final_tests:
  - requirement_id: config/app-yaml-parse
    evidence_ref: { locator: "opaque-p6-locator-3" }
    observed_outcome: PASS
develop_session_ids:
  - dev-20260827T130500Z-c0ffee00
```

### 38.3 Develop Session metadata + manifest

```yaml
# CONTRACT EXAMPLE — not live host data
# File: .scaffold/runtime/develop-sessions/dev-20260827T121000Z-11aa22bb/session.yaml
record_type: develop_session
schema_version: "1"
record_id: dev-20260827T121000Z-11aa22bb
created_at: 2026-08-27T12:10:00Z
updated_at: 2026-08-27T15:00:00Z
status: SEALED
task_id: task-20260827T120501Z-a1b2c3d4
baseline:
  kind: git
  value: 3944e932c9a1d40a78402fc1d244c6a3d99e09f9
# Workspace boundary overlays (not Develop attribution)
workspace_overlay_s0:
  coverage: complete
  paths:
    - path: notes/local-todo.md
      kind: regular_file
      digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
workspace_overlay_s1:
  coverage: complete
  paths:
    - path: notes/local-todo.md
      kind: regular_file
      digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
session_s1_sealed_at: 2026-08-27T15:00:00Z
```

```yaml
# CONTRACT EXAMPLE — not live host data
# File: .../files.yaml  — Develop-touched paths only
files:
  - path: src/save/Save.cpp
    change_kind: modified
    was_preexisting_dirty: false
    before_kind: regular_file
    after_kind: regular_file
    before_digest: sha256:1111111111111111111111111111111111111111111111111111111111111111
    after_digest: sha256:2222222222222222222222222222222222222222222222222222222222222222
    content_class: text
    patch_ref: patches/3c9b0a1f8e2d7c44.patch
    stage_ids: [stage-1]
  - path: assets/icon.bin
    change_kind: modified
    was_preexisting_dirty: false
    before_kind: regular_file
    after_kind: regular_file
    before_digest: sha256:3333333333333333333333333333333333333333333333333333333333333333
    after_digest: sha256:4444444444444444444444444444444444444444444444444444444444444444
    content_class: binary
    patch_ref: null
    stage_ids: [stage-1]
```

No file bodies, no secrets, no chat transcript.

### 38.4 Change Record (no Commit SHA, no submitted flag)

```yaml
# CONTRACT EXAMPLE — not live host data
record_type: change_record
schema_version: "1"
record_id: change-20260827T180000Z-feed1234
created_at: 2026-08-27T18:00:00Z
summary: Save header checksum plus load verification and module doc update.
base:
  kind: git
  value: 3944e932c9a1d40a78402fc1d244c6a3d99e09f9
affected:
  modules: [save]
  areas: [src/save/, docs/project/modules/]
# path_summary = REVIEWED CANDIDATE DIFF; MUST NOT list this Change Record file
path_summary:
  representation: exact
  total_changed_paths: 3
  paths:
    - path: src/save/Save.cpp
      change: modified
    - path: src/save/Save.h
      change: modified
    - path: docs/project/modules/save.md
      change: modified
structural_summary: No module add/delete. Save header field added.
knowledge_updates: Save module entry documents the checksum field.
verification:
  summary: Stage and task-final required tests have terminal PASS results for this candidate.
  evidence_refs:
    - locator: "opaque-p6-locator-final"
understand_involvement:
  refresh: true
  compatibility: false
task_book_ids:
  - task-20260827T120501Z-a1b2c3d4
provenance:
  relevant_develop_session_count: 2
  classes:
    DEVELOP_KNOWN: { path_count: 2 }
    MIXED_CHANGE: { path_count: 0 }
    PREEXISTING_CHANGE: { path_count: 0 }
    POST_DEVELOP_ADDITIONAL: { path_count: 1 }
    UNATTRIBUTED: { path_count: 0 }
limitations: []
```

No `commit_sha`. No `submitted: true`. No `submit_authorized`.

### 38.5 Adoption Session metadata

```yaml
# CONTRACT EXAMPLE — not live host data
# LOCAL / TEMPORARY / DELETE AFTER SUCCESSFUL ACTIVATION
# File: .scaffold/runtime/adoption-sessions/adopt-20260827T090000Z-0abc1234/session.yaml
record_type: adoption_session
schema_version: "1"
record_id: adopt-20260827T090000Z-0abc1234
created_at: 2026-08-27T09:00:00Z
updated_at: 2026-08-27T10:15:00Z
status: INTERRUPTED
baseline:
  kind: git
  value: 6ea16e343fdd4324983786186b17b2d59b059fb7
plan:
  identity: plan-candidate-3
  digest: sha256:5555555555555555555555555555555555555555555555555555555555555555
  observed_approved: true   # NOT permanent permission; P5 MUST revalidate
completed_steps: [B1, B2, B3, B4, B5]
applied_mutation_summary:
  - action_class: CREATE
    target: .scaffold/project.yaml
pending_validation: [B7]
# MUST NOT duplicate full project knowledge here.
```

`observed_approved: true` is resume metadata only. It MUST NOT be treated as standing B4 authorization.

---

## 39. Acceptance scenarios

Contract-level behavior. No fixtures.

| Case | Behavior |
| --- | --- |
| **A** Simple one-stage typo/config task | Same Task Book schema; one Stage; small scope; Task-level `acceptance` MAY match the Stage `acceptance`; READY_FOR_REVIEW only after that Stage COMPLETE, planned final tests meet acceptance, and Task-level `acceptance` is satisfied. |
| **B** Multi-stage feature task | Ordered stages; a later Stage MAY stay PENDING while earlier work is IN_PROGRESS; TASK_COMPLETE only when **all** required stages COMPLETE. |
| **C** Stage test fails, later passes | Failed required test ⇒ Stage stays non-complete (typically IN_PROGRESS). After fix + tests meet acceptance ⇒ Stage MAY become COMPLETE. Execution alone never completes the Stage. |
| **D** All stages complete but final tests fail | TASK_COMPLETE holds; `status` MUST NOT become READY_FOR_REVIEW; remain in Develop ↔ Test. |
| **E** Task canceled | `status: CANCELED`. Not READY_FOR_REVIEW. Sessions MUST NOT be silently deleted; explicit cleanup MAY remove them. No fake Change Record. |
| **F** Develop starts from clean working tree | Session-S0 workspace overlay empty (or coverage complete with no dirty paths). Touched paths MAY become DEVELOP_KNOWN if chain and Observed-S2 match. |
| **G** Unrelated dirty file exists before Develop | Recorded in Session-S0 workspace overlay. PREEXISTING_CHANGE only if Develop never touches it **and** Observed-S2 still matches that S0 pre-existing state. If S0 and S2 differ without Develop coverage ⇒ not pure PREEXISTING; use a provable class or UNATTRIBUTED. |
| **H** Develop edits a file that was already dirty | `was_preexisting_dirty: true`. Final path ⇒ MIXED_CHANGE. MUST NOT be DEVELOP_KNOWN. MUST NOT claim the extra portion is human. |
| **I** New file appears after Session-S1 | POST_DEVELOP_ADDITIONAL only if: not pre-existing dirty; Develop did not touch it; Session-S1 overlay shows still baseline-equivalent/absent at Develop end; Observed-S2 shows the addition. MUST NOT infer POST from “not in S0 and exists at S2”. If S1 coverage is partial/unavailable ⇒ UNATTRIBUTED. |
| **J** Develop-edited file changes again after Session-S1 | Observed-S2 ≠ Session-S1 ⇒ MIXED_CHANGE, not POST_DEVELOP_ADDITIONAL. |
| **K** Two Sessions touch the same file with a continuous chain | Previous Session-S1 after-state = next before-state; latest Session-S1 = Observed-S2; not preexisting dirty ⇒ MAY be DEVELOP_KNOWN. |
| **L** Two Sessions have an unexplained state gap | Path cannot be DEVELOP_KNOWN ⇒ MIXED_CHANGE if Develop touched it. |
| **M** Human-only; no Task Book and no Session | Submit still starts. TASK_COMPLETE = NOT APPLICABLE. Provenance typically UNATTRIBUTED. MUST NOT synthesize a Task Book. |
| **N** Task exists but manual/external changes exceed Task scope | Task Book MUST NOT be silently rewritten. Extra paths still count in the real Diff. Provenance classes apply. P8 reviews/resolves. |
| **O** Several Task Books enter one Submit candidate | One Change Record MAY list multiple `task_book_ids`. Each listed Task Book SHOULD not be reused afterwards once that Change Record is durable. |
| **P** Submit sync changes the final Diff after a Change Record candidate existed | Candidate A record MUST NOT ship with Candidate B. Regenerate/revalidate Change Record before the next Commit. Prior S6 authorization is invalid (Constitution). |
| **Q** Commit fails after Change Record was finalized | Record remains a **candidate**. MUST NOT be described as submitted history. No SUBMITTED field to lie with. Retry the same staged/normalized record if the reviewed candidate is unchanged; otherwise regenerate. |
| **R** Commit succeeds but Push is not authorized | Change Record representation in the Commit is durable as-built. Submit-S12 MUST clean corresponding completed SEALED Sessions. Push remains optional and separately authorized. |
| **S** Successful Commit cleans Develop Sessions | Submit-S12 MUST delete corresponding completed SEALED Session directories. Task Book is not mutated at S9 for compaction. `develop_session_ids` if still present are advisory and not required. Push not required. |
| **T** Binary/large file touched by Develop | Manifest + digests + kind/class. MUST NOT store the body. Provenance still works from digests. |
| **U** Sensitive local file touched | MUST NOT store a content patch. Metadata/digest only if safe. Not a secrets product. |
| **V** External CI/human Test Evidence referenced | Opaque `evidence_ref.locator` only. P6 owns schema/resolution. MUST NOT copy CI logs into Task/Change records. |
| **W** Stale/open Develop Session exists | MUST NOT silently delete OPEN. Stale detector MAY prompt. OPEN/ABORTED Sessions do not complete a DEVELOP_KNOWN chain. |
| **X** Adoption interrupted and resumed | Session retained (`INTERRUPTED`/`BLOCKED`) with baseline, plan digest, steps, mutations, pending validation. P5 revalidates Plan identity, host, approval. `observed_approved` is not standing permission. |
| **Y** Historical Task Book after Session cleanup | Task Book (Session IDs advisory / not required) + Change Record + repository Diff suffice. MUST NOT require `runtime/develop-sessions/` to understand history. MUST NOT depend on an S9 Task Book mutation. |
| **Z** Two Agents update the same Task Book from stale revisions | Writer with old `record_revision` MUST NOT overwrite. Re-read, reconcile, increment. No lock service. |
| **AA** No SCM project | `baseline.kind: none` or `unavailable`. No invented SHA. Digests still assist provenance. Change Record valid; history association may be limited (P8). |
| **AB** Change Record would otherwise need its own final Commit SHA | Forbidden. Record stores pre-Commit `base` only. SCM history binds the Commit to the record. |
| **AC** Unplanned extra file neither Session-covered nor clearly pre-existing | UNATTRIBUTED. Insufficient S0/S1 boundary evidence to prove PREEXISTING or POST. Still part of actual Diff. Not an error. Timestamps/mtimes alone MUST NOT promote it to POST. |
| **AD** Task Book says tests complete but actual Diff adds another module | Planned Task tests ≠ TEST_COMPLETE. Submit derives required tests from actual Diff + `tests.yaml` + Task Book + policy. Extra module still requires its tests. |

---

## 40. Invariant checklist

Agents implementing later phases MUST preserve:

| ID | Invariant |
| --- | --- |
| A | Exactly three canonical development record kinds |
| B | Other distinct artifacts remain allowed |
| C | Task Book = plan/progress, not final Diff truth |
| D | Develop Session = temporary advisory provenance |
| E | Change Record = final durable submitted summary |
| F | Repository reality remains physical authority |
| G | No clean-tree assumption |
| H | Session-S0 workspace overlay preserves pre-existing dirty state (with coverage class) |
| I | Session-S1 seals Develop-touched after-state **and** an end-of-session workspace overlay |
| J | Observed-S2 is freshly observed by Submit |
| K | Develop-touched pre-existing dirty path → MIXED_CHANGE |
| L | Post-Session-S1 modification of Develop-touched path → MIXED_CHANGE |
| M | No “human change” attribution is inferred |
| N | Human-only work can Submit with no Task/Session |
| O | Task Book planned tests do not equal TEST_COMPLETE |
| P | READY_FOR_REVIEW requires final task tests accepted and declared Task-level acceptance satisfied |
| Q | Failed required tests do not complete a Stage |
| R | Simple task stays lightweight using the same schema |
| S | Multiple Sessions compose deterministically |
| T | Change Record never depends on retained Session files |
| U | Change Record is finalized before Commit |
| V | Commit failure does not create false submitted history |
| W | No final Commit SHA inside the same Change Record |
| X | No persisted boolean grants Submit authorization |
| Y | Successful authorized Commit + durable Change Record → Submit-S12 MUST clean corresponding completed SEALED Sessions; Push not required |
| Z | Task Book remains understandable after Session cleanup without an S9 Task mutation |
| AA | Runtime Sessions are local/temporary |
| AB | No chain-of-thought/chat logs are stored |
| AC | Large/binary/sensitive files do not require body copies |
| AD | Task Book stale writes are detectable via `record_revision` |
| AE | No-SCM is supported |
| AF | P4–P8 runtimes are not specified as implementations here |
