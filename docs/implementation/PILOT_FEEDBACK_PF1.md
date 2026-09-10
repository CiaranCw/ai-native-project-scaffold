# Pilot Feedback PF-1 — Understand real-project discovery

This implementation note does not modify or outrank P0–P4.

PF-1 is a targeted P5 Understand discovery/planning correction from reproduced
internal Pilot evidence. It does not continue Adoption, approve B4, start
Beacon, start FA-2 Batch 3, or productize Distribution.

Accepted Pilot behaviors remain in force: zero-context entry, `NOT_ADOPTED`
recognition, Understand bootstrap routing, preservation of existing AGENTS /
CLAUDE / Cursor Rules, stop before persistent Adoption mutation, and no manual
`.scaffold` editing.

## PF1-MAJ-001 Observed test discovery

Read-only discovery no longer depends on a top-level `tests/` directory.

Generic evidence channels:

- declared manifest test commands (`package.json` scripts named `test` / `test*`);
- small known test-runner config filenames;
- test filename patterns (`*.test.*`, `*.spec.*`, `test_*.py`);
- test directories under observed source areas (`tests`, `test`, `spec`, `__tests__`);
- existing human testing documentation (`docs/testing.md`, `TESTING.md`).

Observed test availability is not a REQUIRED test policy. `tests.yaml` profiles
created from observation use `policy: observed` and `required_authority: UNKNOWN`.
They omit `required: true` and do not write an authoritative `required: false`
policy decision. FA-2 Batch 3 closed C-MAJ-005. Discovery does not execute tests and does not install dependencies.

When a test surface is observed, the B3 plan can CREATE `docs/project/testing.md`.

## PF1-MAJ-002 Repository path case

Internal lookup may be case-insensitive. Emitted/shared paths use the actual
repository spelling. When Git observation succeeds, tracked-path spelling wins
over a normalized lookup key. A wrong-case path is never marked VERIFIED.

## PF1-MAJ-003 Project identity

Workspace basename is weak fallback evidence only. Stronger sources, when
present:

- adopted `project.yaml` `name` when it is not merely the worktree basename;
- `package.json` `name`;
- README heading title.

Disagreement is `CONFLICTING`. Discovery does not invent a canonical product name
for schema convenience. `project.yaml` `name` may be empty when identity is
unresolved.

## PF1-MAJ-004 Unsupported negative secret claim

`secrets_in_shared_knowledge` is `UNKNOWN` with no inspection. This is not a
security feature. No secret scanning, credential scanning, entropy scanning, or
vulnerability logic was added. `.gitignore` / missing `.env` is not evidence.

## PF1-QUAL-001 Module discovery

First-level source directories are not automatically modules. A coarse source
area such as `src` remains the module when only folder names exist. When two or
more child directories are corroborated by a second channel (architecture/docs/
rules text, or package workspace metadata), those boundaries are preserved.

## PF1-QUAL-002 Preservation presentation

Ownership is unchanged: reference does not transfer ownership, and the mutation
envelope remains CREATE/MANAGED_UPDATE. Bootstrap extras now include a human-facing
`preservation_presentation` of important PRESERVE areas (Agent/client files,
docs, observed source areas). This is not a per-file ownership registry.

## Command discovery

B6 already writes `.scaffold/commands.yaml`. PF-1 extracts `package.json`
scripts as declared commands with `availability: declared` and
`execution: not_validated`. That is not duplicated into B2/B3. DECLARED is
not PASS or FAIL. Missing `node_modules` does not fabricate a test/build result.

## Existing AI infrastructure

Existing `CLAUDE.md` and `.cursor/rules/` remain PRESERVE / HUMAN_OWNED unless a
separately authorized client strategy applies. PF-1 still requires that none of
those files are mutated before B4. PF-2 supersedes the AGENTS plan action: an
ordinary human-owned non-router `AGENTS.md` may be proposed as a bounded
`MANAGED_UPDATE` / `THIN_BRIDGE` instead of PRESERVE/DEFER. That proposal is
not an apply, and existing human bytes remain unchanged until B4.

## Distribution productization — deferred

Internal Pilot live-skills-checkout from a local Distribution checkout is an
acceptable harness. Installer, release catalog productization, Cursor plugin,
Claude integration, Codex integration, and automatic Distribution discovery remain
a Teammate Alpha productization gap. Not started in PF-1.

## Explicitly not absorbed

C-MAJ-001, C-MAJ-002, C-MAJ-003, C-MAJ-007, C-MAJ-008, C-MAJ-009,
and C-MAJ-013 through C-MAJ-019 are not closed by this task.
C-MAJ-005 is closed by later FA-2 Batch 3, not by PF-1.
