# P10 Incremental Understanding / Multi-Agent

This note records the compressed P10 zero-context resume and incremental
understanding capability. It is not a Foundation Contract and does not outrank
P0–P9.

P10 status: **PASS / CLOSED.** Post-P10 real-pilot corrections are recorded in
[DIVE_PILOT_CORRECTION_01.md](DIVE_PILOT_CORRECTION_01.md) through
[DIVE_PILOT_CORRECTION_05.md](DIVE_PILOT_CORRECTION_05.md) and do not reopen
P10. DIVE Day-1 is not closed. P11 is not started. This tree is not a v2.0
release.

P9 Repair/Migration remains PASS / CLOSED. P10 consumes Repair, Migration,
Test, and Submit authority; it does not reimplement them.

## Product intent

A fresh Agent with no prior conversation can enter an already normalized
project and determine, from project-local durable truth:

- what the project is;
- which modules exist;
- what changed since the last trustworthy understanding;
- which Tasks, Sessions, Repair, Migration, Test, and Submit states exist;
- what is stale or UNKNOWN;
- what to read or do next.

Physical observation decides **what** requires refresh. A distinct Understand
refresh-completion receipt decides **whether** that refresh has actually
occurred against the exact observed bytes. Observing a new module digest is
not proof that those bytes were re-understood. `incremental=true` is a caller
request, not completion authority.

Existing valid understanding plus physical project change yields a bounded
refresh **scope** when module mapping is deterministic. Structural or
ambiguous change fails closed to `FULL_REFRESH_REQUIRED` / `UNKNOWN`.

## Non-goals

P10 is not a multi-Agent orchestration platform, scheduler, message broker,
distributed lock service, worktree manager, Scenario-Aware Verification
design, or real DIVE implementation.

Exactly four Skills. Exactly three canonical development records. Submit
remains S1–S12. UNKNOWN remains valid.

## Entry contract

Client-neutral project-local entry:

```text
Understand refresh  action=resume
Understand refresh  action=understand   [incremental=true]
```

Natural language maps to those actions. There is no fifth routing engine.

- “Continue this project.”
- “Understand the current state and tell me what needs doing.”

→ `refresh action=resume`

`AGENTS.md` remains a thin router. It must not become a duplicated project
database.

Default `refresh` with no action remains GENERATED/MANAGED knowledge refresh.

## Currentness model

```text
CURRENT
PARTIAL_REFRESH_REQUIRED
FULL_REFRESH_REQUIRED
UNKNOWN
```

Physical authority:

- per-module file digests under declared `modules.yaml` paths;
- structural digest of `modules.yaml`, `commands.yaml`, `tests.yaml`,
  `skills.lock`, and selected `project.yaml` identity fields
  (schema, contract generation, ownership, source areas, capabilities).

Not authority: timestamps, Agent claims, “last reviewed” prose, Task title,
or changed-filename lexical hints alone.

| Observation | Result |
| --- | --- |
| No current-head snapshot | `FULL_REFRESH_REQUIRED` |
| Malformed head / digest mismatch | `UNKNOWN` |
| Structural / module-set / unmapped-path change | `FULL_REFRESH_REQUIRED` |
| One or more declared module digests changed, mapping bounded | `PARTIAL_REFRESH_REQUIRED` |
| Physical digest matches current-head | `CURRENT` only if snapshot completion locators still bind current knowledge bytes and output artifacts |

Caller may request incremental persist. Observation decides the required
scope. Incremental request plus `FULL_REFRESH_REQUIRED` / `UNKNOWN` is
rejected; stale understanding is not reused.

A new current-head may become `CURRENT` only after Understand-produced
refresh-completion authority covers the required scope and still binds the
exact current source/module digests, structural digest, output locator
digest, **and current knowledge-file digest**. Persist consumes completions; it
does not self-attest them. Physical source equality cannot hide later
knowledge-byte drift.

Refresh-completion receipts do not create mutation authority. Knowledge
mutation still follows `project.yaml` ownership resolved by
`resolve_ownership(...)` (exact, directory/area, CONFLICTING, UNKNOWN).
`ownership.get(path)` is not authority.

| Resolved ownership | Refresh-completion knowledge mutation |
| --- | --- |
| GENERATED (exact or area) | Lawful whole-file generated knowledge write |
| MANAGED | Bounded registered region only; otherwise fail closed |
| HUMAN_OWNED (exact or area) | Preserve bytes; no binding marker; `NEEDS_HUMAN` if that surface must refresh |
| UNKNOWN existing file | No mutation; not CURRENT |
| UNKNOWN absent file | Register exact GENERATED through existing Refresh ownership authority, then re-observe, then write; never leave Scaffold-touched knowledge UNKNOWN |
| CONFLICTING | Fail closed |

