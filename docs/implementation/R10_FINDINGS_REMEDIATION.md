# R10 Findings Remediation

Scaffold baseline `fec48986ec1e3a1ae7744454027ac4742a95303b`.
Worktree `F:\NewResearch\scaffold-r10-findings-remediation`.
Branch `r10-findings-remediation` (uncommitted; no commit, push, merge, tag, or release).

The frozen R10 consumer `F:\NewResearch\Project-City-consumer-pilot-r10` was read only. Its `AGENTS.md` bytes were compared before and after the attestation check. No lifecycle command, commit, or push was run there.

`.tsx` lifecycle `UNKNOWN` stays `UNVERIFIED`. Product ADS sources were not edited.

The sections through "Remaining limitations" are the first remediation record. They are kept as written. The independent closure audit later failed Finding C's production handoff and Finding D's resume route. That audit record is not replaced by the PASS lines below. The focused correction follows it.

## Source-code authorities used by Finding B

These names already exist. `ABORTED_ATTRIBUTED` is the only new class.

| Name | Authority |
| --- | --- |
| `observed_success` | Physical execution attribution for one Session row. It says a mutation was observed. It does not seal the Session, accept the candidate, or make the row `DEVELOP_KNOWN`. |
| `DEVELOP_KNOWN` | Sealed execution authority. A continuous `files.yaml` chain on `SEALED` sessions whose latest after-bytes match the live path. An `ABORTED` session cannot supply this class. |
| `PREEXISTING_CHANGE` | Every linked `SEALED` session has complete S0 and S1 overlays equal to the live bytes, and no sealed touch explains the path. This is not proof that Develop produced the bytes. |
| `inherited_baseline` | Task-delta role for `PREEXISTING_CHANGE` and `MIXED_CHANGE`. It means the path is not this Task's product or supporting delta. |
| `task_product_delta` | Task-association role. The path is inside the Task's resolved product scope. It is not sealed acceptance. |
| `ABORTED_ATTRIBUTED` | Non-authoritative attribution. Same Task, linked `ABORTED` session, physical `observed_success` or reconciled row, continuous before/after chain, latest after-bytes equal the live path, and every later sealed overlay that names the path still shows those bytes. Not `DEVELOP_KNOWN`. Not `inherited_baseline`. |

A matching path name or hash does not skip a broken chain, a failed or pending write, another Task's session, or a later sealed edit.

## Finding A — AGENTS.md Submit S3

`R10_FND001_AGENTS_S3 = PASS`

Install writes `scaffold-consumer`. Adoption writes `agents-router` through `integrated_agents_text`. The old human-surface projection ran only `apply_consumer_install_region`, so a legal adopted file did not match.

`_installer_projection` still uses `apply_consumer_install_region` for an unadopted host. After `skills.lock` exists, it also runs `integrated_agents_text`, and presence requires both region ids. `project.yaml` alone does not select that phase, because review fixtures write it without the router integration. Region digests, reference presence, and the human-surface comparison are unchanged. Blank lines are not ignored. An Ownership `MANAGED` entry is not consulted. Unexplained drift keeps the install-phase projection for `AGENTS.md`, so a mixed file is not reclassified as wholesale install-managed merely because the adopted router is present. Submit S3 uses the two-phase projection.

Reproduction and checks are in `tests/test_r10_findings_remediation.py`:

- Install, adoption, then `review_structure` treats `AGENTS.md` as install-managed.
- A human line, a forged region, a deleted `agents-router` region, and a tampered region body are rejected. `MANAGED` ownership does not rescue the human edit.
- Read-only check on the frozen R10 tree: install-only `AGENTS.md` still attests, and the file bytes are unchanged.

Contract impact: adopted hosts must keep both legal regions. Install-only hosts keep the install projection. Submit S3 still rejects real human edits.

## Finding B — ABORTED Session attribution

`R10_FND002_SESSION_ATTRIBUTION = PASS`

`load_sealed_sessions` still returns only `SEALED` sessions. `classify_delta` additionally reads Task-linked `ABORTED` sessions. A proven same-task chain becomes `ABORTED_ATTRIBUTED` and then `task_product_delta` or `task_supporting_delta` by scope. It never becomes `DEVELOP_KNOWN`. A later sealed physical touch remains `DEVELOP_KNOWN`. A broken chain that would have been laundered into `PREEXISTING_CHANGE` becomes `UNATTRIBUTED` instead of `inherited_baseline`.

Tests cover:

