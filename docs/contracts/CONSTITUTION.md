# Constitution — AI-Native Project Scaffold v2.0

This document is the highest in-repo authority for v2.0. It freezes product definition, the four Skills, record types, submission control, and design principles.

It does **not** freeze YAML fields, Python APIs, Skill directory trees, CLI flags, adapter protocols, or runtime code. Those belong to later phases.

**Normative words:** MUST, MUST NOT, SHOULD, MAY.

If this Constitution conflicts with Architecture, the ADR, or README, this Constitution wins. If a later implementation conflicts with this Constitution, the implementation is wrong.

Related:

- Structure and data flow: [../architecture/V2_ARCHITECTURE.md](../architecture/V2_ARCHITECTURE.md)
- Why a new repository: [../decisions/0001-v2-clean-restart.md](../decisions/0001-v2-clean-restart.md)

---

## 1. Product definition

AI-Native Project Scaffold v2.0 is a **portable project-development scaffold** that can be imported into an **existing** project.

Its purpose is to normalize an ordinary project so AI can continuously:

- understand it
- develop it
- test it
- submit work
- hand it off to a later Agent or human who has **no chat history**

Game projects are the primary research subject.

The top-level architecture MUST NOT bind to:

- Unreal Engine
- Unity
- a game genre
- Git
- Perforce
- Cursor
- Claude Code
- Codex
- a model vendor
- a specific IDE

Concrete project environment (engine, SCM, client, commands) MUST be described later by Project Contract, Rules, Commands, and Adapters — not by this Constitution.

v2 is **not** “a game testing framework.” Game Legibility / advanced test runtime MAY later become a capability **inside Test**. That capability MUST NOT define the whole product.

---

## 2. Four Skills only

v2 exposes **exactly four** top-level Skills:

| Skill | Question |
| --- | --- |
| **Understand** | What is this project, and how should a new Agent correctly understand and maintain it? |
| **Develop** | How should the current task be completed under this project’s rules? |
| **Test** | For the specified scope, what was actually verified, and what was the result? |
| **Submit** | Does the current **real** working tree already meet submission conditions? |

MUST NOT promote any of the following to a top-level Skill:

| Name | Home |
| --- | --- |
| Bootstrap / Adoption | Understand’s first-attach path |
| Refresh | Understand mode |
| Compatibility | Understand mode |
| Repair | Develop special mode |
| Stage Validation | Develop invokes Test |
| Structural Review | Submit internal stage |

A Skill is a **multi-step workflow that completes one whole job**.

A **Project Rule** is a local constraint applied while running those workflows (language, module, domain, file class). Examples: C++ conventions; Save-module constraints; no hardcoded absolute paths; schema changes require migration. Rules MUST NOT be inflated into new macro Skills.

---

## 3. Adoption / Bootstrap

Bootstrap is **not** a fifth Skill.

It happens when an ordinary project attaches to the scaffold for the first time. Conceptual path:

```text
read-only discovery
  → adoption plan
  → apply minimal scaffold integration
  → Understand Full
  → validation
  → activate
```

Adoption MUST:

- work on a non-empty project
- work on a dirty working tree
- detect existing uncommitted changes
- detect existing `AGENTS.md`, `CLAUDE.md`, Cursor Rules, docs, tests, and CI
- allow resume after failure
- be reversible

Adoption MUST NOT:

- require the user to commit existing work merely to attach the scaffold
- blindly overwrite existing user documentation
- make the scaffold a mandatory runtime dependency of business code

The Adoption Contract is P1. This Constitution only freezes the principles.

---

## 4. Understand

Understand has at least three modes:

| Mode | When |
| --- | --- |
| **Full** | First complete understanding and normalization |
| **Refresh** | Incremental update after structural or important knowledge change |
| **Compatibility** | Scaffold / Skill version change; compatibility and migration judgment |

Understand establishes and maintains:

- project entry knowledge
- module map
- architecture information
- development norms
- test entry points
- project commands
- project constraints
- Agent routing
- Skill routing
- document authority relationships
- knowledge freshness

Understand is **not** “write a README.” Its goal is: a new Agent with **zero chat context** can enter the project correctly.

---

## 5. Three-layer knowledge model

P0 freezes the **layers**, not final fields or filenames beyond the layer names below.

### Layer 1 — `AGENTS.md`

Project **router**. SHOULD stay short.

It SHOULD say: which project this is; current status; global hard constraints; authoritative doc entry points; main module entries; when to use the four Skills; how to maintain docs; what to do on Skill updates; what to do on new modules.

