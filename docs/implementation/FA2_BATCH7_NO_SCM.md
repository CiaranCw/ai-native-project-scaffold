# FA-2 Batch 7 — True no-SCM observation + authorized namespace + exact publication

This implementation note does not modify or outrank P0–P4. FA2-FND-001,
FA2-FND-002, and FA2-FND-003 remain effective Foundation input.

Batch 7 implements the correction direction for:

- C-MAJ-018 true no-SCM S2 as a real physical Diff
- C-MAJ-013 authorized no-SCM finalization namespace
- C-MAJ-014 exact durable no-SCM publication

It does not start Batch 8, P9, or DIVE. It does not claim those findings closed.
It does not absorb C-MAJ-001 (authorization) or C-MAJ-019 (S12 cleanup).

`submit@2.1.0` remains the unreleased MINOR candidate. This batch refines that
candidate. `skills.lock` is not rewritten.

## Contract authority for `.scaffold/ext/submit/`

Project Contract §8 table lists `.scaffold/ext/` as the namespaced-extension
root. The following paragraph authorizes a later phase to place a
deterministic support-artifact representation under `.scaffold/ext/<namespace>/`
when that phase owns the schema and ownership is registered:

> A later phase MAY place a deterministic support-artifact representation under
> `.scaffold/ext/<namespace>/` when that phase owns the artifact schema and a
> durable Change Record must retain a resolvable opaque reference to it. Such
> use is shared and durable when tracked, remains non-core, and MUST satisfy
> the ownership registry. It MUST NOT redefine `runtime/` as durable, add an
> unnamespaced `.scaffold/` root, or create another canonical development record.

§26 repeats that domain extras MUST live under `.scaffold/ext/<namespace>/`
and MUST NOT drop arbitrary files on the `.scaffold/` root.

P8 therefore writes no-SCM baseline and publication support only under:

`.scaffold/ext/submit/`

Reservation of `.scaffold/ext/` is not automatic write permission. When
`project.yaml` exists, Submit requires GENERATED or MANAGED ownership of
`.scaffold/ext/submit/`. It does not grant write over `.scaffold/ext/test/` or
any other extension namespace. Business source is not marked GENERATED.

`.scaffold/finalizations/`, `.scaffold/baselines/`, and
`.scaffold/snapshots/` are not approved roots and are not created.

## Not a fourth canonical record

Canonical development records remain exactly:

- Task Book
- Develop Session
- Change Record

The no-SCM baseline and publication COMPLETE/manifest/objects are
`record_class: support_artifact`. They are repository-observation and
publication support, not workflow records.

## C-MAJ-018 — physical no-SCM Diff

Historical S2 for `scm.kind != git` walked the tree and labeled every existing
file `modified`. Unchanged files looked dirty. Deleted files could not appear.
That is not a Diff.

Batch 7 stores durable baseline B at:

`.scaffold/ext/submit/noscms/baseline.yaml`

Each relevant physical file records path, `regular_file` kind, and content
digest. S2 compares B against current workspace W:

| Classification | Rule |
| --- | --- |
| ADDED | absent in B, present in W |
| MODIFIED | same relevant type, different digest |
| DELETED | present in B, absent in W |
| TYPE_CHANGED | ordinary local kind change (file → directory) |
| UNCHANGED | omitted from the changed set |

Missing baseline is UNKNOWN / `baseline_required`. UNKNOWN != CLEAN.
Initialization is explicit: the current physical state becomes known B. Submit
does not fabricate historical pre-change truth.

Physical Diff is not the P6 semantic candidate projection. FA2-FND-003
candidate-neutral Task control-plane bytes can still appear in the physical
Diff. Runtime and Submit support paths are excluded; core artifacts such as
`project.yaml` are not hidden merely because they live under `.scaffold`.

## C-MAJ-013 — forbidden root removed

Successful no-SCM S10 must not create `.scaffold/finalizations/`. Publication
support exists only under `.scaffold/ext/submit/noscms/publications/`.
Tests inspect the actual directory layout.

