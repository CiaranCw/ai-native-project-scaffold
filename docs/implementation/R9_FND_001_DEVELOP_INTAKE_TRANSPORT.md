# R9-FND-001 Develop Intake Transport

Remediation of the confirmed Develop Intake bootstrap deadlock on Scaffold
`2e3b86438c68170255ae55020296051f6708d8f4`. The frozen R9 consumer at
`F:\NewResearch\Project-City-consumer-pilot-r9` was not modified. Work is on
branch `r9-fnd001-remediation` in
`F:\NewResearch\scaffold-r9-fnd001-remediation`.

Independent audit:
`F:\NewResearch\scaffold-r9-fnd001-audit\R9_FND_001_DEVELOP_INTAKE_AUDIT.md`.

## R9 reproduction

On an ACTIVE / ESTABLISHED_HOST with no Task and no Develop Session, the
public command was:

```text
python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>
```

The audit measured:

- A literal base64 token reaches the runner and can publish a Task.
- A zero-context Cursor Agent cannot legally construct that token.
- PowerShell subexpressions and here-strings are denied by the installed
  `beforeShellExecution` hook before `run.py` starts.
- `--intake-json` is not a Windows PowerShell transport: the shell strips
  embedded quotes and the runner reports `intake JSON is not parseable`.
- Editor Write of a temporary envelope is denied because Develop authority
  does not exist yet. That authority is what Intake is supposed to create.

```text
SCAFFOLD_CURSOR_ADAPTER_CAUSE = YES
PUBLIC_AUTONOMOUS_RECOVERY_PATH = NO
BOOTSTRAP_DEADLOCK = YES
SEVERITY = BLOCKING
```

## Bootstrap deadlock

The mutation and shell operations that can build an Intake envelope were
closed until an IN_PROGRESS Task, a mutable Stage, and an OPEN Develop
Session existed. Those three are created only after Intake accepts the
envelope. The hook deny text sent the Agent back to the same literal
`--intake-json-b64` command.

## Root cause

Scaffold's Cursor adapter, not Cursor's own shell classifier. The installed
hook parses the unexpanded command and requires the payload to already be
valid JSON or one base64 token. Cursor on this host executes that string as
Windows PowerShell, which cannot carry an arbitrary JSON object as one
literal argument. The editor Write gate then refuses every project path,
including a drop file, until the Session that Intake has not created yet.

## Chosen transport contract

One public, pre-Develop file transport. No parallel Intake parser.

Canonical relative path:

```text
.scaffold/transport/develop-intake.json
```

Commands:

```text
python .scaffold/install/run.py enter develop --intake-json-file .scaffold/transport/develop-intake.json
python .scaffold/install/run.py develop intake --intake-json-file .scaffold/transport/develop-intake.json
```

The runner:

1. Accepts only that relative token. Absolute paths, `..`, and any other
   relative path are rejected.
2. Resolves it inside the host and refuses a symlink or directory junction
   on any component.
3. Reads UTF-8 text.
4. Passes that text through the existing `load_intake_envelope_flags` /
   `parse_intake_envelope` path.
5. Publishes a Task only when existing Intake validation succeeds.
6. Creates no Develop Session.
7. Deletes the staging file only after a Task record id exists.

`--intake-json` and `--intake-json-b64` remain accepted and mutually
exclusive with the file flag. `--intake-json` still means inline JSON. It
does not read a file.

## Staging-file authority

The path is inside the workspace and under `.scaffold/`, so
`classify_path` remains `SCAFFOLD_AUTHORITY`. It is outside ordinary
product and source authority. It is not `.scaffold/tasks/`, not a Session,
not `project.yaml`, and not install or derived lifecycle truth.

`is_protected_mutation_target` still returns true for this path. Shell
governance checks, in-session product mutation, and supporting-path
declarations still treat it as protected Scaffold governance. The general
protection of `.scaffold` is unchanged.

The only exception is in the Cursor pre-tool gate, and only when all of
these hold:

- host policy is healthy ACTIVE / ESTABLISHED_HOST
- required route is Develop (no current execution binding)
- the tool is an ordinary editor Write or Edit
  (`Write`, `WriteFile`, `StrReplace`, `ApplyPatch`, `Edit`, `EditFile`,
  `MultiEdit`)