It MUST NOT become the project encyclopedia.

### Layer 2 — `docs/project/`

Human-readable project knowledge base. Conceptual examples: overview, architecture, development, testing, modules.

Projects MUST NOT be forced into a fixed four- or five-document set. Each **important module MUST have a clear authoritative entry**.

### Layer 3 — `.scaffold/`

Machine-readable project state and scaffold metadata. Conceptual contents: project metadata, modules, commands, tests, Skill versions, tasks, change records, runtime temporary state.

Natural-language docs explain. Machine-readable state is what validation checks.

Final structure is frozen in **P2**.

If several Agent clients need different files, the model is:

```text
authoritative knowledge
        ↓
thin client entry / one-way generation
```

MUST NOT hand-maintain the same facts in `AGENTS.md`, `CLAUDE.md`, Cursor Rules, README, and YAML in parallel.

Skill **bodies** MUST have a single real source. Client-specific files MAY point at that source. They MUST NOT copy the Skill.

---

## 6. Develop

Develop is **task-driven development**. It is not “let the AI write code.” Develop MUST NOT perform Submit-S10 durable finalization, including SCM Commit.

Complete development MUST be driven by a **Task Book** that states:

- this round’s full goal
- scope
- stages
- acceptance criteria per stage
- test requirements per stage
- final tests
- current progress

A large task is staged:

```text
Task
  ├─ Stage A
  ├─ Stage B
  ├─ Stage C
  └─ Final Tests
```

A stage Test PASS proves **that stage’s required tests passed**. It MUST NOT be treated as: Stage acceptance satisfied; task complete; all tests complete; or submittable.

The Task Book carries a P3-defined structured **Stage Completion Decision**
about each human-readable Stage acceptance criterion. Develop owns that
candidate-bound lifecycle decision; Test owns Test/Evidence truth. A Stage
may enter `COMPLETE` only when its current decision is `SATISFIED`, required
Stage Test obligations are satisfied, and no required blocker remains.
`UNKNOWN` is not `UNSATISFIED`, and neither permits completion.

The Task Book also carries a distinct P3-defined structured **Task Completion
Decision** about its human-readable Task-level acceptance criterion. It uses
the same `SATISFIED` / `UNSATISFIED` / `UNKNOWN` outcomes and candidate-bound,
reconstructable authority principles. All Stage completion and final Test
success does not automatically satisfy the Task criterion.

### Internal phases

| Phase | Duty |
| --- | --- |
| **D1 Prepare** | Read AGENTS; read relevant project knowledge; read Task Book; inspect real repository state; determine whether the local baseline is current vs the project’s configured upstream / source-of-truth SCM; read recent Change Records; decide whether Understand Refresh is required |
| **D2 Implement** | Implement the current stage; sync necessary docs; local verification |
| **D3 Validate** | Invoke Test Skill; publish the candidate-bound Stage Completion Decision and Task progress through P3 conditional publication; if incomplete, stale, unknown, or acceptance unmet, continue Develop ↔ Test; do **not** mark READY_FOR_REVIEW merely because tests executed |

### Candidate currentness and the Task control plane

P6 remains the **single owner** of candidate identity. Its candidate digest
MUST represent the substantive project candidate, including source, business
content, project/configuration authority, and the substantive authority
projection of every Task Book. The digest MUST NOT be defined as an
unqualified hash of every mutable workspace byte when doing so would make a
Completion Decision stale solely because that decision was canonically
published into its own Task Book.

The Task authority projection is narrow. Goal, acceptance, scope, baseline,
Stage identity/goal/acceptance, planned requirement identities, and explicit
requirement-to-Test-profile execution bindings are candidate-significant.
Creating/removing a Task Book or changing any of those facts changes candidate
identity. Bounded lifecycle/control-plane facts of the **current** Task
content — revision and update metadata, Task/Stage progress status, Session
links, result summaries, P6 Evidence locators and observed outcomes, and
Stage/Task Completion Decisions — MAY be candidate-neutral when the
substantive Task authority projection of that current content is unchanged.

P6 `candidate_digest` answers what substantive project/Task candidate exists
now. It MUST be content-deterministic: identical currently observed substantive
content yields the same digest. It MUST NOT depend on unverifiable historical
facts such as which process wrote identical current Task bytes, and it MUST
NOT prove Task mutation authorization.

