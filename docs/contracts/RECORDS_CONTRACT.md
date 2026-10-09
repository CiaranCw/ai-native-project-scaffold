# Records Contract

This document is the P3 contract for **development-record kinds**, **identifiers**, **schemas**, **lifecycles**, **provenance classes**, and **retention**.

It does **not** implement Develop, Submit, Test, YAML parsers, validators, hashing tools, or live host `.scaffold/` trees.

**Normative words:** MUST, MUST NOT, SHOULD, MAY.

**Authority is topic-scoped, not “later phase wins.”**

- [CONSTITUTION.md](CONSTITUTION.md) owns the highest product-wide invariants.
- [ADOPTION_CONTRACT.md](ADOPTION_CONTRACT.md) owns Adoption lifecycle, approval envelope, resume/recovery behavior, and B1–B9 semantics.
- [PROJECT_CONTRACT.md](PROJECT_CONTRACT.md) owns host structure, ownership model, and project lifecycle/maintenance representation.
- This Records Contract owns record representation, record lifecycle, record retention, record relationships, and record-specific concurrency/provenance semantics.
- [SKILL_CONTRACT.md](SKILL_CONTRACT.md) owns Skill package, routing, version, compatibility, and migration protocol within those higher invariants.

Architecture documents visualize their corresponding Contracts and do not reverse this topic ownership. For Adoption Session specifically, P1 owns **what Adoption does** and how approval/resume/recovery behaves; P3 owns **how those facts and states are represented and retained**. P3 MUST NOT use record representation semantics to override P1 Adoption behavior.

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
| **Change Record** | What actually ended up in the final submission candidate and became durable after successful Submit-S10 finalization? | Durable **submitted-change summary** derived from **real** final project state. The repository/workspace and any available SCM remain authority for the physical Diff. |

MUST NOT introduce another record that duplicates the lifecycle or duty of these three. MUST NOT create parallel work-log, handoff-log, scratchpad, session-history, developer-diary, or mega-CHANGELOG copies of the same development facts.

Other artifacts MAY exist when they have a clearly different purpose, authority, lifecycle, and retention. They are **not** a fourth canonical development record:

| Artifact | Why it is distinct |
| --- | --- |
| **Adoption Session** | First-attach resume/recovery only. Temporary. P1 authority. |
| **Test Report / Evidence** | What a specified test scope actually verified. P6 schema. |
| External CI result | External verification input. Not development plan or as-built summary. |
| Analysis artifact | Bounded later-phase work. Must not clone Task/Session/Change duties. |
| **Migration Execution** | Bounded operational checkpoints for P5 migration interruption/recovery. Not development plan or submitted-change history. |

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
| Change Record | `.scaffold/changes/<change-id>.yaml` | YES | YES after successful Submit-S10 durable finalization; candidate before S10 (same logical content) |
| Develop Session | `.scaffold/runtime/develop-sessions/<develop-session-id>/` | NO — local | NO — temporary |
| Adoption Session | `.scaffold/runtime/adoption-sessions/<adoption-session-id>/` | NO — local | NO — temporary |
| Knowledge Assessment | `.scaffold/runtime/understand-assessments/<assessment-id>/assessment.yaml` | NO — local | NO — temporary supporting artifact; not a canonical development record |
| Understanding currentness | `.scaffold/runtime/understand-currentness/<snapshot-id>/snapshot.yaml` | NO — local | NO — temporary supporting artifact; not a canonical development record |
| Repair supporting state | `.scaffold/runtime/repair-state/<task-id>.yaml` | NO — local | NO — temporary supporting artifact; not a canonical development record |
| Scenario-Aware Verification plan | `.scaffold/runtime/test-plans/<plan-id>/plan.yaml` | NO — local | NO — temporary supporting artifact; not a canonical development record |

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

Knowledge Assessment directory (Understand-owned supporting artifact):

```text
.scaffold/runtime/understand-assessments/<assessment-id>/
└── assessment.yaml       REQUIRED
.scaffold/runtime/understand-assessments/heads/<binding-digest>/
└── head.yaml             REQUIRED current-head for one (candidate, impact) binding
```

Knowledge Assessment is **not** a canonical development record. It is candidate-bound and impact-bound supporting authority for Submit-S4. Candidate + impact equality is not enough: S4 may use only the current-head Assessment whose published bytes still match the head integrity digest. A superseded locator MUST NOT be replayed.

Understanding currentness directory (Understand-owned supporting artifact):

```text
.scaffold/runtime/understand-currentness/<snapshot-id>/
└── snapshot.yaml         REQUIRED physical/module currentness snapshot
.scaffold/runtime/understand-currentness/heads/project/
└── head.yaml             REQUIRED current-head for project-scope understanding
.scaffold/runtime/understand-currentness/completions/<completion-id>/
├── completion.yaml       REQUIRED supporting refresh-completion receipt
└── result.yaml           REQUIRED Understand refresh output binding
.scaffold/runtime/understand-currentness/handoff.yaml
                          OPTIONAL derived summary; not authority
```

Understanding currentness is **not** a canonical development record and is **not** a Knowledge Assessment. Observation of declared module physical digests and structural indexes decides the required refresh scope. A new current-head may become CURRENT only after Understand-produced supporting refresh-completion receipts bind that exact physical/output authority **and** current module knowledge bytes still match each bound `knowledge_digest`. `head.record_id` MUST identify the snapshot named by `head.locator`. A derived handoff summary MUST NOT be trusted when its locator/digest does not match the current-head snapshot. Missing currentness fails closed to `FULL_REFRESH_REQUIRED` / `UNKNOWN`. A review package that includes `completion.yaml` MUST also include referenced `result.yaml`.

Scenario-Aware Verification directory (Test-owned supporting artifact):

```text
.scaffold/runtime/test-plans/<plan-id>/
└── plan.yaml             REQUIRED supporting verification plan
.scaffold/runtime/test-plans/heads/<task-id>/<requirement-id>/
└── head.yaml             REQUIRED current-head for one Task requirement
```

Scenario-Aware Verification plans are **not** a canonical development record
and are **not** a fifth Skill. They describe what a bound Test profile must
prove for one Task requirement. Missing/stale/mismatched current-head fails
closed.

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

Every durable canonical Task/Change YAML record, and every Adoption/Develop Session `session.yaml`, MUST be self-describing.

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
| `acceptance` | Human-readable final Task-level acceptance criterion — **how we know the whole Task is done**. It remains intent, not a DSL. |
| `task_completion_decision` | Current structured, durable, candidate-bound P7 decision about whether the declared Task-level acceptance criterion is satisfied |
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

### 8.1.1 Task Completion Decision

The Task-level `acceptance` text remains human-readable intent and is not
automatically satisfied by all Stage statuses or final Test results. The
current `task_completion_decision` is the structured decision **about** that
criterion. It is supporting Task Book authority, not a fifth Task status or a
fourth canonical record.

The mapping MUST represent:

| Concept | Required semantics |
| --- | --- |
| `candidate_digest` | Actual candidate evaluated by the Task decision |
| `outcome` | The same bounded decision enum: exactly `SATISFIED` \| `UNSATISFIED` \| `UNKNOWN` |
| `basis` | Nonempty bounded list of current authoritative facts used for the decision |
| `rationale` | Concise reconstructable explanation of why the basis supports the outcome |
| `supersedes` | Optional fixed summary of a prior Task decision that is no longer current: prior candidate digest, outcome, and concise rationale |

P7 owns the Task lifecycle/acceptance decision. Its basis MAY reference
current repository and Task facts, current Stage Completion Decisions, P6
Evidence locators, final Test Evidence, and legitimate human-observation
Evidence. P6 remains sole owner of Test/Evidence truth.

Hidden chat reasoning, raw Test Report mappings, uncited “the user said yes,”
successful source writes, `TEST_PASS`, or `TEST_COMPLETE` alone are not
durable Task-acceptance authority. If the declared Task criterion cannot be
determined from current authoritative facts, the outcome MUST be `UNKNOWN`
and `READY_FOR_REVIEW` is not legal.

A Task Completion Decision is current only when its `candidate_digest`
equals the actual candidate digest and every cited P6 Evidence locator
resolves as authoritative for that candidate. A `SATISFIED` Task decision for
C1 MUST NOT support `READY_FOR_REVIEW` for C2.

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
| `completion_decision` | Current structured, durable, candidate-bound P7 decision about whether this Stage's human-readable acceptance criterion is satisfied |

A Stage MUST NOT become `COMPLETE` merely because its tests **executed**.

The transition `IN_PROGRESS` → `COMPLETE` is legal only when all of the
following hold for the actual candidate at publication:

1. current Stage Completion Decision is `SATISFIED` for the actual candidate
2. required Stage tests satisfy their **defined acceptance requirements**
3. no unresolved required-test blocker for that Stage

If required tests fail: the Stage remains non-complete. Develop ↔ Test continues. Typical status remains `IN_PROGRESS`. `BLOCKED` is for an external/human/policy stop, not the ordinary fail-and-fix loop.

#### 8.4.1 Stage Completion Decision

The Stage `acceptance` text remains human-readable intent. It is not a DSL and
need not be reducible to an automated Test. A Stage Completion Decision is the
structured decision **about** that criterion; it does not replace the
criterion or create a fourth canonical record.

The current `completion_decision` MUST be a mapping capable of representing:

| Concept | Required semantics |
| --- | --- |
| `stage_id` | Exact target Stage identity; MUST match the containing Stage |
| `candidate_digest` | Actual candidate evaluated by the decision |
| `outcome` | Exactly `SATISFIED` \| `UNSATISFIED` \| `UNKNOWN` |
| `basis` | Nonempty bounded list of authoritative facts used for the decision |
| `rationale` | Concise reconstructable explanation of why the basis supports the outcome |
| `supersedes` | Optional fixed summary of a prior decision that is no longer current: prior candidate digest, outcome, and concise rationale |