- the resolved in-host path is exactly the staging file

Still denied: product source, tests, tools, arbitrary temp paths,
`AGENTS.md`, `.cursor` governance, other `.scaffold` paths, outside-workspace
paths, and Delete/Move/Rename. After a Session exists, the staging write is
denied again as protected governance. The exception is transport authority
only.

## Shell-gate behavior

The official launcher form with `--intake-json-file` and the canonical
relative path is an allowed lifecycle command on `enter develop` and
`develop intake`.

`--intake-json-file` does not inherit the inline JSON/base64 metacharacter
exemption. The substring `--intake-json` still exempts `--intake-json` and
`--intake-json-b64`, which keeps those transports backward compatible.
Command chaining, redirection, here-strings, PowerShell subexpressions, and
inline eval stay denied for the file transport.

## Security and governance boundaries

- The staging file is not Task authority, Session authority, an ownership
  override, candidate evidence, `TEST_PASS`, or `TEST_COMPLETE`.
- Invalid JSON, a non-object root, and an invalid `structured_intent` fail
  closed: no Task, no Session, no manufactured proposal. The staging file
  is left unchanged so it can be corrected. It remains non-authoritative.
- A symlink or junction escape is rejected and is not followed for read or
  delete.
- Successful Task publication consumes the file and removes an empty
  `transport` directory. A delete failure after publication does not roll
  back the Task and does not turn the leftover file into authority.

## Tests

`tests/test_r9_fnd001_develop_intake_transport.py` drives the installed
`cursor_first_use_hook.py` and `.scaffold/install/run.py` from a vendored
copy of this runtime:

- ACTIVE host, no Task, no Session: staging Write/Edit allowed; product,
  tests, tools, `AGENTS.md`, `.cursor`, other `.scaffold`, temp, and
  outside paths denied.
- File Intake publishes an IN_PROGRESS Task and no Session, then removes
  the staging file. Product writes stay denied until `develop session`.
- A realistic request containing an apostrophe, parentheses, `$`, and
  `< >` is preserved as exact JSON text.
- Absolute, `..`, noncanonical, governance, and product arguments are
  rejected by both the shell classifier and the runner.
- A directory junction escape is rejected. This host cannot create file
  symlinks (`WinError 1314`); junctions are the Windows escape that
  `Path.is_symlink()` misses and `Path.is_junction()` catches.
- Malformed JSON, a non-object root, and invalid `structured_intent` publish
  nothing.
- Literal `--intake-json-b64` still publishes a Task. `--intake-json` given
  the staging path is still treated as inline JSON and does not read or
  consume the file.
- After `develop session`, in-scope product Write is allowed and the staging
  path is denied.
- The staging file does not become Task, Session, or ownership authority.

## Paired regression

Baseline: `2e3b86438c68170255ae55020296051f6708d8f4`
(`F:\NewResearch\scaffold-r9-fnd001-baseline`).

Candidate: this worktree.

JUnit:

- `F:\NewResearch\scaffold-r9-fnd001-junit\baseline.xml`
- `F:\NewResearch\scaffold-r9-fnd001-junit\candidate-first.xml` (tree before the projection-test overlay)
- `F:\NewResearch\scaffold-r9-fnd001-junit\candidate.xml` (tree after that overlay)

Focused suites before the full pair covered first-use enforcement, consumer
installation, Develop intake, Develop lifecycle, project authority, shell
boundary, R8 findings, and Submit lifecycle guards. Identity tests were
updated to the new Develop package digest
`25ac19783621d64afff3d250ba1bde73cd4e2264485c0f987824aced3b784e70` because
`skills/develop/SKILL.md` now documents the transport. Skill version stays
`2.1.0`. The digest-pin failures from that focused run were re-run and passed
(24 tests). The `test_pc_consumer_003` failures and the `test_engine`
collection error in that focused run match the baseline, below.

First paired `pytest` (about 75 minutes each):

| Tree | Failed | Passed | Skipped | Errors |
| --- | ---: | ---: | ---: | ---: |
| Baseline `2e3b864` | 16 | 2026 | 2 | 16 |
| Candidate before overlay | 17 | 2034 | 2 | 16 |

