# FA-2 Batch 6 — Submit intake + Diff-semantic S3/S4

This implementation note does not modify or outrank P0–P4. FA2-FND-001,
FA2-FND-002, FA2-FND-003, and FA2-FND-004 remain effective Foundation input.
FA2-FND-004 supersedes the Batch-6 lexical S4 relevance heuristic.

Batch 6 implements:

- C-MAJ-003 no-Task Submit
- C-MAJ-007 Diff-semantic S3 Structural Review
- C-MAJ-008 Diff/impact-driven S4 Knowledge Consistency
- C-MIN-001 boundary-aware directory/area Task scope

It does not start Batch 7, P9, or DIVE. It does not claim those findings closed.

`submit@2.1.0` remains the unreleased MINOR candidate. This batch refines that
candidate. `skills.lock` is not rewritten.

## No-Task Submit

Records §13 and scenario M already require Submit to start when no Task Book
governs the candidate. P8 now observes the real S2 Diff first, then:

- explicit `task_id` uses the Task-aware path;
- omitted identity classifies each valid non-CANCELED Task as APPLICABLE,
  NOT_APPLICABLE, or UNKNOWN;
- exactly one APPLICABLE and zero UNKNOWN selects that Task;
- more than one APPLICABLE remains an ambiguous Task identity blocker;
- zero APPLICABLE and zero UNKNOWN is genuine no-Task (`task is None`);
- any UNKNOWN fails closed and does not enter no-Task, including when another
  Task is known applicable.

UNKNOWN applicability is not false. A Task whose known resolved paths already
cover the Diff is APPLICABLE even if another declared module cannot be resolved;
that Task then fails later at S3. CANCELED Tasks never govern and never create
applicability UNKNOWN.

No-Task does not invent a Task, READY_FOR_REVIEW, or Task COMPLETE. Result
extras report `task_complete` / `ready_for_review` as `NOT_APPLICABLE` and
`task_book_ids: []`. Change Records store zero Task identities and a
limitation that no Task Book governed the candidate.

An applicable IN_PROGRESS/DRAFT Task cannot masquerade as no-Task.

No-Task S5 still applies project-required Test policy. Absence of Task
requirements is not zero-required completeness.

## Directory scope

S3 and Task-applicability use the shared P5 `path_covered` relation.
`src/` includes `src/app.py` and `src/sub/a.py`, and does not include `src2/`
or `source/`. `foo/bar/` does not include `foo/barista/`. A scope directory
that exists is not reported missing merely because it is not a file.

## S3 structural impact

S3 consumes the authoritative S2 Diff (`paths` + `entries`), never caller
`changed_paths`, Task writes, or Change Record claims. Observation UNKNOWN
fails closed before S3/S4.

Bounded impact classes:

- MODULE_STRUCTURE
- PUBLIC_INTERFACE
- DEPENDENCY
- COMMAND
- TEST_CONFIGURATION
- PROJECT_CONFIGURATION
- SCAFFOLD_STRUCTURE

Ordinary implementation edits without a known structural surface remain
reviewable. A known surface whose effect cannot be determined is UNKNOWN and
is not PASS. `skills.lock` remains a compatibility fail-closed surface.
Batch 1 Rules/ownership still apply on the real Diff.

## S4 knowledge consistency

S4 maps determined S3 impacts to current knowledge surfaces (architecture,
module docs, development, testing, overview, AGENTS). The previous Batch-6
model treated current added bytes containing an impacted path, filename, or
module id as relevance authority. **FA2-FND-004 supersedes that lexical
model.** Mapped knowledge is current only when a current validated
Understand-owned Knowledge Assessment is bound to the current P6 candidate
and the exact current S3 knowledge-relevant impact digest, and every required
impact has `outcome = SATISFIED`. Path presence of a mapped document in the real
Diff is not enough, including when the current edit is unrelated. A
pre-existing textual mention of an impacted path, filename, or module id is
not a current update. Token co-occurrence of path, basename, module id, and
impact class MUST NOT independently establish SATISFIED. If no usable current
Knowledge Assessment exists, S4 is UNKNOWN and fails closed to
`understand.refresh`, not PASS. `NEEDS_HUMAN` is an explicit human blocker.
Module-doc mapping remains the mapped document for that module identity, not
any file under `docs/project/modules/`. Caller `maintenance_required=false`
cannot hide required updates. Maintenance NEEDS_REFRESH / NEEDS_MIGRATION
still route to Understand. Submit does not auto-edit documentation. Change
Record `knowledge_updates` is not S4 authority.

## Task scope in S3

Task-aware S3 derives allowed area from `scope.paths` union resolved
`scope.modules` (same modules.yaml `id`/`name` + `path`/`root` as P7), then
applies `scope.exclude` with boundary-aware `path_covered`. Module-only
Tasks are constrained. An unresolvable declared module is UNKNOWN and does not
become unrestricted scope. Genuine no-Task Submit still skips Task scope.

## Focused correction (B6-C01 / B6-C02 / B6-C03)

This note records the Batch-6 focused corrections for knowledge currentness,
complete Task scope, and tri-state implicit Task applicability. It does not
close C-MAJ-003/007/008 or C-MIN-001.

## Non-absorption

C-MAJ-001, C-MAJ-013, C-MAJ-014, C-MAJ-018, C-MAJ-019, C-MIN-004,
C-MIN-005, and C-MIN-006 remain later findings.