Each basis item MUST name its kind and contain a concise summary. When the
basis relies on Test, CI, external, or human-observation Evidence, it MUST
carry the relevant opaque P6 `evidence_ref.locator`. Repository observations
and current Task/Stage facts MAY be named directly when observable under
Develop authority. Hidden chat memory, a raw Test Report mapping, or an
uncited “the user said yes” statement is not a durable basis.

P7 owns the lifecycle decision and publication. P6 remains the sole owner of
Test execution, Evidence truth, locator schema, integrity, and resolution.
P7 MUST NOT forge or reinterpret P6 Evidence. P8 does not decide Stage
completion.

`UNKNOWN` is distinct from `UNSATISFIED`. If authoritative facts cannot
determine the criterion, the outcome MUST be `UNKNOWN`; the Stage MUST NOT
become `COMPLETE`, and Develop routes to the applicable Test, human
observation, Understand, or repair action. Subjective acceptance MAY become
`SATISFIED` only after an existing legitimate P6 human-observation or other
explicit control/Evidence path supplies the cited authority.

#### 8.4.2 Candidate currentness and revalidation

A Stage Completion Decision is current only when its `candidate_digest`
equals the actual candidate digest at publication/use and every cited
Evidence locator resolves as authoritative for that candidate. Chat or
Session continuity does not establish freshness.

A `SATISFIED` decision for C1 MUST NOT complete a Stage or support
`READY_FOR_REVIEW` for C2. A successful source write, `TEST_PASS`, or
`TEST_COMPLETE` alone is insufficient.

A `COMPLETE` status records that Stage completion was validly established
under §8.4 when that status was published; it does not assert that the stored
decision remains current for every later candidate. A Stage MAY therefore
remain `COMPLETE` while P7 re-evaluates and atomically publishes a replacement
`SATISFIED` completion decision for C2. Until that publication, its stale C1
decision is historical progress only and cannot support Task readiness. If
re-evaluation for C2 is `UNSATISFIED` or `UNKNOWN`, P7 MUST atomically move
the Stage to `IN_PROGRESS`, or to `BLOCKED` only when the existing
external/human/policy-stop meaning applies. No `REVALIDATING` Stage state is
introduced.

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

Each Task planned Test reference keeps its own `requirement_id`. That identity
names the Task obligation; it is **not** a P6 Test profile identity.

When P7 expects a fresh P6 Test profile execution to produce Evidence for the
requirement, the Task reference MUST carry an explicit durable
`execution_binding` before execution:

```yaml
# CONTRACT EXAMPLE fragment
required_tests:
  - requirement_id: "task-required/check-save"
    execution_binding:
      kind: test_profile
      profile_id: "unit-save-check"
```

`execution_binding.kind` is `test_profile` and `profile_id` is the exact P6
Test Contract profile selected to execute. The binding is Task-owned planned
authority. Creating, removing, or changing it is a substantive requirement-plan
mutation, not a lifecycle-result update. P7 MUST NOT infer this association
from string equality, list position, the only selected profile, or caller
prose.
Without explicit current Task binding, matching names, selection order, or a
sole result MUST NOT be used to guess the association.

The Develop→Test handoff carries the exact
`requirement_id`→`profile_id` pairs derived from current Task authority plus
the selected profile identities. P6 does not decide that a profile proves a
Task requirement. P6 preserves the producing `profile_id` in its report and
public locator resolution. P7 MAY attach the returned locator only when its
resolved producing profile matches the Task reference's explicit
`execution_binding.profile_id`.

After that explicit join, Task Book and Change Record MAY reference Test
Evidence with an **opaque locator**:

```yaml
# CONTRACT EXAMPLE fragment
required_tests:
  - requirement_id: "task-required/check-save"
    execution_binding:
      kind: test_profile
      profile_id: "unit-save-check"
    evidence_ref:
      locator: "opaque-p6-locator"
    observed_outcome: PASS
```

The durable Task reference therefore lets a fresh Agent recover both the
planned execution association and the exact Evidence proof without chat or a
raw Test Report. `requirement_id` and `profile_id` MAY intentionally differ.
No binding means a fresh profile execution supplies no automatic Task
association, even if the strings happen to match; the requirement remains
unresolved until explicit Task authority or an explicit legitimate Evidence
locator exists. A wrong or mismatched binding cannot satisfy another
requirement.

Project-required Test profiles remain a separate obligation set derived from
the Test Contract/project policy. They MUST NOT be collapsed into Task planned
requirement identities. A Task requirement MAY instead cite legitimate P6
HUMAN, CI, or EXTERNAL Evidence directly through its opaque locator where
appropriate; no local automated profile or profile-ID equality is required.

`observed_outcome` when present MUST be one of: `PASS` | `FAIL` | `NOT_EXECUTED` | `UNKNOWN`.

MUST NOT copy full logs, screenshots, Evidence Bundles, or CI output into Task Book or Change Record.

`WAIVED` / exception mechanics are **P8**. P3 MUST NOT invent a waiver that grants TEST_COMPLETE.

### 8.7 P6 candidate projection and Task control-plane neutrality

P6 owns one candidate identity and one public `candidate_digest`. P3 does not
define a competing digest. To avoid a Task Book self-reference that cannot be
represented, P6's candidate projection MUST treat Task Book content
semantically rather than hashing every mutable Task byte without
classification.

For candidate currentness, the **substantive Task authority projection**
includes at least:

- record/schema/Task identity and creation identity
- title, goal, Task acceptance, baseline, and scope
- Stage identities, goals, and acceptance criteria
- planned Stage/final `requirement_id` values
- explicit `execution_binding` values and other requirement-plan authority

Creating or removing a Task Book, or changing any projected fact above, changes
the candidate. The following bounded control-plane facts MAY be omitted from
the candidate-currentness projection:

- `record_revision` and `updated_at`
- Task and Stage progress `status`
- `develop_session_ids` and concise progress/result summaries
- result-side `evidence_ref`, `evidence_refs`, and `observed_outcome`
- Stage `completion_decision` and Task `task_completion_decision`, including
  bounded `supersedes`

Those control-plane facts are omitted from candidate currentness whenever
the **current** Task content's substantive Task authority projection is
unchanged. P6 MUST NOT condition that omission on unverifiable historical facts
such as which process wrote the identical current bytes. Identical current
Task bytes MUST contribute the same candidate identity regardless of writer
or publication path.

P6 `candidate_digest` is content-deterministic. It answers what substantive
project/Task candidate exists now. It is not a publication-provenance oracle
and does not prove Task mutation authorization.

§31 expected-revision atomic conditional publication remains mandatory for
every authorized semantic Task mutation performed by Scaffold.
**candidate-equivalent != publication-authorized.** A direct/manual/non-CAS
write is not converted into an authorized P7 publication merely because it
changes only candidate-neutral fields.

A mutation that mixes a lifecycle update with goal, acceptance, scope,
baseline, Stage plan, requirement identity, or execution-binding change is
candidate-changing. Malformed or lifecycle-illegal content is not made
authoritative by projection neutrality and MUST fail closed under Task
schema and lifecycle authority, not by claiming the candidate digest knows
the historical writer.

This is **semantic currentness**, not a Diff exclusion, write permission,
ownership permission, provenance proof, or Task lifecycle validation.
Git status/Diff and no-SCM physical inventory continue to observe the complete
Task Book bytes. Submit-S2/S3 may classify and review those changes, including
unexpected or unattributed Task mutation. Arbitrary project/source/configuration
content is never hidden by this Task-specific rule. Direct human or tool edits
do not gain P7 Task publication authority merely because they touch a
control-plane-shaped field.

For Git, P6 keeps the repository revision, path/status observations, and real
dirty-path facts, while the Task path's contribution to candidate identity uses
the semantic Task authority projection. For no-SCM, the inventory keeps the
Task path and file existence while using the same semantic projection for
candidate identity. All non-Task files and all candidate-significant Task facts
retain their ordinary candidate effect.

Therefore a P6 report for substantive candidate C remains usable after a
Task-only control-plane update whose current substantive projection is
unchanged: fresh `observe_candidate` still yields C, whether those identical
current bytes were published by P7 CAS or written by another process.
Source/business/project mutation or a substantive Task authority mutation
yields C2 and makes C Evidence stale. Stage/Task Completion Decisions bind
to this same P6 digest. READY publication does not self-invalidate, while
P8 still re-observes P6 candidate identity and the complete real Diff. The
candidate remaining C does not prove the write was publication-authorized.

This rule is independent of the FA2-FND-001 reviewed-candidate C versus S9
finalization-candidate F distinction. C/F describes the permitted deterministic
Finalization Bundle after review. Task control-plane neutrality defines the
single P6 candidate projection before and during Develop/Submit currentness.
It neither enlarges the S9 exception nor weakens C/F.

---

## 9. Stage statuses

Frozen Stage states (exactly these four):

| Status | Meaning |
| --- | --- |
| `PENDING` | Not started |
| `IN_PROGRESS` | Implementation and/or Develop ↔ Test underway |
| `BLOCKED` | Cannot continue without external/human/policy resolution beyond the ordinary test-fail-fix loop |
| `COMPLETE` | Stage completion was validly established under §8.4 when published; current-candidate readiness MAY require §8.4.2 revalidation |

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

MUST NOT persist `SUBMITTED` (or equivalent) as a Task status that would be written **before** S10 and could lie if durable finalization fails or is interrupted.