Error node ids and skipped node ids were identical. No `WinError 32` /
`os.replace` flake appeared. The nine extra candidate passes are
`tests/test_r9_fnd001_develop_intake_transport.py`.

The one candidate-only failure in that pair was
`PublishedBoundaryTests::test_distribution_update_from_published_base_keeps_legacy_authority`.
The first response copied `src/scaffold_p5/first_use.py` and
`src/scaffold_p5/consumer_install.py` into the historical install base and
described the failure as guidance drift. That description is withdrawn.
The independent audit showed the copy masks a real loss of READY
currentness. The correction is in "Distribution update correction" below.
The public lifecycle reference copy was already in the published baseline
and remains. It is not the same mechanism.

These node ids fail on the untouched baseline with the same assertions, so
they are not candidate-only regressions:

- `tests/test_pc_consumer_003.py`: ten failures. Ordinary in-project shell
  is allowed (`ordinary in-project development command`), and an open
  Session allows editor writes up to the hard boundary
  (`current Develop execution Session authorizes scoped mutation`).
  Fail-closed and recovery cases in that file fail the same way on baseline.
- Sixteen `test_engine` collection errors (`fixture 'host' not found` on
  `tests/p6_support.py::test_engine`), including
  `tests/test_fa2_batch1_project_authority.py::test_engine`.
- `tests/test_fa2_batch9_package_docs.py::test_B9D06_p9_not_started`
- `tests/test_fa2_foundation_amendment_005.py::test_FND5_E02_aborted_observed_success_is_attribution_not_develop_known`
- `tests/test_fa2_reaudit_tranche_a.py::test_RA_MIN02_05_p9_remains_blocked`
- `tests/test_pilot_feedback_pf2_agents_integration.py::test_PF2_03_ordinary_human_agents_proposes_bounded_integration`
- `tests/test_project_import.py::test_IMP03_product_surface_and_first_use_smoke`
- `tests/test_project_import.py::test_IMP07_portability_without_distribution`

Skipped on both trees:

- `tests/test_pc_scf_gate1b_c04.py::test_C04_12_case_fold_collision_is_ambiguous`
- `tests/test_r7_p2_implementation.py::test_F4_04_installed_consumer_document_synced`

## Remaining limitations

- `--intake-json` is unchanged and still does not survive Windows PowerShell
  quote stripping. The file transport is the zero-context path.
- A failed Intake leaves the staging file in place. It is not Task, Session,
  or completion authority. Session inventory skips `.scaffold/`. On a no-SCM
  host the candidate inventory includes
  `.scaffold/transport/develop-intake.json` while it exists, and removing it
  changes that candidate digest. A later currentness check can therefore see
  a different tree than the post-consumption tree. Retry of the same envelope
  removes the file and reuses the one Task. Git status can also show the
  file until it is consumed. This is the audited MINOR. It is not fixed here.
- The runner deletes the file only after a Task record exists. A filesystem
  error on that delete does not undo publication.
- Pre-session Delete of the staging file stays denied. Consumption is the
  runner's job.
- The file transport does not relax shell metacharacters. Building the
  envelope with a subexpression or here-string is still denied.
- After a Session exists, the existing pre-write gate still applies the
  hard-boundary check rather than a Task-scope allowlist. That behavior is
  baseline. The staging path remains inside the protected-governance
  boundary.

## Regression result

Confirming full candidate run after the overlay
(`candidate.xml`, 3670.82s):

| Tree | Failed | Passed | Skipped | Errors |
| --- | ---: | ---: | ---: | ---: |
| Baseline `2e3b864` | 16 | 2026 | 2 | 16 |
| Candidate | 16 | 2035 | 2 | 16 |

Failed, error, and skipped node ids match exactly. No baseline pass is
missing on the candidate. The nine extra passes are
`tests/test_r9_fnd001_develop_intake_transport.py`. No `WinError 32` /
`os.replace` flake appeared in either full run. That pair still contained
the invalid generator overlay. It is not the closure pair. The closure pair
is below.

## Distribution update correction

