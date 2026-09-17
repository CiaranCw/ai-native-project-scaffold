# FA2-FND-005 — Cross-Session Develop Authority / Durable Unexplained Drift

Status: candidate Foundation amendment; requires independent re-audit.

This amendment freezes the approved architecture for R4-DEVELOP-MAJ-008. It
does not implement runtime behavior, does not solve R4-DEVELOP-MAJ-007,
R4-SCAFFOLD-MAJ-005, R4-FIRSTUSE-MAJ-006, R4-DEVELOP-MIN-009, R4-PERF-MIN-010,
R4-TASK-MIN-011, or the shell-observation policy track, and does not claim
FA-2 PASS or FA-2 CLOSED.

It does not add a fifth Skill, S13, a fourth canonical development record, a
second candidate digest, a per-Task full-workspace accepted baseline, a new
acceptance ceremony, or a generic “human clear = accept bytes” operation.

## Reason

Current Session abort plus a later Session open can re-baseline live bytes.
Unexplained physical mutation W0→W1 can then appear in surviving Session
overlays as if it had been pre-existing. P8 may classify that mutation as
`inherited_baseline` / `PREEXISTING_CHANGE`. Abort therefore removes the
contradicting witness and launders unexplained physical drift across Session
boundaries.

That contradicts existing architecture: workspace / SCM is physical Diff
authority; mutation authorization is not mutation provenance; successful
observation is required for trustworthy provenance; unexplained same-scope
drift must fail closed; an ABORTED Session is not `DEVELOP_KNOWN`; clearing
runtime authority must not launder physical drift; repository truth outranks
Session memory.

## Governing design principle

```text
MINIMUM NECESSARY CONSTRAINT
+
MAXIMUM MODEL AUTONOMY
```

The Scaffold constrains facts a model cannot safely infer: authoritative
record locations, current execution identity, ownership, mutation authority,
mutation provenance, accepted physical truth, unexplained drift, candidate /
evidence identity, project-specific required Test bindings, and explicit
human Commit / Push authority.

The Scaffold MUST NOT prescribe implementation strategy, source exploration
order, helper decomposition, algorithm design, ordinary engineering
reasoning, or arbitrary procedural ceremony. MAJ-008 MUST be solved through
durable internal truth. It MUST NOT require a longer abort/reopen ritual.

## Three layers of physical authority

### 1. Accepted physical truth

Accepted physical truth already exists. Develop does not create it.

- Git host: SCM HEAD
- no-SCM host: successful S10 publication / durable publication inventory

Session seal is NOT acceptance. Stage Completion is NOT acceptance. Task
Completion is NOT acceptance. P6 publication is NOT acceptance. S10 remains
the existing acceptance boundary. No new acceptance ceremony is introduced.

### 2. Attributed but unaccepted change

A physical change MAY have trustworthy mutation provenance without being
accepted physical truth.

`observed_success` provenance from Develop remains attribution even if the
Session later becomes ABORTED.

This does NOT make the aborted Session `DEVELOP_KNOWN`, complete, sealed,
accepted, or candidate-authoritative. Attribution authority and completion
authority are distinct.

An ABORTED Session MAY answer “which mutation produced these bytes?” It MUST
NOT answer “was the Session complete?”, “was the Stage satisfied?”, “was this
candidate accepted?”, or “was this DEVELOP_KNOWN?”

### 3. Unexplained physical drift

A physical change that differs from the accepted anchor and has no
trustworthy provenance MUST remain durably identifiable as unexplained.

Its unexplained status MUST survive abort, execution-pointer clearing, new
Session creation, process restart, later Session overlays, and normal cleanup
of old Sessions.

Opening a new Session MUST NEVER transform unexplained drift into accepted
truth or ordinary inherited baseline.

## Durable support artifact

Introduce one host/workspace-level, Task-agnostic, Session-independent
durable support artifact:

```text
.scaffold/ext/develop/unexplained.yaml
```

This is not a fourth canonical development record. Canonical development
records remain Task Book, Develop Session, and Change Record.

The artifact exists only to preserve a non-inferable physical authority
fact: this path was observed to differ from accepted physical truth without
trustworthy attribution.

It MUST NOT duplicate the whole workspace. It MUST NOT create a Task-local
full-workspace baseline. It MUST NOT create a new global inventory when
existing SCM / no-SCM accepted authority already provides the anchor.

The artifact MUST live outside ephemeral Session runtime so that Submit-S12
or other normal Session cleanup cannot erase the fact. It MUST NOT depend
indefinitely on walking the full historical Session directory chain.

Like other `.scaffold/ext/<namespace>/` support, it is not P6 candidate
identity. Future runtime exclusion MUST follow the existing ext-support
pattern. This amendment does not itself change production candidate code.

