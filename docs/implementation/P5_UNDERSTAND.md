# P5 Understand — concrete implementation notes

This document records P5-owned concrete schemas and runtime boundaries so later phases can consume them without redefining Foundation. It is not a Foundation Contract and does not outrank P0–P4.

P5 status: **ACTIVE / IMPLEMENTATION** (Rev5 candidate). Not COMPLETE, BASELINED, or PASS.

## Layout

```text
skills/understand/          canonical Understand package
src/scaffold_p5/            P5 runtime / Compatibility Preflight support
tests/                      ordinary local correctness tests
tests/fixtures/distribution TEST FIXTURES only (including simulated D/T/S)
```

This distribution repository root MUST NOT hold a live adopted-host `.scaffold/project.yaml` or `.scaffold/skills.lock`.

## Support layer

Compatibility Preflight is one Distribution support layer with exactly two contexts:

1. `PRE_ADOPTION_BOOTSTRAP`
2. `HOST_COMPATIBILITY`

Interrupted initial-Adoption recovery is a rule inside Host Compatibility. It is not a third context, Skill, lifecycle state, or permission.

Host classification observes P5-local evidence in this order:

```text
raw Scaffold-specific artifact presence
→ parse/structural validity
→ supported concrete schema
→ lifecycle / authority interpretation
→ compatibility
→ mutation eligibility
```

Artifact presence is never inferred from successful parsing. A present malformed,
non-mapping, unsupported, or incomplete Scaffold-specific artifact remains host
identity/recovery evidence and fails closed. These observation classifications
are P5-local support data, not new Foundation lifecycle states or Preflight
contexts.

## Concrete schemas frozen by P5

All YAML uses `schema_version` / format versions as applicable. Unknown required structure blocks. There is no global `records_schema_version`.

### `skills.lock`

```text
lock_format_version: "1"
schema_version: "1"
release_provenance: <release-id>   # provenance only; not a second expected-version SSOT
authoritative: true
skills:
  understand|develop|test|submit:
    skill_version: MAJOR.MINOR.PATCH
    package_digest: sha256
    package_format_version: "1"
```

Complete authoritative lock requires supported lock/schema versions,
`authoritative: true`, exactly the four core Skills (no fifth key), and a valid
exact semantic version, SHA-256 package identity, and package-format version for
every entry. `authoritative` absent/false, candidate, partial, malformed, or
unpublished lock state is recovery/consistency evidence, not normal authority.

### `.scaffold/project.yaml`

```text
schema_version: "1"
project_contract_generation: "1"
lifecycle: ADOPTING | ACTIVE | RECOVERY_REQUIRED
maintenance: [NEEDS_REFRESH?, NEEDS_MIGRATION?]
baseline:
  kind: git|none
  revision: <concrete HEAD identity|null>
  branch: <branch|null>
  head_state: attached|detached|unborn|not_applicable|unavailable
  working_tree: clean|dirty|unknown
  tracked_changes: present|absent|unknown
  untracked_changes: present|absent|unknown
  nested_workspace: observed|absent|unknown
  filesystem: {project_state, fingerprint, file_count}
ownership: {path: GENERATED|MANAGED|HUMAN_OWNED}
knowledge / capabilities / facts / clients
```

Ownership registry lives here. No `ownership.yaml`. `.scaffold/runtime` is ephemeral.

Docs and client surfaces may be `GENERATED`, `MANAGED`, or `HUMAN_OWNED`.
`AGENTS.md` and `docs/project/architecture.md` may be `HUMAN_OWNED` and are
preserved.

The required durable machine artifacts must be declared explicitly and may use
only `GENERATED` or `MANAGED`:

```text
.scaffold/project.yaml
.scaffold/modules.yaml
.scaffold/commands.yaml
.scaffold/tests.yaml
.scaffold/skills.lock
```

`HUMAN_OWNED` on any of those paths is a concrete Project schema violation.
Missing coverage is incomplete / non-executable. P5 does not coerce
`HUMAN_OWNED` to `GENERATED` and does not invent missing registry entries on an
established host.

`MANAGED` means a bounded region, not whole-file write authority. P5 has no
generic managed-region writer. Therefore a whole-file mutation against
`MANAGED` blocks / returns `NEEDS_HUMAN` and does not write.

Whole-file persistent mutation eligibility is one P5-local policy:

