# P8 Submit — concrete implementation notes

This document records P8-owned concrete schemas and runtime boundaries. It is not a Foundation Contract and does not outrank P0–P7.

P8 status: **CLOSED / BASELINED / REMOTELY PUBLISHED.** Implementation phase closed; later FA-2 corrections were applied in the current unreleased candidate. FA-2 is independently PASS / CLOSED. P9 Repair/Migration is ready for human review. This note does not claim P9 closed or v2.0 released.

## Role and boundaries

Submit is the fourth Skill. It reviews the real candidate and, when authorized, performs durable finalization.

It does **not** become Develop, Repair, or Migration. It does not manufacture `READY_FOR_REVIEW`, `SUBMIT_AUTHORIZED`, or Push authorization. It does not persist a reusable `submit_authorized` bit.

## Skill package identity

| Field | Value |
| --- | --- |
| `skill_id` | `submit` |
| `skill_version` | `2.1.0` |
| modes | `[]` (S1–S12 are internal stages) |
| `provides` | `submit.review` |
| `requires` | `test.scoped_verification`, `understand.refresh`, `understand.compatibility` |

## Flow

```text
S1 intake (READY_FOR_REVIEW Task whose current Stage/Task completion authority holds, or genuine no-Task when no applicable Task Book exists)
→ S2 real Diff / provenance classification
→ S3 Structural Review (real S2 Diff + ownership/Rules + bounded structural impact)
→ S4 Knowledge Consistency (Understand route if stale or impact-required knowledge is missing)
→ S5 Test Completeness (P6 public reports / TestEngine; project Test policy still applies with no Task)
→ S6 candidate-bound SUBMIT_AUTHORIZED
→ S7 re-observe candidate + configured-upstream currentness
→ S8 loop to S3–S6 if candidate or repository basis changed
→ S9 candidate Change Record + exact deterministic Finalization Bundle
→ S10 exact-bundle SCM Commit or no-SCM conflict-detectable publication
→ S11 optional separately authorized Push
→ S12 cleanup linked SEALED Sessions
```

S9 does not make the Change Record or its deterministic support durable
history. S10 does. S9 is pre-durable and abortable: it allocates a Change
Record in memory, PREPARE/materializes required P6 durable Evidence, and only
then persists the Change Record. Ordinary failure before a durable S10
boundary (ownership/materialization, Change Record persist, finalization
candidate observation, or trusted-grant consumption) rolls back only artifacts
created by that attempt. Failed non-durable S10 after grant consumption aborts
only support created by that attempt and may leave the non-durable Change
Record; durable-but-blocked S10 preserves the committed bundle. Failed Push
does not erase a valid S10 Commit.

A stranded non-durable Change Record from a pre-durable S9 failure is recovered
only through Submit `abandon_pre_durable_change`: plan-first, exact
approval-bound, one `change_id`, and only when S10 durability is proven
absent. This is not S12 and not Git cleanup.

`reviewed_candidate_digest` (`C`) binds P6 currentness and S3–S6.
`finalization_candidate_digest` (`F`) binds the exact S10 candidate after
adding only the permitted S9 bundle. Submit does not re-test the report against
`F`; it verifies that the physical transition is exactly `C` plus that bundle.

Before Git staging, Submit validates usable author/committer identity and
persists an exact temporary index snapshot for the paths it may touch,
including rename/delete originals, the Change Record, and P6 support. A
non-durable failure after staging restores the prior index without disturbing
unrelated or pre-existing staged state; only then may candidate-only P6 support
be aborted. If safe rollback cannot be proven, P8 preserves its index-recovery
coordination and the P6 `PREPARED` descriptor and blocks before normal S2.
An established Commit is durable truth and is never rolled back.

S5 consumes the current P6 Test completeness result. Foundation `TEST_COMPLETE` is P6 `test_complete` after current-candidate usability checks. Required FAIL cannot yield it. Unknown required policy cannot masquerade as authoritative zero-required completeness. Any false `test_complete` stops both review-only and finalizing flows at S5, before S6 authorization or S7 repository synchronization. Terminal coverage remains `coverage_complete`. Batch `TEST_PASS` is reported but is not a second required-obligation gate: a selected optional FAIL does not block S10 when required verification is complete. Batch 3 left caller-report trust and requirement-id Evidence coverage for the later correction below.

Batch 4 narrows the S5 trust boundary to P6-published completed reports. Both
`report_id` and P8-invoked Test are reloaded through the same P6 reader; raw
report mappings are not authoritative. Task required-test labels are proven
only through their P6-owned `evidence_ref.locator`, never by equality with a
profile name. Project-required profile identities are checked separately.
S9 copies P6-minted Evidence locators into the Change Record and asks P6 to
materialize exactly those durable references under existing GENERATED
ownership. S12 still cleans only linked Develop Sessions. Ordinary P6 runtime
cleanup may remove a finalized Test run because the durable locator resolves
independently from its capsule/sidecar representation.

