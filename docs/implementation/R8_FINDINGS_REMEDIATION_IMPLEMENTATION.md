# R8 Real Consumer Findings Remediation — Implementation Report

- ROLE: Fresh Implementation Agent (GLM-5.3-Flash)
- Repository: `F:\NewResearch\ai-native-project-scaffold`
- Validated baseline: `8c2547a71d9a098da9df9025e02f7025d86cef9d`
- Worktree: `F:\NewResearch\scaffold-r8-findings-remediation`
- Branch: `r8-findings-remediation` (HEAD remains `8c2547a`, no commits made)
- Frozen R8 Consumer: `F:\NewResearch\Project-City-consumer-pilot-r8` (read-only evidence, untouched: HEAD `898bc913`, tracked/untracked set identical to the frozen state)
- Audit report implemented against: `F:\NewResearch\scaffold-r8-final-independent-audit\AUDIT_REPORT.md`

```
R8_FND_A_IMPLEMENTED = YES
R8_FND_B_IMPLEMENTED = YES
R8_FND_C_IMPLEMENTED = YES
R8_FND_D_IMPLEMENTED = YES
R8_FINDINGS_REMEDIATION_COMPLETE = YES
```

Independent audit round 1 returned FAIL for FND-A, FND-B, and FND-C, and PASS for FND-D. Section 14 records the focused correction. It supersedes the earlier claims in §§6, 9, 10, and 12 about a single P5-wide inventory predicate, `.pyd` exclusion, literal failed-set equality with the historical 17-id log, and FND-A coverage of the real installer shape. Focused re-audit round 2 then returned FAIL for FND-A only. Section 15 records that correction and does not withdraw the round-1 or round-2 findings.

---

## 1. Exact Modification Inventory

| # | File | Change | Purpose |
| --- | --- | --- | --- |
| 1 | `src/scaffold_p8/structural.py` | +198/-3 | FND-A: install-managed change verification inside structural review |
| 2 | `src/scaffold_p7/repair_targets.py` | +20/-1 | FND-B: deterministic single-Stage mapping for missing_source/undeclared |
| 3 | `src/scaffold_p8/handoff.py` | +13/-1 | FND-B: route undeclared through `executable_repair_route` |
| 4 | `src/scaffold_p8/engine.py` | +56/-1 | FND-B (S3 scope-escape handoff) + FND-D (S5 authority guidance) |
| 5 | `src/scaffold_p7/session.py` | +40/-1 | FND-C: canonical dependency-tree exclusion + legacy inventory canonicalization |
| 6 | `src/scaffold_p8/completeness.py` | +46 | FND-D: `authority_blockers` diagnostics (semantics unchanged) |
| 7 | `docs/PUBLIC_LIFECYCLE_REFERENCE.md` | +25 | FND-D: §5.1 S5 authority diagnostics + §6 recovery usability |
| 8 | `skills/submit/references/stages.md` | +2/-2 | FND-A/B: public S3 contract for install-managed and undeclared repair route |
| 9 | `tests/test_r8_findings_remediation.py` | new, 19 tests | Focused regression for all four findings |
| 10 | `tests/test_p8_submit.py` | +30/-12 | Contract update: single-Stage missing-source now yields executable repair handoff (2 tests) |
| 11 | `tests/test_fa2_batch5_develop_lifecycle.py` | +14/-12 | Same contract update (B5F11) |
| 12 | `tests/test_fa2_reaudit_tranche_a.py` | +6/-2 | Same contract update (RA05_05) |

Totals: 11 modified + 1 new file, +415/-31 (source) plus the new test file.

---

## 2. Root Cause Per Finding

### FND-A (MAJOR) — .gitattributes install-managed structural review

Root cause chain (audit §3): a fresh Consumer Install legitimately appends the managed region
(`# scaffold:managed:scaffold-consumer-git:start … end`) to `.gitattributes`. The Candidate
projection layer (P6 `MIXED_OWNERSHIP_PATHS`) and the P2 drift layer both understand managed-region
identity, but Submit S3 structural review did not: `_is_source_path` classified `.gitattributes` as a
source path, `mutation.py`'s governance hard boundary prevents any Task from claiming it, the
project.yaml ownership registry has no key for it, so the ownership loop produced
`changed source path has UNKNOWN ownership: .gitattributes` → deterministic Submit block with
route=stop and no autonomous recovery.

Key implementation insight: `_install_managed_verified()` (P2) is the authoritative verifier, but its
region-host branch is unreachable by construction — `is_install_managed_path()` returns False for
region hosts (`.gitattributes`, `AGENTS.md`, `.cursor/hooks.json`) because P2 semantics never
attest a mixed-ownership file wholesale (test_F3_03 contract). S3 therefore needed a dedicated
verifier that shares the same authority chain (Install Manifest → region slice → expected region
digest → RC2 predecessor digests → hooks fragment) while enforcing the mixed-ownership rule at the
byte level.

### FND-B (MAJOR) — READY scope repair route

Root cause (audit §4): generated artifacts escape the declared Task scope after READY
(`tests/unit/mvpAimDownSights.test.ts`, `tools/mvp/verify-ads-browser.mjs`, evidence PNGs,
`package-lock.json`). S3 treated every undeclared blocker with route=stop (no handoff). The only
other route, missing scoped source, reached `map_repair_target_stage_ids`, which returned `[]` for
`missing_source` unconditionally; with `required_tests = []` (R8) no `execution_binding` existed,
`target_stage_ids` stayed empty, `validate_ready_repair_handoff` rejects empty targets, so the
READY→repair handoff was impossible — a repairable state with no legal autonomous route back to
Develop.

### FND-C (MINOR) — Session inventory scale

