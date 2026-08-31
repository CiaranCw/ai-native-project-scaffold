# Submit stages

Exactly S1–S12. There is no S13.

1. S1 Intake — READY_FOR_REVIEW Task, host, current candidate
2. S2 Delta Classification — fail-closed real workspace/SCM Diff with exact add/modify/delete/rename/copy identity; P3 conservative provenance; Session memory is advisory
3. S3 Structural Review — real Diff, scope, ownership, core artifacts
4. S4 Knowledge Consistency — stale knowledge routes to Understand refresh/compatibility
5. S5 Test Completeness — current-candidate P6 evidence; TEST_PASS ≠ TEST_COMPLETE
6. S6 Human Approval — candidate-bound SUBMIT_AUTHORIZED; default false
7. S7 Repository Sync — re-observe; do not reset/rebase/merge automatically
8. S8 Re-review — material candidate change returns to S3/S4/S5/S6
9. S9 Finalize Records — recursively validated candidate Change Record; not durable history
10. S10 Commit / Durable Finalization — exact SCM tree + CR Commit, or serialized conflict-detectable no-SCM publication. A successful Git Commit remains durable even if later verification is unresolved.
11. S11 Optional Push — every attempt requires separate candidate-bound authorization, the exact S10 Commit, and the S10-bound branch; N/A on no-SCM
12. S12 Cleanup — delete exact identity-linked valid SEALED Sessions only after successful S10