```text
GENERATED → allowed
HUMAN_OWNED → blocked
MANAGED without an implemented bounded region → blocked
missing / unknown ownership → blocked
```

Adoption Plan Approval, Migration Plan Approval, and lock-update approval do
not override that policy.

P5 observes `project.yaml` as `ABSENT`, `VALID`, `MALFORMED`,
`UNSUPPORTED`, or `INCOMPLETE`. Schema-1 execution requires a mapping with
supported project generation and persisted lifecycle, the existing maintenance
taxonomy, an interpretable baseline, a mapping ownership registry containing
only `GENERATED|MANAGED|HUMAN_OWNED`, explicit `GENERATED|MANAGED` coverage of
the five core machine artifacts, and structurally interpretable
knowledge, capability, fact, and client collections. A malformed or unsupported
file remains explicit Scaffold identity. It is never overwritten by fresh
Bootstrap.

Restricted YAML parsing requires complete document consumption. Every nonblank,
non-comment line must belong to the parsed top-level document. A mapping line
must contain a delimiter, keys must be nonempty, and duplicate keys are
rejected. Trailing list items, unstructured lines, or other leftover sibling
content fail closed as `ValueError` / `MALFORMED`. Canonical `dump()` output
continues to `load()` with the same logical value. Parse failure is not
converted into an empty map: Project becomes `MALFORMED`, Adoption/Migration
recovery evidence is unresolved, and a package manifest becomes `INVALID`.

Only a `VALID` project view is executable. Unsupported or incomplete project
schema may be reported read-only, but cannot produce executable
`EXACT|COMPATIBLE` host evaluation and cannot authorize Full, lock update,
Migration start/resume, or project maintenance mutation. If the only concrete
schema issue is an illegal `HUMAN_OWNED` mark on a required core machine
artifact, Refresh still applies the existing ownership-aware
preserve/repair/block policy and does not overwrite those files. This adds no
compatibility result or lifecycle state.

### Adoption Session (P3 kind, P5 concrete files)

`.scaffold/runtime/adoption-sessions/<adopt-...>/`

- `session.yaml` — P3 header + status `OPEN|BLOCKED|INTERRUPTED`
- `plan.yaml` — temporary Plan copy for zero-context resume (not a fourth canonical record)

`plan.observed_approved` is revalidation input, not standing permission. Successful activation deletes the session.

Adoption recovery discovery inspects every immediate entry even when parsing
fails. It distinguishes no evidence, one coherent current interrupted
Session/Plan pair, ambiguous current recovery, Plan without Session, Session
without Plan, orphan entry/directory, malformed or non-mapping Session/Plan,
and unsupported/incomplete Session/Plan. Only one coherent current pair is
resumable. Every other present recovery form blocks fresh Bootstrap and
preserves the evidence for human consistency resolution.

The concrete Session gate requires `record_type: adoption_session`,
`schema_version: "1"`, a supported current status, record id, baseline,
Session/Plan identity and digest binding, release id, exact intended lock,
mutation envelope, checkpoints, applied mutation summary, and the applicable
expected-mutation/provenance structures. Missing or unsupported required
structure cannot disappear into a fresh-host fallback.

The Plan baseline contains a portable durable inventory of path/type/digest
metadata. It excludes SCM internals, bytecode/cache files, and
`.scaffold/runtime/` bookkeeping. Recovery requires exactly one usable current
Session, an intact Session/Plan identity and content digest binding, and an
actual host state that is a proven prefix of the approved envelope. Checkpoint
mutations carry observed file digests. Extra or changed durable state outside
the envelope, or a changed checkpoint artifact, blocks and routes to
re-discovery, a replacement Plan, and new P1 approval.

Envelope membership is permission, not progress provenance. Before B5/B6
writes, the Session stores deterministic expected digests for the approved
artifacts. Recovery accepts an in-envelope delta only when its current digest
matches a Session mutation observation, a deterministic write-ahead expected
digest, or the existing exact lock/ACTIVE handoff rule. An absent target is
retryable; unknown or different bytes are divergence and are never overwritten
under the old approval.

Replacement planning receives the current Session provenance. A newly appearing
canonical target remains `PRESERVE/HUMAN_OWNED` unless the original baseline and
current Session digest evidence prove Scaffold produced it. Old `CREATE` intent
alone never grants GENERATED ownership. Proven current-Session artifacts may
retain GENERATED ownership and bounded update intent.

