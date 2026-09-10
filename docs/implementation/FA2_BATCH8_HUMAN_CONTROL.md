# FA-2 Batch 8 — Trusted one-shot human authorization + truthful S12 partial result

This implementation note does not modify or outrank P0–P4. FA2-FND-001,
FA2-FND-002, and FA2-FND-003 remain effective Foundation input.

Batch 8 implements the correction direction for:

- C-MAJ-001 caller-forgeable / replayable Submit and Push authorization
- C-MAJ-019 S12 cleanup failure remaining top-level COMPLETED

It does not start Batch 9, P9, or DIVE. It does not claim those findings closed.
It does not reopen Batches 1–7.

This note also records the focused correction for:

- B8-C01 attempt identity stored but not enforced
- B8-C02 S12 retry expanding cleanup to Sessions linked after durable S10

`submit@2.1.0` remains the unreleased MINOR candidate. This batch refines that
candidate. `skills.lock` is not rewritten.

Canonical development records remain exactly Task Book, Develop Session, and
Change Record. There is no fifth Skill, no new Submit stage, no
`COMMIT_AUTHORIZED` record, and no persistent `submit_authorized` /
`push_authorized` YAML.

## C-MAJ-001 — trust boundary

The retired caller object `{granted: true, candidate_digest: C}` is public
information plus a boolean. It is not human permission. After this batch it
never authorizes S10 or Push. There is no compatibility authorization path
through that dictionary.

`SubmitEngine(..., authorization_provider=<host capability>)` is the trusted
boundary. `engine.run(authorization_provider=...)` is ignored. Production
Submit may only validate and atomically consume an opaque grant reference.
It does not expose `grant(candidate)` that an Agent can invoke to
self-authorize. Tests use a TEST-ONLY issuer that calls the provider insert
helper.

A grant binds operation (`S10` vs `PUSH`), attempt identity, and candidate
digest. Trusted `validate`/`consume` require the expected attempt. An A1 grant
cannot authorize A2 on the same candidate, even while unconsumed. The
`authorization_request` exposes a non-authoritative `authorization_attempt_id`
for host grant issuance; a caller-minted attempt without a matching trusted
grant is not authority. Consumption is one-shot and lock-serialized. Replay
fails because the grant is consumed, even when the candidate is unchanged. A
C1 grant cannot authorize C2. An S10 grant cannot authorize Push.

S6 validates. Consumption happens immediately before S10 mutation, after
S7/S8/S9 and final currentness. Review-only does not consume. Failed S10
still spends the grant. No provider / no grant remains the human gate.

Push is a separate one-shot. Failed authorized Push consumes the Push grant
and leaves S10 durable. Grants are process-local ephemeral state, not
project authority.

## C-MAJ-019 — truthful S12

After durable S10, `cleanup_sessions` may return `ok: false`. That failure is
now a top-level `BLOCKED` or `NEEDS_HUMAN` result at stage S12. S10 remains
durable. The result carries `cleanup_retry: {operation: cleanup_retry,
change_id: ...}` with `next_route: submit`.

Cleanup retry proves durable S10 from current Git / no-SCM durability truth
plus the Change Record. The S12 target set is the exact Develop Session
identities frozen on that Change Record at finalization
(`provenance.relevant_develop_session_ids`). Retry resumes remaining members of
that frozen set. The current Task Book must not expand the historical target
set. A Session linked after durable S10 is outside T and must not be deleted.
Partial cleanup is idempotent. Malformed linked Session state is
`NEEDS_HUMAN`. Non-durable S10 never runs S12.

## Tests

`tests/test_fa2_batch8_human_control.py` covers B8A01–B8A14, B8C01–B8C12, and
the authorization/cleanup cross-case. Existing P8 S10 fixtures use the
trusted TEST provider via `run_submit` / `authorized_submit_engine`.
Tests that prove the retired dictionary is not authority still pass it to
`submit_engine(...).run(...)`.