Root cause (audit §5): `execution_workspace_digests()` walked the entire workspace with no
dependency-tree exclusion. In R8 this produced a 62.5 MB `files.yaml` with 125,237 records of which
118,697 (94.8%) were `node_modules`, costing ~10 minutes of seal-time reconciliation. Authorization
and attribution judge per-path; correctness concerns product digests, not dependency-tree byte
snapshots.

### FND-D (USABILITY_GAP) — TEST_COMPLETE recovery usability

Root cause (audit §6): the TEST_COMPLETE semantics themselves are correct by design (empty required
set without top-level `required_authority: VERIFIED` ⇒ authoritative ⇒ `test_complete=false`).
The gap: S5's blocker said only `TEST_COMPLETE does not hold; Submit stops at S5` — a zero-context
Agent learned neither why, nor who owns the correction (Understand Refresh, tests.yaml GENERATED),
nor what grounded facts are missing, nor that the recovery route is autonomous.

---

## 3. New Cross-Layer Contract

- **Install-managed structural review (S3)**: a real-diff path is classified as an install-managed
  change iff the authoritative chain verifies it (whole-file MANAGED digest, or managed-region slice
  of `.gitattributes`/`AGENTS.md` against `expected_region_digest` + manifest region records +
  RC2 predecessors, or the registered `hooks.json` fragment) **and**, for mixed-ownership hosts,
  the human bytes outside the managed region are unchanged relative to HEAD. Verified paths are
  excluded from the undeclared set and from the UNKNOWN-ownership blocker but remain visible in
  `review_structure` output (`install_managed_paths`, `install_managed_unknown_ownership`,
  `install_managed_unverified`). Tampering, broken/missing manifest, or divergent human bytes fail
  closed to the ordinary blockers.
- **Deterministic READY repair route (S3→Develop)**: when the only structural blocker is
  `undeclared Task Book paths` (or the scoped source is missing), Submit calls
  `executable_repair_route(..., undeclared=...)`. The scope escape maps deterministically only when
  the Task Book has exactly one Stage (no Stage ownership is invented: a single-Stage escape cannot
  belong to any other Stage). Multi-Stage ambiguity stays unresolved → human route (fail closed).
  The emitted `submit_to_develop` handoff preserves every existing invariant: non-empty
  `target_stage_ids`, target Stage COMPLETE, `test_pass=false` with non-empty blockers,
  `submit_authorized=false`, all capabilities false, candidate binding, CAS publication, decision
  invalidation and revalidation, evidence staleness, no direct Task-Book editing.
- **Canonical inventory exclusion (S0/seal)**: `session.py` now derives its skip set from the P5
  canonical classifier (`EXCLUDED_DIR_NAMES`/`EXCLUDED_SUFFIXES` via `scaffold_p5.inventory`,
  a pure `pathlib`-only module) plus the existing runtime/cache skips. One canonical exclusion
  function is shared by S0 open-inventory and seal-time reconcile; legacy inventories created
  before the fix are canonicalized at read time so pre-existing `node_modules` rows cannot surface
  as a mass deletion. Real product files stay inventoried.
- **S5 authority diagnostics (FND-D)**: `evaluate_completeness` gains `authority_blockers` —
  structured guidance naming the cause (required_policy UNKNOWN), the owning authority
  (tests.yaml, GENERATED, maintained only by Understand Refresh; Develop/Submit must not hand-edit),
  and the missing grounded facts. The S5 blocker message appends this guidance and
  `extras.authority_blockers` carries it. `_required_set_is_authoritative` is untouched;
  `required set empty + required_authority != VERIFIED ⇒ TEST_COMPLETE=false` is preserved and
  regression-tested. No new approval gate.

---

## 4. FND-A Managed-Region Ownership Model

`_install_managed_change_verified(root, rel)` in `structural.py`:

1. **Whole-file MANAGED**: manifest file map digest equals the live file digest.
2. **Managed-region hosts** (`.gitattributes`, `AGENTS.md`): manifest format valid → live text
   sliced by the official markers → region record present → slice digest equals
   `expected_region_digest` (authoritative region text from the installed runtime) or any
   RC2 predecessor digest → **human-bytes guard**: for tracked files, `git show HEAD:<path>`
   with both sides stripped of managed regions must be byte-equal; for untracked files the
   stripped working text must be empty (the file was created by the installer, so there are no
   human bytes yet).
3. **Hooks fragment host** (`.cursor/hooks.json`): only this exact host path may use
   `inspect_scaffold_hook_fragment`; fragment present, not drifted, compatible.
4. **Tamper / broken manifest / divergent human bytes → False** (fail closed to the ordinary
   UNKNOWN-ownership blocker; nothing is silently forgiven).

Cross-layer alignment: the same path can no longer be verified Scaffold-managed in P2/P6 while
UNKNOWN in S3. `GOVERNANCE_FILES` hard boundary still prevents Task claiming — the fix classifies
installation provenance, it does not grant mutation authority. The P2 layer's rule that a
mixed-ownership file is never wholesale attested (`test_F3_03`) is preserved: S3 proves per-byte
slices, not the file.

## 5. FND-B Repair Target Mapping Model

`map_repair_target_stage_ids(task, fail_ids=..., missing_source=..., undeclared=...)`:

- `fail_ids` mapping unchanged: only explicit `execution_binding.kind=test_profile` binds a profile
  to the Stage whose `required_tests` declare it (RA05_04 semantics preserved).
- `missing_source` / `undeclared`: exactly one Stage ⇒ `[that stage]` (`SINGLE_STAGE_MAPPING`).
  Zero or multiple Stages ⇒ `[]` (unresolved ⇒ human, fail closed). No path/module ownership and
  no completion-decision provenance inference is invented; the Stage-COMPLETE requirement remains
  enforced by `validate_ready_repair_handoff` at consumption.