- aborted bytes still present, later sealed `files.yaml` empty;
- sealed-only classification of that case is still `PREEXISTING_CHANGE` / `inherited_baseline`;
- a later sealed edit of the same file stays `DEVELOP_KNOWN`;
- another Task's aborted edit stays `inherited_baseline` for this Task;
- `failed` alone is not aborted attribution; a pending row beside a success is `UNATTRIBUTED`;
- two aborted rows whose before/after chain does not connect stay `UNATTRIBUTED` even when the last hash matches live bytes.

Read-only frozen R10: aborted session `dev-20261008T032116Z-048d0f2f` has 29 files; sealed session `dev-20261008T035123Z-a0d10232` has an empty `files.yaml`. The product paths that aborted session recorded are now `ABORTED_ATTRIBUTED`, not `inherited_baseline` and not `DEVELOP_KNOWN`. `src/mvp/MvpAimReticle.ts` is absent from that aborted manifest, so it stays `UNATTRIBUTED`.

Contract impact: `PROVENANCE_CLASSES` and Change Record class counts include `ABORTED_ATTRIBUTED` with path count 0 when unused. Records §15 states the class. Submit still does not treat an aborted session as sealed authority.

## Finding C — duplicate selected Test Profile

`R10_FND003_TEST_DEDUP = PASS`

`build_develop_to_test` dedupes automatic Profile IDs in first-seen order (`final_tests`, then stage `required_tests`). `requirement_bindings` still lists every requirement, including two requirements that share one profile. An explicit `selected` list is not deduped, so P6 `validate_selected` still reports `duplicate selected profile id`. `src/scaffold_p6/contract.py` was not changed.

Frozen R10 task `task-20261008T032103Z-3d10ebac` binds two requirements to `discovered-package-json-test-mvp-rules`. Automatic selection now has that id once.

## Finding D — pending Repair after recovery

`R10_FND004_REPAIR_STATE = PASS`

`reconcile_pending_repair` marks `pending` as `resolved` only when all of the following hold:

- the covering execution is the same Task;
- `test_pass` is true and `test_complete` is true;
- its candidate digest is the live candidate;
- its report id differs from the recorded failure;
- every pending target stage exists once and has a `SATISFIED` decision current for that candidate.

`fail_ids`, the original report id, and a `failure_history` entry are kept. A second call does not append history. A bare `PASS`, a candidate mismatch, a different Task, or a different Stage leaves `pending` in place. `DevelopEngine` calls this after the published Task is current and only on `TEST_COMPLETE`.

`reconstruct_repair_view` no longer says the repair loop is complete while status is still `pending` and READY gates hold.

Frozen R10 repair state is `pending`, `target_mapping: unresolved`, with empty `target_stage_ids` and empty `fail_ids`, while READY gates hold. The view now says READY is current but the pending repair is not covered. It is not marked resolved, because the original failure has no stage binding to cover.

## Preserved contracts

- R9-FND-001 intake file transport tests were included in the targeted run.
- The pre-session mutation boundary and distribution-update currentness code were not edited.
- Submit S3 still fails closed on human `AGENTS.md` edits.
- `ABORTED` is not `DEVELOP_KNOWN`. P6 `TEST_PASS` / `TEST_COMPLETE` and S5's `TEST_COMPLETE` requirement were not weakened.
- Task, Session, Candidate, and Decision currentness checks were not removed.

## Targeted regression

