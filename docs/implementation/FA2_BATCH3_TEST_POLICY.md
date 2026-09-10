# FA-2 Batch 3 — Test policy + completeness semantics

This implementation note does not modify or outrank P0–P4.

Batch 3 closes C-MAJ-005, C-MAJ-002, and C-MIN-002. It does not close
C-MAJ-016 (untrusted caller Test report) or C-MAJ-017 (requirement-id
coverage proof). PF-1 and PF-2 remain closed and are not expanded.

## Versioning

`test@2.0.0` is a released Skill identity. Changing the meaning of P6
`test_complete` from terminal coverage to required-obligation completeness is a
normative package correction, not a silent mutation of `2.0.0`.

Existing SKILL_CONTRACT PATCH + `may_substitute_for` is used:

- live package is `test@2.0.1`
- `may_substitute_for: test@2.0.0`
- host locks are not mass-rewritten
- `submit@2.0.0` is unchanged: S5 already owned Foundation `TEST_COMPLETE`;
  runtime now consumes the corrected P6 result

Distribution fixture `tests/fixtures/distribution/packages/test-2.0.0/`
is left as the historical released identity.

## Observed vs required policy

Observed availability answers "what test capability appears to exist?"
Required-policy authority answers "what verification is mandatory?"

P5 observed profiles now record `policy: observed` and
`required_authority: UNKNOWN`. They omit `required: true` and do not write
authoritative `required: false`. Contract-level `required_authority: UNKNOWN`
keeps `required_set_authoritative` false even when availability confidence is
`VERIFIED`.

True zero-required remains distinct and requires explicit
`required_authority: VERIFIED` plus the existing valid zero-required
declaration. Availability `confidence: VERIFIED`, empty profiles,
`NOT_APPLICABLE`, or discovered test absence cannot establish that authority.

PF-1's temporary `required: false` assertion is superseded, not weakened.

## Completeness

`coverage_complete` = every required profile plus every explicitly selected
optional profile reached a terminal accounting state (`PASS` or `FAIL`).
Unselected optional profiles are outside selected coverage and optional
selection does not make them required.

P6 `test_complete` = required verification obligation satisfied. Required FAIL
is terminally accounted and cannot yield `test_complete`. Unknown required
policy cannot yield `test_complete` from observed PASS.

P8 S5 consumes that `test_complete` and fail-closes required FAIL. It does
not reconstruct a contradictory S5 definition.

## Scope and NOT_RUN

Reports expose `scope` (candidate, project-relative paths/modules, selected,
required, optional, not_selected, required_policy). Empty area scope remains
empty and machine-absolute paths are excluded. Every `NOT_RUN` entry has
`not_run_reason` in
`{not_selected, not_applicable, dependency_unavailable, prerequisite_blocked, outside_scope}`.
Missing required-policy authority remains `BLOCKED`, not `NOT_RUN`.

## Final narrow closure

B3-R1 keeps P5's verified absence as availability evidence while leaving
`required_authority: UNKNOWN`. P6 requires an explicit
`required_authority: VERIFIED` before an empty required set is authoritative.

B3-R2 persists normalized project-relative `scope.paths` and `scope.modules`
from direct Test invocation and from the P8 Task-scope handoff. Empty area
scope remains empty; machine-absolute values are not shared.

B3-R3 aligns `test@2.0.1` runtime with its package contract:
`coverage_complete` accounts for all required profiles plus explicitly
selected optional profiles. A selected optional blocker makes terminal
coverage incomplete but does not become a required failure or invalidate
required-obligation `test_complete`.

B3-R4 makes S5 a strict sequencing gate for review-only and finalizing Submit
flows. Required FAIL stops at S5 with a bounded Develop repair handoff; every
other false `test_complete` stops at S5 and routes to scoped verification.
S6 authorization and S7 callbacks are not reached after an S5 failure.

B3-R5 removes batch `TEST_PASS` as a second proxy for required-test
satisfaction. A selected optional FAIL remains visible in the Test report and
keeps `TEST_PASS` false, but does not block S10 when `required_fail == 0` and
`test_complete` is true. C-MAJ-016, C-MAJ-017, and C-MIN-003 were explicitly
left for Batch 4.
