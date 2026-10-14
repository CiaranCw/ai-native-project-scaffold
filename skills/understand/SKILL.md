# Understand

Canonical Skill package for AI-Native Project Scaffold v2.0.

- `skill_id`: `understand`
- `skill_version`: `2.3.0`
- `package_format_version`: `1`
- `entry`: `SKILL.md`
- supported modes: `bootstrap`, `full`, `refresh`, `compatibility`

This package provides `understand.bootstrap`, `understand.full`, `understand.refresh`, and `understand.compatibility`. It does not require Develop or Submit capabilities and does not grant Commit, Push, or `SUBMIT_AUTHORIZED`.

Version `2.3.0` is a backward-compatible MINOR workflow extension of published
`understand@2.1.0` and released `understand@2.0.0`. Those packages remain
immutable. `understand@2.0.0` does not include FA2-FND-004 Knowledge
Assessment publication. `understand@2.1.0` does not include project-policy
Required Test Authority. This candidate declares `may_substitute_for` for
`understand@2.0.0` and `understand@2.1.0` on an established host.
Pre-adoption Bootstrap still requires the exact release-pinned Understand
package and MUST NOT use compatible substitution.

Compatibility Preflight is a Distribution support layer, not this Skill and not a fifth Skill.

## bootstrap

Run P1 Adoption B1–B9. B1/B2 are operationally read-only. No persistent host mutation before exact-plan apply of the current Adoption Plan. The Adoption Plan binds the Selected Distribution Release, exact Understand identity, coherent four-Skill initial lock, contract intent, and mutation envelope. `--approved --plan-digest` is the compatibility spelling of that apply request. It is not human Git Commit/Push authority and is not a reusable persisted permission.

A general instruction to adopt or bootstrap the project authorizes the Agent to enter Bootstrap, preview, and then apply that exact Plan when machine/project preconditions still hold. It is not Auto-Adoption outside this explicit lifecycle route. After preview, continue with `plan_id` / `plan_digest` apply of that same Plan. Do not treat chat intent or a self-generated digest as Git Commit or Git Push.

## full

Normalize an adopting or ordinary host into the P2 three-layer model inside the approved envelope. Preserve HUMAN_OWNED content. Register shared durable Scaffold-touched artifacts as GENERATED, MANAGED, or HUMAN_OWNED.

## refresh

Update allowed GENERATED/MANAGED knowledge on an ACTIVE host when the workspace has changed. Do not silently become Develop. Do not edit unrelated business source. When Submit hands off exact S3 knowledge-relevant impacts, Refresh publishes a candidate-bound, impact-bound Knowledge Assessment supporting artifact and the current-head for that binding. That artifact is not a canonical development record. HUMAN_OWNED surfaces are not silently overwritten. A later Assessment for the same candidate and impact set supersedes the previous Assessment as S4 authority.

Refresh also owns zero-context resume and incremental project-understanding currentness as Understand supporting runtime authority, not a fifth mode and not a fourth canonical record.

Natural-language entry maps to existing Refresh actions. There is no fifth routing engine.

