# Submit

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `submit`
- `skill_version`: `2.0.0`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: none beyond the frozen internal Submit-S1…S12 stages

This package provides `submit.review`. Submit is the fourth top-level Skill. It is not Develop, not Repair, not Migration, and not a fifth Skill.

Submit owns independent final review of the real candidate Diff, Structural Review, Knowledge Consistency, Test Completeness, the candidate-bound human `SUBMIT_AUTHORIZED` gate, Repository Sync, the S8 re-review loop, Change Record finalization, S10 Commit / no-SCM durable finalization, optional separately authorized Push, and post-success Develop Session cleanup.

Submit MUST NOT invent a Task Book, manufacture `READY_FOR_REVIEW`, treat `TEST_PASS` as `TEST_COMPLETE` or `SUBMIT_AUTHORIZED`, silently edit source by becoming Develop, reuse C1 authorization for C2, or persist a reusable `submit_authorized` bit.

If substantive implementation repair is required, Submit returns a bounded `submit_to_develop` handoff. Repair remains Develop `mode=repair`.

Git Diff observation is fail-closed and preserves deletion/rename identity through exact S10 staging. Git Commit truth—not a post-Commit marker—establishes Git durability. No-SCM publication is serialized, atomically written, and binding-validated. Push is bound to the exact S10 Commit and the S10-bound branch, never to a later HEAD or later checkout. Push failure injection never bypasses separate Push authorization or exact-Commit validation. Cleanup uses exact linked Session IDs only.

Details: [references/stages.md](references/stages.md).
