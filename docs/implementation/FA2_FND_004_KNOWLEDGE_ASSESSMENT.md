# FA2-FND-004 — Candidate-Bound Knowledge Consistency Assessment

Status: candidate Foundation amendment; requires independent re-audit.

This amendment resolves the Foundation gap that correctly stopped
FA2-REAUDIT-MAJ-002 residual correction. It does not add a fifth Skill, S13, a
fourth canonical development record, or a second project candidate digest. It
does not claim FA-2 PASS, FA-2 CLOSED, or P9 unblocked.

Released `understand@2.0.0` is immutable and does **not** include this
amendment. The FND-004 candidate lives in `understand@2.1.0`, a MINOR
backward-compatible workflow extension. Established hosts locked to released
`2.0.0` MAY evaluate `2.1.0` as `COMPATIBLE` when the package's
`may_substitute_for` declaration applies. Pre-adoption Bootstrap still requires
the exact release-pinned Understand package. This amendment MUST NOT be
rewritten as historical `2.0.0` behavior.

## Reason

Constitution Submit-S4 must determine whether real source/asset/config changes
have made project knowledge stale. Mapped documentation pathname, unrelated
current documentation edits, and pre-existing path/module mentions are already
insufficient. Material UNKNOWN must not become PASS.

The previous Batch-6 / Tranche-B implementation still treated current added text
containing an impacted path, basename, or module id as SATISFIED. That
lexical co-occurrence is unsound. Example that MUST NOT PASS:

```text
Weekly formatting note: api.py was spell-checked;
this does not document any public interface change.
```

P5/P8 had no structured current-candidate proof that impact X was assessed as
covered by knowledge surface Y. This amendment creates that supporting
authority.

## Frozen responsibility split

- Submit-S3 owns structural-impact detection from the real Diff.
- Submit-S4 owns validation that each current knowledge-relevant S3 impact
  has current Understand Knowledge Assessment authority.
- Understand owns semantic project-knowledge assessment / Refresh.

Submit MUST NOT manufacture semantic relevance by inspecting path/module
keywords. When S4 cannot establish current knowledge authority, it routes to
`understand.refresh`. No new Understand top-level mode is created.

## Knowledge Assessment

Knowledge Assessment is an Understand-owned **supporting artifact**. It is
not a Task Book, Develop Session, or Change Record, and MUST NOT be described
as a fourth canonical development record.

Runtime location:

```text
.scaffold/runtime/understand-assessments/<assessment-id>/assessment.yaml
```

The artifact is excluded from P6 candidate identity through the existing
`.scaffold/runtime/` exclusion. P6 remains the single public candidate identity.

Producer publication is atomic. The public locator is:

```text
understand-assessments/<assessment-id>/assessment.yaml
```

P8 consumes the P5 current-head for the exact `(candidate_digest, impact_digest)`
binding. Candidate + impact equality alone is not enough. A raw caller
dictionary such as `{outcome: SATISFIED}` is not S4 authority. An explicit
`knowledge_assessment_ref` is accepted only when it equals that current head
and the published Assessment bytes still match the head integrity digest.

## Current head / supersession

For each exact binding `(candidate_digest, impact_digest)` there is exactly one
authoritative CURRENT Knowledge Assessment head:

```text
.scaffold/runtime/understand-assessments/heads/<binding-digest>/head.yaml
```

The head binds candidate digest, impact digest, Assessment locator/record id,
and the exact published Assessment digest. It is a P5 runtime supporting
artifact, not a canonical development record, and is excluded from P6
candidate identity through `.scaffold/runtime/`.

When P5 publishes Assessment B for the same C/I, B supersedes A. A remains a
historical runtime file and MUST NOT be S4 authority, including SATISFIED →
UNKNOWN and UNKNOWN → SATISFIED. P8 MUST NOT scan runtime assessments by
timestamp, record id, or lexical order. Missing, malformed, unresolvable,
integrity-mismatched, candidate-mismatched, impact-mismatched, or ambiguous
current-head state is UNKNOWN / not PASS.

## Binding

A Knowledge Assessment is usable only when:

- `assessment.candidate.candidate_digest` equals the current P6
  `candidate_digest`
- `assessment.impact_digest` equals the current S3 knowledge-relevant impact
  digest

Impact identity is one shared canonical projection of class, path, status, and
bounded structural detail. If S3 impact semantics change materially, old
assessments are unusable.

After Understand Refresh mutates project/knowledge files, C1 becomes C2. The
assessment used after Refresh MUST bind C2. A C1 assessment MUST NOT support
C2.

## S4 PASS rule