S11 Push is bound to the exact S10 Commit identity and the S10-bound branch, never to a later local HEAD or a later checkout. If publishing that Commit would require force or non-fast-forward semantics, S11 blocks and the remote remains unchanged. An authorized S11 blocker or failure is surfaced as a top-level BLOCKED result; local S10 remains durable. Missing or stale Push authorization does not turn optional Push into a blocker.

The final Skill result re-observes the current candidate after S11/S12. That current observation is distinct from the finalized S10 Commit/tree/branch.

A Git Commit that already succeeded remains durable even if post-Commit verification later reports a blocker. That state is `s10.ok=false` and `s10.durable=true`. S11 and normal S12 do not run until it is resolved. Submit does not reset, amend, or rewrite the Commit.

P8 resolves changed source through the same P5 ownership registry used by
Develop. Task-scoped ordinary business source may be HUMAN_OWNED; it is not
required to be falsely classified GENERATED. Missing/conflicting ownership and
unproven MANAGED whole-file changes remain fail-closed.

Before S3 continues, P8 loads applicable global/module/path/test Project Rules
for the real changed scope. Test-specific Rules use the union of caller-selected
test ids and, when a Task is in force, that Task's declared `final_tests` /
stage `required_tests` identifiers; omitting `selected` cannot suppress a
Task-declared Test Rule. Hard prohibitions and Rule conflicts block and are
reported through the Skill result. Rule availability does not grant
`SUBMIT_AUTHORIZED`, Commit, Push, or source-edit authority.

Genuine no-Task Submit is Records §13: P8 reviews the real candidate without
inventing a Task Book or READY_FOR_REVIEW. Task-dependent gates are
`NOT_APPLICABLE`. Project Test policy, S3, and S4 remain active. An applicable
non-READY Task is not silently discarded. Implicit Task selection is tri-state:
UNKNOWN applicability is not no-Task, and a known-applicable Task plus an
UNKNOWN Task is not a unique selection.

S3 judges the real S2 Diff with boundary-aware directory/area scope matching
and a bounded structural-impact model. Task-aware S3 uses `scope.paths` union
resolved `scope.modules` (fail-closed when a declared module cannot be resolved)
and preserves `scope.exclude`. Genuine no-Task Submit does not apply Task
scope. Ordinary modification or deletion of an existing `skills.lock` remains
fail-closed. First-adoption lock creation is a narrow observational exception:
the real Diff must show the lock absent from the SCM baseline and newly
added/untracked, ownership GENERATED, `inspect_lock()` `complete_authoritative`,
Understand CURRENT binding the exact current lock bytes, Submit preflight
EXACT or COMPATIBLE, and host ACTIVE. Then S3 may classify the lock as
`SCAFFOLD_STRUCTURE` / `DETERMINED` without the generic lock-change blocker.
The lock remains visible in S2 and in the candidate digest. Submit does not
rewrite the lock or infer human approval. S4 validates current Understand-owned Knowledge Assessment authority for
those knowledge-relevant S3 impacts. Candidate + impact equality is not enough:
the Assessment must be the current-head for that exact binding, and its
published bytes must still match the head integrity digest. A superseded
locator MUST NOT be replayed. P8 MUST NOT scan runtime assessments by timestamp or
record-id order. Mapped documentation path presence, an
unrelated current documentation edit, pre-existing path/module mentions, and
current prose containing an impacted path, basename, module id, impact class,
or any combination of those tokens are each insufficient and MUST NOT
independently establish SATISFIED. The previous Batch-6 lexical
path/basename/module-id heuristic is superseded by FA2-FND-004. A raw caller
dictionary is not S4 authority. Missing, stale, partial, UNKNOWN, NEEDS_REFRESH,
and NEEDS_HUMAN assessments are not PASS. Caller maintenance flags alone
are not S4 authority.

## Authorization

S6 does not treat a caller dictionary such as `{granted: true, candidate_digest: C}` as authority. A candidate digest is public project information. Boolean `True` is not a grant.

`SubmitEngine` may receive a host-bound `AuthorizationProvider` at construction. Ordinary `run(..., **opts)` cannot supply or replace that provider. The Skill caller may pass only an opaque `submit_authorization_ref` / `push_authorization_ref` plus the non-authoritative `submit_authorization_attempt_id` / `push_authorization_attempt_id` that the earlier `authorization_request` exposed. Authority is the matching unconsumed grant inside the trusted provider, bound to operation (`S10` vs `PUSH`), attempt identity, and candidate digest. An A1 grant cannot authorize A2. A caller-minted attempt without a matching trusted grant is not authority.