The five-file runtime rule described below was withdrawn. It closed the
READY-currentness gap by letting the live installed runtime authenticate
its own client bytes. That design is the failed trust root recorded in
"Client-support trust root correction". The fixture-overlay removal and
the measured currentness failure remain accurate. The production rule in
this section does not.

Independent audit MAJOR:
`DISTRIBUTION_UPDATE_FIXTURE_CHANGE = MASKS_REAL_MIGRATION_REGRESSION`.

A Consumer installed from published `2e3b864`, with a READY Task bound to
the pre-update generation-1 digest, lost currentness after UPDATE to this
candidate. `establish_projection_migration` seals a generation-2 target for
the pre-update tree. The update then rewrites
`.cursor/rules/scaffold-first-use.mdc` and
`.cursor/skills/scaffold-develop/SKILL.md`. Those bytes were still in the
generation-2 candidate, so the live digest no longer matched the sealed
target. `report_usable_for`, `decision_is_satisfied_current`, and
`evaluate_ready_for_review` then failed. Copying the two generator modules
into the historical base made the update a no-op for those files. That
fixture change is removed.

The production rule follows the existing generation-2 model. Install
infrastructure under `.scaffold/install/` is already candidate-neutral.
`AGENTS.md` and `.gitattributes` already drop Scaffold-owned regions from
the generation-2 digest while human bytes stay visible. The Cursor rule and
the four Scaffold Cursor adapters are the same class of Scaffold-owned
delivery, but they live outside `.scaffold/install/`.

Generation 2 now omits one of those five paths only when its live bytes
equal the text emitted by the installed runtime
(`FIRST_USE_RULE_TEXT` or `CURSOR_BODIES` in
`.scaffold/install/runtime`). `install.yaml` is not the source of those
bytes. A rewritten manifest digest cannot neutralize a tampered file.
Verify also rejects that mismatch, so the file fails the integrity gate
rather than becoming trusted. An unrelated `.cursor` path, a sibling such
as `.cursor/skills/scaffold-develop/notes.md`, product source, and human
`AGENTS.md` text stay in the candidate. The omission applies to tracked
and untracked files, and to no-SCM inventories.

Identities for a maintenance-only update:

- `PRE_UPDATE_LEGACY_DIGEST` is the generation-1 digest the READY decision
  cites. It still includes the old client-delivery bytes.
- `PRE_UPDATE_GEN2_DIGEST` omits those bytes because they match the
  pre-update runtime. The migration record's target is this digest.
- `POST_UPDATE_GEN2_DIGEST` omits the new bytes because they match the
  post-update runtime. It equals the sealed target when no product bytes
  changed.

The durable proof therefore connects the cited pre-update legacy digest to
the generation-2 digest of the tree that still exists after the update.
A later product edit moves the live digest off that target, and the old
READY decision stops being current.

The historical `79755b15` test no longer copies the generator modules. It
still copies `docs/PUBLIC_LIFECYCLE_REFERENCE.md`, which was already in the
published baseline test. That file is installed under
`.scaffold/install/docs/` and is generation-2 install infrastructure. The
test now also asserts that the rule and Develop adapter bytes actually
change. `tests/test_r9_fnd001_distribution_update.py` replays an untouched
`2e3b864` install, including the tracked-commit shape, and covers the
negative authority cases plus a no-SCM delivery check.

Focused suites after this correction: 284 passed
(`test_candidate_projection_generation`,
`test_r9_fnd001_distribution_update`,
`test_r9_fnd001_develop_intake_transport`,
`test_consumer_installation`, `test_consumer_self_update`,
`test_r8_findings_remediation`, `test_pc_r4_client_neutrality`,
`test_public_lifecycle_completion_surface`,
`test_fa2_batch5_develop_lifecycle`, `test_p7_develop`,
`test_dive_pilot_correction05`).

## Closure regression