- “Continue this project.” / “Understand the current state and tell me what needs doing.” → `refresh` `action=resume`. Reconstruct from project-local Task Book, Develop Session, Change Record, Repair, Migration, Test, Submit, and understanding current-head artifacts. Chat history is not authority.
- Bounded understanding refresh → `refresh` `action=understand`. Physical observation decides the required refresh **scope**. A new current-head may become `CURRENT` only after Understand-produced refresh-completion receipts bind that exact physical scope **and** the current module knowledge bytes still match each bound `knowledge_digest`. `output_locator` / `output_digest` are real authority: missing or mismatched `result.yaml` fails closed. Caller MAY request `incremental=true`, but that flag is not completion proof. If incremental is requested while currentness is `FULL_REFRESH_REQUIRED` or `UNKNOWN`, do not reuse stale understanding. Refresh-completion receipts do not create mutation authority. Knowledge mutation still follows `project.yaml` ownership: GENERATED whole-file, MANAGED bounded region only, HUMAN_OWNED preserve, UNKNOWN/CONFLICTING fail closed. The completion binds the **final** Understand-produced knowledge payload. Do not rewrite meaningful GENERATED knowledge back to a stub after the receipt, and do not enrich knowledge after the receipt without invalidating CURRENT.
- Malformed, unreadable, or orphaned canonical Task Book / Develop Session authority fail-closes zero-context resume to `human`. Do not route `submit` / `develop.continue` from the remaining healthy subset.
- Required Test Authority → `refresh` `action=required_tests`. This is not a fifth mode. The required set comes from `docs/project/required-test-policy.yaml`. Understand does not write that file, and a Develop session cannot write it either: it is protected governance. The file is authoritative only when its bytes match an accepted baseline: a clean Git HEAD blob, or the accepted no-SCM baseline inventory. The bound record stores that source, its version, and the content digest. An uncommitted or Agent-written copy stays UNKNOWN, including `policy: zero_required`. The staging JSON is transport: `{"publish": true}`. It may echo `required_profile_ids` or `zero_required` only when that echo matches the policy exactly. An Agent selection, a plan digest, a passing Test run, and inferred command confidence do not approve the required set. Preview does not write `.scaffold/tests.yaml` and does not change discovery `confidence`. Apply writes only when `--plan-digest` matches the current accepted policy, command definition, and profile execution identity. `CONFLICTING` discovery confidence cannot be published or consumed as required authority. Develop and Submit must not hand-edit `tests.yaml`. After apply, rerun official Test before Submit; the apply itself does not require a post-publication Test report. Stage the proposal only at `.scaffold/transport/required-tests.json`. `--plan-digest` without `--action required_tests` is rejected.

```text
python .scaffold/install/run.py understand refresh --action required_tests --required-tests-json-file .scaffold/transport/required-tests.json
python .scaffold/install/run.py understand refresh --action required_tests --required-tests-json-file .scaffold/transport/required-tests.json --plan-digest <hex>
```

Default `refresh` with no action remains GENERATED/MANAGED host-knowledge refresh. A later default Refresh keeps a published required set only while the stored grounding matches its own plan digest and the current policy, command definition, and profile execution identity. A disappeared profile, a changed argv, a changed package script body or declared source file, a changed exit code, timeout, or evidence requirement, contradictory zero-required grounding, or a digest that does not match its content downgrades the whole set to UNKNOWN and reports `authority_diagnostics`. Transitive dependencies and the package-manager binary are outside this identity boundary.

## compatibility

Evaluate package validity then exactly one of `EXACT`, `COMPATIBLE`, `MIGRATION_REQUIRED`, `INCOMPATIBLE`, `UNKNOWN`. Do not silently rewrite `skills.lock`. Lock update and project migration are distinct.

Installed launcher:

```text
python .scaffold/install/run.py understand compatibility
python .scaffold/install/run.py understand compatibility --action lock_update --new-expected <json>
python .scaffold/install/run.py understand compatibility --action lock_update --new-expected <json> --plan-digest <hex>
```

`--new-expected` is a JSON object of core Skill id to `{skill_version, package_digest}` and optional `package_format_version`. `--new-expected-b64` carries the same object. The new expected identity MUST resolve to one currently installed VALID package. Preview is not apply; continue with that exact `--plan-digest`. The apply request is Agent-autonomous lifecycle work. It is not `--approved` Adoption apply and not Git Commit or Push. Consumer UPDATE does not rewrite `skills.lock`.

Compatibility owns Plan construction and the canonical Migration Execution lifecycle/recovery implementation. It MUST NOT start a fresh persistent Migration from Plan-only approval; fresh apply is Task-bound Develop work. After successful Migration validation, current compatibility is the post-migration `EXACT` or `COMPATIBLE` result; pre-migration `MIGRATION_REQUIRED` is historical, not current authority.
