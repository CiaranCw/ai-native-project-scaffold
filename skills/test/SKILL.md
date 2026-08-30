# Test

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `test`
- `skill_version`: `2.0.0`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: `scoped_verification`

This package provides `test.scoped_verification`. It does not require Develop or Submit capabilities and does not grant Commit, Push, or `SUBMIT_AUTHORIZED`.

Test is the verification/evidence Skill. It performs a read-only Host Compatibility Preflight for the actual Test package, binds to the current real candidate, resolves the Test Contract, executes or collects permitted verification, and publishes candidate-bound Test Reports as support artifacts. It is independently invocable. Task Book and Develop Session are optional references only.

Test MUST NOT develop or repair business source, authorize Submit, perform Structural Review, Commit, Push, create Develop Sessions, persist lock/project mutations, or treat `TEST_PASS` as Submit `TEST_COMPLETE` or `SUBMIT_AUTHORIZED`.

P6 `test_complete` is coverage completeness for the current candidate. Submit-S5 `TEST_COMPLETE` remains a later P8 judgment.

## scoped_verification

Resolve the current candidate, the applicable Test Contract/profiles, and the required verification set. Execute or collect permitted verification through a Target Adapter. Compile Evidence and a Test Report. Compute `TEST_PASS` for the executed batch and P6 coverage completeness separately.

If required Test Contract or command authority is UNKNOWN, CONFLICTING, malformed, or missing on an ACTIVE host, block and route toward Understand Refresh. Do not invent commands.

Details: [references/modes.md](references/modes.md).
