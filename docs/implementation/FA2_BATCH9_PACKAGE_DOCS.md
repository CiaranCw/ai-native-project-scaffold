# FA-2 Batch 9 — Package validity, uniform compatible substitution, documentation truth

This implementation note does not modify or outrank P0–P4. FA2-FND-001,
FA2-FND-002, and FA2-FND-003 remain effective Foundation input. No new Foundation
Amendment is created by this batch.

Batch 9 implements the correction direction for:

- C-MIN-004 non-Understand intrinsic package validation
- C-MIN-005 non-Understand compatible substitution unreachable
- C-MIN-006 README / implementation status contradiction

It also stabilizes a non-blocking Batch-8 test-hygiene item in
`tests/test_fa2_batch8_human_control.py` (B8A08) without changing authorization
product semantics.

This note does not start P9 or DIVE. It does not claim FA-2 PASS or FA-2 CLOSED.
Independent FA-2 closure audit remains pending. v2.0 is not released.

`develop@2.1.0`, `test@2.0.1`, `submit@2.1.0`, and `understand@2.1.0` remain the
unreleased Skill candidates. Released `understand@2.0.0` remains immutable and
does not include later FND-004 Knowledge Assessment behavior. This batch
corrects framework validator/resolver behavior and status documentation.
Released id+version normative meaning is unchanged. `skills.lock` is not
rewritten.

## C-MIN-004 — four-Skill intrinsic validity

Package validity remains `VALID` / `INVALID` only. INVALID is not a sixth
compatibility result.

Intrinsic checks now apply mode-home ownership to all four Skills:

- Understand: exactly `bootstrap`, `full`, `refresh`, `compatibility`
- Develop: only Develop-owned `normal_task` and `repair`
- Test: reject foreign Skill homes and Submit stages S1–S12 as top-level
  modes; Test-owned names are not frozen beyond current contract
- Submit: no extra top-level modes; S1–S12 are internal stages

A current-environment capability miss does not rewrite a legal package as
INVALID.

## C-MIN-005 — uniform established-host substitution

For an established host with a complete authoritative lock, Develop, Test,
and Submit may evaluate a unique valid non-exact candidate when exact identity is
absent and explicit compatibility declarations prove safe substitution.

Exact identity still has priority when present. Compatible substitution:

- reports the actual package version
- is not `EXACT`
- does not rewrite `skills.lock`
- does not infer `MIGRATION_REQUIRED` from version difference alone

Multiple equally eligible substitutes are `UNKNOWN` / blocked. An INVALID
package cannot become `COMPATIBLE`. Pre-adoption bootstrap still requires the
release-pinned Understand exactly. No pre-lock compatible substitution.

A uniquely resolved intrinsically VALID non-exact package whose compatibility
is `UNKNOWN`, `INCOMPATIBLE`, or `MIGRATION_REQUIRED` remains `VALID`. Host
resolution must not rewrite that package as `INVALID`. Exact lock identities
are collected first. Remaining non-exact Skills are resolved by a bounded
four-Skill fixpoint: a legal core `requires` whose owner is not yet bound is
deferred, not treated as a final environment miss. Dependents are retried after
the owner is resolved. True ambiguity remains `UNKNOWN`.

## C-MIN-006 — documentation truth

P5–P8 implementation-phase status headers now match their closed/baselined
history. Later FA-2 corrections live in this unreleased candidate. History
sections are preserved rather than rewritten as if earlier events never
happened.
