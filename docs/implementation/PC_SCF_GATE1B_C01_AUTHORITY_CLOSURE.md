# Gate-1B-C01 — Core authority closure

Bounded correction of six Gate-1B BLOCKING findings. Not H3. No new product
feature. Not a Skill package. Not a fourth canonical development record.

`G1B-T2-SHOULD-001` remains fail-closed and unrepaired.

## Finding → root cause → fix → regression

| Finding | Root cause | Fix | Regression |
| --- | --- | --- | --- |
| G1B-T1-001 | Initial Adoption still used unbudgeted `os.walk` / `rglob` for test-tree, human-doc preservation, and nested-workspace scans. Digest inventory was bounded; workflow discovery was not. | One shared `bounded_metadata_walk` on `InventoryBudget.max_entries`. Truncation preserves `UNKNOWN` / `truncated` and cannot claim complete `VERIFIED` truth. Apply is blocked when preservation discovery is incomplete. | C1-01…C1-06, `test_G1B_T1_001` |
| G1B-T1-002 | `resolve_existing` followed index and case-insensitive walks through out-of-root indirection and read escaped bytes as project facts. | Both resolution paths call `project_relative_path` / `resolved_inside_root` before listdir/read. Architecture, module corroboration, and package/README facts refuse escaped targets. | C1-07…C1-10, `test_G1B_T1_002` |
| G1B-T2-001 | Published SAV reconstruction dropped exact `requirement_id`; consume searched another current Task requirement. | Persist `task_id` + `requirement_id` on the completed report. Consume reconstructs only that identity. Missing identity fails closed. No requirement-search fallback. | C2-01…C2-05, `test_G1B_T2_001` |
| G1B-T2-002 | Declared `evidence_requirements` did not constrain sufficiency. Profile PASS was treated as fictional `command_result`. | Any-of declared proof kinds. Supporting logs cannot satisfy. Suite POs that declare `command_result` require eligible result-bearing `command_result` Evidence. | C2-06…C2-11, `test_G1B_T2_002a/b` |
| G1B-T2-003 | Stale per-PO `candidate_digest` and stale generic trace-envelope `candidate` still SATISFIED. | PO candidate conflict → fail-closed UNKNOWN. Envelope `candidate` is normalized from the generic envelope only and compared with current authority. Opaque namespaces are not scanned. | C2-12…C2-17, `test_G1B_T2_003a/b` |
| G1B-T3-001 | `build_published_evidence_refs` selected the first resolvable profile-associated Ref, often supporting `log_text`, bypassing DEBUG/TEMPORARY_RUNTIME result retention. | Select Evidence that bears the profile result. Apply retention to that item at selection time. Support artifacts cannot substitute. | C3-01…C3-07, `test_G1B_T3_001` |

## C1 — bounded metadata traversal

`InventoryBudget.max_entries` counts listed directory entries, not hashed bytes.
A directory-only explosion cannot bypass the budget. Wall-clock time is not the
contract. One primitive is reused by:

- P5 test-tree discovery (`src/scaffold_p5/discovery.py`)
- human-doc preservation (`src/scaffold_p5/adoption.py`)
- nested-workspace scan (`src/scaffold_p5/host_state.py`)

Truncation truth:

- truncated test discovery → confidence `UNKNOWN`, never complete `VERIFIED`
- truncated preserve discovery → critical `human_owned_preservation:UNKNOWN`; Apply blocked
- truncated nested-workspace scan → status `truncated`, never verified `absent`

## C2 — exact Test authority

Published reports keep exact Task + Requirement identity. Consume never iterates
unrelated requirements. Declared evidence kinds are authority (any-of among
declared proof kinds, not an invented all-of rule). Association is not
sufficiency. Profile PASS is not Evidence.

## C3 — result-bearing durable refs

A durable Test result locator must resolve to Evidence that bears the selected
profile result. `log_text` / `file_artifact` never substitute. DEBUG and
TEMPORARY_RUNTIME result items fail closed rather than selecting a support log.
Correction-04 materialize-before-Change-Record ordering is unchanged.

## Generality

No Project-City, Vault, Babylon, or game-specific fields in Core. The same
authority applies to web/monorepo, backend/CLI, native/C++, data/ML, and
interactive hosts as ordinary directory trees.

## Remaining SHOULD

`G1B-T2-SHOULD-001`: explicit UNKNOWN verdict still collapses in diagnostic
classification toward UNSATISFIED in some surfaces. It remains fail-closed
(cannot SATISFY). Out of scope for C01.