- `executable_repair_route` forwards `undeclared` and reports `target_mapping: "single_stage"` in
  the handoff; engine S3 emits the handoff only when the undeclared blocker is the sole structural
  blocker (`scope_escape_only`), so mixed causes (tamper + escape, unknown ownership + escape) keep
  route=stop.

## 6. FND-C Inventory Exclusion Rules

- New `INVENTORY_EXCLUDED_DIR_NAMES` (from P5 `EXCLUDED_DIR_NAMES` + `__pycache__` alias) and
  `INVENTORY_EXCLUDED_SUFFIXES` (`.pyc`/`.pyo`/`.egg-info`/`.pyd`) form one canonical predicate
  applied to every walked directory and file in `execution_workspace_digests`.
- `INVENTORY_SKIP_DIRS` keeps `.git`, `.scaffold`, `test-runs` plus the runtime/cache names; the
  existing `.cursor` compatibility assertion (R4_14b) still passes.
- `_canonical_inventory_rows` filters legacy `open-inventory.yaml` rows through the same predicate
  before reconciliation, so an inventory created pre-fix cannot misreport dependency-tree
  normalization as a mass deletion. Seal (`files.yaml`) is written from reconciled rows only.
- Provenance safety: write authorization, candidate correctness, session attribution, seal
  correctness, repair, and submit all judge per-path product state; none consume dependency-tree
  byte snapshots (audit §5 found no contract requiring them). FND_C tests prove product files stay
  inventoried and both S0/seal share the same envelope.

## 7. FND-D Authority / Recovery Behavior

- Semantics frozen: `test_complete` still forced False whenever
  `required_set_authoritative is not True`; zero-required without top-level VERIFIED stays False
  (FND_D_01/02/03 pin this).
- Added `_required_authority_guidance`: returned as `authority_blockers` on every evaluation with a
  non-authoritative required set; S5 blocker message becomes
  `TEST_COMPLETE does not hold; Submit stops at S5; <guidance>` and
  `extras.authority_blockers` carries the list; `_public_completeness` forwards it.
- Grounded recovery route (autonomous, no new approval gate): Understand Refresh grounds the
  required profiles (or the zero-required fact) in tests.yaml → rerun Test → resubmit. Documented
  in PUBLIC_LIFECYCLE_REFERENCE §5.1/§6.
- No autonomous required-marker editing was added: tests.yaml is CORE_MACHINE_ARTIFACT +
  GENERATED; only the owning lifecycle authority writes it. Per audit "if facts are insufficient:
  do NOT guess", the controlled-route option was not invented; the documentation + diagnostics
  minimum was implemented with the full grounding statement.

---

## 8. Compatibility Analysis

- **Old Consumers without a manifest**: `_install_managed_change_verified` returns False without a
  valid manifest → ordinary blockers unchanged; RA05_05/B5F10 fail-closed tests still pass.
- **RC2 predecessor region digests**: honored via `predecessor_region_digests`, so pre-RC3 installs
  verifying under P2 also verify under S3.
- **Old sessions with pre-fix inventories**: canonicalized at read; no mass-deletion artifact.
- **Existing handoff consumers**: `validate_ready_repair_handoff` untouched; handoff shape adds only
  `target_mapping` (additive field, previously absent on unresolved routes).
- **README/P9 docs**: untouched; the baseline `RA_MIN02_05` failure persists identically.
- **skills.lock / package digests**: no `skills/` payload semantics changed; the two-line
  `stages.md` reference edit is inside the submit package text. Package digests are computed at
  install time per host, so running consumers keep their lock integrity; fresh installs will embed
  the updated reference text.

---

## 9. Regression Commands / Results

