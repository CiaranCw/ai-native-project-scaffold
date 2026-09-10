# Submit

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `submit`
- `skill_version`: `2.1.0`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: none beyond the frozen internal Submit-S1…S12 stages

This package provides `submit.review`. Submit is the fourth top-level Skill. It is not Develop, not Repair, not Migration, and not a fifth Skill.

Submit owns independent final review of the real candidate Diff, including
human-only / no-Task candidates, applicable Project Rule loading, Diff-semantic
Structural Review (including lawful first-adoption `skills.lock` creation under
current Understand authority; ordinary lock edits remain fail-closed), impact-driven Knowledge Consistency (Understand-owned
candidate-bound Knowledge Assessment; lexical path/basename/module mentions
are not SATISFIED), Test Completeness,
the candidate-bound human `SUBMIT_AUTHORIZED` gate (trusted one-shot host
grant, never a caller dictionary), Repository Sync, the S8
re-review loop, deterministic S9 Finalization Bundle orchestration, S10 Commit /
no-SCM durable finalization, optional separately authorized one-shot Push, and
post-success Develop Session cleanup. Test-specific Rules follow a READY Task's
declared test identifiers even when the caller omits `selected`. Applicable
Rule prohibitions and conflicts block review; Rules never grant Commit, Push,
or `SUBMIT_AUTHORIZED`.

Submit MUST NOT invent a Task Book, manufacture `READY_FOR_REVIEW`, treat
`TEST_PASS` as `TEST_COMPLETE` or `SUBMIT_AUTHORIZED`, silently edit source by
becoming Develop, reuse C1 authorization for C2, or persist a reusable
`submit_authorized` bit. An applicable Task that is not READY MUST NOT be
treated as no-Task. A caller `{granted: true, candidate_digest: C}` object is
not Submit or Push authority. Cleanup failure after durable S10 must not
return top-level COMPLETED; S12 retry does not require another S10 grant.

If substantive implementation repair is required, Submit returns a bounded `submit_to_develop` handoff. When the blocker deterministically maps to current Task Stage authority, the handoff includes nonempty `target_stage_ids` and `next_route` may be `develop.repair`. When mapping is unresolved, Submit does not guess first, last, or all Stages, does not emit an executable `develop.repair` route, and surfaces a human/unresolved blocker. Submit does not write the Task Book. Repair remains Develop `mode=repair`.

Git Diff observation is fail-closed, recognizes projects nested below a parent
worktree, projects paths back to project root, and preserves deletion/rename
identity through exact S10 staging. S7 validates local configured-upstream
currentness after S6 without auto-sync; candidate or basis changes invalidate
authorization through the existing S8 loop. Local-only Git does not invent an
upstream requirement. Git Commit truth—not a post-Commit marker—establishes
Git durability. When a Change Record carries P6 Evidence locators, Submit asks
P6 to materialize only their deterministic support and admits only P6-returned,
ownership-authorized paths into the exact S10 tree. Runtime Test state is not
durable Evidence. No-SCM publication is serialized, atomically written, and
binding-validated. Push is bound to the exact S10 Commit and the S10-bound
branch, never to a later HEAD or later checkout. Push failure injection never
bypasses separate Push authorization or exact-Commit validation. Cleanup uses
exact linked Session IDs frozen on the Change Record at finalization.

Git index mutation is transactional. Submit checks simple identity authority
before staging, snapshots the exact pre-S10 index state for every authorized
touched path, and restores it after any non-durable post-staging failure.
Pre-existing staged state is preserved. Failed rollback keeps both P8 recovery
coordination and P6 PREPARED coordination; a successful Commit is durable and
is never rolled back.

True no-SCM S2 compares a durable baseline under `.scaffold/ext/submit/`
against the current workspace. Missing baseline is UNKNOWN, not clean and not
“every file modified”. Successful no-SCM S10 publishes an immutable
manifest/object representation and a COMPLETE marker in that same Submit
namespace; it does not create `.scaffold/finalizations/`.

Version `2.1.0` is a backward-compatible MINOR workflow extension and declares
compatibility with a `2.0.0` host lock. The lock is not rewritten. Package
resolution must still surface the actual version; this declaration does not
repair generic non-Understand compatible-substitution reachability.

Details: [references/stages.md](references/stages.md).