The concrete Adoption Plan uses `schema_version: "1"`. Its content digest and
`plan-<digest-prefix>` identity bind that schema version together with release,
package/lock intent, target generation, mutation envelope, actions, facts,
baseline, and activation blockers. Changing only the schema version therefore
changes the computed content identity; the persisted digest and Plan id fail
validation, and an approval for the prior digest cannot authorize recovery.

### Migration Execution (operational artifact)

`.scaffold/runtime/migration-executions/<mig-...>/`

- `execution.yaml` — `PREPARED|APPLYING|VALIDATING|COMPLETED|RECOVERY_REQUIRED|ABORTED`
- `plan.yaml` — bound Migration Plan

Not a fifth Skill. Not a fourth canonical development record.

The durable checkpoint sequence is:

```text
PRE_MUTATION
  completed: []
  remaining: [CONTRACT_GENERATION_UPDATED, VALIDATION_PASSED]

VALIDATING
  completed: [CONTRACT_GENERATION_UPDATED]
  remaining: [VALIDATION_PASSED]

VALIDATION_PASSED
  completed: [CONTRACT_GENERATION_UPDATED, VALIDATION_PASSED]
  remaining: []
```

`RECOVERY_REQUIRED` retains one of those exact prefixes. Resume compares actual
project and lock state with the prefix, reconciles the exact atomic
write/checkpoint publication gap when necessary, reruns validation, and either
continues deterministically or blocks on real divergence. While any unresolved
current Execution exists, Full, Refresh, lock update, and independent
persistent Compatibility mutations are isolated. Compatibility evaluation may
run read-only and does not persist maintenance changes.

Migration recovery discovery inspects each immediate execution directory as
evidence, including plan-only, execution-only, orphan, malformed, non-mapping,
unsupported, incomplete, terminal, valid unresolved, and ambiguous cases.
Malformed evidence never disappears from host observation. Any unresolved
evidence, or lifecycle `RECOVERY_REQUIRED` independently, isolates Full,
Refresh, lock update, new migration, and other persistent compatibility
mutation. Only one coherent valid unresolved Execution is resumable; other
cases return a controlled human recovery blocker without deleting evidence.

### Understand result

Generic P4 result: `skill_id`, `skill_version`, mode, `COMPLETED|BLOCKED|FAILED|NEEDS_HUMAN`, baseline, mutations, artifacts, evidence, blockers, next route, compatibility when relevant.

## Package identity

Package digest = SHA-256 of canonical `skill.yaml` + `SKILL.md` bytes. Matching id/version strings are not enough.

Selected Release metadata independently stores, for each of exactly four core
members, `skill_id`, exact `skill_version`, `package_digest`, and
`package_format_version`. Expected release digests are never derived from the
package currently being checked. The resolver compares actual package bytes to
those release-owned facts.

Static package validity checks required structure, a numeric
`MAJOR.MINOR.PATCH`, a well-formed package format declaration, an existing
interpretable entry, coherent Understand modes, manifest/entry identity,
capability-list shape, legal non-cyclic `requires`, runtime declaration shape,
and forbidden permission/identity fields. A well-formed but locally unsupported
format or unavailable legal dependency remains a VALID package and is handled
as `INCOMPATIBLE`/`UNKNOWN` by environment compatibility.

Capability ownership is the core Skill prefix. Package validity rejects a
provider that claims another Skill's capability, self-dependencies, non-core
owners, and forbidden core edges. The permitted prerequisite edges are
Develop→Test, Submit→Test, and Submit→Understand; `requires` grants no invocation
permission. Distribution release validation builds the graph from exactly the
four pinned members and detects self or multi-node cycles. Legal acyclic
requirements remain intrinsically VALID when their exact capability is absent;
that absence is an environment/compatibility resolution failure.

Capability satisfaction is scoped to the exact selected release, authoritative
host lock, or proposed final lock package set. An unrelated package elsewhere
in the Distribution index cannot satisfy or invalidate the active set.

Fresh bootstrap and R5 recovery require:

```text
Selected Distribution Release pinned Understand
= actual resolved Understand
= intended initial lock Understand
```

Established-host `COMPATIBLE` substitution is explicit (`may_substitute_for`) only. No pre-lock substitution.

Bootstrap additionally checks release-set validity, supported package format,
target Project Contract generation, Adoption Session record capability,
`understand.bootstrap`, legal dependency satisfaction, and declared
runtime/client facts. Unknown required facts block.

