# Pilot Readiness PR-1 — Entry and Task Intake

This implementation note does not modify or outrank P0–P4.

## Ownership decision

Task Intake is a bounded P7-owned Develop prelude because P3 assigns practical
Task Book creation/update to P7. It is exposed as `DevelopEngine.intake()` and
capability `develop.task_intake`; it is not a third Develop mode, fifth Skill,
or mutating Distribution preflight. `normal_task` and `repair` retain their
existing semantics.

`scaffold_entry.enter_project()` is a thin non-authoritative projection and
orchestration boundary. The Agent—not Python keyword matching—turns human
language into structured intent. The entry layer reuses P5 host
classification, delegates Task creation to P7, and projects status/human gates.
It owns no Rules, ownership, SCM, compatibility, Test, Submit, or Task
validation semantics.

`enter_project()` and `project_status()` share the same host-route projection:
NOT_ADOPTED, recovery/established-host consistency, `NEEDS_MIGRATION`, and
`NEEDS_REFRESH` outrank any existing Task. Unresolved candidate/SCM observation,
malformed Task authority, and multiple `IN_PROGRESS` Tasks fail closed to
human/block. Exactly one coherent `IN_PROGRESS` Task with no higher-priority
blocker may project `develop.normal_task`. Status projects lock observation
only; executable package compatibility remains Skill execution preflight.
Status does not evaluate actual package compatibility and does not absorb
C-MIN-005.

## Proposal and activation

Caller prose is never persisted and never becomes canonical Task authority.
P7 normalizes a structured proposal and computes an ephemeral digest over its
canonical Task semantics. Existing Task Books are normalized the same way for
idempotent matching; the digest adds no Task Book field.

Direct `IN_PROGRESS` creation requires all of:

- structured `develop/implement` intent with a current explicit human request;
- intent grounding for goal, scope, acceptance, stages, and tests;
- project grounding for scope, Rules, ownership, and tests;
- valid current project paths/modules/test references;
- resolved ownership registry, applicable Rules, candidate, and currentness;
- no material uncertainty, scope expansion, inferred product decision, or
  governance decision.

Grounded planning intent may publish revision-1 `DRAFT`. Ambiguous intent
publishes nothing and returns `NEEDS_HUMAN`. Intake creates no Session or
source mutation. Intake Skill results report `skill_id=develop`,
`mode=normal_task`, and `extras.operation=task_intake`.

Matching status behavior:

- `DRAFT`: activate only through current grounded explicit implementation
  intent and expected-revision publication;
- `IN_PROGRESS`: reuse;
- `READY_FOR_REVIEW`: surface without reopening;
- `CANCELED`: surface without resurrection; materially new work needs a new
  proposal/identity;
- multiple matches: conflict / `NEEDS_HUMAN`.

Initial creation is serialized with proposal matching, allocates a canonical
P3 ID, validates the ordinary Task schema, and atomically links a fully written
revision-1 file only when the identity is absent. Existing Task updates continue
to use `publish_task` expected-revision semantics.

## Versioning

This is an additive workflow capability, so the live Develop package is
`2.1.0` (MINOR), not a mutation of released `2.0.0`. Its modes remain exactly
`normal_task` and `repair`.

The existing generic manifest declaration `may_substitute_for` names
`develop@2.0.0`. The existing generic evaluator therefore may return
`COMPATIBLE` for a 2.0.0 lock and actual 2.1.0 package, while surfacing 2.1.0
and leaving the lock unchanged. No semantic-version shortcut or
Develop-specific resolver rule exists. Exact 2.1.0 lock adoption remains an
explicit Compatibility lock-update decision.

## Pilot boundary

Internal Pilot #1 requires the Agent to have both the target project and this
known local Distribution checkout/package path available. This is sufficient
for research operation and does not require hand-editing host `.scaffold`.

Automatic Distribution discovery, client installers/bridges, and one-click
teammate setup remain Teammate Alpha/P10 deployment work. PR-1 does not claim
those capabilities.