S6 validates the S10 grant and surfaces a non-authoritative `authorization_request` that includes `authorization_attempt_id`. Consumption is atomic and one-shot, immediately before S10 mutation. Review-only S1–S6 does not consume. A consumed grant cannot authorize a retry, even when the candidate is unchanged. A grant for C1 cannot authorize C2. An S10 grant cannot authorize Push, and a Push grant cannot authorize S10.

No provider / no grant remains the human gate. Review-only Submit stays usable. Grants are not written into Task Book, Change Record, Develop Session, `skills.lock`, `skill.yaml`, `project.yaml`, or `AGENTS.md`.

## S12 cleanup and retry

Durable S10 plus failed S12 is a truthful partial result: top-level is `BLOCKED` or `NEEDS_HUMAN`, never `COMPLETED`. Extras report `stage: S12`, `s10_durable: true`, cleanup blockers, and `cleanup_retry: {operation: cleanup_retry, change_id: ...}`. Cleanup failure does not roll back Git Commit or no-SCM publication.

`mode=cleanup_retry` (or `cleanup_retry={...}`) resumes only incomplete S12 for an already-durable finalization. It does not re-run S1–S10, consume another S10 grant, create another Change Record, or Push. The cleanup target set is frozen on the durable Change Record as `provenance.relevant_develop_session_ids`. Retry inspects only remaining members of that historical set. A Session linked after S10 is outside T. Current Task Book `develop_session_ids` is not historical cleanup authority. Partial cleanup is idempotent. Non-durable S10 never runs S12.

## S7 repository currentness

S7 is a distinct lifecycle gate, not another name for candidate hashing. It
re-observes the P6 candidate and uses the shared read-only SCM currentness
result. A candidate-byte change, a locally advanced tracking ref that makes
the reviewed basis `STALE`/`DIVERGED`, or another material basis change
invalidates S6 authorization through the existing `S8→S3/S4/S5/S6` loop.
Unresolved SCM/currentness observation blocks at S7. `CURRENT`, local `AHEAD`,
and `NOT_CONFIGURED` local-only Git are valid observations. Submit does not
fetch, pull, merge, rebase, reset, or checkout.

## Git S2

Git real-Diff observation uses NUL-delimited porcelain and preserves added, modified, deleted, renamed/copied, and untracked entries. Git membership is discovered through the actual worktree root, including a project nested below a parent worktree, while Diff paths are projected to project root. Observation failure is `UNKNOWN` and blocks; it is never an empty Diff or no-SCM fallback.

## No-SCM S2

True no-SCM hosts need durable comparison truth. Explicit initialization writes
`.scaffold/ext/submit/noscms/baseline.yaml`. That file is not a fourth canonical
record. It must not live under `.scaffold/runtime`. After a committed no-SCM
S10, the authoritative next baseline is the COMPLETE publication inventory;
`baseline.yaml` is only a cache. Missing initial baseline (no file and no
committed publication) is `UNKNOWN` and `baseline_required`. Submit does not
treat that as a clean Diff and does not mark every existing file modified.
Arbitrary publication support without COMPLETE is not an initial baseline.
Explicit `initialize_noscms_baseline` snapshots the current physical state as
known B and refuses Git hosts, including a project directory inside a parent
Git worktree.

Once B exists, S2 compares B against current workspace W and emits the
existing P8 Delta change kinds: `added`, `modified`, `deleted`,
`type_changed`. Unchanged paths are omitted. Physical Diff is not the P6
semantic candidate digest. Candidate-neutral Task control-plane bytes can
still appear in the physical Diff.

Excluded from no-SCM observation and from P6 candidate identity:

- `.scaffold/runtime/`
- `.scaffold/ext/submit/` (Submit no-SCM baseline and publication support)

Core machine artifacts such as `.scaffold/project.yaml` remain visible when
they actually change.

## SCM S10

Git finalization translates project-relative reviewed paths to worktree-relative
Git index/tree paths, so nested projects stage and verify their own files and
Change Record without admitting unrelated parent-worktree changes. It stages
only the reviewed pathspecs plus the S9 Change Record and exact P6-returned
support set, including explicit
deletion/rename removals. It refuses unrelated index entries, requires the
current HEAD to remain the reviewed parent/base, and verifies the committed
tree, exact staged Change Record blob, and clean reviewed paths. Durability
lookup uses the same worktree-relative Change Record path. The Commit itself is
authoritative durable S10 truth; Git hosts do not get a post-Commit
finalization marker.