## Initial Adoption authority handoff

Understand Full writes the complete initial lock first as
`authoritative: false`. The Session then records `B7_PASSED`; P5 validates and
publishes the lock as authoritative; records `LOCK_AUTHORITY_ESTABLISHED`;
publishes lifecycle `ACTIVE`; records `B8_ACTIVE`; then performs B9 cleanup.

Every write boundary is restart-aware:

- before B7: Selected Release/approved Plan remains bounded recovery authority;
- B7 passed, candidate lock: resume lock validation/publication;
- authoritative lock written before its Session checkpoint: reconcile only when
  the lock exactly equals the approved intended lock;
- lock authority established before ACTIVE: the lock drives package resolution;
  Plan release authority has expired;
- ACTIVE before cleanup: revalidate ACTIVE + lock and clean the current Session.

A B7 failure keeps lifecycle `ADOPTING`, a non-authoritative candidate lock, and
a `BLOCKED` Session. `replan=true` produces a replacement Plan candidate from
fresh discovery/current durable state; it still requires new digest-bound P1
approval.

## Full / Refresh / clients

UNKNOWN test evidence remains `knowledge.testing: unknown` and
`tests.yaml.applicability: UNKNOWN`; it is never converted to NOT_APPLICABLE.
Observed build/test/architecture/module facts create the applicable generated
`development.md`, `testing.md`, architecture pointer, and minimal module
entries only when their target paths are absent. A pre-existing canonical
target is explicitly planned `PRESERVE/HUMAN_OWNED`; it is neither overwritten
nor silently reclassified. Pointers do not copy or take ownership of
HUMAN_OWNED authorities; module entries state verified path and UNKNOWN
purpose.

Mere existence of `docs/project/` is ordinary project material, not Scaffold
identity. Prior-host/recovery classification requires actual Scaffold evidence
such as `project.yaml`, lock state, a current Adoption/Migration artifact,
recognized core metadata, or an explicit generated router marker.

Fresh Bootstrap additionally requires both Adoption and Migration recovery
observations to be `NONE`. Historical, orphan, malformed, ambiguous, or
incomplete runtime evidence on an otherwise unidentified host is prior Scaffold
footprint, not legitimate `NOT_ADOPTED`. This rule remains inside the existing
`PRE_ADOPTION_BOOTSTRAP` / `HOST_COMPATIBILITY` model.

Refresh regenerates the affected module, command, test, project-fact, ownership,
and canonical-knowledge surfaces together. Missing indexed paths become
CONFLICTING/NEEDS_REFRESH. Safe GENERATED updates may be applied while another
authority conflict remains, but the top-level result is `NEEDS_HUMAN`, the
conflicts are blockers, and the next route is human ownership/knowledge
resolution followed by Refresh. It never reports ordinary
`COMPLETED/continue` while such conflicts remain. It does not edit business
source.

The P5-owned `modules.yaml`, `commands.yaml`, and `tests.yaml` indexes require
mapping form, `schema_version: "1"`, and the expected list-of-mappings
collection. Refresh classifies malformed/non-mapping/unsupported input instead
of calling mapping methods on it. A `GENERATED` malformed index is
deterministically reconstructed from current Discovery facts and validated
after publication; that repair is reported as a bounded mutation.
`HUMAN_OWNED` bytes are preserved and produce `NEEDS_HUMAN` when conflicting.
`MANAGED` cannot be whole-file replaced without a real bounded managed region,
so malformed/conflicting input blocks. If project ownership itself cannot be
safely established, Refresh blocks before index mutation.

`AGENTS.md` and `docs/project/overview.md` are required primary freshness
surfaces. Missing or stale GENERATED forms are deterministically restored and
post-write discovery validates the router before convergence. HUMAN_OWNED forms
are never rewritten; a missing/empty overview or incoherent human router
produces `NEEDS_HUMAN`, a top-level blocker, `NEEDS_REFRESH`, and no baseline
advance. MANAGED forms require an actual bounded region.

On coherent Full/activation and each successful converged Refresh,
`project.yaml.baseline` records the newly observed last-understood workspace.
Conflict-bearing Refresh retains the previous baseline and `NEEDS_REFRESH`.
Its unresolved conflict list remains durable so an unchanged second Refresh
cannot silently forget the conflict. After resolution and convergence, Refresh
clears `NEEDS_REFRESH` and the conflict list, then advances the baseline
together.

