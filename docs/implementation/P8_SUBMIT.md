# P8 Submit — concrete implementation notes

This document records P8-owned concrete schemas and runtime boundaries. It is not a Foundation Contract and does not outrank P0–P7.

P8 status: **ACTIVE / IMPLEMENTATION**. Not COMPLETE, BASELINED, or PASS. P5, P6, and P7 remain **CLOSED / BASELINED / REMOTELY PUBLISHED**. P9 and FA-2 are not started.

## Role and boundaries

Submit is the fourth Skill. It reviews the real candidate and, when authorized, performs durable finalization.

It does **not** become Develop, Repair, or Migration. It does not manufacture `READY_FOR_REVIEW`, `SUBMIT_AUTHORIZED`, or Push authorization. It does not persist a reusable `submit_authorized` bit.

## Skill package identity

| Field | Value |
| --- | --- |
| `skill_id` | `submit` |
| `skill_version` | `2.0.0` |
| modes | `[]` (S1–S12 are internal stages) |
| `provides` | `submit.review` |
| `requires` | `test.scoped_verification`, `understand.refresh`, `understand.compatibility` |

## Flow

```text
S1 intake (READY_FOR_REVIEW Task + host/package gate)
→ S2 real Diff / provenance classification
→ S3 Structural Review
→ S4 Knowledge Consistency (Understand route if stale)
→ S5 Test Completeness (P6 public reports / TestEngine)
→ S6 candidate-bound SUBMIT_AUTHORIZED
→ S7 re-observe Repository Sync
→ S8 loop to S3–S6 if candidate changed
→ S9 candidate Change Record
→ S10 SCM Commit or no-SCM conflict-detectable publication
→ S11 optional separately authorized Push
→ S12 cleanup linked SEALED Sessions
```

S9 does not make the Change Record durable history. S10 does. Failed S10 leaves the record a candidate. Failed Push does not erase a valid S10 Commit.

S11 Push is bound to the exact S10 Commit identity and the S10-bound branch, never to a later local HEAD or a later checkout. If publishing that Commit would require force or non-fast-forward semantics, S11 blocks and the remote remains unchanged. An authorized S11 blocker or failure is surfaced as a top-level BLOCKED result; local S10 remains durable. Missing or stale Push authorization does not turn optional Push into a blocker.

The final Skill result re-observes the current candidate after S11/S12. That current observation is distinct from the finalized S10 Commit/tree/branch.

A Git Commit that already succeeded remains durable even if post-Commit verification later reports a blocker. That state is `s10.ok=false` and `s10.durable=true`. S11 and normal S12 do not run until it is resolved. Submit does not reset, amend, or rewrite the Commit.

## Authorization

`SUBMIT_AUTHORIZED` is a current caller-supplied object `{granted: true, candidate_digest: <current>}`. It is Commit authorization when S10 is Git. Push requires a second current object and does not inherit from `SUBMIT_AUTHORIZED`.

## SCM S10

Git real-Diff observation uses NUL-delimited porcelain and preserves added, modified, deleted, renamed/copied, and untracked entries. Observation failure is `UNKNOWN` and blocks; it is never an empty Diff.

Git finalization stages only the reviewed pathspecs plus the S9 Change Record, including explicit deletion/rename removals. It refuses unrelated index entries, requires the current HEAD to remain the reviewed parent/base, and verifies the committed tree, exact staged Change Record blob, and clean reviewed paths. The Commit itself is authoritative durable S10 truth; Git hosts do not get a post-Commit finalization marker.

Submit uses the repository/environment's existing usable Git author and committer identity. Missing identity blocks. Submit does not modify Git configuration, fabricate a framework identity, amend, rebase, reset, or rewrite history.

## No-SCM S10

Durable success is a validated support artifact at `.scaffold/finalizations/<change-id>.yaml`. It binds the candidate and exact Change Record digest. Publication is serialized under a runtime lock and written atomically. A valid same-identity retry is idempotent; an incompatible writer, malformed artifact, or binding mismatch fails closed. The artifact is not a fourth canonical record.

## Rev1 integrity boundaries

- Provenance applies P3 precedence and boundary evidence: `MIXED_CHANGE`, `PREEXISTING_CHANGE`, `POST_DEVELOP_ADDITIONAL`, `DEVELOP_KNOWN`, then conservative `UNATTRIBUTED`.
- Change Record validation is recursive and strict for every P8-generated nested field, including counts, identities, evidence locators, booleans, and provenance coherence.
- `fail_push` is only failure injection after separately bound Push authorization permits S11. It cannot grant authority.
- S12 deletes only exact Task-linked, valid `SEALED` Develop Session identities. Same-Task identity alone is insufficient; OPEN, ABORTED, malformed, and unlinked Sessions are retained.

## Safety

P8 tests use temporary hosts, local Git fixtures, and local bare remotes only. No network, adversarial, or path-escape families.