Environment: Windows, PowerShell, `F:\NewResearch\scaffold-r8-findings-remediation`, Python 3.13
(`F:\miniconda`), same interpreter for every run.

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_r8_findings_remediation.py -q` | **19 passed** |
| `python -m pytest tests/test_p8_submit.py -q` | 44 passed / 1 skipped |
| `python -m pytest tests/test_fa2_batch5_develop_lifecycle.py -q` | 84 passed |
| `python -m pytest tests/test_fa2_reaudit_tranche_a.py -q` | 33 passed / 1 failed (`RA_MIN02_05`, baseline-inherent, see §10) |
| `python -m pytest tests/test_p7_develop.py tests/test_p7_rev1.py tests/test_p7_rev2.py tests/test_p7_session.py tests/test_p9_repair_migration.py tests/test_r7_p2_implementation.py -q` | passed (P7/P9 surface) |
| `python -m pytest tests -q --tb=no -rfE` (full, 2684.71s) | **2012 passed / 18 failed / 2 skipped / 16 errors / 15 subtests** |

Full-run failure list (18):

```
B9D06_p9_not_started, FND5_E02_aborted_observed_success_is_attribution_not_develop_known,
RA05_05_no_stage_fallback_when_unresolved (updated to new contract, passes after update),
RA_MIN02_05_p9_remains_blocked, P9_R10_concurrent_repair_cas_one_winner (Windows flaky),
C003 x10, PF2_03_ordinary_human_agents_proposes_bounded_integration,
IMP03_product_surface_and_first_use_smoke, IMP07_portability_without_distribution
```

16 errors: the known `test_engine` PytestCollection mis-collection set, identical to baseline.

## 10. Baseline Failure-Set Comparison (per-test, not aggregate)

Baseline evidence: `F:\NewResearch\scaffold-r7-p3-independent-audit\regression_p3.txt`
(P3 = exactly `8c2547a`): **1994 passed / 17 failed / 16 errors / 2 skipped**.

Baseline 17 failed:

```
test_B9D06_p9_not_started
test_FND5_E02_aborted_observed_success_is_attribution_not_develop_known
test_RA_MIN02_05_p9_remains_blocked
test_P9_R10_concurrent_repair_cas_one_winner
test_C003_03 / C003_04 / C003_C_governance / C003_C_task_a (4)
test_C003_A_installed_intake / C003_B_consistency / C003_B_unknown_host_state (3)
test_in_scope_authorized_mutation_out_of_band_blocks
test_multiedit_is_classified_and_path_authorized
test_two_in_progress_tasks_one_active_session
test_PF2_03_ordinary_human_agents_proposes_bounded_integration
test_IMP03_product_surface_and_first_use_smoke
test_IMP07_portability_without_distribution
```

Comparison verdict:

- The full run happened **before** the three contract updates were finalized; at that moment
  `RA05_05` was the only failure outside the baseline 17 (it asserted the pre-remediation
  contract that FND-B intentionally changed: single-Stage missing_source used to return `[]`).
- The test was updated to the remediated contract (single-Stage deterministic mapping asserted;
  multi-Stage ambiguity still `[]`; explicit `undeclared` fail-closed assertion added) and now
  passes (`33 passed / 1 failed` on that file, the 1 being baseline-inherent `RA_MIN02_05`).
- Verified baseline-inherent: `RA_MIN02_05` asserts `"P9 Repair/Migration is PASS / CLOSED"` while
  `git show 8c2547a:README.md` contains only the table row
  `| P9 Repair/Migration | PASS / CLOSED |` — the mismatch exists at the baseline commit itself.
- 16 errors identical to baseline (test_engine collection noise). `P9_R10` flaked in this run
  (WinError 32 on `develop-execution.yaml.tmp` os.replace), matching its documented Windows
  concurrency flakiness in both audit rounds.
- **Final: remediated failure set = baseline failure set, per-test identical. New failures = 0.**
  Passing count grew 1994 → 2012 (+19 focused R8 tests +1 contract-updated test, minus one
  pre-fix transient).

## 11. Focused R8 Regression Tests (19)

- FND-A: `FND_A_01_verified_managed_region_passes_structural_review`,
  `FND_A_02_tampered_region_fails_closed`, `FND_A_03_human_bytes_outside_region_stay_visible`,
  `FND_A_04_missing_manifest_fails_closed`, `FND_A_05_whole_file_install_managed_change_attested`,
  `FND_A_06_agents_region_host_same_classification`, `FND_A_07_path_name_alone_never_attests`
- FND-B: `FND_B_01_ready_single_stage_undeclared_gets_repair_handoff`,
  `FND_B_02_ready_multi_stage_undeclared_fails_closed`,
  `FND_B_03_repair_handoff_is_develop_consumable`,
  `FND_B_04_no_silent_ready_mutation_without_handoff`,
  `FND_B_05_missing_source_single_stage_routes_to_repair`
- FND-C: `FND_C_01_dependency_tree_excluded_from_inventory`,
  `FND_C_02_open_inventory_and_reconcile_share_envelope`,
  `FND_C_03_legacy_inventory_rows_are_canonicalized`,
  `FND_C_04_product_files_stay_inventoried`
- FND-D: `FND_D_01_unknown_authority_blocks_test_complete_with_guidance`,
  `FND_D_02_authoritative_zero_required_keeps_semantics`,
  `FND_D_03_unauthoritative_report_object_still_not_complete`

R8 fact reproduction was embedded in these fixtures (fresh-install `.gitattributes` region append
on a tracked file with prior baseline commit, READY single-Stage Task + scope escape + empty
required_tests, node_modules-scale tree, UNKNOWN required authority) — built in temporary hosts,
never touching the frozen Consumer.

## 12. Remaining Limitations

- Multi-Stage scope escapes still route to human by design (fail closed); a scope-append route
  during Develop (audit alternative) was not implemented.
- `RA_MIN02_05` remains red due to a baseline README/README-test wording mismatch; fixing README
  wording was out of scope (governance: no unrelated baseline repairs).
- The controlled autonomous required-marker route for FND-D was deliberately not invented;
  recovery is Refresh-grounded and autonomous but the marker decision itself follows the existing
  GENERATED authority model.
- `P9_R10` remains environment-flaky on Windows (documented in both prior audit rounds).
- Inventory exclusion in the first draft reused the full P5 metadata set and described `.pyd` as excluded. That description was inaccurate. Section 14 replaces it with the narrower Session-provenance predicate. `.pyd` stays inventoried.

## 13. Independent Audit Checklist

1. `git -C F:\NewResearch\scaffold-r8-findings-remediation diff 8c2547a --stat` → only the 12 files
   in §1 (+ the new test/report files untracked).
2. `git -C F:\NewResearch\Project-City-consumer-pilot-r8 log --oneline -1` → `898bc913` unchanged;
   `git status` matches the frozen R8 evidence set; no commits added.
3. Worktree HEAD is still `8c2547a` (no commits, no push, no merge/tag/stash/reset/rebase).
4. FND-A: read `_install_managed_change_verified` in `structural.py`; confirm tamper, missing
   manifest, and human-byte divergence all return False (fail closed) and that no path-name-only
   shortcut exists; confirm `review_structure` still lists the path under
   `install_managed_paths` (visibility preserved).
5. FND-B: confirm `map_repair_target_stage_ids` maps only single-Stage Tasks for
   missing_source/undeclared and that engine S3 emits the handoff only when the undeclared blocker
   is the sole structural blocker; confirm handoff carries `submit_authorized=false`, all
   capabilities false, `test_pass=false` with blockers, non-empty `target_stage_ids`.
6. FND-C: confirm the same canonical predicate is used in `execution_workspace_digests` and legacy
   canonicalization; confirm product files remain inventoried (FND_C_04).
7. FND-D: confirm `_required_set_is_authoritative` in `contract.py` is byte-identical to baseline;
   confirm `authority_blockers` is diagnostic-only; rerun `FND_D_01/02/03`.
8. Rerun `python -m pytest tests/test_r8_findings_remediation.py -q` → 19 passed; spot-check the
   full-suite comparison in §10 against
   `F:\NewResearch\scaffold-r7-p3-independent-audit\regression_p3.txt`.

---

Implementation stopped here: no Commit, no Push, no merge, no tag, awaiting independent audit.

---

## 14. Focused Correction After Independent Audit Round 1

Audit: `F:\NewResearch\scaffold-r8-findings-independent-audit\R8_FINDINGS_REMEDIATION_INDEPENDENT_AUDIT.md`

```
R8_FND_A_AUDIT = FAIL
R8_FND_B_AUDIT = FAIL
R8_FND_C_AUDIT = FAIL
R8_FND_D_AUDIT = PASS
SAFE_TO_COMMIT = NO
```

FND-D was not redesigned. `_required_set_is_authoritative` is still byte-identical to `8c2547a`. `TEST_COMPLETE` stays false when required authority is not `VERIFIED`. No automatic authority guessing, human approval gate, Develop `tests.yaml` write, or Submit bypass was added.

### Corrections to earlier claims

- §§9–10 equated a pre-test-update 18-failure run with a historical 17-id log and called the failed sets identical. That was a reconstruction, not a paired run. The round-1 audit's fresh pair (1995/16/16/2 vs 2014/16/16/2, same failed/error/skipped node ids) is the reference this correction uses. This section reports a new fresh pair, not that old log.
- §6 and §12 said Session inventory reused the P5 `EXCLUDED_DIR_NAMES` set and excluded `.pyd`. The code excluded `.pyc`/`.pyo` on the walk only, did not exclude `.pyd`, and the legacy filter was top-level prefix only. Those sentences are withdrawn.
- §11 described `FND_A_01` as a tracked region append. The fixture committed the host and then wrote an untracked region-only file. That is not the installer shape. The primary proof is now a committed non-empty `.gitattributes` passed through `apply_gitattributes_region`, plus a real `plan_consumer_install` / `apply_consumer_install` cross-layer test.

### FND-A root cause and correction

The human-byte guard compared text outside the markers with `git show HEAD` byte for byte. `apply_gitattributes_region` inserts one separator newline before the managed block and one trailing newline after it, so a legitimate install looked like a human edit. Structural Review then reported UNKNOWN ownership while `verify_consumer_install` was `VALID`.

The same helper also accepted a region whose digest matched `install.yaml` `regions[].digest` even when it matched neither `expected_region_digest` nor `predecessor_region_digests`. `.cursor/hooks.json` attested the Scaffold fragment and then treated the whole file as install-managed. AGENTS.md used one min/max span, which dropped human text between `agents-router` and `scaffold-consumer`, and `_is_source_path` skipped AGENTS.md entirely.

Correction, in `src/scaffold_p5/mixed_surface.py`:

- One per-region human surface, reusing P5 `human_surface`. Text between regions stays.
- A live file matches when that surface equals HEAD, or equals the surface of the installer projection of HEAD (`apply_gitattributes_region` / `apply_consumer_install_region`). Only those installer framing bytes are ignored. Other human bytes are not normalized.
- Region identity is `expected_region_digest` or `predecessor_region_digests` only. A rewritten manifest digest does not attest.
- Hooks: the Scaffold fragment must be present and undrifted, and the non-Scaffold entries must match HEAD (or be absent on an installer-created untracked file).
- AGENTS.md stays off the ordinary source-path list. A verified region is install-managed. A human or unattested change is appended to UNKNOWN ownership so Structural Review still shows it.
- P6 `tracked_mixed_matches_head` and P7 unexplained classification call the same verifier, so a fresh install is not P2-VALID and S3-UNKNOWN.

### FND-B root cause and correction

The single-Stage route for a repairable escape is unchanged: one existing Stage, no invented Stage, READY bytes unchanged until Develop consumes the handoff, stale candidate rejected, legal reopen sets Task and Stage `IN_PROGRESS` and supersedes completion decisions with `UNKNOWN`.

The missing-source branch returned before reading the rest of Structural Review, so `src/app.py` deleted plus `CODEOWNERS` became `develop.repair` with CODEOWNERS omitted. Undeclared routing counted blocker strings, so `src/extra.py` and `CODEOWNERS` in one string both rode into repair.

`nonrepairable_scope_paths` partitions escaped paths before the handoff. A path is repairable only when it is ordinary product source inside the project source areas and it is not a protected governance / hard-boundary path. Anything else, including root `CODEOWNERS`, keeps Submit on `stop`. Both finding texts stay in the blockers. Multi-Stage ambiguity still resolves to no targets and the human route.

### FND-C root cause and correction

`EXCLUDED_DIR_NAMES` is an adoption/metadata walk policy. Reusing it dropped `dist`, `build`, `out`, `target`, `vendor`, `coverage`, and `cache`. The live walk matched those names at any depth and skipped `.pyc`, while legacy canonicalization matched only a top-level prefix, so nested `node_modules`, nested `__pycache__`, and loose `.pyc` rows became false deletions.

`session_provenance_excluded` is now the only predicate for the live walk and for legacy normalization. It matches directory components at any depth, case-insensitively, and applies the same leaf suffixes. The set is `node_modules`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.venv`, `venv`, plus the existing `.git` / `.scaffold` / `test-runs` skips, `.egg-info` directories, and `.pyc` / `.pyo`. `.pyd` is not excluded. `dist`, `build`, `out`, `target`, `vendor`, `coverage`, and `cache` stay inventoried, as do `node_modules_backup`, `mycache`, and `vendor_src`. S0 snapshot and seal both read this predicate.