P3/P7 expected-revision conditional publication answers whether a Scaffold
Task mutation was legally published. **candidate-equivalent !=
publication-authorized.** A direct/manual/non-CAS write of identical
control-plane bytes does not become an authorized P7 publication merely
because those bytes are candidate-neutral.

Candidate-neutral does not mean invisible, unreviewed, or freely writable.
The real workspace/SCM Diff MUST retain the complete Task Book byte change.
Malformed or lifecycle-illegal Task content MUST fail closed under Task
schema and lifecycle authority. A source, business, project, configuration,
Task acceptance/scope/baseline, or requirement-plan mutation still changes
the P6 candidate and invalidates old candidate-bound Evidence, decisions,
review, and authorization as otherwise required.

Git and no-SCM hosts use the same P6-owned semantic projection. Git status and
Diff remain physical truth; no-SCM inventory still observes every file.
Projection affects candidate currentness only, not whether changed bytes exist.
No P7 digest, caller digest, or second candidate identity is introduced.

### Explicit Task requirement execution binding

A Task planned requirement identity and a P6 Test profile identity are
different concepts. Equality of their strings MUST NOT establish proof.
When Develop expects a fresh executable Test profile to produce Evidence for a
Task requirement, the Task reference MUST first carry an explicit durable
binding from that `requirement_id` to the selected P6 `profile_id`. That
binding is substantive Task authority and therefore candidate-significant.

Develop derives the Develop→Test execution mapping from that Task authority.
P6 executes and reports the selected profile and returns a public Evidence
locator whose resolution preserves the producing profile identity. P7 may
attach that locator only to the exact requirement whose explicit binding names
that profile. Without the binding, matching names, selection order, or a sole
result MUST NOT be used to guess. Existing legitimate HUMAN, CI, or EXTERNAL
P6 Evidence may satisfy a requirement through its explicit opaque locator
without an automated profile binding.

### D1 — upstream currentness

D1 MUST determine whether the local development baseline is current relative to the project’s configured upstream / source-of-truth SCM state.

When safe and permitted by project SCM policy, D1 SHOULD synchronize / reconcile **before** implementation.

D1 MUST NOT destroy or overwrite pre-existing dirty work. D1 MUST NOT assume Git or Perforce. Exact SCM commands and protocols are later-phase concerns.

If that pre-development synchronization materially changes repository structure, modules, commands, tests, architecture knowledge, or other important project facts, Understand Refresh MUST occur before implementation continues.

### READY_FOR_REVIEW

Develop’s terminal state is at most **READY_FOR_REVIEW**.

The normal successful Develop path reaches READY_FOR_REVIEW only when:

- all Task Book development stages are complete
- every Stage Completion Decision is `SATISFIED` and current for the actual candidate
- task-level final required tests satisfy their **defined acceptance conditions**
- the Task Completion Decision is `SATISFIED` and current for the actual candidate
- no required blocker remains

If required tests fail, Develop ↔ Test continues. MUST NOT silently mark a failed task READY_FOR_REVIEW merely because those tests executed.

If the Task Completion Decision is `UNKNOWN` or stale, READY_FOR_REVIEW is
forbidden even when all Stage decisions and final Tests are satisfied.

If Submit finds a repair blocker for a READY Task, Submit may return only a
bounded `submit_to_develop` handoff whose target Stage identities are
deterministically grounded in current Task authority. Submit MUST NOT guess a
first, last, or all-Stage target and MUST NOT mutate the Task. Given a valid
current handoff, Develop may use P3 atomic conditional publication to move the
Task `READY_FOR_REVIEW` → `IN_PROGRESS`, move exactly the target Stages
`COMPLETE` → `IN_PROGRESS`, and supersede their prior completion decisions.
Before READY is restored for a repaired candidate, every target and non-target
Stage decision relied upon for READY and the Task Completion Decision MUST be
current and `SATISFIED` for that candidate.

READY_FOR_REVIEW is **not** submit authorization and MUST NOT start S10 durable finalization or Push. Future WIP / checkpoint-submit exceptions are out of P0.

---

## 7. Canonical development records

The development / handoff lifecycle has exactly three **canonical development record** kinds:

1. Task Book
2. Develop Session
3. Change Record

MUST NOT introduce another record that duplicates the lifecycle or duty of these three. MUST NOT create parallel scratchpad / work-log / handoff-log / session-history / changelog copies of the same development facts.