Successful submission is established through a **durably finalized Change Record + the host’s authoritative S10 success evidence**, not by pre-writing submitted into the Task Book.

If work continues after `READY_FOR_REVIEW` and before a durable Change Record exists, `status` MUST return to `IN_PROGRESS` until §11 holds again. For a Submit-requested repair, this transition is legal only through the explicit Stage-targeted protocol in §10.1.

`CANCELED` is explicit. Canceled tasks MUST NOT be treated as READY_FOR_REVIEW. Associated OPEN Sessions MUST NOT be silently deleted; see §28.

### 10.1 Stage-targeted READY repair

A bounded `submit_to_develop` repair handoff for a
`READY_FOR_REVIEW` Task MUST carry:

- `kind: submit_to_develop`
- the exact `task_id`
- the current `candidate_digest`
- a nonempty list of blocker facts
- a nonempty `target_stage_ids` list
- optional P6 Evidence refs
- bounded capabilities that do not grant Commit, Push, or submission authorization

P8 MAY name a target Stage only when the blocker deterministically maps to
current Task Stage authority, such as a Stage-required Test failure, an
explicit Stage-scoped acceptance blocker, or a source/structural blocker with
an authoritative Task-to-Stage mapping. If no deterministic mapping exists,
P8 MUST return unresolved repair routing; it MUST NOT guess the first, last,
or all Stages.

Given a matching Task, current candidate, existing target Stage identities,
and expected Task revision N, P7 MAY atomically publish:

```text
Task READY_FOR_REVIEW → IN_PROGRESS
each target Stage COMPLETE → IN_PROGRESS
revision N → N+1
```

This is not generic READY reopening authority. A stale, malformed,
wrong-Task, candidate-mismatched, empty-target, nonexistent-target, or
capability-escalating handoff MUST NOT mutate the Task or any Stage. P8 does
not write or reopen the Task; P7 consumes the handoff and uses §31 conditional
publication.

On target-Stage reopen, the prior current `SATISFIED` completion decision
MUST cease to be current authority. The same atomic publication replaces it
with an `UNKNOWN` repair-reopen decision and records the fixed `supersedes`
summary of the prior decision. This preserves that the Stage was complete for
C1 while making clear that the old decision cannot prove the repair
lifecycle or a later C2.

The same reopen publication MUST replace the current
`task_completion_decision` with an `UNKNOWN` repair-reopen Task decision and
MAY retain its bounded `supersedes` summary. Thus the old C1 Task decision
cannot immediately restore READY before repair and current-candidate
re-evaluation.

A later Agent MUST be able to reconstruct the open Repair from the Task Book
and project-local supporting state without chat history. Temporary Repair
coordination MAY live at `.scaffold/runtime/repair-state/<task-id>.yaml`.
That file is not a fourth canonical development record.

P8 MAY name a target Stage only when the blocker deterministically maps
through current Task `execution_binding.kind: test_profile`. Equal
requirement and profile names MUST NOT manufacture that mapping.

---

## 11. TASK_COMPLETE and READY_FOR_REVIEW

**TASK_COMPLETE** is a **derived** condition. It MUST NOT be stored as a fifth Task status.

For a standard Task Book:

```text
TASK_COMPLETE  =  all required Task stages are COMPLETE
```

`TASK_COMPLETE` is only the structural aggregation of required Stage status
values. Because a Stage may remain `COMPLETE` while its prior decision is
stale under §8.4.2, TASK_COMPLETE alone does **not** imply current-candidate
Stage acceptance, current Task acceptance, `READY_FOR_REVIEW`, final
task-level tests accepted, TEST_COMPLETE, Structural Review pass, submission
authorization, or S10 readiness.

**READY_FOR_REVIEW** (persisted Task `status`) requires:

```text
all stages COMPLETE
+ every Stage completion_decision is SATISFIED and current for the actual candidate
+ task-level final required tests satisfy their defined acceptance conditions
+ task_completion_decision is SATISFIED and current for the actual candidate
+ no unresolved required blocker
```

MUST NOT mark `READY_FOR_REVIEW` merely because final tests **ran** or because
all Stage decisions and final Tests are satisfied while the current Task
Completion Decision is `UNKNOWN` or `UNSATISFIED`. MUST NOT persist a
redundant `acceptance_met` boolean; the structured
`task_completion_decision` supplies reconstructable Task-acceptance authority.

Every Stage decision relied upon for READY, including a
non-target Stage left `COMPLETE` during repair, MUST be current for the actual
candidate. A non-target Stage need not be blindly reopened, but its stale C1
decision cannot support READY on C2; P7 must revalidate it under §8.4.2 or
keep the Task non-ready. The Task Completion Decision must likewise be
re-established as current and `SATISFIED` for C2.

READY_FOR_REVIEW is **not** submit authorization and MUST NOT start S10 durable finalization or Push (Constitution).

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
| `ABORTED` | No trustworthy complete Session-S1 exists. Not acceptance of current bytes. |

```text
OPEN → SEALED
OPEN → ABORTED
```

MUST NOT create `SUBMITTED` as a Session state. Successful S10 durable finalization causes **cleanup**, not another durable Session transition.

A SEALED session remains locally available until successful Submit cleanup (or explicit cancel/stale cleanup). It MUST NOT be silently deleted while Submit is incomplete or blocked.

ABORTED sessions MUST NOT be used as DEVELOP_KNOWN evidence. They MAY remain until explicit cleanup so the abort is inspectable.

Abort means this Session is not trustworthy as a completed Develop result.
It does NOT mean successful `observed_success` mutations never occurred, that
current workspace bytes are accepted, or that unexplained drift may be
forgotten (FA2-FND-005). ABORTED `observed_success` MAY remain attribution.
When that attribution is bound to the same Task, the path, the live byte
state, and a continuous later chain, Submit S2 records it as
`ABORTED_ATTRIBUTED`. That class is not `DEVELOP_KNOWN` and is not
ordinary inherited baseline. A matching path or hash alone does not
establish it. Pending authorization is not upgraded to provenance. Candidate acceptance
does not occur. Abort MUST remain an escape path: persist unresolved physical
truth, then proceed. Drift MUST NOT make abort impossible.

---

## 16. Session-S0 / Session-S1 / Observed-S2

Two evidence kinds MUST stay distinct:

| Kind | Answers | Must not be treated as |
| --- | --- | --- |
| **Workspace boundary overlay** | Which paths already differed from the Session baseline at a Session boundary? | Proof that Develop produced those paths |
| **Develop-touched manifest** (`files.yaml`) | Which paths did this Develop execution explicitly touch? | A whole-workspace inventory |

**Boundary observation ≠ Develop attribution.** An ambient overlay change MUST NOT be treated as if Develop produced it.

Session-S0 / open-inventory are physical starting observation, not
acceptance. Opening a Session MUST NOT mint a new accepted anchor, erase
durable unexplained drift, or convert unexplained bytes into ordinary
inherited baseline (FA2-FND-005).

MUST NOT snapshot the whole project. Overlays record only paths that **differ from the Session baseline**, where the host can honestly observe them.

### 16.1 Session-S0 (start)

Develop MUST NOT assume a clean tree.

Session-S0 is physical starting observation, not acceptance. Opening a
Session MUST NOT mint a new accepted anchor.

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
| `mutation_state` | `observed_success` when a successful observation enriched the row; `reconciled` when physical reconciliation wrote the row. Both are legitimate physical attribution when `after_digest` matches live bytes. Hook provenance is not required. |
| `patch_ref` | Optional relative patch file |
| `stage_ids` | Relevant Stage(s), if a Task Book exists |

MUST NOT store huge file bodies in the manifest.

`mutation-attempts.yaml` is not a canonical record and is not Session
authority. Legacy files MAY remain readable. Unresolved `authorized_pending`
rows MUST NOT block seal.

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

A durable unexplained-drift fact for the path MUST NOT become
`PREEXISTING_CHANGE` / `inherited_baseline` merely because later Session
overlays still show the same bytes, or because an earlier contradicting
Session was aborted or cleaned up (FA2-FND-005).

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
- S0 dirty, never Develop-touched, S2 still equals that S0 state → `PREEXISTING_CHANGE` possible only when no durable unexplained-drift fact contradicts that inference
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

Shared: **YES**. Durable after successful Submit-S10 finalization: **YES**.

Generated/finalized by Submit from:

```text
REVIEWED CANDIDATE DIFF
+ final review
+ final test evidence
+ knowledge consistency state
```

MUST NOT be generated merely from Agent memory, Task Book claims, or Develop Session claims.

Repository/workspace reality remains authority for the exact physical Diff. On an SCM host, the Commit Diff includes the Change Record artifact. Change Record is a **compact durable summary**, not a second diff store.

---

## 22. Change Record schema

A Change Record MUST be capable of representing:

| Concept | Purpose |
| --- | --- |
| `record_type`, `schema_version`, `record_id`, `created_at` | Header. `updated_at` only while still a **candidate** being regenerated. |
| `summary` | Concise human summary |
| `base` | Final **pre-S10** parent/baseline or project-defined base (known before durable finalization; SCM-agnostic) |
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

MUST NOT persist `status: submitted` (or equivalent) before successful S10 durable finalization.

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

`path_summary` describes the **REVIEWED CANDIDATE DIFF** (§23). It MUST NOT recursively count or list its own `.scaffold/changes/<change-id>.yaml` as part of the change set it summarizes. The complete S10-finalized result still includes that artifact/content; on SCM hosts the Commit Diff includes it. Repository/workspace reality remains authority for the full physical Diff.

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
| **S9 FINALIZATION BUNDLE** | The exact deterministic Change Record plus zero or more deterministic support artifacts required solely to keep durable references in that Change Record resolvable after ordinary runtime expiry. |
| **S10 FINALIZATION CANDIDATE** | The reviewed candidate **plus** the permitted S9 Finalization Bundle in the representation P8 will durably finalize. On SCM hosts this is the exact Commit candidate tree. |

