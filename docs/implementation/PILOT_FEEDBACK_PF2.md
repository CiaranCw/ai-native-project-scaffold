# Pilot Feedback PF-2 — Existing human AGENTS Adoption integration

This implementation note does not modify or outrank P0–P4.

PF-2 is a targeted P5 Adoption correction from reproduced internal Pilot
evidence. It does not approve B4 for DIVE, start FA-2 Batch 3, productize
Distribution, or redesign Foundation.

## Defect

An unadopted host with an ordinary HUMAN_OWNED `AGENTS.md` (valid project
instruction text, not a Scaffold Layer-1 router) previously produced:

- `PRESERVE` + `HUMAN_OWNED` + `client_strategy=DEFER`
- `agents_scaffold_bridge` CONFLICTING / critical
- `activation_blockers: agents_scaffold_bridge:CONFLICTING`

The Adoption Plan could be approved and applied, but B7 always failed because
it reused the stale pre-Apply bridge fact. Ordinary first-time Adoption could
not reach ACTIVE.

Z19 remains: explicit anti-Scaffold text (`Do not use scaffold metadata.`) is
DEFER and cannot activate. Z20 remains: a genuine existing thin bridge is
PRESERVE / THIN_BRIDGE and is not rewritten.

## Foundation case

P2 already authorizes:

- no file → GENERATED whole-file router
- existing file, approved integration region → MANAGED region only
- existing file remains human text → HUMAN_OWNED + THIN_BRIDGE / pointer
- no silent whole-file replace

THIN_BRIDGE is the P1 client-entry strategy. Realization uses only generic B3
classes. The ordinary safe case is `MANAGED_UPDATE` of a unique bounded
region:

```text
<!-- scaffold:managed:agents-router:start -->
…thin router body…
<!-- scaffold:managed:agents-router:end -->
```

Human bytes outside that region stay. The file is not deleted/recreated, and
human instructions are not moved elsewhere.

## B3 proposal

Classification (helper, not a new record/mode/Skill):

| State | B3 |
|---|---|
| absent | CREATE GENERATED |
| genuine router (whole file or unique managed region) | PRESERVE + THIN_BRIDGE |
| safe ordinary human text | MANAGED_UPDATE + MANAGED + THIN_BRIDGE |
| unsafe (broken markers, unreadable, explicit anti-Scaffold) | PRESERVE + DEFER; no guess |

B3 does not edit `AGENTS.md`. The proposed mutation is in the envelope, action
list, human-facing Plan, and Plan digest. A material strategy/envelope change
invalidates the previous digest-bound approval.

When `MANAGED_UPDATE` is proposed, Plan `activation_blockers` omit the
pre-Apply `agents_scaffold_bridge:CONFLICTING` fact because that fact is the
condition the approved mutation is intended to resolve. Unsafe/DEFER plans
still list it.

## Durable managed-region authority (PF2-R1)

`ownership.AGENTS.md: MANAGED` stays the whole-artifact mode. Approved region
id `agents-router` is recorded in adjacent `project.yaml` `managed_regions`.
The Adoption Plan action carries the same `managed_region` so it participates
in Plan digest binding. After B9 session cleanup, later Agents read the
registry plus `AGENTS.md` markers. Registry/marker disagreement is CONFLICTING
and is not silently repaired.

## Human-conflict precedence (PF2-R2)

Classification order:

1. malformed managed markers → UNSAFE
2. explicit whole-file human anti-integration / no-edit (outside the region)
   → UNSAFE / DEFER
3. only then a valid approved `agents-router` region → GENUINE

A previously valid Scaffold region does not mask later human text such as
“Do not use Scaffold.” or “Do not modify AGENTS.md.” Ordinary unrelated
instructions are not a blacklist.

## B7

B7 re-discovers the host after Apply. A successful approved integration that
actually established a VERIFIED Layer-1 bridge may activate. If the approved
region/bridge did not materialize, B7 fails closed. The stale pre-Apply
blocker is not suppressed.

## Human-facing gate

Canonical blockers may still name B4 internally. Human-facing presentation
(`extras.human_gate` / `present_result`) uses plain language, for example:

“Review and approve this Adoption Plan before any project files are changed.”

No result-schema redesign.

## Explicitly not absorbed

C-MAJ-001, C-MAJ-002, C-MAJ-003, C-MAJ-005, C-MAJ-007, C-MAJ-008, C-MAJ-009,
and C-MAJ-013 through C-MAJ-019 remain open. Observed tests ≠ REQUIRED tests
remains FA-2 Batch 3. Distribution installer/catalog is not started here.
