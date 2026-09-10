# FA-2 Batch 4 — Validated Evidence + requirement coverage

This implementation note does not modify or outrank P0–P4.

Batch 4 addresses C-MAJ-016, C-MAJ-017, and C-MIN-003. It preserves the
accepted Batch-3 separation of `TEST_PASS`, terminal coverage, and
required-obligation `test_complete`.

## Completed-report trust boundary

P8 no longer treats a caller-supplied report mapping as Test authority. A
caller supplies `report_id`, or P8 invokes Test. Both paths reload the report
through P6's completed-report reader before S5 consumes it. The reader checks
completed publication, storage/report identity, report schema and semantics,
and every locally resolvable Evidence Ref digest. P8 then separately checks
the current candidate.

`report=<dict>` is not a frozen public interface of `submit@2.0.0`: neither
the package manifest nor normative package text declares that input. Rejecting
it is runtime conformance to the existing S5 requirement for
current-candidate P6 Evidence.

## Required-obligation coverage

Task `requirement_id` remains a planned-requirement identity. It is never
matched to a Test profile by name. Its frozen join to Test is
`evidence_ref.locator`.

At S5, each Task stage/final required-test locator must resolve through P6 to
Evidence in a valid completed report for the current candidate. The resolved
profile accounting must be terminal, evidence-complete, and PASS to satisfy
the obligation. FAIL routes to Develop repair. Missing, conflicting,
unresolvable, BLOCKED, or NOT_RUN Evidence routes to scoped verification.
`observed_outcome` is advisory and must agree with resolved P6 truth.

Repeated Task requirement IDs dedupe only when their Evidence locator and any
observed outcome are coherent. Project `tests.yaml` required profiles remain a
separate set and are proven by required profile identities in the validated
primary report.

Batch 4 does not publish Evidence locators back into Task Books. Candidate-
bound Task mutation and Stage/READY compare-and-swap progression remain later
Develop lifecycle work.

## P6-owned locator protocol

P6 mints locator-only references under `test-runs/<run-id>/...`. Resolution
reloads the owning completed report and preserves the original Evidence kind.
For a local artifact, the digest-bearing full P6 Evidence Ref is recovered
from the report and checked. Result-bearing Evidence embedded in the completed
report may use a P6 report-fragment locator. HUMAN, CI, and EXTERNAL Evidence
are not rewritten as command results.

P8 Change Records copy only locators minted or successfully resolved by P6.
They do not format a second locator syntax. S12 remains limited to linked
Develop Session cleanup.

## Durable locator retention

Under `FA2-FND-001`, S9 may ask P6 to materialize only the Evidence locators
that the candidate Change Record durably references. P6 writes deterministic
metadata capsules and, only when needed, deterministic raw-byte sidecars under
`.scaffold/ext/test/evidence/`. Every concrete target must already resolve to
whole-file `GENERATED` ownership under the existing Project ownership rules;
S9 never edits `project.yaml`.

Current-report trust and durable-history resolution are separate. The runtime
`load_completed_report(report_id)` path always validates current temporary
state and fails on corruption. A durable Change Record locator resolves from
its valid capsule even if stale or corrupt runtime state with the same run
identity remains. After S10 durable finalization, ordinary
`cleanup_test_run()` may delete that temporary run without breaking the
locator. Cleanup instead blocks while the P6 materialization is PREPARED.

Physical capsule existence is not durability authority. While any P6
coordination for a locator remains `PREPARED`, public resolution uses valid
runtime Evidence only. Missing or corrupt runtime state then fails closed and
requires P8 durability reconciliation. Only after P8 establishes S10
durability and releases/reconciles that coordination may the capsule report
`resolution_source=durable`.

`reviewed_candidate_digest` (`C`) remains the Evidence/S3–S6 identity.
`finalization_candidate_digest` (`F`) is `C` plus the exact S9 Finalization
Bundle and binds S10. P6 usability is not re-evaluated against `F`; any
mutation beyond the expected Change Record and P6-returned support set still
invalidates finalization. Durable support paths are not retroactively added to
the reviewed business/source Diff recorded by the Change Record.

## Versioning and boundaries

`test@2.0.1` remains the same unreleased Batch-3 candidate; no `2.0.2` is
created. The FA2-FND-001 S9 Finalization Bundle is a normative Submit workflow
extension, so the controlled Batch-4 package is `submit@2.1.0` and truthfully
declares `may_substitute_for: submit@2.0.0`. `skills.lock` is not rewritten.
This does not make generic non-Understand compatible-substitution selection
reachable; C-MIN-005 remains reproducible and open.

Retention closure is exercised by B4R01–B4R15: exact Git/no-SCM bundle
membership, ordinary P6 cleanup, unreferenced-run deletion, ownership
fail-closed behavior, tamper/unexpected-path rejection, PREPARED abort and
reconciliation, durable-but-blocked preservation, non-local Evidence
semantics, portable/minimal support, corrupt-runtime independence, and the
explicit `C`/`F` identity split. B4V01–B4V02 preserve the `2.0.0` lock while
surfacing the controlled direct `2.1.0` package and keep C-MIN-005 open.

B4R16 freezes the PREPARED-versus-durable resolution barrier. B4R17–B4R18
freeze S10 Git-index transactionality: fallible identity checks occur before
staging, the exact pre-staging index is recoverably snapshotted, and every
non-durable post-staging failure restores that index before P6 candidate
support is aborted. Successful Commit durability never rolls back. A failed
rollback preserves both P8 index-recovery coordination and P6 PREPARED state
for a later pre-S2 reconciliation.

C-MAJ-001, C-MAJ-003, C-MAJ-007, C-MAJ-008, C-MAJ-009, C-MAJ-015,
C-MAJ-013/014/018, and C-MAJ-019 are not absorbed by this batch.