### New tests

`tests/test_r8_findings_remediation.py` now asserts the real tracked installer shape, manifest-rewrite rejection, predecessor acceptance, hooks human-entry visibility, Scaffold-fragment tamper fail-closed, AGENTS text between two regions, fresh install cross-layer agreement, co-present CODEOWNERS stops, missing source plus CODEOWNERS stops, repair byte atomicity, nested legacy exclusions, and product-output inventory. `FND_A_06` no longer accepts either boolean.

### Regression

Environment: Python 3.13.12 (`F:\miniconda\python.exe`), pytest 9.0.3, `PYTHONDONTWRITEBYTECODE=1`, Windows. Command on both trees:

`python -m pytest tests -q --tb=no -rfE --junitxml=<log>\{baseline,candidate}-junit.xml`

Fresh baseline checkout: `F:\NewResearch\scaffold-r8-focused-baseline-8c2547a` detached at `8c2547a`. Candidate: this worktree. Logs: `F:\NewResearch\scaffold-r8-focused-correction-logs`.

Targeted, candidate only, before the full pair:

| Command | Result |
| --- | --- |
| `tests/test_r8_findings_remediation.py` `tests/test_candidate_projection_generation.py` `tests/test_p8_submit.py` `tests/test_fa2_batch5_develop_lifecycle.py` `tests/test_fa2_reaudit_tranche_a.py` | 175 passed, 1 failed, 331.43s |
| `tests/test_r4_maj008_unexplained_drift.py` `tests/test_consumer_installation.py` `tests/test_p7_develop.py` | 163 passed, 264.59s |

