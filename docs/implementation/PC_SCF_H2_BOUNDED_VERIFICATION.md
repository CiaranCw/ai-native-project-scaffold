# PC-SCF-H2 — Bounded inventory, Evidence sufficiency, and generic traces

This note records the H2 implementation maturation under existing contracts. It is not a Foundation Contract, not a Skill package, and not a fourth canonical development record. Core authority stays project-independent.

## Bounded inventory truth

Adoption inventory is produced by `list_files`, `durable_inventory`, and Plan baseline consumers through `src/scaffold_p5/inventory.py`.

Directory-name classes are generic observation policy, not content truth:

| Class | Meaning |
| --- | --- |
| `DEEP` | ordinary in-scope roots; files are hashed until budget |
| `BOUNDED` | shallow file hash; child directories are recorded without recursive hashing |
| `EXCLUDED` | heavy/generated/dependency roots; presence is recorded; contents are not recursively hashed |

Default excluded directory names include `node_modules`, `vendor`, `dist`, `build`, `coverage`, `__pycache__`, `.venv`, `venv`, `target`, `out`, and common cache/tool roots. Core does not list consumer-project paths.

Observation outcomes:

| Status | Meaning |
| --- | --- |
| `FULLY_OBSERVED` | in-scope hashing completed under budget |
| `EXCLUDED_BY_POLICY` | present excluded root; not empty and not fully verified |
| `TRUNCATED_BY_BUDGET` | in-scope traversal exceeded max files or hashed bytes |
| `UNKNOWN` | observation failure; fail closed |
| `ABSENT` | exact-observed path does not exist |

Budgets are deterministic (`max_files`, `max_hash_bytes`). Wall-clock time is not the contract. Truncation cannot be reported as `verified_complete`.

Preservation:

- exact digest for fully observed and mutation-relevant paths
- approved Adoption mutations cannot touch excluded/unobserved areas outside the mutation envelope
- “not hashed” is not “does not matter”

Any exact path the Adoption Plan may mutate is exact-observed before approval/apply, even under an otherwise excluded root. An unobserved envelope target cannot be approved as if it were known.

Traversal does not follow directory symlinks/junctions out of the project root and does not recurse cycles.

Cross-domain examples: a web `node_modules` tree, a CLI `dist/` build, a native `target/` crate output, an ML `checkpoints/` directory, and an interactive `vendor/` asset pack are all generic excluded/bounded roots.

## Verification obligation coverage

Existing chain remains:

Requirement → `execution_binding` → SAV → `proof_obligations` → P6 Evidence → `test_complete`.

SAV remains a supporting artifact. H2 does not add a Verification Skill, Verification Record, `TEST_ADEQUATE` Foundation state, or parallel Test authority.

`po_id` / `covers` associate Evidence with a proof obligation. Association is not sufficiency. Coverage requires binding, candidate currentness, provenance validity, kind/method sufficiency, and an explicit passing oracle/verdict for that PO. Each covered PO is evaluated independently.

## Evidence sufficiency

| Kind | Direct satisfaction |
| --- | --- |
| `command_result` | only a suite/regression/profile PO whose strategy is the suite strategy |
| `structured_assertion` | bound PO with explicit PASS; missing role is implicit PRIMARY |
| `structured_state` | only with a PO-bound structured assertion/oracle/verdict |
| `event_trace` | only with PO-bound assertion/verdict data and a valid candidate binding |
| `human_observation` | only when the SAV/PO method/evidence requirements permit it and a verdict is explicit |
| `visual_checkpoint` | does not prove a structurally measurable PO by default |
| `log_text` / `file_artifact` | supporting only by default |
| `external_ci` | existing provenance rules plus a usable structured verdict |

Caller `adequacy.status = SATISFIED` is not authority. Engine-derived adequacy checks PRIMARY evidence, kind/method observability, explicit verdict, candidate/provenance, and any declared deterministic negative-control obligation. `UNSATISFIED` or required `UNKNOWN` adequacy cannot yield `test_complete`. Profile required/optional remains distinct from PO required/optional.

Negative controls are ordinary correctness checks (invalid input rejected, blocked transition remains blocked). They are required only when the SAV/PO or adequacy policy explicitly requires them. No fuzzing, penetration, adversarial, or DoS testing.

## Generic trace envelope

Existing kinds `event_trace` and `structured_state` may carry:

`scenario_id`, `candidate`, `requirement_ids`, `obligation_ids`, `initial_state`, `actions`, `observations`, `assertions`, `artifacts`, `result`

Domain payload is opaque (`domain` / `payload` / `extension` / `opaque`). Unknown top-level keys are not Core authority, are not rejected by name, and cannot independently satisfy a proof obligation. Opaque namespaces are not scanned for nested assertions. Scenario is not a canonical record.

## Role

Optional Evidence `role`: `PRIMARY` | `SECONDARY` | `ESCALATION`.

- PRIMARY: cheapest sufficient proof of a PO
- SECONDARY: justified cross-layer corroboration; cannot be the only proof of a required PO
- ESCALATION: used because primary evidence is insufficient/conflicted or the requirement demands the higher-cost observation

Legacy structured assertion without role remains PRIMARY.

## Retention

Optional `retention_class`: `DURABLE_FINALIZATION` | `TEMPORARY_RUNTIME` | `DEBUG` | `OPTIONAL_VISUAL`.

Legacy missing retention keeps existing behavior. `DEBUG` must never enter durable Change Record materialization. `TEMPORARY_RUNTIME` must not become S9 durable finalization Evidence. `DURABLE_FINALIZATION` is eligible if referenced by the Change Record and otherwise valid. `OPTIONAL_VISUAL` defaults to runtime only; durable retention needs an explicit justification.

S9 still materializes only Evidence locators already referenced by the Change Record. Retention class is not a request to retain everything. Correction 04 materialize-before-Change-Record ordering is unchanged.

## Visual policy

Visual-model Evidence is not required by default. A visual observation may be justified when the requirement is inherently visual, structured/runtime Evidence conflicts with human observation, or no reliable nonvisual oracle exists. Visual Evidence never replaces structural Evidence for directly measurable facts. H2 does not implement a vision runner.