Other bounded artifacts MAY exist only when they have a clearly different purpose, authority, lifecycle, and retention policy. Examples such as Test Reports / Evidence, Adoption Session, migration artifacts, analysis artifacts, or the FA2-FND-005 host-level unexplained-drift support under `.scaffold/ext/develop/` are **not** automatically prohibited, and are **not** a fourth canonical development record.

| Record | Answers | Lifecycle |
| --- | --- | --- |
| **Task Book** | What are we preparing to do, and where are we? | Live during the task. After success: completed / historical. |
| **Develop Session** | What did this Develop run explicitly produce? | Temporary. Assists Submit in explaining the current diff. After successful Submit-S10 durable finalization: MUST be cleaned up (mechanism is P3). |
| **Change Record** | What is the final reviewed candidate, and (after S10 succeeds) what was durably submitted? | Finalized at **S9 before durable finalization**. Before S10 success it describes the candidate. After S10 succeeds it becomes long-term as-built history for that finalization. If S10 fails or is interrupted, it MUST NOT be described as already-submitted history. Draft / final state mechanics are **P3**. |

Analogy: Task Book = construction plan. Develop Session = temporary site notes. Change Record = as-built packet prepared before handover, then filed after the handover succeeds.

Final schemas and directories are **P3**.

### Develop Session is not repository truth

A Develop Session is **not** the final source of fact. It only helps Submit classify what Develop explicitly did.

```text
S0 = working tree at Develop start
S1 = working tree at Develop end
S2 = real working tree at Submit start
```

Submit MAY classify paths as:

| Class | Meaning |
| --- | --- |
| `DEVELOP_KNOWN` | Changed by Develop; unchanged since |
| `POST_DEVELOP_ADDITIONAL` | Appeared after Develop ended |
| `MIXED_CHANGE` | Changed by Develop; same path changed again after |
| `PREEXISTING_CHANGE` | Already present before Develop started |

`PREEXISTING_CHANGE` / `inherited_baseline` MUST NOT be inferred from later
Session overlays when a durable unexplained-drift fact contradicts that
inference (FA2-FND-005). Abort MUST NOT launder unexplained physical drift
into ordinary inherited baseline.

MUST NOT use `HUMAN_CHANGE` as a definite class. Later edits cannot be reliably attributed to a human. They MAY come from a developer, IDE, script, another Agent, a generator, or other tools.

**Repository truth overrides agent memory.** Real SCM / working tree always outranks the Develop Session.

Accepted physical truth is SCM HEAD on a Git host, or successful S10
publication / durable publication inventory on a no-SCM host. Session seal is
not acceptance. ABORT does NOT mean current workspace bytes are accepted.
`observed_success` provenance remains attribution after abort and is not
`DEVELOP_KNOWN`.

Submit MUST work even when there is **no** Develop Session and **no** Task Book (pure human or mixed edits that never used Develop). Missing Develop history MUST NOT make Submit unable to start.

---

## 8. Test

Test answers only: **what did this specified scope actually verify?**

Test MUST NOT answer: **may we submit now?**

### Two capability classes

**A. Native Project Tests** — discovered and recorded by Understand. Examples: build, unit, integration, project test scripts, engine test systems, CI smoke.

**B. Game Legibility / Advanced Test Runtime** — later, selective reuse of mature v1.0.1 pieces (Scenario, Adapter, Harness, Evidence, Analysis). These are **one advanced capability of Test**. They MUST NOT represent the whole scaffold.

### Output

Every Test result MUST include a **Scope** (examples: Stage Test, Task Final Test, Regression Test, Submit Verification, Smoke, Other).

Every Test result MUST state:

- which tests actually ran
- which PASS
- which FAIL
- which were not executed
- why they were not executed
- where evidence lives
- whether the run is replayable

MUST NOT emit a bare `PASS` as the whole result.

A Test PASS is **TEST_PASS** only for the batch that actually ran. See §9.

---

## 9. Four statuses — not interchangeable

| Status | Meaning |
| --- | --- |
| **TEST_PASS** | A specific executed test batch passed. |
| **TASK_COMPLETE** | All development stages in the Task Book are done. |
| **TEST_COMPLETE** | For the **current real submission candidate**: every required test has a terminal recorded result; required-test coverage is complete; and there is no unresolved required-test blocker. |
| **SUBMIT_AUTHORIZED** | A human has **currently and explicitly** authorized **this reviewed candidate** for Submit-S10 durable submission finalization. On an SCM host where S10 is Commit, this is the required human Commit authorization for that candidate. |