Submit uses the repository/environment's existing usable Git author and committer identity. Missing identity blocks. Submit does not modify Git configuration, fabricate a framework identity, amend, rebase, reset, or rewrite history.

## No-SCM S10

Durable no-SCM success lives only under the owned Submit extension namespace:

`.scaffold/ext/submit/noscms/publications/<change-id>/`

That directory holds content-addressed `objects/`, a `manifest.yaml` inventory,
and `COMPLETE.yaml` written last. The COMPLETE marker is the durable-success
indicator only when `validate_finalization_marker` accepts it, including
`ok: true`. It binds candidate digest, Change Record digest, finalization
binding, and `representation_digest`. Restart verification validates the
marker, reconstructs the inventory from stored objects, and checks those
bindings. A digest field alone is not sufficient. A present but invalid
COMPLETE does not fall back to `baseline.yaml` as CLEAN.

Publication ordering:

1. Observe exact candidate F
2. Prepare the immutable representation
3. Recheck current physical inventory and candidate digest
4. Write COMPLETE only after required objects/manifest exist.
   COMPLETE is the single restart-resolvable commit: publication of F
   and the next no-SCM baseline of F become true together.
5. `baseline.yaml` is a derived cache/pointer only. Its absence or a failed
   cache write cannot contradict durable COMPLETE truth. Restart recovers
   the finalized baseline from the committed publication inventory.

The authoritative no-SCM head is publication lineage, not change-id
filename order. COMPLETE carries `baseline_generation` and parent
identity. Restart verifies publication material, validates lineage, and
selects exactly one committed head. Duplicate or broken lineage is
UNKNOWN. A stale `baseline.yaml` cache cannot override a newer committed
head. Generation allocation is serialized by a runtime lock under
`.scaffold/runtime/`; the lock is not durable authority.

Workspace mutation during preparation returns BLOCKED. There is no COMPLETE
marker, and baseline B does not advance. Failed `fail_s10` before publication
likewise leaves B unchanged. A crash after COMPLETE is COMMITTED: restart
verifies F and resolves baseline F even if the cache was never written.

A valid same-identity retry is idempotent. An incompatible writer, malformed
COMPLETE/manifest, or binding mismatch fails closed.

Submit must not create `.scaffold/finalizations/` or another unapproved
`.scaffold/` root. Reservation of `.scaffold/ext/` is not automatic write
permission: `project.yaml` must grant GENERATED or MANAGED ownership of
`.scaffold/ext/submit/` when that file exists. P8 does not receive write
authority over other `ext/<namespace>/` trees. `src/` remains HUMAN_OWNED.

S10-only publication support is excluded from P6 candidate identity so it does
not self-stale F (FA2-FND-001 C/F). The support is not a fourth canonical
record. Canonical records remain Task Book, Develop Session, and Change
Record.

State machine:

```text
INITIALIZED BASELINE B
        ↓
workspace candidate C
        ↓
S2–S8 review
        ↓
S9 deterministic finalization candidate F
        ↓
S10 exact durable publication of F
        ↓
successful publication
        ↓
next no-SCM baseline represents finalized F

If S10 fails: baseline remains B.
Do not advance baseline during S2/S6/S9.
```

## Rev1 integrity boundaries

- Provenance applies P3 precedence and boundary evidence: `MIXED_CHANGE`, `PREEXISTING_CHANGE`, `POST_DEVELOP_ADDITIONAL`, `DEVELOP_KNOWN`, then conservative `UNATTRIBUTED`.
- Change Record validation is recursive and strict for every P8-generated nested field, including counts, identities, evidence locators, booleans, and provenance coherence.
- `fail_push` is only failure injection after separately bound Push authorization permits S11. It cannot grant authority.
- S12 deletes only exact identity-linked, valid `SEALED` Develop Session identities that belong to the frozen finalization target set stored on the Change Record. Same-Task identity alone is insufficient; OPEN, ABORTED, malformed, unlinked, and post-S10 Sessions are retained. Cleanup failure after durable S10 is not `COMPLETED`; Submit exposes an S12-only `cleanup_retry` that cannot create a second S10.

When a review package claims to contain currentness or Test-plan authority
needed for review, it MUST include the transitive supporting locator targets
required to verify bound digests. Packaging `completion.yaml` without the
referenced `result.yaml` is incomplete. Do not package the whole runtime tree;
include the small authority closure. This does not change S1–S12.

## Safety

P8 tests use temporary hosts, local Git fixtures, and local bare remotes only. No network, adversarial, or path-escape families.
