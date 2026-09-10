# Test modes

Exactly one mode is declared for Test `2.0.1`.

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

Published runtime reports remain the sole current-report authority. A
Submit-controlled durable finalization may separately ask Test to retain only
the P6-owned Evidence locators referenced by its Change Record. Such retention
uses deterministic metadata plus sidecars when raw bytes are required, obeys
existing concrete-target ownership resolution, and does not change the
reviewed candidate binding of the Evidence.

`TEST_PASS` is batch correctness for actually executed/accepted verification.
`coverage_complete` is terminal accounting: every required profile and every explicitly selected optional profile reached a terminal result. Unselected optional profiles are outside selected coverage.
P6 `test_complete` is required-verification obligation completeness for this candidate. Selected optional status does not become a required obligation. A required FAIL cannot yield it.
Unknown required policy—including verified absence of a discovered test surface—is not authoritative zero-required. An empty required set needs explicit `required_authority: VERIFIED`.
The report retains normalized project-relative `scope.paths` and `scope.modules`; empty scope stays empty and machine-absolute paths are not shared.
Neither is `SUBMIT_AUTHORIZED`.

When `task_id` and `requirement_id` are supplied, scoped verification also
loads Test-owned Scenario-Aware Verification supporting plans. Reconstruction
uses `.scaffold/runtime/test-plans/heads/<task_id>/<requirement_id>/head.yaml`.
New plans use `task_contract_digest` as currentness authority. Legacy plans
without that field still require exact `task_revision`. Required proof
obligations are SATISFIED only by matching structured Evidence
or, for an explicit suite/regression strategy, a passing bound profile. A
required `INSUFFICIENT_OBSERVABILITY` obligation is a Test→Develop handoff,
not a PASS.