MUST:

```text
TEST_PASS        ≠  TASK_COMPLETE
TASK_COMPLETE    ≠  TEST_COMPLETE
TEST_COMPLETE    ≠  SUBMIT_AUTHORIZED
```

TEST_COMPLETE is **not** proof of real-world correctness, **not** TASK_COMPLETE, and **not** SUBMIT_AUTHORIZED. Human judgment remains mandatory.

TEST_COMPLETE MUST NOT become true merely because failing required tests were executed. A required-test failure normally blocks TEST_COMPLETE until the problem is fixed and re-tested. An explicit human-reviewed exception / waiver mechanism, if any, belongs to the later Submit Contract (**P8**). P0 MUST NOT invent that waiver.

TEST_PASS MUST NOT by itself launch Submit.

Develop MUST NOT auto-finalize or auto-commit.

**Submit is the only Skill allowed to enter the real durable submission finalization / optional Push flow.**

When a Task Book exists, Submit-S10’s minimum conditions are:

```text
TASK_COMPLETE
+ TEST_COMPLETE
+ STRUCTURAL_REVIEW_PASS
+ SUBMIT_AUTHORIZED
```

When there is no Develop Task / Task Book, later Records and Submit contracts MUST define the applicable substitute for `TASK_COMPLETE` (including “not applicable”). P0 freezes only: Submit MUST still operate; absence of Develop history is not a hard stop at intake.

---

## 10. Submit

Submit is an independent top-level Skill because the real working tree MAY contain AI Develop edits, human edits, mixed edits, pre-existing dirty work, tool rewrites, or changes that never used Develop.

Submit MUST NOT trust the previous Agent’s summary. It MUST re-read the real repository.

### Frozen stages

| Stage | Name |
| --- | --- |
| S1 | Intake |
| S2 | Delta Classification |
| S3 | Structural Review |
| S4 | Knowledge Consistency |
| S5 | Test Completeness |
| S6 | Human Approval |
| S7 | Repository Sync |
| S8 | Re-review / Re-test |
| S9 | Finalize Records |
| S10 | Commit / Durable Finalization |
| S11 | Optional Push |
| S12 | Cleanup |

After S3–S5 pass and before S6 authorization, the pipeline MUST stop at **READY_FOR_HUMAN_APPROVAL**. That is still not authorization to perform S10.

### S3 Structural Review

Submit MUST judge from the **real diff**:

- which files actually changed
- which modules are affected
- added / deleted modules
- interface, dependency, command, config-format, test-method, or project-structure changes
- changes undeclared in the Task Book
- changes unknown to the Develop Session

`MIXED_CHANGE` and `POST_DEVELOP_ADDITIONAL` MUST receive extra attention. `DEVELOP_KNOWN` MUST NOT skip final review.

### S4 Knowledge Consistency

Submit MUST check whether current code / asset / config changes have stale project knowledge, including whether AGENTS, architecture, module docs, modules / commands / testing metadata, or the Test Matrix need updates, and whether Understand Refresh is required.

**Knowledge freshness is testable.** Stale docs in an AI-first project can be more dangerous than missing docs. Freshness MUST NOT rely only on a developer “remembering to update.”

S4 MUST NOT independently establish knowledge consistency from mapped documentation pathnames, unrelated current documentation edits, pre-existing path/module mentions, or current prose that merely contains an impacted path, basename, module id, impact class, or any combination of those tokens.

For each knowledge-relevant determined S3 impact, S4 MAY treat the impact as knowledge-consistent only when a current validated Understand-owned **Knowledge Assessment** has `outcome = SATISFIED` for that exact current impact, is bound to the current P6 `candidate_digest` and the current S3 knowledge-relevant impact digest, and is the current-head Assessment for that exact binding whose published bytes still match the head integrity digest. Candidate + impact equality alone is not enough. A superseded locator MUST NOT be replayed. Missing assessment, missing/broken current head, integrity mismatch, candidate mismatch, impact-digest mismatch, partial coverage, `NEEDS_REFRESH`, `NEEDS_HUMAN`, and `UNKNOWN` MUST NOT become PASS. Boolean false MUST NOT represent UNKNOWN. A raw caller dictionary is not S4 authority. Knowledge Assessment is a supporting artifact, not a fourth canonical development record and not a fifth Skill. Change Record `knowledge_updates` is not S4 authority.

### S5 Test Completeness