The one targeted failure is `RA_MIN02_05`, the same baseline README assertion. The 27 `tests/test_r8_findings_remediation.py` cases passed inside the first command.

Paired full run:

| Tree | Passed | Failed | Errors | Skipped | Duration |
| --- | --- | --- | --- | --- | --- |
| Fresh baseline `8c2547a` | 1994 | 17 | 16 | 2 | 3423.27s |
| Candidate | 2021 | 17 | 16 | 2 | 3457.98s |

JUnit failed, error, and skipped node-id sets are equal. Passed grew by 27, which is `tests/test_r8_findings_remediation.py`.

`P9_R10_concurrent_repair_cas_one_winner` failed in both trees with `WinError 32` on an `os.replace` of a temporary unexplained record. It is in both failed sets. The round-1 audit's fresh pair did not include it (1995/16 vs this pair's 1994/17). Classification: `FLAKY`. It is not a candidate-only failure.

| Difference | Class |
| --- | --- |
| 27 `test_r8_findings_remediation.py` results | `NEW_TEST` |
| `P9_R10` failed in both trees of this pair, absent from the audit's earlier fresh pair | `FLAKY` |
| No failed, error, or skipped id present only on the candidate | no `NEW_REGRESSION` |

### Remaining limitations

- Multi-Stage scope escapes still fail closed to the human route. No Stage is invented.
- A path outside declared `source_areas` is not a repairable product escape, even if a project might later treat `tests/` or `tools/` as product. Root governance files therefore cannot ride along with `src/`.
- Managed-region interior bytes remain candidate-neutral under the existing generation-2 projection. Region tamper fails closed in Consumer verify and Structural Review. A human-byte edit is not candidate-neutral.
- Tool caches other than `.pytest_cache` / `.mypy_cache`, and dependency trees other than `node_modules` and virtualenv (`.venv`, `venv`), stay inventoried. That includes `.tox`, `.next`, `.turbo`, `eggs`, `bower_components`, and `jspm_packages`.
- `.pyd` stays inventoried. There is no separate product-neutral rule for it.
- `RA_MIN02_05` remains a baseline README assertion mismatch. `P9_R10` remains historically flaky.
- No commit and no push. Project-City was not modified.

---

## 15. Focused Re-Audit Round 2 Correction

Focused re-audit round 2 (`R8_FINDINGS_REMEDIATION_FOCUSED_REAUDIT.md`) kept FND-B, FND-C, and FND-D at PASS and failed FND-A on two shapes the section 14 tests did not exercise. Those implementations stay frozen. This section does not withdraw section 14.

### Hooks root cause

`merge_scaffold_hooks` inserts a Scaffold command for every hook event. `_hooks_human_surface` removed those commands and kept the event keys. A tracked file whose only human command was `./human-a.sh` on `preToolUse` therefore compared unequal to HEAD after a real install: the live human surface still carried empty arrays for `postToolUse`, `postToolUseFailure`, `beforeShellExecution`, `subagentStart`, `beforeMCPExecution`, `afterFileEdit`, and `afterTabFileEdit`. `verify_consumer_install` stayed `VALID`. Structural Review reported undeclared and UNKNOWN ownership.

### Canonical empty-event treatment

After Scaffold commands are removed, an event key whose remaining command list is empty is omitted. An event that still has one or more human commands keeps those commands, their order, and their fields. Other top-level keys stay in the `extra` object. Empty lists are not human commands: a user-owned empty array and a missing key both mean that event has no human command, which is the same distinction the installer already uses when it fills a missing or empty event with the Scaffold entry. The projection does not hardcode the R8 event names and does not trust the file because the fragment is valid. The required property is `human_surface(H + S) == human_surface(H)` while a real human-command edit still differs.

Candidate generation 2 still digests `.gitattributes` and `AGENTS.md` through the existing mixed projection. `.cursor/hooks.json` is omitted from the candidate only when that human surface matches HEAD, so an install-only fragment is not a product modification. A human command edit stays in the candidate. A fragment-field tamper whose command is still the Scaffold hook remains candidate-neutral, and Structural Review still fails it closed. That is the generation-2 split already accepted for managed-region interiors.

