# FA2-FND-001 — Deterministic S9 Finalization Support Artifacts

Status: candidate Foundation amendment; requires independent re-audit.

This post-FA-1 amendment closes the Foundation gap that blocked the retention
half of FA-2 Batch 4 C-MIN-003. It does not implement the Batch-4 runtime
mechanism and does not retroactively pretend that FA-1 contained this rule.

## Reason

The prior Foundation made S6 authorization candidate-bound and allowed S9 to
add the deterministic Change Record before S10. It also required any other
material S9 mutation to return through S3–S6. That left no defined treatment
for minimal durable P6 Evidence support bytes needed by an opaque locator in
the Change Record after `.scaffold/runtime/` expires.

Keeping runtime forever would conflict with the Project Contract. Adding a
tracked Evidence representation at S9 without an amendment would conflict with
candidate-bound review.

## Amended clauses

- Constitution Submit S7–S10: permits only the exact deterministic S9
  Finalization Bundle without a second S6 approval.
- Records Contract §§23–24: defines the bundle, deterministic support
  constraints, exact S10 binding, and candidate-only failure/recovery state.
- Records Contract §30: requires durable P6 locator resolution after ordinary
  runtime expiry.
- Records Contract §35: preserves P6 Evidence ownership and P8 finalization
  orchestration.
- Project Contract §§8 and 26: recognizes the existing namespaced
  `.scaffold/ext/<namespace>/` boundary for owned durable support artifacts.

## Frozen decision

The S9 Finalization Bundle is:

```text
exact deterministic Change Record
+
zero or more minimal deterministic support artifacts required solely by
durable references in that Change Record
```

The exception is valid only when the final support set and semantic content are
deterministic consequences of authority and Evidence already validated before
S6. Support artifacts add no business/source intent, are produced by their
authority owner, use an already-authorized durable boundary and existing
ownership mode, and belong to the exact S10 finalization candidate.

Any unrelated, substantive, unexpected, or non-deterministic S9 mutation is
not exempt. It invalidates the prior authorization and returns through S3–S6.
No S13, second permission, fourth canonical record, fifth Skill, or fourth
ownership mode is introduced.

## Test Evidence specialization

P6 owns Test Evidence materialization, physical representation, integrity, and
resolution. P8 may request materialization only through already-validated
opaque Evidence references and owns whether the resulting bundle becomes
durable. P8 does not construct the Test storage layout, and P6 gains no Commit
or Submit authority.

Foundation does not freeze an extension namespace spelling. A later Batch-4
implementation may select one stable P6 namespace under `.scaffold/ext/` and
must retain only the minimal report/Evidence/integrity material needed for
resolution. It must preserve HUMAN, CI, and EXTERNAL Evidence provenance rather
than converting all Evidence to local command results.

P6 Evidence continues to validate the reviewed substantive candidate. The S9
artifact is a deterministic retained representation of that already-validated
truth, not evidence that newly introduced business content was tested.

## Failure and durability

Before S10 success, prepared support artifacts are candidate-only. A
non-durable S10 exit requires deterministic cleanup or recoverable
coordination. Temporary coordination may use `.scaffold/runtime/` but is not
durable Evidence authority.

For Git, every tracked support artifact must be present in the exact S10 Commit
tree. For no-SCM, the same logical bundle must participate in the existing
P8-owned atomic or conflict-detectable finalization. This amendment does not
redesign no-SCM publication.

After durable S10, public P6 locators in the Change Record must remain
resolvable from durable support even when the originating runtime Test-run
directory no longer exists.

## Foundation acceptance cases

- **FND-E01:** reviewed candidate C, validated P6 Evidence E, current S6
  authorization for C, the deterministic Change Record reference to E, and
  E's minimal deterministic retained representation form one permitted S9
  Finalization Bundle without a second S6 approval.
- **FND-E02:** unrelated source, business, or configuration content written at
  S9 is outside the bundle, invalidates the prior authorization, and returns
  through S3–S6.
- **FND-E03:** retained bytes not deterministically derivable from the
  pre-S6-validated Evidence and exact Change Record references are outside the
  exception.
- **FND-E04:** on Git, a Change Record that points to a retained tracked
  artifact absent from the exact S10 Commit tree is not validly finalized.
- **FND-E05:** failed or interrupted S10 leaves support artifacts
  candidate-only and requires deterministic cleanup or recovery.
- **FND-E06:** after durable S10, ordinary removal of
  `.scaffold/runtime/test-runs/<run-id>/` cannot break public P6 resolution of
  the Change Record's durable locator.
- **FND-E07:** the amendment introduces no fourth canonical record, ownership
  mode, top-level Skill, Submit stage, or human authorization.

## Downstream work and required re-audit

FA-2 Batch 4 must be re-planned against this amended authority before it adds:

- the P6 durable representation and resolver fallback
- transient S9-to-S10 coordination
- P8 materialization and exact-bundle finalization
- cleanup/recovery behavior
- B4R01–B4R08 retention regressions

Independent re-audit must verify candidate-bound authorization, deterministic
derivation, minimal retention, ownership coverage, exact Git/no-SCM bundle
binding, runtime independence, and non-escalation between Submit and Test.

C-MAJ-001, C-MAJ-003, C-MAJ-007, C-MAJ-008, C-MAJ-009, C-MAJ-013,
C-MAJ-014, C-MAJ-015, C-MAJ-018, C-MAJ-019, remaining MINOR findings, Batch 5,
and P9 remain outside this amendment.