```text
REVIEWED CANDIDATE DIFF
  → Submit-S9 finalize Change Record into .scaffold/changes/
  → authority owner materializes any required deterministic support artifacts
  → S10 FINALIZATION CANDIDATE = reviewed candidate + exact bundle
  → Submit-S10 Commit / Durable Finalization
```

MUST NOT create the Change Record **after** S10.

The Change Record `path_summary` describes the **REVIEWED CANDIDATE DIFF**. It MUST NOT recursively include itself.

Support artifacts in the S9 Finalization Bundle are not canonical development
records. Each support artifact MUST:

- be deterministically derivable from authority or Evidence already validated
  before S6 and from the exact durable references selected for the Change
  Record
- add no business/source intent or substantive result not present in that
  reviewed truth
- be necessary for durable resolution of a reference in that exact Change
  Record
- be materialized by the phase that owns its schema, storage, and resolution
- occupy an already-authorized durable project boundary and satisfy its
  existing ownership rules
- preserve the candidate binding, provenance, and integrity required by its
  owning phase
- be included in the exact S10 finalization candidate

For P6 Test Evidence, P8 MAY request materialization using validated opaque
Evidence references. P6 owns the physical representation and public resolver;
P8 MUST NOT construct Test Evidence storage internals. The Change Record MUST
use the public P6 locator protocol. P6 MUST retain only the minimal
report/Evidence/integrity material required for durable resolution, and the
locator MUST remain P6-resolvable without `.scaffold/runtime/`.

The permitted Finalization Bundle is the only additional S9 exception. Any
Submit-S9 mutation outside that exact deterministic bundle, or any support
content that cannot be deterministically derived as required above, is **not**
exempt from candidate-bound review and MUST return through S3–S6. Submit-S9
MUST NOT mutate Task Books (see §28.3).

If the reviewed candidate **materially** changes before retry (including after Submit-S7/S8 sync): the Change Record MUST be regenerated or revalidated **before** the next S10 attempt. A Change Record describing Candidate A MUST NOT be durably finalized with Candidate B.

If only the S10 attempt failed and the candidate record and support-artifact
representations are unchanged: the same Finalization Bundle MAY be retried.

---

## 24. Candidate vs durable semantics

Publication is **contextual**. There is no second operation solely to flip a status field.

| Context | Meaning |
| --- | --- |
| S9 Finalization Bundle exists but authoritative S10 success has **not** occurred | **Candidate** Change Record and candidate-only support artifacts |
| The same S9-finalized logical content/representation is included in a **successful** S10 durable finalization | **Durable as-built** Change Record and durable referenced support artifacts |

**“Same bytes”** means the exact Change Record content representation **selected/staged for the SCM commit after** repository-configured normalization / clean filtering (P2 already recognizes CRLF/LF and repository text policy).

It does **not** require raw Windows working-tree bytes to equal the committed blob bytes when the SCM normally normalizes text.

| Host | Candidate identity |
| --- | --- |
| SCM with text normalization / clean filtering | Staged representation after that filtering |
| SCM without such filtering | The finalized serialized record bytes |
| No SCM | The project-defined finalized record representation (P8) |

The candidate Change Record or support artifacts MUST NOT be rewritten after
S10 merely to become “submitted” or “durable.” MUST NOT invent a second
post-finalization mutation. This contract does **not** design Git-specific
runtime filtering or the no-SCM publication mechanism.

If S10 fails or is interrupted: the record and prepared support artifacts
remain candidate-only. They MUST NOT be described as successfully submitted
history or durable Evidence, and deterministic cleanup or recovery is
required. Temporary coordination state MAY live under `.scaffold/runtime/`,
but it is not durable Evidence authority.

This avoids lying if durable finalization fails, avoids a self-referential Commit SHA on SCM hosts, and avoids a second content mutation after S10.

For an SCM host with Commit capability, S10 success is the successful Commit
containing the exact Finalization Bundle. A Change Record that points to a
tracked support artifact absent from that Commit tree is not validly
finalized. For a no-SCM host, S10 success is a P8-defined **atomic or
conflict-detectable durable finalization/publication** of the same logical
bundle. It MUST be durably distinguishable after restart, MUST NOT pretend a
Git/SCM Commit occurred, and MUST NOT create false submitted history on
failure or interruption. P8 owns the concrete recoverable success
marker/publication mechanism.

Before S10 success, the bundle remains candidate/not-yet-durable. After S10
success, the same S9-finalized logical content becomes durable as-built history
and referenced durable support; no second content rewrite is required.
Session cleanup follows that successful durable finalization, not Push and not
an invented revision.

---

## 25. No final Commit SHA

The Change Record MUST NOT contain the final Commit SHA (or equivalent SCM identifier) of the **Commit that contains that Change Record**.

Reason: self-reference / circular finalization.

Git/SCM history associates the record with the Commit.

The record MAY contain the final candidate’s **base / parent** baseline, because that is known before Commit.

MUST NOT invent a post-Commit second mutation merely to insert the Commit SHA.

---

## 26. Change Record immutability

Once a Change Record becomes durable as-built through successful S10 finalization, it SHOULD be treated as historical / immutable.

Future corrections SHOULD normally create a **new change** and/or a **new corrective Change Record**, rather than rewriting old submitted history.

History rewriting remains explicit exceptional human/SCM action, not normal Scaffold behavior.

Candidate files MAY be replaced before successful S10 durable finalization.

---

## 27. Human authorization is not a record permission bit

Git Commit and Git Push require a **current explicit user instruction**. That
instruction is Agent execution policy, not a persisted record bit.

P3 MUST NOT create a reusable YAML boolean such as `submit_authorized: true`
that an Agent can persist and later reuse as authority to `git commit` or
`git push`.

Submit S1-S12 MAY finalize Scaffold records without that instruction. A record
MAY retain a **non-authoritative historical statement** that Commit or Push
later occurred; Git remains physical authority for those facts.

The same principle applies to Adoption Plan apply snapshots (P1): persisted
history ≠ standing permission.

Logical commit decomposition for a compound Task is **version-history planning**.
It is not a fourth canonical development record, not Stage identity, and not
Git Commit authority. During development the Agent MUST maintain the grouping
from Task / Stage / Session / Diff / Change Record facts. After the user
authorizes Commit, Git is physical authority. If the grouping cannot be
reconstructed uniquely from those facts, the task-completion report carries
the recommended plan until Commit; that report is not a grant.

---

## 28. Task / Session cleanup and historical Task Books

### 28.1 Develop Session cleanup

Constitution: after successful Submit-S10 durable finalization, the Develop Session **MUST** be cleaned up. P3 does not weaken that.

```text
Develop starts            → Session OPEN (Session-S0)
Develop ends normally     → SEALED (Session-S1)
Submit incomplete/blocked → retain
Successful authorized S10 durable finalization
  + durable Change Record established
                          → Submit-S12 MUST clean corresponding
                            completed SEALED Develop Sessions
Push                      → NOT required for cleanup
```

In this storage model, cleanup means **deleting** the corresponding local Session directories.

OPEN Sessions MUST NOT be silently deleted. If an OPEN Session unexpectedly conflicts with finalization, surface it for P8 / human handling rather than pretending cleanup succeeded.

If mandatory post-S10 cleanup fails because of a local operational error: report the cleanup failure and retry cleanup. MUST NOT rewrite or invalidate the successful durable finalization solely for that reason.

If the task is **CANCELED**: explicit cleanup MAY remove Sessions. That is not the successful-S10 rule.

A stale detector MAY **prompt** cleanup of stale/ABORTED Sessions. MUST NOT silently delete an **OPEN** Session. Temporary memory MUST NOT accumulate unboundedly (Constitution principle 10).

ABORTED Sessions MAY be removed by explicit cleanup or stale prompt; they MUST NOT be treated as DEVELOP_KNOWN evidence while they remain.

### 28.2 Task Book after successful submission

After successful S10 durable finalization represented by a Change Record:

- the Task Book becomes **historical task evidence**
- it SHOULD normally stop mutating
- lasting role: what was intended, how work was staged, what task-level acceptance was reached
- Change Record describes what actually shipped in the **REVIEWED CANDIDATE DIFF**
- repository/workspace reality and the host’s S10 success evidence describe the exact finalized result (including the Change Record artifact/content)

MUST NOT rewrite the Task Book to pretend unplanned final changes were always part of the original plan.

Historicity is **contextual**: a Task Book is historical when a **durable as-built** Change Record lists its `record_id` **and** authoritative S10 success evidence establishes that durable finalization. Until S10 succeeds, `READY_FOR_REVIEW` is **not** submitted history.

No Task-side Change Record back-reference is required or permitted as a contract field.

### 28.3 Session IDs on the Task Book (no Submit-S9 mutation)

`develop_session_ids` MAY remain on an active Task Book. They MUST always be:

- operational / advisory
- non-authoritative
- **not required** for interpretation
- allowed to become non-resolvable after runtime cleanup

After successful S10, a historical Task Book MUST already be understandable without `runtime/`. Durable provenance lives in the Change Record as a compact summary. MUST NOT copy Session hashes or patches into the Task Book.

If P8 chooses to remove or compact operational Session IDs, that mutation MUST occur **before** the candidate is finalized through Submit-S3 / S4 / S5 / S6 review.

Submit-S9 MUST NOT mutate the Task Book merely for:

- Session reference compaction
- a Change Record back-reference
- cosmetic historical cleanup