If a lawful operation registers GENERATED ownership, that `project.yaml`
mutation happens before the structural digest bound into the completion is
observed. Completions never bind a stale pre-registration structural digest.

Knowledge Assessment (FA2-FND-004) remains S4 supporting authority. A stale
SATISFIED Assessment cannot establish current project understanding.

## Supporting artifacts

```text
.scaffold/runtime/understand-currentness/<uc-id>/snapshot.yaml
.scaffold/runtime/understand-currentness/heads/project/head.yaml
.scaffold/runtime/understand-currentness/completions/<rc-id>/completion.yaml
.scaffold/runtime/understand-currentness/completions/<rc-id>/result.yaml
.scaffold/runtime/understand-currentness/handoff.yaml
```

These are SUPPORTING, not canonical. Refresh-completion receipts are
`supporting: true` / `canonical: false`. They are not a fourth canonical
development record, Handoff Record, Agent Record, or Understanding Record.

`handoff.yaml` is derived, locator/digest-bound, and non-authoritative. If it
is stale, a fresh Agent reconstructs from canonical records and current heads.

Missing runtime currentness fails closed; it is not required durable handoff
in the P2 sense. Reconstructable work still comes from Task Book / Session /
Repair / Migration / Test / Submit authority.

## Zero-context resume surfaces

Resume reports separate surfaces. It does not invent a single collapsed
project status.

- PROJECT: identity, lifecycle, contract generation, compatibility/versions
- UNDERSTANDING: currentness, modules, locators, refresh reasons
- WORK: Tasks, Sessions, READY, Repair, Migration / `RECOVERY_REQUIRED`,
  plus derived `durably_finalized_task_ids` / `continuable_ready_task_ids`
- TEST: recorded required failures/blockers from existing Repair/Test state
- SUBMIT: historical READY Tasks, derived durable-finalization ids, and
  Submit index-recovery presence
- NEXT_ROUTE: one truthful route token

Route tokens:

`understand.bootstrap` | `understand.refresh` | `develop.continue` |
`develop.repair` | `test` | `submit` | `migration.recovery` | `human` | `none`

`summary` is convenience prose. `authority` is reconstructed from locators and
digests.

## Routing precedence

1. Not adopted → `understand.bootstrap`
2. Migration `RECOVERY_REQUIRED` / isolation → `migration.recovery`
3. `NEEDS_MIGRATION` without recovery → `human`
4. Malformed, unreadable, or orphaned canonical Task Book / Develop Session
   authority → `human`
5. Submit index recovery → `submit`
6. Multiple continuable Tasks and no `task_id` → `human`
7. Repair supporting state bound to a **continuable** Task → `develop.repair`
8. Required Test failure bound to a **continuable** Task without repair state → `test`
9. Exactly one **continuable** `READY_FOR_REVIEW` Task → `submit`.
   Historical READY Tasks already consumed by proven S10 Change Record
   durability are excluded from this route. Task Book status is not rewritten.
10. Understanding `FULL` / `UNKNOWN` → `understand.refresh`
11. Understanding `PARTIAL` → `understand.refresh`
12. Unique IN_PROGRESS / OPEN Session on a **continuable** Task → `develop.continue`
13. Else → `none`

Zero-context resume must not filter broken canonical work authority and then
route from the remaining healthy subset. `submit`, `develop.continue`,
`develop.repair`, and `test` are not selected from an incomplete filtered
Task/Session universe.

P10 does not pick “the project Task” when several legal targets exist.

## Replay / CAS

Repeated resume with no change creates no new current-head.

Repeated `action=understand` against already-current physical state is a
no-op.

Publication may supply `expected_head_digest`. A mismatch is BLOCKED. At most
one current-head exists for project-scope understanding.

## Versioning

Live Understand candidate remains `understand@2.1.0`. P10 is a backward-
compatible workflow extension of the already unreleased 2.1.0 candidate.
Released `understand@2.0.0` is not mutated. Develop/Test/Submit were not
bumped.

## Tests

Focused suite: `tests/test_p10_incremental_multiagent.py` (P10-U01..U08,
P10-H01..H08, P10-X01..X08, P10-Y01..Y08, P10-Z01..Z10, current-head identity,
local current-head CAS/concurrency, fresh-agent E2E, DIVE-shaped pre-pilot).