Submit MUST NOT ask only “did some tests PASS?” It MUST ask whether **TEST_COMPLETE** holds for the current real submission candidate: every required test has a terminal recorded result, required-test coverage is complete, and there is no unresolved required-test blocker.

Executing a failing required test does **not** satisfy TEST_COMPLETE.

Future inputs include Task Book + actual diff + Test Matrix + project testing rules. If the developer extra-edited Save, Save tests remain required even if the Task Book omitted them. The Test Matrix Contract is a later phase. Any waiver mechanism is **P8**.

### S6 Human Submission Gate

Default: `submission authorization = false`.

Human submission authorization is **candidate-bound**.

S3–S5 produce **Candidate A**. Submit MUST stop at READY_FOR_HUMAN_APPROVAL until a developer **currently** and **explicitly** authorizes Candidate A (in substance: “submit now” / “run the submit flow” for **this** reviewed candidate).

MUST NOT treat a past authorization as a standing grant.

MUST NOT reuse authorization from another Submit attempt.

MUST NOT let an Agent flip the submit switch for itself.

`SUBMIT_AUTHORIZED` is the current, candidate-bound human authorization for **Submit-S10**. It is the Commit authorization when S10 is realized as an SCM Commit; there is no second foundational `COMMIT_AUTHORIZED` state or gate. Push is separate: it MUST have additional current explicit authorization, MUST NOT be the default, and MUST NOT inherit authorization from `SUBMIT_AUTHORIZED`. Neither permission is a reusable persisted bit.

### S7–S8 after sync

Upstream sync MAY merge, rebase, resolve conflicts, or otherwise change the real submission candidate.

If the real submission diff is **unchanged**, the S6 authorization for Candidate A remains valid.

If S7 / S8 changes the real submission candidate:

- Candidate A authorization is **invalidated**
- Submit MUST re-diff
- re-run S3 / S4 / S5 as needed
- re-test as needed
- return to **S6**
- the human MUST explicitly authorize **Candidate B**

Only then may S10 durable finalization occur.

This is a loop, not a thirteenth stage:

```text
S8 → S3 / S4 / S5 → S6
```

Submit MUST NOT durably finalize a changed, un-reviewed, or un-reauthorized candidate. Authorization from an earlier Submit attempt is never reusable.

The sole S9 exception is the deterministic **Finalization Bundle** defined by
the Records Contract. Adding that exact bundle does not invalidate the
authorization for the reviewed candidate because its content is a bounded
finalization consequence of authority and Evidence already validated before
S6, not new business/source intent. This exception does not apply to arbitrary
generated files, arbitrary `.scaffold/ext/` content, or support content that is
not deterministically derivable from the reviewed Evidence and exact Change
Record references. Any other S9 mutation is a candidate change and MUST return
through S3–S6.

### S9 Finalization Bundle

S9 finalizes the exact logical Change Record content/representation for the
authorized final candidate **before** S10. It MAY also include zero or more
deterministic support artifacts required solely to keep durable references in
that exact Change Record resolvable after ordinary runtime expiry. Together
these form the **Finalization Bundle**. On an SCM host, the exact bundle can
therefore be included in the same Commit.

```text
final reviewed candidate
  → S9 finalize Change Record + permitted deterministic support artifacts
  → S10 Commit / Durable Finalization
  → S11 Optional Push or N/A
  → S12 Cleanup
```

A Change Record MUST be generated from:

- the **final real diff** of the authorized candidate
- final test status
- final Structural Review
- final knowledge-update status

MUST NOT be generated from “the Agent remembers what it did.”

Every support artifact in the Finalization Bundle MUST:

- be deterministic from authority and Evidence already validated before S6
- introduce no new business/source intent
- be necessary to resolve a durable reference in the exact Change Record
- be produced by the authority owner of that support artifact
- be written inside an already-authorized durable project boundary under the
  existing ownership model
- be included in and integrity-bound to the exact S10 finalization candidate

The final support set and its semantic content MUST be deterministic
consequences of the validated Evidence references and Change Record
finalization rules. Additional substantive or non-deterministic content is a
candidate change and requires re-review and current S6 authorization.

Temporal semantics:

- Before S10 succeeds, the Change Record and any prepared support artifacts
  are candidate-only and are not yet durable history.
- After S10 succeeds, the same S9-finalized logical Change Record becomes
  long-term durable as-built history and its referenced support artifacts
  become durable support. No second content rewrite is required.