Fresh pair after the generator overlay was removed. Python 3.13.12,
pytest 9.0.3, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`,
`-p no:cacheprovider`.

- `F:\NewResearch\scaffold-r9-fnd001-junit\closure-baseline.xml`
- `F:\NewResearch\scaffold-r9-fnd001-junit\closure-candidate.xml`

| Tree | Failed | Passed | Skipped | Errors | Duration |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline `2e3b864` | 17 | 2025 | 2 | 16 | 4523.02s |
| Candidate | 16 | 2040 | 2 | 16 | 4594.20s |

Error node ids match. Skipped node ids match. There is no candidate-only
failed, error, or skipped node. No baseline pass is missing.

The only failed-node difference is baseline-only
`tests/test_p9_repair_migration.py::P9RepairTests::test_P9_R10_concurrent_repair_cas_one_winner`
(`AssertionError: 0 != 1`). The full run used `--tb=no`, so it did not
record an `os.replace` / `WinError 32` signature. An isolated baseline
rerun failed in the same test with `PermissionError: [Errno 13]` while
writing `.scaffold/ext/develop/unexplained.yaml.tmp`. That is the same
test and the same temporary file as the known Windows lock, and the
candidate run passed the node. `io_util.py` and `unexplained.py` are not
in this correction. It is not a candidate regression, and it is not
recorded here as the `WinError 32` `os.replace` signature.

The fifteen extra candidate passes are the nine Intake transport tests,
the five distribution-update tests, and that baseline-only `P9_R10` pass.

## Client-support trust root correction

The final re-audit (`R9_FND_001_FINAL_REAUDIT.md`) accepted the Intake
transport and the removal of the generator-copy fixture. It rejected the
generation-2 five-file rule. That rule read `FIRST_USE_RULE_TEXT` and
`CURSOR_BODIES` from the live `.scaffold/install/runtime/` and omitted a
Cursor client file when the live client bytes equalled those constants.
`install.yaml` was not the byte source, but it is also unsigned and
candidate-neutral. The measured loop was:

- D/E. Change the runtime generator and the matching Cursor adapter to the
  same new text. The adapter stayed candidate-neutral. Verify was
  `DRIFTED` only because the manifest digest was stale. The candidate
  digest did not move.
- F/G. The same agreement for the first-use rule, and the same agreement
  plus rewritten `install.yaml` digests. With the manifest rewritten,
  verify returned `VALID` and the candidate digest still did not move.

A byte source must not authenticate itself. Agreement among the live
runtime, the live adapter, and the live manifest is not an independent
trust root. The five-file rule and the verify check that compared client
files to those same runtime constants are removed. No expected-hash file
was added under `.scaffold/install/` or `.scaffold/runtime/`.

On a real adopted host the rule was also redundant. Adoption writes
`clients:` path `.cursor/` with strategy `CLIENT_SUPPORT` into
`.scaffold/project.yaml`. `excluded_from_candidate` already omits that
tree for both projection generations. That declaration is itself a core
machine artifact, so changing it moves the generation-2 digest. Baseline
`2e3b864` already omitted `.cursor/` on an adopted host. This correction
does not widen that exclusion.

Replacement model:

- Adopted Consumer UPDATE keeps currentness through that existing project
  client authority, plus the existing mixed-ownership projection for
  `AGENTS.md` and `.gitattributes`. Install infrastructure stays
  generation-2 neutral. No new trust store.
- If an update plan would change generation-2-visible bytes while a
  SATISFIED Completion Decision is already current, `apply_consumer_install`
  returns `BLOCKED` before migration records and before install writes.
  The planned bytes are the Distribution plan's payloads. The host is left
  unchanged, so the cited decision stays current.
- A same-distribution update with no generation-2-visible delta is still
  applied. An update with no current SATISFIED decision is still applied,
  and the candidate simply moves.
- Core machine artifacts stay in the generation-2 identity. Consumer
  UPDATE does not rewrite them, so they are not used as a new hash store
  for client bytes.

Real published replay: untouched `2e3b864` install, then the installed
`understand bootstrap` and `--approved --plan-digest` adoption
(`ESTABLISHED_HOST`, `.cursor/` declared), then a SATISFIED decision
citing the live generation-2 digest with `projection_generation: "2"`,
then UPDATE from this candidate Distribution. UPDATE completes, verify is
`VALID`, the generation-2 digest is unchanged, and the old READY decision
stays current. A following README edit moves the digest and makes READY
false. The same holds after the adopted tree is committed and the client
files are tracked. Unrelated `.cursor` settings, a human rule, and an
unmanaged sibling Skill stay omitted by the pre-existing `.cursor/`
declaration. Human `AGENTS.md` text and human `.gitattributes` text stay
visible. On a non-adopted host, those `.cursor` paths stay visible.

Historical `79755b15` (plus the pre-existing public lifecycle document
overlay, not the generator modules) has no `.cursor/` client declaration.
The cited generation-1 decision is current, and the candidate Distribution
would change generation-2-visible Cursor bytes. UPDATE is `BLOCKED`
before any install write. The rule and adapter bytes stay at their
historical values, no migration record is written, and the READY decision
remains current. That is `HISTORICAL_REPLAY = SAFELY_BLOCKED`.

Tamper matrix on a non-adopted install, where `.cursor/` is not declared:

| Case | Change | Result |
| --- | --- | --- |
| A | adapter only | verify `DRIFTED`; adapter stays in the candidate; digest changes |
| B | adapter + `install.yaml` digest | verify `VALID`; adapter stays in the candidate; digest changes |
| C | runtime generator only | verify `DRIFTED` on the runtime file; client file unchanged and still visible |
| D | runtime generator + adapter, same new bytes | verify not `VALID`; adapter stays in the candidate; digest changes |
| E | D + matching `install.yaml` digests | verify `VALID`; adapter stays in the candidate; digest changes |
| F | first-use constant + rule, same new bytes | verify not `VALID`; rule stays in the candidate; digest changes |
| G | F + matching `install.yaml` digests | verify `VALID`; rule stays in the candidate; digest changes |

D/E/F/G do not drop the changed client byte because the live files agree.
No-SCM inventories behave the same way: a runtime literal that matches a
client file does not omit it. Ordinary product bytes stay in the
inventory. The accepted MINOR remains: a leftover
`.scaffold/transport/develop-intake.json` is candidate-visible and moves
the no-SCM digest. Canonical maintenance behavior is unchanged apart from
the removed self-attestation.

Intake transport is unchanged. The nine tests in
`tests/test_r9_fnd001_develop_intake_transport.py` stay the public
contract for `--intake-json-file` and
`.scaffold/transport/develop-intake.json`.

## Trust-root regression

Focused suites after the trust-root removal: 291 passed in 679.52s
(`test_candidate_projection_generation`,
`test_r9_fnd001_distribution_update`,
`test_r9_fnd001_develop_intake_transport`,
`test_consumer_installation`, `test_consumer_self_update`,
`test_r8_findings_remediation`, `test_pc_r4_client_neutrality`,
`test_public_lifecycle_completion_surface`,
`test_fa2_batch5_develop_lifecycle`, `test_p7_develop`,
`test_dive_pilot_correction05`).

Fresh pair. Python 3.13.12, pytest 9.0.3, `PYTHONHASHSEED=0`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`.

- `F:\NewResearch\scaffold-r9-fnd001-junit\trust-baseline.xml`
- `F:\NewResearch\scaffold-r9-fnd001-junit\trust-candidate.xml`

| Tree | Failed | Passed | Skipped | Errors | Duration |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline `2e3b864` | 17 | 2025 | 2 | 16 | 3844.44s |
| Candidate | 17 | 2046 | 2 | 16 | 3421.01s |

Error node ids match. Skipped node ids match. Passed grew by 21: the nine
Intake transport tests and the twelve distribution-update tests.

The failed-node sets differ by one swap. Baseline only:
`tests/test_fa2_batch7_no_scm_publication.py::FA2Batch7NoScmPublicationTests::test_B7P18_distinct_record_ids_cannot_claim_same_generation`.
Candidate only:
`tests/test_p9_repair_migration.py::P9RepairTests::test_P9_R10_concurrent_repair_cas_one_winner`.
The full candidate run used `--tb=no`, so it did not record an
`os.replace` / `WinError 32` signature. An immediate isolated candidate
rerun of that node passed in 1.07s. It is not a stable candidate-only
failure, and it is not recorded here as the `WinError 32` signature.
`io_util.py` and `unexplained.py` are not in this correction.