For each knowledge-relevant determined S3 impact, S4 may treat the impact as
knowledge-consistent only when a current validated Understand Knowledge Assessment
has `outcome = SATISFIED` for that exact current impact, is the current-head for
the exact `(candidate_digest, impact_digest)` binding, and its published bytes
still match the head integrity digest. All required impacts must be SATISFIED.
Candidate + impact equality alone is not enough.

`NEEDS_REFRESH`, `NEEDS_HUMAN`, and `UNKNOWN` prevent S4 PASS. Missing
assessment, missing/broken current-head, superseded locator, and integrity
mismatch are UNKNOWN / `understand.refresh`, not PASS. Partial coverage,
candidate mismatch, and impact-digest mismatch are not PASS. Boolean false
MUST NOT represent UNKNOWN.

Non-structural changes with no knowledge-relevant S3 impact do not require
documentation churn.

## Lexical information is non-authoritative

The following MAY be used for routing, surface discovery, search, or review
assistance, but MUST NOT independently establish SATISFIED:

- mapped doc pathname appears in the Diff
- impacted path appears in prose
- basename appears in prose
- module id appears in prose
- impact class appears in prose
- any combination or count of those tokens

Do not replace one-keyword heuristics with two-keyword or full-path
heuristics.

## Understand semantic result

Understand is the semantic knowledge owner. Generic Python string matching
cannot prove arbitrary free-form prose correct. Allowed per-impact outcomes
are exactly `SATISFIED`, `NEEDS_REFRESH`, `NEEDS_HUMAN`, and `UNKNOWN`.

Understand MUST respect ownership. HUMAN_OWNED whole-file surfaces are not
silently overwritten to make S4 pass. Understand may assess them as already
satisfactory, return `NEEDS_HUMAN` / `UNKNOWN`, or identify the exact surface
requiring human correction.

## Change Record

Change Record `knowledge_updates` / `understand_involvement` remain S9 final
summaries. They are not S4 authority and MUST NOT justify S4 retroactively.

## Affected authority

- Constitution §10 S4
- Records Contract §§3, 39, 40, and 41
- Skill Contract Submit→Understand Refresh boundary
- P5 Understand Refresh publication
- P8 Submit S4 validation

## Expected cases

| ID | Case | Behavior |
| --- | --- | --- |
| **FND4-E01** | Structural impact + no Knowledge Assessment | S4 not PASS; route Understand |
| **FND4-E02** | SATISFIED assessment for current C and exact impact I | S4 may PASS |
| **FND4-E03** | Assessment for C1 used after candidate becomes C2 | stale / blocked |
| **FND4-E04** | Candidate current but impact digest differs | blocked |
| **FND4-E05** | Assessment covers only a subset of required impacts | blocked |
| **FND4-E06** | Outcome UNKNOWN | blocked / Understand route |
| **FND4-E07** | Outcome NEEDS_HUMAN | explicit human blocker |
| **FND4-E08** | Runtime assessment artifact exists | P6 candidate digest unchanged |
| **FND4-V01** | Live Understand identity after FND-004 | no longer released `2.0.0`; candidate `2.1.0` |
| **FND4-V02** | SKILL.md header and skill.yaml identity | agree; package VALID |
| **FND4-V03** | Live Understand candidate package validation | VALID |
| **FND4-V04** | Established host locked to released `2.0.0` | live `2.1.0` is COMPATIBLE, not EXACT; lock unchanged |
| **FND4-V05** | Pre-adoption Bootstrap | exact release-pinned Understand; live `2.1.0` is not pre-lock substitution |
| **FND4-V06** | Released `understand@2.0.0` | does not represent FND-004 semantics |
| **FND4-C01** | SATISFIED A then UNKNOWN B; explicit A | A superseded; S4 not PASS |
| **FND4-C02** | Same; explicit B | UNKNOWN; S4 not PASS |
| **FND4-C03** | UNKNOWN A then SATISFIED B | B may PASS; A cannot |
| **FND4-C04** | No explicit locator | resolve current head only; no scan |
| **FND4-C05** | Artifacts exist; current head missing/broken | UNKNOWN; P8 does not guess |
| **FND4-C06** | Assessment bytes mutated after head publication | integrity mismatch; S4 not PASS |
| **FND4-C07** | C1 head then candidate becomes C2 | old head stale; not PASS |
| **FND4-C08** | Candidate C stays; S3 impact I1 → I2 | I1 head cannot support I2 |
| **FND4-C09** | Current-head publication | P6 candidate digest unchanged |
| **FND4-C10** | Fresh process reads project-local runtime state | recovers the same current Assessment authority |