This preserves candidate-bound S6 review of the exact candidate that S10 may later finalize.

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

On resume, P5 MUST revalidate: Plan identity, host state, and whether an exact-plan apply request still matches. P1 remains authoritative. If checks fail: re-discover → re-plan → exact-plan apply.

### 29.2 Adoption cleanup

| Event | Fate |
| --- | --- |
| Successful activation | Corresponding Adoption Session → cleanup |
| Blocked / interrupted | Retain enough to resume |
| Abandoned | Explicit cleanup MAY remove it |

MUST NOT silently delete an active/recoverable adoption state.

---

## Migration Execution operational artifact

A migration MAY use a bounded operational **Migration Execution** artifact/session so P5 can reason about interruption after Apply begins. It is **not** a fourth canonical development record, not a Change Record replacement, and not development handoff history. P5 owns its exact path/schema and runtime use; fresh persistent Migration application MUST be initiated through Task-bound Develop authority without creating a Migration Record. Understand compatibility may plan and route, and MUST resume an already-begun Execution through P5 recovery. It MUST NOT start a fresh persistent apply from Plan-only preview. Develop application of that Plan is Task-bound: the machine binding MUST name the exact `plan_id`, `plan_digest`, `task_id`, `task_revision`, and current `candidate_digest`. Human approval is not one of those predicates. The Execution MAY record a supporting `develop_binding` for recovery inspection. It remains an operational artifact, not Task Book / Develop Session / Change Record / Migration Record authority. Any representation MUST remain within P2-approved storage/ownership boundaries and survive process restart while recovery may be required.

Minimum representation obligations:

- migration plan identity/content binding
- source host state/fingerprint
- source `skills.lock`
- relevant source record/metadata generation
- target intent
- approved mutation envelope
- current execution state
- approved actions/checkpoints completed and remaining
- observed expected state needed for recovery
- rollback/recovery information where the plan defines it
- timestamps and concise blocker/error facts

It MUST NOT persist human approval as a reusable permission bit. A remembered approval observation is revalidation input only.

Frozen execution states:

| State | Representation meaning |
| --- | --- |
| **PREPARED** | Execution context is bound to the plan, source state, lock, generations, target intent, and mutation envelope. This does **not** mean apply is currently authorized. Before first mutation, bindings MUST be revalidated and a valid current Plan+Task+candidate machine binding MUST exist. |
| **APPLYING** | Persistent mutation has begun. Checkpoints MUST show completed/remaining approved actions and enough observed expected state for deterministic recovery reasoning. Universal rollback is **not** required. |
| **VALIDATING** | Approved mutation actions ran, but required post-apply validation has not established successful migration. Normal operation MUST NOT treat migration as complete. |
| **COMPLETED** | Approved actions and required validation succeeded. P5 may then update/clear applicable P2 maintenance/recovery state and clean temporary execution state according to its lifecycle. |
| **RECOVERY_REQUIRED** | Partial/uncertain mutation, unexpected divergence, failed coherence validation, or an unsafe-to-decide restart prevents proof of safe completion. P2 `RECOVERY_REQUIRED` semantics apply where host consistency is uncertain. |
| **ABORTED** | Valid only when no persistent migration mutation occurred, or every applied mutation is proven safely reverted/neutralized and the host is coherent. Unknown partial mutation MUST be `RECOVERY_REQUIRED`, not ABORTED. |

Conceptual transitions include:

```text
PREPARED → APPLYING → VALIDATING → COMPLETED
PREPARED → ABORTED
APPLYING / VALIDATING → RECOVERY_REQUIRED
RECOVERY_REQUIRED → APPLYING or VALIDATING
RECOVERY_REQUIRED → ABORTED only after proven safe reversion/neutralization
```

Recovery MUST observe the actual host, read checkpoints, and compare both against the approved mutation envelope. A provable expected prefix/checkpoint MAY be resumed by P5 according to the approved recovery protocol. Expected Apply actions moving the host through approved checkpoints do **not** by themselves invalidate approval applicability.

Material unexpected divergence, or a changed remaining mutation envelope/assumption, invalidates the prior Plan applicability: re-evaluate compatibility, update/regenerate the plan, and apply the current Plan under the current Task/candidate machine binding before further mutation.

The artifact MUST be retained while interruption/recovery reasoning is required and cleaned only according to a lifecycle that does not erase uncertain partial mutation. It MUST NOT duplicate the final submitted-change role of Change Record.

---

## 30. Historical-reference behavior

| From | To | Survival |
| --- | --- | --- |
| Task Book → Develop Session | Temporary operational / advisory | MUST NOT be required for interpretation, including after Session cleanup |
| Change Record → Task Book | Durable (the only durable association direction) | Task IDs remain; Task files remain historical |
| Change Record → Test Evidence | Durable / externally resolvable as P6 defines | Opaque locator; P6 resolution remains possible after ordinary `.scaffold/runtime/` expiry |
| Change Record → Develop Session | MUST NOT require Session survival | Compact summary only |

Cross-record references MUST be stable, explicit, and non-circular where practical.

Change Record MUST NOT require Develop Session directories to survive.

Task Book MUST NOT require deleted Sessions to survive after submission.

A durable Change Record's P6 Evidence locator MUST NOT require its originating
`.scaffold/runtime/test-runs/` directory to survive. The S9 Finalization Bundle
MUST contain the minimal deterministic P6-owned durable representation required
to preserve candidate binding, provenance, integrity, and resolution. It MUST
NOT copy full logs or Evidence bodies into the Change Record, and it does not
promote Test Report to a canonical development record.

A later Agent with durably finalized `tasks/` + `changes/` and the host’s authoritative S10 success evidence MUST be able to interpret intent vs as-built **without** `runtime/`.

---

## 31. Concurrency / `record_revision`

Task Book is a **shared mutable** record during development. Multiple Agents MAY interact with it.

`record_revision` is a required stale-write token, but a read/re-read/write sequence alone is **not** sufficient concurrency control.

Every semantic Task Book mutation MUST use:

```text
expected revision N
+ atomic conditional publication
→ publish revision N+1 only if the current published revision is still N
```

Two writers based on the same revision N MUST NOT both successfully publish different revision N+1 states. A successful mutation increments the revision exactly once.

P3 does not freeze one implementation mechanism. P7 MAY use an atomic compare-and-swap backend, per-record file lock or serialization guard, single-writer coordinator, transactional storage, or another conflict-producing conditional publication mechanism. If compare-and-swap is unavailable, writers MUST be safely serialized. If safe serialization or conditional publication cannot be established, the mutation MUST **BLOCK** or surface a conflict; it MUST NOT silently overwrite another successful mutation.

On conflict, the writer MUST re-read the current Task Book, reconcile/re-plan as appropriate, and retry as a **new mutation** against the new expected revision.

P3 does not require a central or distributed lock service. This MUST NOT be interpreted to forbid local/per-record synchronization needed to satisfy the atomic conditional-publication invariant. Implementations MUST NOT assume one Agent.

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

Change Record remains valid. Before S10 success it is candidate-only; after S10 success the same S9-finalized logical content is durable as-built history.

P8 owns the no-SCM atomic or conflict-detectable finalization/publication mechanism and recoverable durable success evidence. S10 success MUST be distinguishable after restart. Failure/interruption MUST NOT create false submitted history or trigger submitted-history cleanup. P3 MUST NOT pretend a Commit or Commit SHA exists.

Session cleanup still requires **successful authorized durable finalization** of the Change Record as defined by P8 for that host — not Push and not an invented revision.

---

## 33. Ownership

P2 left detailed Task/Change ownership to P3. P2’s three modes remain the **only** three: GENERATED, MANAGED, HUMAN_OWNED. MUST NOT invent a fourth P2 ownership mode.

| Record | Ownership |
| --- | --- |
| **Task Books** | **GENERATED** durable record artifacts. Mutable according to the Task lifecycle; that does not change the ownership mode. |
| **Change Records** | **GENERATED** durable record artifacts finalized by Submit. Immutable after successful S10 durable finalization; that does not change the ownership mode. |
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
| Durable S10-finalized Change Records | MUST NOT be routinely deleted |
| Historical Task Books represented by durably finalized changes | SHOULD NOT be routinely deleted |
| Temporary runtime Sessions | Cleaned by lifecycle rules (§28, §29) |
| Draft / canceled Task Books with no durable historical value | MAY be removed only through **explicit** project/user action |

MUST NOT silently clean history. MUST NOT accumulate unbounded session logs (Constitution principle 10). Stale OPEN Sessions: prompt, do not silent-delete.

---

## 35. Cross-phase responsibilities

| Phase | Owns |
| --- | --- |
| **P3** (this contract) | Data/lifecycle contracts: schemas, IDs, states, provenance classes, cleanup invariants, candidate/durable publication |
| **P4** | Skill package, Skill routing, Rule loading, `skills.lock` contents, compatibility/migration protocol |
| **P5** | Adoption execution, Understand Full / Refresh / Compatibility, Adoption Session **operational use**, Migration Execution operational use |
| **P6** | Test Report/Evidence schema, test execution, Test Matrix, Evidence storage/resolution, and deterministic materialization of minimal durable Test support artifacts requested through validated opaque references |
| **P7** | Task-driven Develop behavior; creating/updating Task Books in practice; creating/sealing Develop Sessions; Repair Mode |
| **P8** | Observed-S2; provenance classification **execution**; Structural Review; Knowledge Consistency; Test Completeness; candidate-bound human authorization; Change Record and Finalization Bundle orchestration; SCM Commit or no-SCM durable finalization; optional Push; Session cleanup |

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
- central/distributed lock service, database mandate, agent-memory service, or changelog generator (local/per-record synchronization needed by §31 remains allowed)