## Critical scenarios

### FND5-E01 — Abort with unexplained drift

Accepted physical truth = W0. S1 opens. An unexplained mutation produces W1.
S1 aborts. S2 opens.

The W0→W1 unexplained mutation remains durably unexplained. S2 observing W1
MUST NOT accept it, legitimize it, convert it to `inherited_baseline`, erase
the violation, or make it ordinary Session baseline authority.

S2's open snapshot MAY truthfully say these bytes were on disk when S2
opened. It MUST NOT say these bytes were therefore legitimate. Abort MUST
NOT launder unexplained drift.

### FND5-E02 — Abort after trustworthy provenanced work

Accepted physical truth = W0. S1 records mutation A and mutation B as
`observed_success`, then aborts for another reason.

A and B remain ATTRIBUTED. They MUST NOT become UNEXPLAINED merely because
S1 was aborted. They MUST NOT become ACCEPTED merely because they are
attributed. ABORTED `observed_success` may remain attribution but is not
`DEVELOP_KNOWN`.

### FND5-E03 — New Session open is observation, not acceptance

Opening a new Develop Session MAY observe current physical workspace, create
its own open-inventory, create `workspace_overlay_s0`, and bind current
execution authority.

It MUST NOT accept current disk state, erase existing unexplained drift,
reinterpret attributed changes as accepted, mint a new accepted anchor, or
launder prior physical divergence.

The Session open snapshot is physical starting observation, not acceptance.
Opening a Session MUST NOT mint a new accepted anchor.

### FND5-E04 — Multiple IN_PROGRESS Tasks

The physical workspace is shared. Task B's legitimate `observed_success` on
path B MUST NOT become Task A rogue drift merely because Task A did not
produce it.

Task scope remains affiliation / mutation authorization, not exclusive
ownership of global workspace history. Cross-Task physical truth belongs at
host/workspace level. MUST NOT introduce per-Task full-workspace accepted
baselines.

### FND5-E05 — Later overlays cannot mint inherited_baseline

P8 remains responsible for observing actual physical Diff fresh. Durable
drift/provenance records are attribution inputs. They NEVER replace actual
physical Diff.

```text
physical Diff authority
>
advisory/provenance records
```

P8 MUST NO LONGER infer “present in every surviving sealed S0/S1 overlay”
⇒ `inherited_baseline` when a durable unexplained-drift fact contradicts
that inference.

Known unexplained drift MUST NOT become `inherited_baseline` merely because
the earlier contradicting Session was aborted or cleaned up.

### FND5-E06 — Cleanup durability

Current successful cleanup MAY delete Session runtime directories. Any
safety fact that must survive normal Session cleanup MUST live outside
ephemeral Session runtime. Normal cleanup MUST NOT erase durable unexplained
truth.

### FND5-E07 — No extra Agent ceremony

No new normal-path Agent command, flag, or abort/reopen ritual is
introduced. Existing `develop session`, `develop seal`, and `develop abort`
remain the execution window. Scaffold internally maintains unexplained vs
accepted vs attributed facts.

### FND5-E08 — Generic human clear is forbidden

Do NOT define a generic “human clears drift” operation that silently accepts
current bytes. Generic human clear of unexplained bytes is forbidden.

If a later product requires “human explicitly accepts currently unexplained
bytes without normal S10”, that MUST be separately designed and governed. It
is OUT OF SCOPE for FA2-FND-005.

### FND5-E09 — S10 remains the acceptance boundary

If human-authorized finalization accepts physical state through the existing
S10 boundary, the new accepted anchor supersedes prior drift. Do NOT
introduce a second hidden acceptance path.

### FND5-E10 — Path-scoped Develop vs Submit visibility

Known unexplained drift on path X does NOT automatically deny every
legitimate mutation on unrelated path Y. path-scoped Develop permissiveness
does NOT mean Submit may ignore known unexplained drift. Known unresolved
drift remains visible at final reconciliation / Submit.

### FND5-E11 — Imperfect client coverage

The architecture MUST NOT assume perfect pre-write interception. Future
clients MAY expose pre-write events, post-write-only events, partial hook
surfaces, or different adapter capabilities.

If an unexplained physical mutation reaches disk, later Scaffold observation
MUST still detect and preserve that physical fact. MAJ-008 correctness MUST
NOT depend on solving MAJ-007's unknown Cursor event path.

### FND5-E12 — no-SCM, unavailable anchor, existing-host initialization

On a true no-SCM host, the accepted anchor comes from existing durable
no-SCM publication/baseline authority. If required accepted-anchor authority
is unavailable, UNKNOWN / fail-closed remains valid. Do NOT fabricate an
anchor.