- If S10 fails or is interrupted, neither the Change Record nor its prepared
  support artifacts may be described as durable historical fact. Candidate-only
  support artifacts require deterministic cleanup or recovery, and completed
  Develop Sessions MUST NOT be cleaned up as submitted history.

P6 Test Evidence validates the **reviewed candidate**. A permitted S9 support
artifact is only a deterministic retained representation of that
already-validated Evidence. It does not claim that P6 re-tested new substantive
candidate content, and this treatment MUST NOT be generalized to generated
files or `.scaffold/ext/` broadly.

P3 defines draft / final state mechanics.

S10 is the authoritative durable submission finalization operation:

- On an SCM host with Commit capability, S10 is Commit of the reviewed
  candidate plus the exact Finalization Bundle. Every tracked support artifact
  in the bundle MUST belong to that exact Commit tree.
- On a no-SCM host, S10 is a P8-defined atomic or conflict-detectable durable
  finalization/publication operation for the same logical Finalization Bundle.
  Its success MUST be durably distinguishable after restart; failure or
  interruption MUST NOT create false submitted history. It MUST NOT pretend
  that an SCM Commit occurred.
- S11 Push is optional when a push-capable SCM exists and **N/A** otherwise.
- Concrete no-SCM success-marker/publication and recovery mechanics belong to P8; these semantics do not add a thirteenth stage.

S10 MUST bind the exact resulting candidate/tree. A missing, changed,
unexpected, or incompletely finalized support artifact is a finalization
mismatch and MUST fail closed.

After successful S10:

- Develop Session → clean up (S12)
- Task Book → completed / historical
- Change Record → retain long-term (already finalized at S9; now as-built)

---

## 11. Core principles (12)

### 1. Knowledge before action

Before developing, Agents MUST read project rules and inspect **current real** repository state. Guessing from chat memory is not enough.

### 2. Every change is verifiable

Important changes MUST have an explicit verification basis (tests actually run, evidence location, scope). Opinion is not verification.

### 3. Every important change is handoff-ready

A later member MUST be able to understand important changes without the original chat. That is what Task Book (intent/progress), Change Record (as-built after successful S10 durable finalization), and knowledge docs are for.

### 4. Knowledge evolves with the project

After structural or important knowledge change, Understand Refresh MUST be possible. Knowledge is not a one-time bootstrap artifact.

### 5. Repository truth overrides agent memory

Working tree and SCM are authoritative. Develop Session, Agent summaries, and chat are auxiliary. On conflict, the repository wins. Unexplained physical drift versus accepted physical truth is a durable host-level fact; abort and later Session overlays MUST NOT launder it into ordinary inherited baseline (FA2-FND-005).

### 6. Single Source of Truth

Each fact MUST have one authoritative source. MUST NOT maintain the same fact in multiple documents by hand. Multiple clients get **thin entries**, not cloned encyclopedias.

### 7. Progressive Disclosure

Load the minimum knowledge by default; read a module only when needed. Skills MUST follow the same rule. MUST NOT ship a multi-thousand-line `SKILL.md` that parks every case in context. Concept: `SKILL.md` holds the minimal workflow and hard rules; references / workflow docs are read per current stage. Directory detail is **P4**.

### 8. Rules must be enforceable

Important rules MUST NOT live only in Markdown as AI conscience. What can be machine-checked SHOULD be machine-checked (valid Task Book, required tests present, Change Record exists, AGENTS refs resolve, metadata consistent, Submit authorized). P0 does not implement hooks. This principle is frozen.

### 9. Infrastructure must verify itself

If a Gate claims to be mandatory, the system MUST be able to tell whether that Gate is healthy, broken, unavailable, or unknown. A crashed Gate MUST NOT be treated as a pass. Future Submit Gate, Test Completeness Gate, Knowledge Consistency Gate, session tracking, indices, and generated client entries all need a self-verification story. P0 does not implement it.

### 10. Temporary memory must expire

Every temporary state MUST have a lifecycle. Examples: Adoption Session cleaned after Adoption; Develop Session cleaned after successful S10 durable finalization (S12); analysis caches with explicit retention. MUST NOT accumulate unbounded session logs, scratchpads, temporary diffs, agent notes, or intermediate plans. Long-term knowledge MAY enter only the explicit long-term structures.

### 11. Knowledge freshness is testable

Whether docs are stale MUST be checkable. It MUST NOT depend only on human memory. Submit Knowledge Consistency is the top-level home for this check.

### 12. Human controls submission

