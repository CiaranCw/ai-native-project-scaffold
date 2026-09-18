# DIVE Pilot Scaffold Correction 01

Post-P10 real-pilot correction. This is **not** P11.

Historical status remains:

- FA-2: PASS / CLOSED
- P9: PASS / CLOSED
- P10: PASS / CLOSED

This note records three real-pilot gaps found on DIVE Day-1 evidence. The DIVE
repository is evidence only and is not modified here.

## Finding A — knowledge currentness

A refresh completion that binds stub knowledge digests cannot remain CURRENT
after later enrichment of those knowledge files. Physical source equality is
not knowledge currentness.

Invariant: for every module knowledge entry covered by the current
Understanding head, current bytes digest MUST equal the completion
`knowledge_digest`. `output_locator` / `output_digest` must resolve to real
`result.yaml` bytes. Missing or mismatched output authority fails closed.

The completion producer binds **final** Understand-produced knowledge. Existing
GENERATED knowledge is bound as-is unless the Understand operation supplies a
replacement payload. Post-receipt enrichment without a new completion cannot
stay CURRENT.

## Finding B — Scenario-Aware Verification

Scenario-Aware Verification is Test-owned supporting authority:

`.scaffold/runtime/test-plans/**`

`supporting: true`, `canonical: false`. Not a fifth Skill. Not a fourth
canonical record. Not a replacement for Test Profile or Task Book.

A fresh Test Agent reconstructs **current applicable** SAV authority only when
the live Task Book, revision, requirement, `test_profile` binding, and optional
candidate digest still match. Reconstructable plan bytes are not enough.
`publish_sav_plan` may keep a historical plan file but MUST NOT install a
current-head without that same live authority. Publication, reconstruction, and
TestEngine execution share `revalidate_sav_plan`.

Caller `sav_evidence` is compiled through existing P6 supplied-evidence
provenance rules. It cannot claim `LOCAL_EXECUTION`, and omitted provenance
does not become `HUMAN_OBSERVATION`. Feature POs may be satisfied by lawful
`EXTERNAL_RESULT` (explicit current `candidate_digest`) or explicit
`HUMAN_OBSERVATION` under existing human-evidence rules. Internal verifier
execution uses `EXTERNAL_RESULT` / `mechanism: verifier_execution`, not human
provenance.

Versioning: `test@2.0.1` is the current unreleased candidate. SKILL_CONTRACT
requires a version change when a **released** identity gains materially
different normative behavior. This candidate is unreleased and is extended
in place, matching P10's treatment of `understand@2.1.0`. Released
`test@2.0.0` is not mutated.

## Finding C — Bootstrap exact-plan apply (historical; superseded by PC-R4)

Historical finding: generic “Adopt this project” / “Run Day-1 Bootstrap”
authorized preview only and required explicit human approval of an exact
Adoption Plan.

Current behavior: that generic instruction authorizes the Agent to enter
Bootstrap, preview, and apply the generated `plan_id` / `plan_digest` when
machine preconditions still hold. `--approved --plan-digest` is the apply
request, not human Git Commit/Push authority. Agents must not invent Git
Commit or Push permission from chat intent. Preview is still not apply:
persistent Adoption mutation uses that exact Plan.

## Review-package locator completeness

When a package claims currentness authority for review, include the transitive
supporting locator targets needed to verify digests. `completion.yaml` requires
its referenced `result.yaml`. Do not dump the whole runtime tree.

## Preservation

Exactly four Skills. Exactly three canonical development records. P9 Repair
and Migration, P10 ownership / CAS / fail-closed routing, and Submit S1–S12
are not reopened.
