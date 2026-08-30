# Test modes

Exactly one mode is declared for Test `2.0.0`.

## scoped_verification

Product-level verification for the current real candidate.

1. Observe candidate identity before verification using the P6 candidate projection.
2. Perform a read-only Host Compatibility Preflight. Execute only on EXACT or COMPATIBLE. Do not mutate lock or project.
3. Validate referenced project schema/ownership when `.scaffold/project.yaml` is present.
4. Resolve `.scaffold/tests.yaml` and command authority from `.scaffold/commands.yaml`.
5. Execute or collect only declared profiles. Do not invent tests or guess UNKNOWN/CONFLICTING/INFERRED authority.
6. Observe candidate identity after verification.
7. Compile Evidence and atomically publish a completed Test Report last.
8. Return the generic Skill envelope with the actual package version. Verification FAIL is not a Skill crash.

`TEST_PASS` is batch correctness for actually executed/accepted verification.
P6 `test_complete` is required-test coverage completeness for this candidate.
Neither is `SUBMIT_AUTHORIZED`.