---

## 37. P3 specialization of P0 advisory provenance semantics

P0 remains authoritative. Constitution §7 says Submit **MAY** classify paths using the four named classes and forbids `HUMAN_CHANGE`. It does **not** state that the list is exhaustive, and it requires Submit to work with no Session.

P3 only makes those advisory mechanics precise:

1. **`UNATTRIBUTED`** is the honest fallback when Session/baseline/overlay evidence cannot safely establish a tighter class (including human-only Submit).
2. **`MIXED_CHANGE`** includes “already dirty, then Develop edited” and “Session gap,” as well as Develop-touched paths whose Observed-S2 diverges from Session-S1, so they are not mislabeled `DEVELOP_KNOWN` or `PREEXISTING_CHANGE`.
3. **`PREEXISTING_CHANGE`** and **`POST_DEVELOP_ADDITIONAL`** require the Session boundary-overlay evidence in §16 and §19. Insufficient evidence → `UNATTRIBUTED`.
4. Task “completed / historical” after success is **contextual** (durable Change Record listing the Task Book + authoritative S10 success evidence), not a pre-S10 `SUBMITTED` field.

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
    completion_decision:
      stage_id: stage-1
      candidate_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      outcome: SATISFIED
      basis:
        - kind: repository_observation
          summary: Header writer emits the required checksum field.
        - kind: test_evidence
          summary: Required checksum-write verification passed.
          evidence_ref: { locator: "opaque-p6-locator-1" }
      rationale: Current implementation observation and required P6 Evidence satisfy this Stage.
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
    completion_decision:
      stage_id: stage-1
      candidate_digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
      outcome: SATISFIED
      basis:
        - kind: repository_observation
          summary: Current config contains the corrected display name.
        - kind: test_evidence
          summary: Current config parse verification passed.
          evidence_ref: { locator: "opaque-p6-locator-3" }
      rationale: The observed correction and P6 Evidence satisfy the Stage criterion.
    result_summary: Typo corrected; parse check passed.