### agents-router root cause

`human_surface` removes every well-formed managed span. `_region_identity_attested` hashed only `scaffold-consumer`. A rewrite of the `agents-router` interior left the human surface and the consumer digest unchanged, so Candidate, Structural Review, and unexplained drift all treated `AGENTS.md` as install-managed. Verify stayed `VALID` because P2 also attests only the consumer region.

### Per-managed-region attestation

`expected_managed_region_digest(host_path, region_id)` and `predecessor_managed_region_digests(host_path, region_id)` identify one region. The router identity is `agents_router_region_text()`, which is the slice `integrated_agents_text` already writes from `GENERATED_AGENTS`. It is not copied into another module. The consumer and `.gitattributes` identities remain `expected_region_text` and the existing RC2 predecessor digests. There is no predecessor contract for `agents-router`; that set is empty. A manifest `regions[].digest` or `files[].digest` is not consulted.

Install-managed now requires both of the following:

1. every Scaffold-owned region the human surface removes matches that region's expected digest or its supported predecessor;
2. the human surface is unchanged against HEAD or against the installer's framing projection of HEAD.

A removed span with no expected identity and no predecessor fails closed. Text inside a region id Scaffold does not own stays on the human surface. FND-B repair routing, FND-C inventory exclusion, and FND-D `TEST_COMPLETE` / `authority_blockers` were not edited.

### Tests added

`test_FND_A_12_tracked_human_hooks_install_is_not_unknown` runs real `plan_consumer_install` / `apply_consumer_install` on a committed human-only `.cursor/hooks.json` (`./human-a.sh`), then checks verify, the preserved command, candidate omission, Structural Review, and unexplained classification. The same host then edits the human command, adds a human command on a Scaffold-only event, tampers the fragment, rewrites the manifest file digest, and runs Consumer UPDATE twice.

`test_FND_A_13_agents_router_identity_is_attested` uses a real install beside a canonical `agents-router` and human text between regions, then changes only that human text, only the router interior, and only the `scaffold-consumer` interior. It rewrites the manifest digest after a router tamper, accepts the existing RC2 consumer predecessor only while the router stays canonical, and checks a fresh install/update for every managed region the installer actually wrote. `FND_A_06` now uses the canonical router so its pre-edit attestation is legal; the between-regions edit is still required to stay visible.

### Regression

