# FA-2 Batch 8 — Submit authorization boundary + truthful S12 partial result

This implementation note does not modify or outrank P0–P4. FA2-FND-001,
FA2-FND-002, and FA2-FND-003 remain effective Foundation input. Contracts
remain the normative authority.

## Current behavior (PC-R4)

Submit S1–S12 is Agent-autonomous machine-gated work. Git Commit and Git Push
require a current explicit user instruction at the Agent execution boundary.

The following are **not** current production authority and MUST NOT be read
as live behavior:

- `AuthorizationProvider`
- TrustedIssuer / trusted one-shot grant
- opaque `submit_authorization_ref` / `push_authorization_ref` consumption
- “no provider / no grant remains the human gate”

S6 apply-intent is `request_s10` / `finalize` for the reviewed candidate. It
is not a human grant and not Git Push. A caller dictionary
`{granted: true, candidate_digest: C}` is public information plus a boolean
and never authorizes S10 or Push. Engine kwargs `authorization_provider`,
grant refs, and attempt ids are ignored.

Grant-shaped fields are still forbidden on Change Records
(`submit_authorized`, `grant_ref`, `can_commit`, `can_push`, and the rest of
the fail-closed compatibility set). That anti-over-persistence guard remains.

Canonical development records remain exactly Task Book, Develop Session, and
Change Record. There is no fifth Skill, no new Submit stage, no
`COMMIT_AUTHORIZED` record, and no persistent `submit_authorized` /
`push_authorized` YAML.

## Historical (superseded) — Batch 8 trusted-grant design

The remainder of C-MAJ-001 below records the FA-2 Batch 8 correction that
replaced a caller-forgeable dictionary with a host-bound one-shot grant.
PC-R4 deleted that grant machinery. Keep this section for forensic history
only.

Batch 8 originally implemented:

- C-MAJ-001 caller-forgeable / replayable Submit and Push authorization
- C-MAJ-019 S12 cleanup failure remaining top-level COMPLETED

It also recorded:

- B8-C01 attempt identity stored but not enforced
- B8-C02 S12 retry expanding cleanup to Sessions linked after durable S10

### C-MAJ-001 — historical trust boundary (superseded)

The retired caller object `{granted: true, candidate_digest: C}` is public
information plus a boolean. It is not human permission. It never authorizes
S10 or Push. There is no compatibility authorization path through that
dictionary. That prohibition remains.

Historical design (deleted): `SubmitEngine(..., authorization_provider=...)`
was the trusted boundary; `engine.run(authorization_provider=...)` was
ignored; production Submit consumed an opaque grant reference bound to
operation (`S10` vs `PUSH`), attempt identity, and candidate digest.
No provider / no grant was the human gate. That provider, issuer, and
one-shot grant path no longer exist.

## C-MAJ-019 — truthful S12 (still current)

After durable S10, `cleanup_sessions` may return `ok: false`. That failure is
a top-level `BLOCKED` or `NEEDS_HUMAN` result at stage S12. S10 remains
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
the authorization/cleanup cross-case. S10 fixtures use `run_submit` /
`submit_engine` without a trusted grant provider. Tests that prove the retired
dictionary is not authority still pass it to `submit_engine(...).run(...)`.