task_completion_decision:
  candidate_digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  outcome: SATISFIED
  basis:
    - kind: stage_decisions
      summary: Every required Stage decision is current and SATISFIED.
    - kind: final_test_evidence
      summary: Current final configuration verification passed.
      evidence_ref: { locator: "opaque-p6-locator-3" }
  rationale: Current Stage and final Evidence satisfy the declared Task acceptance.
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
| **A** Simple one-stage typo/config task | Same Task Book schema; one Stage; small scope; Task-level `acceptance` MAY match the Stage `acceptance`, but the two decisions remain distinct. READY_FOR_REVIEW requires that Stage COMPLETE with a current `SATISFIED` Stage decision, planned final tests accepted, and a current `SATISFIED` Task Completion Decision. |
| **B** Multi-stage feature task | Ordered stages; a later Stage MAY stay PENDING while earlier work is IN_PROGRESS; TASK_COMPLETE only when **all** required stages COMPLETE. |
| **C** Stage test fails, later passes | Failed required test ⇒ Stage stays non-complete (typically IN_PROGRESS). After fix + tests meet acceptance ⇒ Stage MAY become COMPLETE. Execution alone never completes the Stage. |
| **D** All stages complete but final tests fail | TASK_COMPLETE holds; `status` MUST NOT become READY_FOR_REVIEW; remain in Develop ↔ Test. |
| **E** Task canceled | `status: CANCELED`. Not READY_FOR_REVIEW. Sessions MUST NOT be silently deleted; explicit cleanup MAY remove them. No fake Change Record. |
| **F** Develop starts from clean working tree | Session-S0 workspace overlay empty (or coverage complete with no dirty paths). Touched paths MAY become DEVELOP_KNOWN if chain and Observed-S2 match. |
| **G** Unrelated dirty file exists before Develop | Recorded in Session-S0 workspace overlay. PREEXISTING_CHANGE only if Develop never touches it **and** Observed-S2 still matches that S0 pre-existing state **and** no durable unexplained-drift fact contradicts the inference (FA2-FND-005). If S0 and S2 differ without Develop coverage ⇒ not pure PREEXISTING; use a provable class or UNATTRIBUTED. |
| **H** Develop edits a file that was already dirty | `was_preexisting_dirty: true`. Final path ⇒ MIXED_CHANGE. MUST NOT be DEVELOP_KNOWN. MUST NOT claim the extra portion is human. |
| **I** New file appears after Session-S1 | POST_DEVELOP_ADDITIONAL only if: not pre-existing dirty; Develop did not touch it; Session-S1 overlay shows still baseline-equivalent/absent at Develop end; Observed-S2 shows the addition. MUST NOT infer POST from “not in S0 and exists at S2”. If S1 coverage is partial/unavailable ⇒ UNATTRIBUTED. |
| **J** Develop-edited file changes again after Session-S1 | Observed-S2 ≠ Session-S1 ⇒ MIXED_CHANGE, not POST_DEVELOP_ADDITIONAL. |
| **K** Two Sessions touch the same file with a continuous chain | Previous Session-S1 after-state = next before-state; latest Session-S1 = Observed-S2; not preexisting dirty ⇒ MAY be DEVELOP_KNOWN. |
| **L** Two Sessions have an unexplained state gap | Path cannot be DEVELOP_KNOWN ⇒ MIXED_CHANGE if Develop touched it. |
| **M** Human-only; no Task Book and no Session | Submit still starts. TASK_COMPLETE = NOT APPLICABLE. Provenance typically UNATTRIBUTED. MUST NOT synthesize a Task Book. |
| **N** Task exists but manual/external changes exceed Task scope | Task Book MUST NOT be silently rewritten. Extra paths still count in the real Diff. Provenance classes apply. P8 reviews/resolves. |
| **O** Several Task Books enter one Submit candidate | One Change Record MAY list multiple `task_book_ids`. Each listed Task Book SHOULD not be reused afterwards once that Change Record is durable. |
| **P** Submit sync changes the final Diff after a Change Record candidate existed | Candidate A record MUST NOT ship with Candidate B. Regenerate/revalidate Change Record before the next S10 attempt. Prior S6 review of Candidate A does not follow Candidate B (Constitution). |
| **Q** S10 fails after Change Record was finalized | Record remains a **candidate**. MUST NOT be described as submitted history. No SUBMITTED field may lie. Retry the same finalized representation if the reviewed candidate is unchanged; otherwise regenerate. Completed Develop Sessions remain retained. |
| **R** SCM Commit succeeds but Push is not authorized | Change Record representation in the Commit is durable as-built. Submit-S12 MUST clean corresponding completed SEALED Sessions. Push remains optional and separately authorized. |
| **S** Successful S10 cleans Develop Sessions | Submit-S12 MUST delete corresponding completed SEALED Session directories. Task Book is not mutated at S9 for compaction. `develop_session_ids` if still present are advisory and not required. Push not required. |
| **T** Binary/large file touched by Develop | Manifest + digests + kind/class. MUST NOT store the body. Provenance still works from digests. |
| **U** Sensitive local file touched | MUST NOT store a content patch. Metadata/digest only if safe. Not a secrets product. |
| **V** External CI/human Test Evidence referenced | Opaque `evidence_ref.locator` only. P6 owns schema/resolution. MUST NOT copy CI logs into Task/Change records. |
| **W** Stale/open Develop Session exists | MUST NOT silently delete OPEN. Stale detector MAY prompt. OPEN/ABORTED Sessions do not complete a DEVELOP_KNOWN chain. |
| **X** Adoption interrupted and resumed | Session retained (`INTERRUPTED`/`BLOCKED`) with baseline, plan digest, steps, mutations, pending validation. P5 revalidates Plan identity, host, and exact-plan apply request. `observed_approved` is not standing permission. |
| **Y** Historical Task Book after Session cleanup | Task Book (Session IDs advisory / not required) + Change Record + repository Diff suffice. MUST NOT require `runtime/develop-sessions/` to understand history. MUST NOT depend on an S9 Task Book mutation. |
| **Z** Two Agents update the same Task Book from revision N | Atomic conditional publication permits at most one N→N+1 result. The other writer gets conflict/block, re-reads, reconciles/re-plans, and retries as a new mutation. Re-read/re-read/write without CAS or serialization is insufficient. |
| **AA** No SCM project | `baseline.kind: none` or `unavailable`. No invented SHA or Commit. Digests still assist provenance. P8 provides atomic/conflict-detectable durable S10 finalization whose success survives restart; failure does not create submitted history or cleanup Sessions. S11 is N/A. |
| **AB** Change Record would otherwise need its own final Commit SHA | Forbidden. Record stores pre-Commit `base` only. SCM history binds the Commit to the record. |
| **AC** Unplanned extra file neither Session-covered nor clearly pre-existing | UNATTRIBUTED. Insufficient S0/S1 boundary evidence to prove PREEXISTING or POST. Still part of actual Diff. Not an error. Timestamps/mtimes alone MUST NOT promote it to POST. |
| **AD** Task Book says tests complete but actual Diff adds another module | Planned Task tests ≠ TEST_COMPLETE. Submit derives required tests from actual Diff + `tests.yaml` + Task Book + policy. Extra module still requires its tests. |
| **AE** Migration Apply interrupted after persistent mutation begins | Retain Migration Execution checkpoints; use RECOVERY_REQUIRED unless safe completion or coherent reversion is proven. Resume only from a provable approved checkpoint/prefix. Unexpected divergence invalidates approval applicability and requires re-evaluation, updated plan, and human re-approval. |
| **FND-E01** Deterministic P6 support required by an exact Change Record reference | Minimal support derived solely from pre-S6 validated Evidence MAY join the S9 Finalization Bundle without a second S6 approval. |
| **FND-E02** S9 writes unrelated source, business, or configuration content | Outside the Finalization Bundle exception. Prior authorization is invalid; return through S3–S6. |
| **FND-E03** Proposed support bytes are not deterministically derivable from validated Evidence and exact Change Record references | Outside the exception; re-review and current authorization are required. |
| **FND-E04** Git S10 Commit omits a tracked support artifact referenced by the Change Record | The exact bundle was not finalized; fail closed. |
| **FND-E05** S10 fails or is interrupted after support preparation | Support remains candidate-only, is not durable historical Evidence, and requires deterministic cleanup or recovery. |
| **FND-E06** Runtime Test-run expires after durable S10 | The Change Record's public P6 locator remains resolvable from the minimal durable support representation. |
| **FND-E07** Finalization Bundle is introduced | Exactly three canonical records, four Skills, S1–S12, one candidate-bound S6 review, and the existing ownership modes remain unchanged. |
| **FND2-E01** Normal completion on candidate C | Current authoritative basis plus satisfied required Stage Test Evidence permits P7 to publish `IN_PROGRESS` → `COMPLETE` only with a `SATISFIED` decision for C through Task CAS. |
| **FND2-E02** Test passes while Stage acceptance is unknown | `TEST_PASS` is not acceptance; decision remains `UNKNOWN` and the Stage does not become `COMPLETE`. |
| **FND2-E03** Acceptance appears satisfied but a required Test fails | Required `FAIL` prevents Stage completion even when the completion decision is `SATISFIED`. |
| **FND2-E04** Completion decision is `SATISFIED` for C1 and candidate becomes C2 | The C1 decision is stale and cannot prove C2 Stage completion or Task readiness. |
| **FND2-E05** Subjective acceptance lacks human-observation authority | Decision is `UNKNOWN`; after valid P6 human-observation Evidence, P7 may represent a candidate-bound `SATISFIED` decision that cites its locator. |
| **FND2-E06** Every Stage is complete/current for C and final obligations hold | P7 may publish Task `IN_PROGRESS` → `READY_FOR_REVIEW` through §31 CAS only when every Stage decision and the Task Completion Decision are current/`SATISFIED` for C and final Task Test obligations are satisfied. If the Task decision is `UNKNOWN`, READY is forbidden even when all Stage decisions and final Tests are satisfied. This grants no Submit authorization. |
| **FND2-E07** READY Task receives a valid current Stage-targeted Submit repair handoff | P7 may atomically publish Task `READY_FOR_REVIEW` → `IN_PROGRESS`, target Stage `COMPLETE` → `IN_PROGRESS`, and supersede the old decision. |
| **FND2-E08** READY repair handoff has no deterministic Stage target | No Stage is guessed and no reopen occurs; routing remains explicitly unresolved. |
| **FND2-E09** Repair handoff has wrong Task, stale candidate, nonexistent target, malformed shape, or elevated capabilities | No Task or Stage mutation occurs. |
| **FND2-E10** Repair changes C1 to C2 | C1 Stage/Task decisions and Evidence cannot immediately restore READY; every relied-upon Stage decision and the Task Completion Decision must be current/`SATISFIED` for C2 and other current C2 obligations must be established. |
| **FND2-E11** A non-target Stage remains `COMPLETE` with a C1 decision | Its status records valid historical completion, but Task cannot return READY on C2 until P7 publishes a current C2 `SATISFIED` Stage decision or legally reopens/blocks that Stage, and the Task Completion Decision is also current/`SATISFIED` for C2. |
| **FND2-E12** FA2-FND-002 taxonomy and authority | Exactly three canonical development records, four Skills, unchanged four-value Task/Stage state sets, S1–S12, P3 CAS, P6 Evidence ownership, P7 Task mutation, P8 non-Task-write authority, and no new Submit authorization remain invariant. |
| **FND3-E01** A `SATISFIED` Completion Decision for substantive candidate C is stored in its containing Task Book | The current Task content's substantive authority projection is unchanged, so the single P6 candidate remains C and the stored decision does not immediately stale itself. Remaining on C does not prove the write was P3/P7 CAS-authorized. |
| **FND3-E02** Source/business content changes after Test or completion | The substantive candidate changes C→C2; old C Evidence and Completion Decisions are stale and cannot support completion or READY on C2. |
| **FND3-E03** Task acceptance, scope, baseline, Stage plan, requirement identity, or execution binding changes | This is a substantive Task authority change, not neutral lifecycle metadata. The P6 candidate changes and old candidate-bound authority cannot be reused. |
| **FND3-E04** Task `READY_FOR_REVIEW` and current decisions are stored without changing substantive Task authority | READY publication is representable: the current content remains on the same substantive candidate C and does not create impossible self-staleness. Remaining on C does not prove the write was P3/P7 CAS-authorized. |
| **FND3-E05** A candidate-neutral Task control-plane byte change exists in the Task Book | Git/no-SCM physical observation and Submit real Diff still see the complete change; neutrality affects only P6 candidate currentness, not review/provenance visibility, write permission, or publication authorization. |
| **FND3-E06** Task requirement `task-required/check-save` explicitly binds `test_profile: unit-save-check` | P7 may execute `unit-save-check` and attach only a P6 locator whose resolution preserves producing profile `unit-save-check` to that exact Task requirement; different IDs are expected and legal. |
| **FND3-E07** A fresh Test execution has no explicit Task execution binding | P7 does not attach a locator by equal names, sole-result inference, list order, or guessing; the Task requirement remains unresolved unless it already has an explicit legitimate Evidence locator. |
| **FND3-E08** An explicit binding names the wrong profile or its locator resolves to another profile | The mismatch cannot satisfy that requirement or any other requirement. |
| **FND3-E09** Project policy requires profile P while a Task declares requirement R | P and R remain separate obligation sets. Project profile completion does not erase or rename Task requirement R, and R does not redefine project-required profile P. |
| **FND3-E10** A Task requirement is satisfied by legitimate HUMAN, CI, or EXTERNAL P6 Evidence | The explicit opaque P6 locator may prove the requirement without a local automated profile binding or any requirement/profile string-equality rule. |
| **FND3-R01** Final Task bytes X are identical after P7 CAS publication and after a direct non-CAS write of the same bytes | P6 candidate identity is content-deterministic and remains the same; candidate neutrality is not conditioned on post-hoc writer/process knowledge. P3 CAS remains mandatory for authorized Task publication. **candidate-equivalent != publication-authorized.** Complete physical Diff remains visible. Substantive Task mutation remains candidate-changing. |
| **FND4-E01** Structural impact + no Knowledge Assessment | S4 is not PASS and routes to Understand. |
| **FND4-E02** SATISFIED assessment for current candidate C and exact impact I | S4 may PASS. |
| **FND4-E03** Assessment for C1 used after candidate becomes C2 | The C1 assessment is stale and cannot support C2. |
| **FND4-E04** Assessment candidate current but impact digest differs | blocked; old impact binding is unusable. |
| **FND4-E05** Assessment covers only a subset of required impacts | not PASS. |
| **FND4-E06** Assessment outcome UNKNOWN | blocked / Understand route; UNKNOWN remains UNKNOWN. |
| **FND4-E07** Assessment outcome NEEDS_HUMAN | explicit human blocker; S4 not PASS. |
| **FND4-E08** Runtime Knowledge Assessment artifact exists | P6 candidate digest is unchanged; the artifact is excluded through existing runtime exclusion. |
| **FND4-V01** Live Understand identity after FND-004 | The live package is no longer released `understand@2.0.0`; it is candidate `understand@2.1.0`. |
| **FND4-V02** SKILL.md and skill.yaml identity | They agree; the package remains VALID. |
| **FND4-V03** Live Understand package validation | VALID. |
| **FND4-V04** Established host expecting released Understand `2.0.0` | Live `2.1.0` evaluates `COMPATIBLE`, not `EXACT`; actual version is surfaced; `skills.lock` is unchanged. |
| **FND4-V05** Pre-adoption Bootstrap | Exact release-pinned Understand remains required; live `2.1.0` is not pre-lock compatible substitution. |
| **FND4-V06** Released `understand@2.0.0` | Does not represent FND-004 Knowledge Assessment / current-head semantics. |
| **FND4-C01** SATISFIED Assessment A then UNKNOWN B for the same C/I; Submit supplies A | A is superseded; S4 is not PASS. |
| **FND4-C02** Same setup; Submit supplies B | Outcome remains UNKNOWN; S4 is not PASS. |
| **FND4-C03** UNKNOWN A then SATISFIED B for the same C/I | B is current and may PASS; A remains superseded. |
| **FND4-C04** No explicit locator | P8 resolves the current head only and MUST NOT scan timestamps or record ids. |
| **FND4-C05** Historical artifacts exist but current head is missing or broken | UNKNOWN; P8 does not guess an Assessment. |
| **FND4-C06** Assessment bytes change after current-head publication while remaining schema-valid | Integrity mismatch; S4 is not PASS. |
| **FND4-C07** Current-head for C1 then candidate becomes C2 | The C1 head is stale and cannot PASS. |
| **FND4-C08** Candidate stays C; S3 impact set changes I1 → I2 | The I1 head cannot support I2. |
| **FND4-C09** Current-head runtime metadata is published or updated | P6 candidate digest is unchanged. |
| **FND4-C10** A later process reads project-local runtime state | It recovers the same current Assessment authority. |
| **FND5-E01** Unexplained W0→W1 then S1 abort then S2 open | The unexplained mutation remains durably unexplained. Abort MUST NOT launder unexplained drift. S2 MUST NOT convert it to `inherited_baseline`. |
| **FND5-E02** S1 `observed_success` A and B then abort | A and B remain attribution and MUST NOT become unexplained merely because S1 aborted. They are not `DEVELOP_KNOWN` and not accepted. |
| **FND5-E03** New Develop Session opens on current disk | Open snapshot is physical starting observation, not acceptance. MUST NOT mint a new accepted anchor. |
| **FND5-E04** Task B attributed mutation; later Task A Session sees those bytes | Host-level physical truth. MUST NOT introduce per-Task full-workspace accepted baselines. Task B's attribution MUST NOT become Task A rogue drift merely because Task A did not produce it. |
| **FND5-E05** Durable unexplained fact vs later sealed overlays | MUST NOT become `inherited_baseline` merely because the earlier contradicting Session was aborted or cleaned up. |
| **FND5-E06** Submit-S12 / normal Session cleanup | MUST NOT erase durable unexplained truth living outside ephemeral Session runtime. |
| **FND5-E07** Agent Develop window after FND-005 | No new normal-path Agent ceremony. MUST NOT require a longer abort/reopen ritual. |
| **FND5-E08** Human wants current unexplained bytes accepted without S10 | Generic human clear of unexplained bytes is forbidden. Out of scope. |
| **FND5-E09** Successful S10 | S10 remains the existing acceptance boundary; the new accepted anchor may retire prior drift. |
| **FND5-E10** Unexplained path X; legitimate mutation on unrelated path Y | Path-scoped Develop permissiveness does not deny Y automatically; Submit still sees unresolved drift. |
| **FND5-E11** Client lacks a pre-write hook and unexplained bytes reach disk | Later observation MUST still preserve the physical fact. MAJ-008 MUST NOT depend on solving MAJ-007. |
| **FND5-E12** no-SCM missing accepted anchor, or existing-host upgrade | UNKNOWN / fail-closed if no anchor. Do NOT fabricate an anchor. `inherited-at-initialization` exists ONLY for the one-time compatibility initialization of an existing established host. A durable initialization boundary is required. After that boundary, UNKNOWN / missing evidence / future divergence MUST NOT fall back to inherited-at-initialization. Post-initialization unexplained drift MUST NOT be downgraded to inherited-at-initialization. |
| **FND5-E13** Attribution appears for a path whose current bytes differ from the provenanced state | Current physical state / current bytes MUST be proven consistent with the durable provenance used. Historical provenance for a different byte/digest state MUST NOT clear a newer unexplained mutation. |

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
| P | READY_FOR_REVIEW requires current `SATISFIED` Stage and Task Completion Decisions plus accepted final Task tests |
| Q | Failed required tests do not complete a Stage |
| R | Simple task stays lightweight using the same schema |
| S | Multiple Sessions compose deterministically |
| T | Change Record never depends on retained Session files |
| U | Change Record is finalized at S9 before S10 |
| V | S10 failure/interruption does not create false submitted history |
| W | No final Commit SHA inside the same Change Record |
| X | No persisted boolean grants Submit authorization |
| Y | Successful authorized S10 + durable Change Record → Submit-S12 MUST clean corresponding completed SEALED Sessions; Push not required |
| Z | Task Book remains understandable after Session cleanup without an S9 Task mutation |
| AA | Runtime Sessions are local/temporary |
| AB | No chain-of-thought/chat logs are stored |
| AC | Large/binary/sensitive files do not require body copies |
| AD | `record_revision` participates in atomic conditional publication; stale writes cannot both publish N+1 |
| AE | No-SCM has durable S10 success semantics without pretending an SCM Commit |
| AF | Migration interruption retains bounded recovery checkpoints without becoming a canonical development record |
| AG | P4–P8 runtimes are not specified as implementations here |
| AH | Only the exact deterministic S9 Finalization Bundle is exempt from a second candidate review |
| AI | Durable P6 Evidence references remain resolvable after ordinary runtime expiry |
| AJ | Finalization support artifacts remain non-canonical and preserve existing Skill, stage, authorization, and ownership boundaries |
| AK | `TASK_COMPLETE` is structural Stage-status aggregation; current Stage/Task decision authority is additionally required for READY |
| AL | P6 owns one content-deterministic semantic candidate projection; current Task control-plane bytes with unchanged substantive projection do not self-invalidate candidate identity, but do not prove publication authorization; substantive Task/source/project mutation changes candidate identity |
| AM | Task `requirement_id` and P6 `profile_id` are distinct; fresh automatic locator attachment requires an explicit durable execution binding |
| AN | Knowledge Assessment is Understand-owned supporting authority, not a fourth canonical development record; S4 SATISFIED requires current candidate-bound and impact-bound SATISFIED outcomes; lexical token presence is not S4 authority |
| AO | Unexplained physical drift vs accepted anchor is host-level durable truth outside Session runtime; abort does not accept bytes or launder drift; ABORTED `observed_success` is attribution not `DEVELOP_KNOWN`; later overlays cannot mint `inherited_baseline` against a durable unexplained fact; attribution retirement requires current-byte consistency with the provenance used; `inherited-at-initialization` is one-time compatibility only and MUST NOT be a runtime fallback; S10 remains the acceptance boundary; generic human clear of unexplained bytes is forbidden (FA2-FND-005) |