AI MUST NEVER decide to perform S10 because tests succeeded. `SUBMIT_AUTHORIZED` defaults to false and is candidate-bound. Where S10 is Commit, it is that candidate’s Commit authorization; Push remains separately and currently authorized.

---

## 12. Additional frozen principles

### Skill versioning / compatibility

A project MUST eventually record: scaffold contract version; Understand / Develop / Test / Submit versions.

If local Skills disagree with the project lock: MUST NOT silently apply the new version. MUST check compatibility → continue if compatible; Understand Compatibility if migration is needed; stop and report if incompatible. Lock/schema detail is **P4**.

### Reversible adoption

Attaching the scaffold MUST NOT permanently lock the host project. In principle, removing scaffold metadata, scaffold-managed docs/blocks, and scaffold client integration MUST leave the business project able to run and be developed. The scaffold MUST NOT be a hard business-runtime dependency.

### Multi-Agent / multi-client

Future clients (Codex, Claude Code, Cursor, VS Code Agent, others) MUST share one project-knowledge core. Client files MAY contain: where to read authority; a few client-specific settings; tool wiring. They MUST NOT replicate the whole project knowledge.

### High-level lifecycle (normative order)

```text
ordinary project
  → Adoption / Bootstrap
  → Understand Full
  → Scaffold-managed project
  → Task Book
  → Develop  ↔  Test
  → all required Task Stages COMPLETE
    + every Stage Completion Decision relied upon for READY is SATISFIED
      and current for the actual candidate
    + task-level final required tests satisfy their defined acceptance conditions
    + the Task Completion Decision is SATISFIED and current for the actual candidate
    + no required blocker remains
  → READY_FOR_REVIEW
  → Submit
  → real-diff review + structural + knowledge + test-completeness reviews
  → READY_FOR_HUMAN_APPROVAL
  → Human Approval (candidate-bound)
  → Repository Sync
  → if the candidate changed: S8 → S3/S4/S5 → S6 (new candidate)
  → S9 finalize Change Record + permitted deterministic referenced support
  → S10 Commit / Durable Finalization
  → S11 Optional Push (separate authorization) or N/A
  → S12 Cleanup
  → Understand Refresh when needed
  → next development round
```

Diagrams and layering: Architecture.

---

## 13. Non-goals (v2 top level)

v2 top level is **not** responsible for:

- a specific game’s gameplay architecture
- NPC runtime LLM
- game-engine wrapping as the product
- asset-pipeline framework
- Unreal-specific framework
- Unity-specific framework
- Git-specific product
- Perforce-specific product
- Cursor-specific product
- Claude Code-specific product
- Codex-specific product
- a general IDE
- a general coding agent
- autonomously deciding product requirements
- AI autonomously deciding to submit
- auto merge / push as default behavior
- unbounded logging of all Agent thought
- copying all project knowledge into every client config

---

## 14. v1.0.1 historical position

`ai-native-game-scaffold` **v1.0.1** =

**Game Legibility / Test Runtime historical baseline**

Status: **FROZEN**, **READ-ONLY REFERENCE**.

v2 MUST NOT continue development in that repository.

Reuse policy: **clean restart, selective reuse**. A v1 capability MAY enter v2 only after inspect → qualify → map to a v2 responsibility → selectively migrate → revalidate under v2.

Primary reuse candidates and homes (no P0 migration):

| v1 (candidates) | v2 home |
| --- | --- |
| Contracts, Scenario, Target Adapter boundary, Harness, Evidence, Evidence Ref, Analysis | Test Skill |
| Repair: qualification, policy, isolated worktree, regression, fresh verification | Develop Repair Mode (P9) |

---

## 15. What P0 does not freeze

Left to later phases (MUST NOT be “helpfully” implemented at P0):

| Topic | Phase |
| --- | --- |
| Adoption Contract | P1 |
| Project Contract (`AGENTS` / `docs/project` / `.scaffold` fields) | P2 |
| Records Contract (schemas, directories, aborted-session retention) | P3 |
| Skill format, Rule format, routing, version lock | P4 |
| Understand / Test / Develop / Submit implementations | P5–P8 |
| Repair migration | P9 |
| YAML fields, Python API, runtime, CLI, adapter protocols, hooks, SCM implementations, test-runner migration | later, as assigned |

Work order: **Contract → Architecture → Implementation**. MUST NOT reverse this.

Current phase map: [../architecture/V2_ARCHITECTURE.md](../architecture/V2_ARCHITECTURE.md#phase-map).