A fresh adopted host initializes against the current accepted anchor.

An existing established host upgraded to this model MAY have pre-upgrade
physical divergence without sufficient historical evidence to distinguish
old legitimate dirt from prior unexplained drift. Do NOT fabricate
historical certainty.

`inherited-at-initialization` exists ONLY for the one-time compatibility
initialization when an existing established host first adopts the FA2-FND-005
authority model. It is not a recurring reconciliation mode. The system MUST
durably know that this compatibility initialization has already occurred
through a durable initialization boundary. Do NOT prescribe that boundary's
filename, schema layout, or low-level implementation here.

That durable initialization boundary MAY be an existing tracked project
contract generation advance owned by Understand / project-migration authority.
Reusing the tracked `project_contract_generation` in `.scaffold/project.yaml`
is permitted and preferred over inventing a new marker, because it already
survives ordinary untracked workspace cleanup and exists for Git and no-SCM
hosts alike. It does NOT create a fourth canonical development record.

Develop reconciliation is a CONSUMER of that boundary. Develop MUST NOT create,
recreate, or re-grant it, and an ordinary Session boundary MUST NOT consume the
one-time compatibility initialization.

An established legacy host MAY therefore need to complete one bounded project
migration before ordinary Develop resumes. That migration remains the existing
Task-bound approved migration authority. It is not a new Skill, mode, or
record.

Loss or unreadability of the tracked project authority that carries the
boundary MUST fail closed. It MUST NOT yield never-initialized, and it MUST NOT
re-grant the one-time compatibility amnesty. Once the boundary has been
consumed, the host resolves only to valid initialized authority or to unusable
authority, never back to never-initialized.

After that initialization boundary exists, UNKNOWN, missing evidence,
reconciliation uncertainty, or ordinary future physical divergence MUST NOT
fall back to inherited-at-initialization merely because attribution cannot
be proven.

Any physical divergence first observed after the compatibility boundary must
follow normal FA2-FND-005 rules. If it lacks trustworthy current-byte
attribution, it is unexplained. It MUST NOT be downgraded to
inherited-at-initialization.

The one-time compatibility rule does not claim that pre-upgrade dirt was
historically legitimate. It only records that historical provenance is
unavailable before the model was introduced. No huge migration framework.

## Abort semantics

ABORT means: this Develop Session is not trustworthy as a completed Develop
result.

ABORT does NOT mean successful observed mutations never occurred.

ABORT does NOT mean current workspace bytes are accepted.

ABORT does NOT mean unexplained drift may be forgotten.

On abort:

- current execution authority is cleared
- Session remains ABORTED
- `DEVELOP_KNOWN` eligibility is lost / absent
- `observed_success` provenance remains attribution
- unexplained drift remains durable
- Task affiliation remains history
- pending authorization is not upgraded to provenance
- candidate acceptance does not occur

Abort MUST remain an escape path. A broken Session MUST NOT become
impossible to abort merely because drift is present. Abort SHOULD observe /
persist unresolved physical truth, then proceed with abort. It MUST NOT
detect drift and refuse abort forever.

## Drift retirement

A drift fact MAY cease being unexplained when authoritative evidence makes
it no longer unexplained. Required safe cases:

1. Path returns to accepted anchor. Current bytes again equal accepted
   physical truth. The drift observation MAY retire automatically.
2. Trustworthy attribution becomes available. A drift observation MAY cease
   being unexplained because attribution becomes available ONLY when the
   current physical state / current bytes of that path are proven consistent
   with the durable trustworthy mutation provenance being used for
   attribution. Historical provenance for a different byte/digest state
   MUST NOT clear a newer unexplained mutation of the same path. The state
   MAY then become attributed-but-unaccepted. This does NOT accept the
   bytes.
3. Accepted anchor advances through successful S10. The new accepted anchor
   supersedes the prior drift.

## Affected authority

- Constitution §7 Develop Session vs repository truth; §11 principle 5
- Records Contract §§15, 16, 19.3, 20, 39, 40, and 42
- P7 Develop Session abort / open / provenance notes
- P8 Submit provenance / `inherited_baseline` classification
- Project Contract `.scaffold/ext/<namespace>/` reservation (no new root file)
- Skill Contract migration semantics
- Project Contract `NEEDS_MIGRATION` semantics
- `.scaffold/project.yaml` `project_contract_generation`

## Preserved boundaries

- exactly three canonical development records
- exactly four top-level Skills
- unchanged Task, Stage, and Session states
- S10 remains the human-authorized acceptance / durable-finalization boundary
- P6 remains the single public candidate identity
- P8 still reads the real Diff
- no extra mandatory Agent rituals
- implementation strategy is not constrained
- source exploration order is not constrained