---

## 41. Knowledge Assessment (FA2-FND-004)

Knowledge Assessment is a candidate-bound Knowledge Consistency Assessment. It
is an Understand-owned supporting artifact, not a canonical development record.

Minimum schema:

```yaml
record_type: knowledge_assessment
schema_version: "1"
record_id: ka-<utc-compact>-<8 hex>
created_at: <RFC3339>
producer:
  skill_id: understand
  mode: refresh  # or full
candidate:
  candidate_digest: <current P6 candidate_digest>
impact_digest: <digest of exact current S3 knowledge-relevant impact set>
assessments:
  - impact_id: <digest of canonical impact projection>
    class: PUBLIC_INTERFACE
    path: src/save/api.py
    outcome: SATISFIED  # SATISFIED | NEEDS_REFRESH | NEEDS_HUMAN | UNKNOWN
    surfaces:
      - docs/project/architecture.md
    rationale: Explanatory text; MUST NOT override candidate or impact binding.
```

Allowed per-impact outcomes are exactly `SATISFIED`, `NEEDS_REFRESH`,
`NEEDS_HUMAN`, and `UNKNOWN`. Boolean false MUST NOT represent UNKNOWN.
`rationale` is explanatory and MUST NOT itself override candidate/impact binding.

S3 owns structural-impact detection. S4 owns validation that each current
knowledge-relevant S3 impact has current Knowledge Assessment authority.
Understand owns semantic assessment / Refresh. Submit MUST NOT manufacture
SATISFIED from mapped documentation pathnames, unrelated current documentation
edits, pre-existing mentions, or current prose containing an impacted path,
basename, module id, impact class, or any combination of those tokens.

A Knowledge Assessment is S4-authoritative only when it is schema-valid,
Understand-produced, candidate-bound, impact-bound, the current-head for that
exact binding, and its published bytes still match the current-head integrity
digest. Candidate + impact equality alone is NOT enough. C1 assessments MUST
NOT support C2. A superseded locator MUST NOT be replayed. Change Record
`knowledge_updates` / `understand_involvement` remain S9 summaries and are not
S4 authority.

---

## 42. Cross-session unexplained drift (FA2-FND-005)

Durable unexplained physical drift is a Develop-owned **supporting artifact**.
It is not a Task Book, Develop Session, or Change Record, and MUST NOT be
described as a fourth canonical development record.

Runtime location:

```text
.scaffold/ext/develop/unexplained.yaml
```

The artifact is host/workspace-level and Task-agnostic. It records path-scoped
facts that current bytes differ from accepted physical truth without
trustworthy attribution. It MUST NOT duplicate the whole workspace and MUST NOT introduce
per-Task full-workspace accepted baselines.

Accepted physical truth is already:

- Git: SCM HEAD
- no-SCM: successful S10 publication / durable publication inventory

Session seal, Stage Completion, Task Completion, and P6 publication are not
acceptance. S10 remains the existing acceptance boundary.

`observed_success` remains attribution even after abort. An ABORTED Session
MUST NOT be consumed as `DEVELOP_KNOWN`. Abort MUST NOT launder unexplained
drift. Session open snapshot is physical starting observation, not
acceptance, and MUST NOT mint a new accepted anchor.

P8 still observes actual physical Diff fresh. Durable drift records never
replace that Diff. Known unexplained drift MUST NOT become
`inherited_baseline` merely because an earlier Session was aborted or cleaned
up. Normal Session cleanup MUST NOT erase this artifact.

Generic human clear of unexplained bytes is forbidden. Drift MAY retire only
when the path returns to the accepted anchor; when the current physical
state / current bytes of that path are proven consistent with the durable
trustworthy mutation provenance being used for attribution, becoming
attributed-but-unaccepted not accepted; or when successful S10 advances the
accepted anchor. Historical provenance for a different byte/digest state
MUST NOT clear a newer unexplained mutation of the same path.

`inherited-at-initialization` exists ONLY for the one-time compatibility
initialization when an existing established host first adopts the FA2-FND-005
authority model. It is not a recurring reconciliation mode. The system MUST
record a durable initialization boundary. After that initialization boundary
exists, UNKNOWN, missing evidence, reconciliation uncertainty, or ordinary
future physical divergence MUST NOT fall back to inherited-at-initialization
merely because attribution cannot be proven. Any physical divergence first
observed after the compatibility boundary that lacks trustworthy current-byte
attribution is unexplained and MUST NOT be downgraded to
inherited-at-initialization. The one-time rule does not fabricate historical
certainty that pre-upgrade dirt was legitimate.
