# Test

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `test`
- `skill_version`: `2.0.1`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: `scoped_verification`

This package provides `test.scoped_verification`. It does not require Develop or Submit capabilities and does not grant Commit, Push, or `SUBMIT_AUTHORIZED`.

Test is the verification/evidence Skill. It performs a read-only Host Compatibility Preflight for the actual Test package, binds to the current real candidate, resolves the Test Contract, executes or collects permitted verification, and publishes candidate-bound Test Reports as support artifacts. Git-backed candidate observation is fail-closed: failed or invalid SCM observation has no usable candidate digest and blocks before adapter execution; it never becomes clean or no-SCM. Nested projects use parent-worktree Git truth projected to the project root. Test is independently invocable. Task Book and Develop Session are optional references only.

Test MUST NOT develop or repair business source, authorize Submit, perform Structural Review, Commit, Push, create Develop Sessions, persist lock/project mutations, or treat `TEST_PASS` as Submit `TEST_COMPLETE` or `SUBMIT_AUTHORIZED`.

P6 `test_complete` is required-verification obligation completeness for the current candidate. A required FAIL is terminally accounted and may yield `coverage_complete`, but it cannot yield `test_complete`. Observed availability is not required-policy authority. Submit-S5 consumes this current `test_complete` result and does not treat terminal coverage alone as Foundation `TEST_COMPLETE`.

This `2.0.1` PATCH corrects those support-artifact semantics without adding modes or capabilities. It may substitute for `test@2.0.0` without a host lock rewrite.

## scoped_verification

Resolve the current candidate, applicable global/module/path/test Project Rules, the Test Contract/profiles, and the required verification set. Rule loading is read-only and cannot grant mutation, Commit, Push, or Submit authority. Execute or collect permitted verification through a Target Adapter only after applicable prohibitions and Rule conflicts are cleared. Compile Evidence and a Test Report. Compute `TEST_PASS` for the executed batch, terminal coverage, and required-obligation completeness separately. Terminal coverage accounts for every required profile plus explicitly selected optional profiles; optional selection does not make a profile required. Every `NOT_RUN` entry records an explicit reason. The report exposes the project-relative area scope, selected verification, candidate, and required-policy authority.

Test owns published Evidence locator construction and resolution. Resolution
revalidates the owning completed report, checks required local digests, and
preserves the original LOCAL, HUMAN, CI, or EXTERNAL Evidence semantics.
Resolved Evidence exposes the producing profile identity so Develop can
verify `execution_binding.profile_id` without trusting caller-provided producer
metadata.
For durable Change Record references, Test may materialize the minimum
deterministic Evidence metadata and required raw bytes under an already
whole-file `GENERATED` `.scaffold/ext/test/` target. Durable locator resolution
validates that representation independently; it does not repair or mask a
corrupt current runtime report. Ordinary Test-run cleanup refuses a run while
its durable materialization is PREPARED and may delete temporary runtime state
after durable finalization without breaking the retained locator.
While a locator remains under PREPARED coordination, its capsule is still
candidate support: resolution uses healthy runtime truth or blocks for P8
reconciliation. Capsule existence alone never establishes durable Evidence.

If required Test Contract or command authority is UNKNOWN, CONFLICTING, malformed, or missing on an ACTIVE host, block and route toward Understand Refresh. Do not invent commands.

Develop may ask Test to consume an already published completed report by
`report_id`. That path reloads durable storage and revalidates schema,
currentness, locators, and claimed SAV coverage. It does not re-execute and
does not accept a caller report dictionary as authority.

When a Task requirement uses Scenario-Aware Verification, Test owns a
supporting (not canonical) plan under `.scaffold/runtime/test-plans/**`. The
plan is Task/requirement-specific: scenario, proof obligations, observability,
and required assertions. New plans bind `task_contract_digest` as currentness
authority and keep `task_revision` for trace. Completion-only Task revision
changes do not stale a new-format plan. Legacy plans without the digest keep
strict revision equality. A fresh Test Agent reconstructs the current plan
from the Test-owned head/locator without chat history.

This unreleased `test@2.0.1` candidate includes that supporting Scenario-Aware
Verification authority. It does not add a fifth Skill, a fourth canonical
record, or a new Test mode. Released `test@2.0.0` remains immutable. This
working-tree identity is not a new released PATCH.

Details: [references/modes.md](references/modes.md).
