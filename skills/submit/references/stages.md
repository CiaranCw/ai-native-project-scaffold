# Submit stages

Exactly S1–S12. There is no S13.

1. S1 Intake — READY_FOR_REVIEW Task, or genuine no-Task only when zero applicable Tasks can be deterministically established; UNKNOWN applicability is not no-Task; host; current candidate
2. S2 Delta Classification — fail-closed real workspace/SCM Diff with exact add/modify/delete/rename/copy identity; true no-SCM hosts require an explicit durable baseline and never treat missing baseline as a clean Diff; P3 conservative provenance; Session memory is advisory
3. S3 Structural Review — real S2 Diff, boundary-aware path+module Task scope, ownership, Rules, bounded structural impact; UNKNOWN is not PASS. Ordinary `skills.lock` modification or deletion remains fail-closed. Lawful first-adoption lock creation (baseline absent, newly added/untracked GENERATED `complete_authoritative` lock bound by current Understand structural authority, executable Submit compatibility, ACTIVE host) may classify as `SCAFFOLD_STRUCTURE` / `DETERMINED` without the generic lock-change blocker. The lock stays visible in S2.
4. S4 Knowledge Consistency — current Understand-owned Knowledge Assessment for knowledge-relevant S3 impacts; lexical path/basename/module mentions are not SATISFIED; missing/stale/UNKNOWN routes to Understand refresh/compatibility; NEEDS_HUMAN is an explicit human blocker
5. S5 Test Completeness — current-candidate P6 evidence; TEST_PASS ≠ TEST_COMPLETE; project Test policy still applies with no Task
6. S6 Review-readiness / S10 apply-intent — default Submit stops review-ready without Git Commit/Push; `request_s10`/`finalize` is candidate-bound machine apply-intent; caller dictionaries are not authority
7. S7 Repository Sync — re-observe candidate plus local configured-upstream currentness; do not fetch/pull/reset/rebase/merge automatically
8. S8 Re-review — material candidate or repository-basis change returns to S3/S4/S5/S6; prior S10 apply-intent does not follow the new candidate
9. S9 Finalize Records — recursively validated candidate Change Record plus only deterministic, ownership-authorized support required by its durable references; not durable history
10. S10 Durable Finalization — exact reviewed candidate + Finalization Bundle tree, or serialized conflict-detectable no-SCM publication under `.scaffold/ext/submit/` with an immutable representation and a COMPLETE marker written last. Git staging uses a recoverable pre-index snapshot; non-durable post-staging failure restores it before candidate support is aborted. A successful Git Commit remains durable even if later verification is unresolved. S10 apply-intent is consumed by this mutation and cannot be reused for a later candidate.
11. S11 Optional Push — every attempt requires a current explicit user Push instruction at the Agent boundary plus the exact S10 Commit and the S10-bound branch; N/A on no-SCM; failed Push does not erase durable S10
12. S12 Cleanup — after successful S10, delete only valid SEALED Sessions in the frozen Change Record target set; cleanup failure is not COMPLETED; S12-only cleanup_retry resumes remaining members of that frozen set without a second S10

If S3 missing source or S5 required FAIL maps deterministically to current Task Stage authority, Submit emits `target_stage_ids` on `submit_to_develop`. It does not guess first, last, or all Stages, and it does not write the Task Book.