Python 3.13.12, pytest 9.0.3, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`.

`tests/test_r10_findings_remediation.py`: 15 passed.

Targeted contract files (intake transport, distribution update, candidate projection, PF2, P8 submit/rev1, FA2-FND-005, P9 repair, PC-R3, consumer install, dive corrections 04 and 05): 362 passed, 2 failed, 1 error.

The two failures and the error are present in unmodified `fec48986` sources:

- `test_PF2_03_ordinary_human_agents_proposes_bounded_integration` expects an adoption sentence that `present_result` no longer emits.
- `test_FND5_E02_aborted_observed_success_is_attribution_not_develop_known` expects a P7 note sentence that file does not contain. The constitution sentence in the same test matches.
- `tests/test_dive_pilot_correction04.py::test_engine` is pytest collecting the imported helper `test_engine` from `tests/p6_support.py`.

```text
R9_INTAKE_REGRESSION = PASS
DISTRIBUTION_UPDATE_REGRESSION = PASS
SUBMIT_GOVERNANCE_REGRESSION = PASS
TARGETED_REGRESSION = 362 passed, 2 pre-existing failed, 1 pre-existing collection error
```

## Full regression

Paired runs use Python 3.13.12, pytest 9.0.3, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, and `-p no:cacheprovider`. Baseline is detached `fec48986` at `F:\NewResearch\scaffold-r10-findings-baseline`. Candidate is this worktree after the AGENTS projection fix. JUnit files are `F:\NewResearch\scaffold-r10-junit\baseline.xml` and `candidate.xml`.

An earlier candidate run, before that projection fix, failed three nodes that baseline passed: `test_F3_03_mixed_ownership_agents_md_not_install_managed`, `test_FND_A_13_agents_router_identity_is_attested`, and `test_FND_A_14_managed_region_absence_fails_closed`. Those three pass in the recorded candidate run.

```text
FULL_BASELINE = 16 failed, 2047 passed, 2 skipped, 16 errors in 4025.87s
FULL_CANDIDATE = 17 failed, 2061 passed, 2 skipped, 16 errors in 4557.32s
NEW_REGRESSIONS = none stable
```

Error node ids match. Skipped node ids match: `test_C04_12_case_fold_collision_is_ambiguous` and `test_F4_04_installed_consumer_document_synced`.

The only candidate-only failure is `test_P9_R10_concurrent_repair_cas_one_winner`. The full-run worker warning is `PermissionError: [Errno 13]` on `.scaffold/runtime/develop-execution.yaml.tmp`. An isolated rerun failed with `AssertionError: 0 != 1` and `PermissionError: [WinError 32]` from `os.replace` of `.scaffold/ext/develop/unexplained.yaml.tmp`. That is the known Windows concurrency flake. It is not a repair-state contract failure. Passed grew by 14, which is the 15 new tests minus that one flipped flake.

## Remaining limitations

- `src/mvp/MvpAimReticle.ts` on the frozen consumer is not in the aborted `files.yaml`, so it stays `UNATTRIBUTED`. Same-path presence is not enough.
- The frozen repair record has `target_mapping: unresolved` and no target stages. READY cannot clear it. A later authoritative execution must name the stages before `resolved` is legal.
- `.tsx` lifecycle `UNKNOWN` remains `UNVERIFIED`.
- No-SCM staging digest behavior from the R9 closure audit is unchanged.
- `test_P9_R10_concurrent_repair_cas_one_winner` remains the known Windows concurrency flake. This run showed `WinError 32` on `os.replace` of `unexplained.yaml.tmp` and `Errno 13` on `develop-execution.yaml.tmp`, with assertion `0 != 1`.

## Independent closure audit

Source: `F:\NewResearch\scaffold-r10-findings-independent-audit\R10_FINDINGS_CLOSURE_AUDIT.md`.

The first implementation's Finding C helper deduped only when `selected is None`. `DevelopEngine` passed `list(opts.get("selected") or [])`, so an omitted selection was `[]`. `invoke_test` then rebuilt a duplicate list from `requirement_bindings`. Stage and final tests that share one profile still reached P6 as `duplicate selected profile id`.

The first implementation's Finding D resolve predicate was fail-closed and stayed so. Resume did not. `_test_view` turned every stored `fail_id` into a current required failure, including after `resolved`, so `select_next_route` sent a resolved READY Task to `test`. A later pending persist omitted `failure_history`, and `persist_repair_state` kept that field only when the payload contained it, so the new pending write dropped the old history.

```text
R10_FND001_AGENTS_S3 = PASS
R10_FND002_ABORTED_ATTRIBUTION = PASS
R10_FND002_NO_AUTHORITY_LAUNDERING = PASS
R10_FND003_TEST_DEDUP = FAIL
R10_FND004_REPAIR_STATE = FAIL
R10_FND004_FAIL_CLOSED = PASS
R9_INTAKE_REGRESSION = PASS
SUBMIT_GOVERNANCE = PASS
REGRESSION = PASS
R10_FROZEN_INTACT = YES
BLOCKING = 1
MAJOR = 1
MINOR = 0
SAFE_TO_COMMIT = NO
```

## Focused correction 2

`R10_FND003_REAL_HANDOFF = PASS`

`None` and `[]` both mean the caller did not name profiles. `build_develop_to_test` then selects bound profile ids in first-seen order and drops duplicates. Requirement bindings stay complete. A non-empty list is copied unchanged, so an explicit duplicate still reaches P6 `validate_selected`. `DevelopEngine` passes `None` for a missing or empty `selected`, and passes a non-empty list through. `invoke_test` applies the same rule when it rebuilds from bindings, and does not dedupe an explicit non-empty list. `src/scaffold_p6/contract.py` was not changed. TEST_COMPLETE was not changed.

`DevelopEngine.run(..., invoke_test=True)` with no `selected`, where final tests and the stage bind `unit`, completes with `selected == ["unit"]`, both bindings kept, `test_pass` true, one report, and one executed profile. The same call with `selected=["unit", "unit"]` leaves that duplicate in the handoff. The Test handoff outcome is `BLOCKED`, `test_pass` is false, and the blocker is `duplicate selected profile id: unit`.

`R10_FND004_RESUME_ROUTE = PASS`

`R10_FND004_FAILURE_HISTORY = PASS`

`R10_FND004_FAIL_CLOSED = PASS`

`reconcile_pending_repair` is unchanged. Resolved and consumed `fail_ids` stay on the repair row and in `failure_history`, and they are not current required failures. `pending`, `active`, and any other recorded status still are. A later persist that omits `failure_history` copies the on-disk history. If the episode changes and the prior row has fail ids or is `resolved`, that episode is appended once. Rewriting the same status, fail ids, and report id does not append. An explicit `failure_history` on the payload is stored as given.

A resolved repair row does not by itself make Resume submit. If that Task's `ready_possible` is not true, `select_next_route` returns `human` because Candidate or Decision authority is not current.

Checked on a real `resume` entry:

- Legal `resolved` plus current READY routes to `submit`. The fail id and history remain queryable. Required failures are empty. A second resume and a fresh-process resume stay on `submit`. A second reconcile does not grow history.
- `pending` and `active` still route to `develop.repair`, and their fail ids stay required failures.
- `consumed` fail ids stay on the row and are not required failures, and the route is not `test` or `develop.repair`.
- A new Develop Test failure after `resolved` writes `pending`, keeps the old fail id and the resolved episode in `failure_history`, and Resume routes to `develop.repair`. Repeating that pending write does not grow history.
- An `UNKNOWN` Stage decision, and a later candidate change, each keep Resume off `submit`.

Finding A, Finding B, the resolve predicate, R9 intake transport, Submit S5 TEST_COMPLETE, and distribution-update currentness were not edited. The frozen R10 consumer was not edited.

## Correction regression

Python 3.13.12, pytest 9.0.3, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`.