## C-MAJ-014 — exact publication

A digest-only marker cannot prove which exact workspace representation was
finalized. Publication stores:

- content-addressed objects (`objects/<sha256>`)
- `manifest.yaml` inventory + `representation_digest`
- `COMPLETE.yaml` written last (durable-success indicator)

Ordering:

observe F → prepare representation → recheck current F → COMPLETE
(the single commit). `baseline.yaml` is a derived cache written after COMPLETE.
Absence or failure of that cache cannot contradict COMPLETE. Restart
resolves baseline F from the committed publication inventory.

If the workspace changes during preparation, S10 does not publish the stale
F, does not write COMPLETE, and does not advance B.

Restart, without original engine memory, verifies COMPLETE through the
canonical finalization-marker schema (`ok` must be true), then objects +
manifest + lineage, and resolves the next no-SCM baseline to the committed
head F. A schema-invalid COMPLETE is UNKNOWN and does not fall back to the
baseline cache. Later workspace mutation must not rewrite stored objects; it
appears as a new Diff against the advanced baseline.

Failed S10 (`fail_s10`, currentness failure, or failure before COMPLETE) does
not advance B and does not claim durable success because a partial support
directory exists.

A call that reaches COMPLETE cannot return non-durable while restart
reports durable for the same finalization (B7-C01).

The committed no-SCM baseline head is publication lineage, not
`change_id` lexical order. Each COMPLETE binds `baseline_generation`,
`parent_generation`, `parent_representation_digest`, and
`parent_change_id` to the previously authoritative head. Restart selects
the unique valid generation chain. Duplicate or broken lineage is
UNKNOWN / fail-closed. `baseline.yaml` remains a cache and cannot override
a newer committed head. A host-wide runtime lock serializes generation
allocation; the lock is not durable baseline authority.

## C/F semantics (FA2-FND-001)

C is the reviewed/tested/S6-authorized candidate. S9 adds the Change Record and
permitted deterministic support. F is that exact finalization candidate. S10
publication metadata under `.scaffold/ext/submit/` is excluded from P6
candidate identity so it does not self-stale F. Arbitrary business/source
mutation between C/F and durable S10 still fails closed.

## State machine

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
```

If S10 fails, baseline remains B. Do not advance baseline during S2, S6, or
S9.

## B7-C01 — one commit state

COMPLETE is the only durable-success indicator. Publication durability and
the next no-SCM baseline share that commit. `baseline.yaml` is a cache.
Restart at COMPLETE resolves F even if the cache write never happened. A
call cannot return non-durable while restart reports durable for the same
finalization.

## B7-C02 — committed head is lineage, not change-id order

Change IDs are identity. They are not commit sequence. Restart must not
choose `max(change_id)` or directory-name chronology.

Each durable COMPLETE binds:

- `baseline_generation`
- `parent_generation` (0 for the initialized B0 root)
- `parent_representation_digest`
- `parent_change_id`

COMPLETE remains the single commit. Lineage is already present in that
material. `baseline.yaml` stays a non-authoritative cache. If restart
finds verified publications but cannot form one unique valid head, it
fails closed (UNKNOWN). It does not pick a publication by lexical id.

## Git is unchanged

Git S2, Git Commit/tree finalization, parent-worktree Git routing, Git
observation UNKNOWN, S7 currentness, and Git index recovery are not redesigned.
Batch-2 `observe_scm` remains authoritative. A project inside a parent Git
worktree MUST NOT take the no-SCM path.

## Versioning

`submit@2.1.0` continues. No `submit@2.2.0`. `skills.lock` is not rewritten.

## Out of scope

- C-MAJ-001 human authorization hardening (Batch 8)
- C-MAJ-019 S12 cleanup top-level truth (Batch 8)
- Delayed FA2-012 retry redesign (not reproduced)
- P9 / DIVE