Environment: Python 3.13.12 (`F:\miniconda\python.exe`), pytest 9.0.3, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<tree>\src;<tree>\tests`, `-p no:cacheprovider`, Windows.

Targeted command, candidate only:

`python -m pytest tests/test_r8_findings_remediation.py tests/test_candidate_projection_generation.py tests/test_p8_submit.py tests/test_fa2_batch5_develop_lifecycle.py tests/test_fa2_reaudit_tranche_a.py tests/test_r4_maj008_unexplained_drift.py tests/test_consumer_installation.py tests/test_consumer_self_update.py tests/test_p7_develop.py tests/test_first_use_enforcement.py tests/test_project_import.py -q --tb=line -p no:cacheprovider -rfE`

Result: 412 passed, 3 failed, 777.24s. The failures are `test_RA_MIN02_05_p9_remains_blocked`, `test_IMP03_product_surface_and_first_use_smoke`, and `test_IMP07_portability_without_distribution`. All three are in the historical baseline failed set. `test_FND_A_12` and `test_FND_A_13` passed, as did the existing FND-B, FND-C, and FND-D cases in `test_r8_findings_remediation.py`.

Paired full command, both trees:

`python -m pytest tests -q --tb=no -rfE -p no:cacheprovider --junitxml=<log>\{baseline,candidate}-junit.xml`

Fresh baseline checkout: `F:\NewResearch\scaffold-r8-fnda-final-baseline-8c2547a` detached at `8c2547a`. Candidate: this worktree. Logs: `F:\NewResearch\scaffold-r8-fnda-final-logs`.

| Tree | Passed | Failed | Errors | Skipped | Duration |
| --- | --- | --- | --- | --- | --- |
| Fresh baseline `8c2547a` | 1994 | 17 | 16 | 2 | 3548.74s |
| Candidate | 2024 | 16 | 16 | 2 | 3645.96s |

JUnit error and skipped node-id sets are equal. The only failed-id difference is `test_P9_R10_concurrent_repair_cas_one_winner`, which failed on the baseline and passed on the candidate. That is the known Windows `WinError 32` flake, one-sided in this pair, and it is not a candidate-only failure. Passed grew by 30: the 29 `tests/test_r8_findings_remediation.py` cases plus that flaky pass. No failed, error, or skipped id is present only on the candidate.

### Limitations

- P2 `verify_consumer_install` still attests the `scaffold-consumer` region and the hooks fragment. It does not itself hash `agents-router`. Structural Review and unexplained drift fail a router rewrite closed. A host whose only change is that rewrite can remain `verify = VALID` while S3 reports UNKNOWN.
- Managed-region interior bytes, including a legal-looking router rewrite, can stay candidate-neutral under generation-2. The candidate omits the file when the human surface matches. Structural Review does not treat that rewrite as install-managed.
- An explicit empty hook-event array is omitted on both sides of the comparison, so adding or removing an empty array with no human command is not a human-surface change.
- FND-B, FND-C, and FND-D limitations in section 14 are unchanged.
- No commit and no push. Project-City was not modified.

Section 15's claim that agents-router attestation was corrected covered present-region identity only. It did not check that a Scaffold-owned region present in HEAD is still present. That absence hole is the final re-audit's MAJOR. Section 16 corrects it and does not withdraw section 15.

---

## 16. Final Re-Audit Region-Absence Correction

### MAJOR root cause

`_region_identity_attested` hashed only Scaffold-owned spans that were still in the live file. After a post-install commit, deleting `agents-router` left `scaffold-consumer` canonical, and deleting `scaffold-consumer` left `agents-router` canonical. The human surface was unchanged because both projections remove managed spans. The deleted region was never hashed. `install_managed_bytes_verified` returned true. Structural Review listed the path install-managed and `structural_review_pass` stayed true, so Submit S3 did not stop. Unexplained drift classified the path `install-managed`. For router deletion, `verify_consumer_install` also stayed `VALID`. For consumer deletion, verify was already `INCOMPLETE`, but S3 does not call verify.

### Reference versus live presence

`install_managed_bytes_verified` now requires three separate facts:

1. every Scaffold-owned region present in the live file matches `expected_managed_region_digest` or `predecessor_managed_region_digests` for that path and region id;
2. every Scaffold-owned region id parsed from the reference is still present in the live file;
3. the human-owned surface is unchanged against the reference or against the installer's framing projection of the reference.

The reference is `git show HEAD` for a tracked file and empty text for an untracked file. Region ids come from `parse_managed_regions` / `parse_gitattributes_region`, not from `install.yaml`. A malformed reference or live file fails closed. Human-surface equality is not used to represent a missing region.

There is no lifecycle operation that deletes a managed region, so absence is not treated as an authorized removal.

### Why addition stays legal

The check is `reference_ids <= live_ids`, not set equality. A fresh Consumer Install of human-only `AGENTS.md` or of a canonical `agents-router` with no consumer region may add `scaffold-consumer`. A human `.gitattributes` with no managed region may gain `scaffold-consumer-git`. The new region must still pass its own identity check. `agents-router` is not required merely because the host type allows it. A fresh install that writes only `scaffold-consumer` stays legal.

### Why silent deletion fails closed

If HEAD contains `agents-router`, `scaffold-consumer`, or `scaffold-consumer-git` and the live file no longer contains that id, presence fails even when the surviving region is canonical and the human surface matches. Rewriting `files[].digest` to the live file does not restore the classification. Consumer verify is unchanged: it still does not hash `agents-router`, and `verify = VALID` after a router interior rewrite remains the accepted layer-scope difference. Structural Review rejects the deletion on its own.

Hook fragment deletion was already rejected by `inspect_scaffold_hook_fragment` (`missing` when the Scaffold command is gone). That path was not redesigned. The new test commits a real install and then removes the Scaffold commands.

### Tests added

`test_FND_A_14_managed_region_absence_fails_closed` covers router deletion, consumer deletion, both-region deletion, legal addition of `scaffold-consumer` beside a canonical router, legal addition onto human-only `AGENTS.md`, a committed consumer-only file, deletion of that consumer region, and both single-region deletions after the manifest file digest is rewritten to the live file.

`test_FND_A_15_gitattributes_and_hooks_absence_fail_closed` covers a real install that adds `scaffold-consumer-git` to human `.gitattributes`, deletion of that region after it is committed, a human rule edit, a real tracked human hooks install, and deletion of the Scaffold hook commands after that install is committed.

### Regression

Environment: Python 3.13.12 (`F:\miniconda\python.exe`), pytest 9.0.3, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<tree>\src;<tree>\tests`, `-p no:cacheprovider`, Windows.

Targeted command, candidate only, same file set as section 15:

Result: 414 passed, 3 failed, 944.39s. The two new cases `test_FND_A_14_managed_region_absence_fails_closed` and `test_FND_A_15_gitattributes_and_hooks_absence_fail_closed` passed. The failures are `test_RA_MIN02_05_p9_remains_blocked`, `test_IMP03_product_surface_and_first_use_smoke`, and `test_IMP07_portability_without_distribution`, the same historical baseline failures. Existing FND-B, FND-C, and FND-D cases passed.

Paired full command, both trees:

`python -m pytest tests -q --tb=no -rfE -p no:cacheprovider --junitxml=<log>\{baseline,candidate}-junit.xml`

Fresh baseline checkout: `F:\NewResearch\scaffold-r8-absence-baseline-8c2547a` detached at `8c2547a`. Candidate: this worktree. Logs: `F:\NewResearch\scaffold-r8-absence-logs`.

| Tree | Passed | Failed | Errors | Skipped | Duration |
| --- | --- | --- | --- | --- | --- |
| Fresh baseline `8c2547a` | 1994 | 17 | 16 | 2 | 3680.61s |
| Candidate | 2025 | 17 | 16 | 2 | 3831.79s |

JUnit failed, error, and skipped node-id sets are equal. Passed grew by 31, which is `tests/test_r8_findings_remediation.py` (the previous 29 cases plus `test_FND_A_14` and `test_FND_A_15`). `test_P9_R10_concurrent_repair_cas_one_winner` failed in both trees with `AssertionError: 0 != 1`. `--tb=no` does not capture the worker thread's `WinError 32` text. The node id and assertion are the known concurrent-repair flake, and it is not candidate-only.

### Remaining limitations

- `verify_consumer_install` still does not hash `agents-router`. A router interior rewrite can remain `verify = VALID` while Structural Review reports UNKNOWN. That split stays the accepted layer-scope difference. Router deletion is no longer install-managed.
- Generation-2 candidate projection still omits a file whose human surface matches HEAD, including a deleted managed region. Structural Review does not grant that deletion install-managed status.
- No lifecycle operation removes a managed region. Absence is always fail-closed.
- FND-B, FND-C, and FND-D limitations in section 14 are unchanged.
- No commit and no push. Project-City was not modified.