`tests/test_r10_findings_remediation.py`: 23 passed.

Focused files were the R10 findings module, R9 intake transport, R9 distribution update, candidate projection, PF2, P8 submit, P8 rev1, FA2-FND-005, P9 repair, PC-R3, consumer installation, dive corrections 04 and 05, and P10 incremental resume. Result: 432 passed, 3 failed, 1 error, in 1173.73s.

The failures and the error:

- `test_PF2_03_ordinary_human_agents_proposes_bounded_integration` and `test_FND5_E02_aborted_observed_success_is_attribution_not_develop_known` are the same pre-existing failures recorded above.
- `tests/test_dive_pilot_correction04.py::test_engine` is the same pre-existing collection of imported `test_engine`.
- `test_P9_R10_concurrent_repair_cas_one_winner` failed with `AssertionError: 0 != 1`. The worker warning is `PermissionError: [WinError 32]` from `os.replace` of `.scaffold/ext/develop/unexplained.yaml.tmp`. That is the known Windows concurrency flake.

```text
R9_INTAKE_REGRESSION = PASS
SUBMIT_GOVERNANCE_REGRESSION = PASS
TARGETED_REGRESSION = 432 passed, 2 pre-existing failed, 1 known P9_R10 Windows flake, 1 pre-existing collection error
```

Paired full runs use the same Python, pytest, hash seed, and cache settings. Baseline is detached `fec48986` at `F:\NewResearch\scaffold-r10-findings-baseline`. Candidate is this worktree. JUnit files are `F:\NewResearch\scaffold-r10-junit\baseline-correction2.xml` and `candidate-correction2.xml`. The earlier pair in "Full regression" is unchanged.

```text
FULL_BASELINE = 18 failed, 2045 passed, 2 skipped, 16 errors in 5059.11s
FULL_CANDIDATE = 17 failed, 2069 passed, 2 skipped, 16 errors in 5111.46s
NEW_REGRESSIONS = none
```

Error node ids match. Skipped node ids match. Candidate-only failure node ids: none.

This baseline failed two nodes the earlier baseline run passed: `test_P9_R10_concurrent_repair_cas_one_winner` (`AssertionError: 0 != 1`) and `test_B4R18_commit_hook_failure_rolls_back_exact_prior_index` (`PermissionError: [WinError 5]` on `os.replace` of `.scaffold/ext/develop/unexplained.yaml.tmp`). The candidate failed P9_R10 with the same `0 != 1` assertion. Its worker warning is `PermissionError: [Errno 13]` on `.scaffold/ext/develop/unexplained.yaml.tmp`. The candidate passed `test_B4R18`. Those are Windows file-lock races on the unexplained-drift replace, not a candidate-only logic failure. Passed on the candidate is 24 above this baseline, which is the 23 R10 findings tests plus the baseline-only B4R18 flake.