An existing `AGENTS.md` is recorded as `THIN_BRIDGE` only when its actual
content routes to `project.yaml`, the project overview, and `skills.lock`.
Otherwise it is PRESERVE/DEFER with a critical integration blocker; P5 never
silently replaces HUMAN_OWNED content.

## Compatibility / lock update

The validity layer remains outside the five-result taxonomy. Any invalid or
unresolvable required core package makes host evaluation non-executable with no
overall `EXACT`/`COMPATIBLE`. Evaluation also checks package format, Project
Contract generation, declared per-kind record requirements, legal
dependencies, and runtime/client facts before identity can be EXACT.

Lock-update planning accepts only core Skill keys and exact identities that
resolve to one intrinsically VALID package. It constructs and validates the
complete four-Skill result, exposes per-change compatibility/migration impact,
requires digest-bound approval, writes atomically, then re-inspects the lock
before reporting completion. A mixed explicit lock update removes stale
single-release provenance.

Persisting `NEEDS_MIGRATION` is reported as a bounded `project.yaml` mutation
only when `project.yaml` ownership authorizes a whole-file write. An
already-present condition produces no write. If compatibility is
`MIGRATION_REQUIRED` but ownership is `HUMAN_OWNED` or `MANAGED` without a
bounded region, evaluation may still report `MIGRATION_REQUIRED` when the
project schema is executable, but persistence is `NEEDS_HUMAN` / blocked,
mutations are none, and bytes stay unchanged. The same ownership gate applies
to Migration project writes and `skills.lock` updates before an Execution is
created or approval is treated as write authority.

## Migration recovery and convergence

Migration target generation is derived from explicit per-package compatibility
causes and intersected with every valid core package's declared generation
constraints. A caller-supplied target is only an assertion and must equal the
unique safe target; absent, ambiguous, unsupported, or conflicting target
evidence blocks.

Migration Plan identity is deterministically bound to its content, source
project, source authoritative lock, durable source Scaffold-state inventory and
fingerprint, exact source and target generations, mutation envelope, relevant
record requirements, and normalized compatibility binding. The source
inventory always covers project, lock, modules, commands, and tests metadata,
plus applicable registered GENERATED/MANAGED knowledge/client surfaces with
path/type/digest or absent evidence. It excludes `.scaffold/runtime`, caches,
temporary files, secrets, and arbitrary business files. The compatibility
binding contains the migration-causing Skill id,
expected and actual package identity (version, digest, package-format version),
declared supported project generations, relevant record-schema inputs, cause,
and evaluation digest. Approval must match both Plan id and digest.

Execution carries the same Plan id/digest, package/evaluation binding,
source/target generations, record requirements, intent, and envelope. Resume
requires one execution, current Plan-id-and-digest approval, unchanged source
lock, exact checkpoint prefix, actual project state equal to that prefix, and a
current package/evaluation runtime signature equal to the approved target.
Immediately before first mutation, P5 re-observes the complete source inventory;
any material change invalidates approval. After Apply begins, Execution
checkpoints permit only the approved project-envelope transition while all
other source authorities remain equal. Unexpected divergence or a changed
package blocks and routes to re-evaluation, a new Plan, and human re-approval.

`requires_host_migration` applies only while the declared target host generation
is unsatisfied. After successful migration, the old lock plus new actual package
evaluates `COMPATIBLE`; an optional explicit lock update can then change the
expected identity, after which evaluation is `EXACT`.

## Safe mutation

Single-file publish uses temp + `os.replace`. That is not a universal transactional filesystem. Partial/interrupted writes are surfaced as INTERRUPTED / RECOVERY_REQUIRED, never as success.

## B1 / SCM-neutral baseline

B1 records project root/existing state and a deterministic portable filesystem
fingerprint for every host. When ordinary local Git inspection is available it
also records the resolved HEAD commit, branch or detached/unborn state,
clean/dirty status, tracked-change presence, untracked-change presence, and
nested Git workspace evidence. Dirty work is valid input and is never
auto-committed or stashed.

No-SCM remains first-class: `kind: none`, null Git identity fields, and the same
portable filesystem evidence. P5 never invents a Git SHA and does not require
history, tags, remotes, or Git itself for core operation.

## Out of scope

P6 Test, P7 Develop, and P8 Submit implementations are absent. Fixture D/T/S manifests exist only so a four-Skill release can be tested.
