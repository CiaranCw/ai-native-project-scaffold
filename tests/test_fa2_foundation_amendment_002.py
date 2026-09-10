from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "docs/contracts/CONSTITUTION.md"
RECORDS = ROOT / "docs/contracts/RECORDS_CONTRACT.md"
SKILLS = ROOT / "docs/contracts/SKILL_CONTRACT.md"
LIFECYCLES = ROOT / "docs/architecture/RECORD_LIFECYCLES.md"
ARCHITECTURE = ROOT / "docs/architecture/V2_ARCHITECTURE.md"
NOTE = ROOT / "docs/implementation/FA2_FND_002_STAGE_COMPLETION_REPAIR.md"


def text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class FA2FoundationAmendment002Tests(unittest.TestCase):
    def test_FND2_E01_normal_candidate_bound_completion_is_legal_via_cas(self):
        records = text(RECORDS)
        constitution = text(CONSTITUTION)
        self.assertIn(
            "current Stage Completion Decision is `SATISFIED` for the actual candidate",
            records,
        )
        self.assertIn(
            "P7 owns the lifecycle decision and publication",
            records,
        )
        self.assertIn(
            "publish revision N+1 only if the current published revision is still N",
            records,
        )
        self.assertIn("FND2-E01", records)
        self.assertIn(
            "A Stage may enter `COMPLETE` only when its current decision is "
            "`SATISFIED`",
            constitution,
        )

    def test_FND2_E02_test_pass_is_not_acceptance(self):
        records = text(RECORDS)
        constitution = text(CONSTITUTION)
        self.assertIn(
            "A successful source write, `TEST_PASS`, or `TEST_COMPLETE` alone is "
            "insufficient.",
            records,
        )
        self.assertIn(
            "It MUST NOT be treated as: Stage acceptance satisfied",
            constitution,
        )
        self.assertIn("FND2-E02", records)

    def test_FND2_E03_required_fail_prevents_complete(self):
        records = text(RECORDS)
        self.assertIn(
            "If required tests fail: the Stage remains non-complete",
            records,
        )
        self.assertIn(
            "Required `FAIL` prevents Stage completion even when the completion "
            "decision is `SATISFIED`.",
            records,
        )
        self.assertIn("FND2-E03", records)

    def test_FND2_E04_stale_decision_cannot_prove_new_candidate(self):
        records = text(RECORDS)
        self.assertIn(
            "A `SATISFIED` decision for C1 MUST NOT complete a Stage or support "
            "`READY_FOR_REVIEW` for C2.",
            records,
        )
        self.assertIn(
            "Chat or Session continuity does not establish freshness.",
            records,
        )
        self.assertIn("FND2-E04", records)

    def test_FND2_E05_subjective_acceptance_requires_cited_authority(self):
        records = text(RECORDS)
        note = text(NOTE)
        self.assertIn(
            "Subjective acceptance MAY become `SATISFIED` only after an existing "
            "legitimate P6 human-observation",
            records,
        )
        self.assertIn(
            "Hidden chat memory, a raw Test Report mapping, or an uncited",
            records,
        )
        self.assertIn(
            "Human or subjective acceptance remains `UNKNOWN` until an existing "
            "legitimate human-observation Evidence/control path",
            note,
        )
        self.assertIn("FND2-E05", records)

    def test_FND2_E06_ready_requires_current_stage_and_task_decisions(self):
        records = text(RECORDS)
        constitution = text(CONSTITUTION)
        self.assertIn(
            "every Stage completion_decision is SATISFIED and current for the actual "
            "candidate",
            records,
        )
        self.assertIn(
            "task_completion_decision is SATISFIED and current for the actual "
            "candidate",
            records,
        )
        self.assertIn(
            "every Stage Completion Decision is `SATISFIED` and current for the "
            "actual candidate",
            constitution,
        )
        self.assertIn(
            "If the Task Completion Decision is `UNKNOWN` or stale, READY_FOR_REVIEW "
            "is forbidden even when all Stage decisions and final Tests are satisfied.",
            constitution,
        )
        self.assertIn("FND2-E06", records)
        self.assertIn(
            "READY_FOR_REVIEW is **not** submit authorization",
            records,
        )

    def test_FND2_E07_valid_ready_repair_targets_exact_stages_via_cas(self):
        records = text(RECORDS)
        skills = text(SKILLS)
        self.assertIn(
            "Task READY_FOR_REVIEW → IN_PROGRESS each target Stage COMPLETE → "
            "IN_PROGRESS revision N → N+1",
            records,
        )
        self.assertIn(
            "only a current, Task-bound, Stage-targeted `submit_to_develop` handoff "
            "permits P7 to atomically reopen",
            skills,
        )
        self.assertIn("FND2-E07", records)

    def test_FND2_E08_missing_target_is_unresolved_not_guessed(self):
        records = text(RECORDS)
        skills = text(SKILLS)
        self.assertIn(
            "P8 MUST return unresolved repair routing; it MUST NOT guess the first, "
            "last, or all Stages.",
            records,
        )
        self.assertIn(
            "return an unresolved repair route rather than guess the first, last, or "
            "all Stages",
            skills,
        )
        self.assertIn("FND2-E08", records)

    def test_FND2_E09_invalid_handoff_cannot_mutate_task_or_stage(self):
        records = text(RECORDS)
        self.assertIn(
            "capability-escalating handoff MUST NOT mutate the Task or any Stage",
            records,
        )
        self.assertIn(
            "bounded capabilities that do not grant Commit, Push, or submission "
            "authorization",
            records,
        )
        self.assertIn("FND2-E09", records)

    def test_FND2_E10_repair_c1_to_c2_invalidates_old_authority(self):
        records = text(RECORDS)
        lifecycles = text(LIFECYCLES)
        self.assertIn(
            "C1 Stage/Task decisions and Evidence cannot immediately restore READY",
            records,
        )
        self.assertIn(
            "target and non-target Stage decisions relied upon for READY must be "
            "SATISFIED and current for C2",
            lifecycles,
        )
        self.assertIn(
            "Task Completion Decision must be SATISFIED/current for C2",
            lifecycles,
        )
        self.assertIn("FND2-E10", records)

    def test_FND2_E11_non_target_stage_requires_current_revalidation(self):
        records = text(RECORDS)
        architecture = text(ARCHITECTURE)
        self.assertIn(
            "A non-target Stage need not be blindly reopened, but its stale C1 "
            "decision cannot support READY on C2",
            records,
        )
        self.assertIn(
            "stale target and non-target Stage decisions cannot restore READY",
            architecture,
        )
        self.assertIn(
            "the Task Completion Decision must be `SATISFIED` and current for C2",
            architecture,
        )
        self.assertIn("FND2-E11", records)

    def test_FND2_R01_task_completion_decision_is_reconstructable_authority(self):
        records = text(RECORDS)
        note = text(NOTE)
        self.assertIn(
            "`task_completion_decision` | Current structured, durable, "
            "candidate-bound P7 decision",
            records,
        )
        self.assertIn("The same bounded decision enum: exactly", records)
        for outcome in ("`SATISFIED`", "`UNSATISFIED`", "`UNKNOWN`"):
            self.assertIn(outcome, records)
        self.assertIn(
            "A `SATISFIED` Task decision for C1 MUST NOT support "
            "`READY_FOR_REVIEW` for C2.",
            records,
        )
        self.assertIn(
            "Hidden chat reasoning, raw Test Report mappings, uncited",
            records,
        )
        self.assertIn(
            "A C1 Task decision cannot support READY on C2.",
            note,
        )

    def test_FND2_R02_complete_and_task_complete_separate_history_from_currentness(self):
        records = text(RECORDS)
        architecture = text(ARCHITECTURE)
        self.assertIn(
            "The transition `IN_PROGRESS` → `COMPLETE` is legal only when all of the "
            "following hold for the actual candidate at publication",
            records,
        )
        self.assertIn(
            "`COMPLETE` | Stage completion was validly established under §8.4 when "
            "published; current-candidate readiness MAY require §8.4.2 revalidation",
            records,
        )
        self.assertIn(
            "its stale C1 decision is historical progress only and cannot support "
            "Task readiness",
            records,
        )
        self.assertIn(
            "`TASK_COMPLETE` is only the structural aggregation of required Stage "
            "status values.",
            records,
        )
        self.assertIn(
            "later stale COMPLETE records historical progress only",
            architecture,
        )

    def test_FND2_E12_taxonomy_authority_and_state_sets_are_unchanged(self):
        records = text(RECORDS)
        constitution = text(CONSTITUTION)
        skills = text(SKILLS)
        note = text(NOTE)
        for record in ("Task Book", "Develop Session", "Change Record"):
            self.assertIn(record, constitution)
        self.assertIn("## 2. Four Skills only", constitution)
        for task_status in ("`DRAFT`", "`READY_FOR_REVIEW`", "`CANCELED`"):
            self.assertIn(task_status, records)
        for stage_status in ("`PENDING`", "`BLOCKED`", "`COMPLETE`"):
            self.assertIn(stage_status, records)
        self.assertIn("Frozen Task Book `status` values (exactly these four)", records)
        self.assertIn("Frozen Stage states (exactly these four)", records)
        self.assertIn(
            "P6 remains the sole owner of Test execution, Evidence truth",
            records,
        )
        self.assertIn("P8 does not write or reopen the Task", records)
        self.assertIn("P8 does not write the Task Book", skills)
        self.assertIn(
            "no S13, new submission permission, Commit/Push escalation",
            note,
        )
        self.assertIn("FND2-E12", records)

    def test_FND2_C01_constitution_section_12_ready_lifecycle_matches_section_6(self):
        lifecycle = _high_level_lifecycle()
        constitution = text(CONSTITUTION)
        self.assertIn("all required Task Stages COMPLETE", lifecycle)
        self.assertIn(
            "every Stage Completion Decision relied upon for READY is SATISFIED "
            "and current for the actual candidate",
            lifecycle,
        )
        self.assertIn(
            "task-level final required tests satisfy their defined acceptance "
            "conditions",
            lifecycle,
        )
        self.assertIn(
            "the Task Completion Decision is SATISFIED and current for the actual "
            "candidate",
            lifecycle,
        )
        self.assertIn("no required blocker remains", lifecycle)
        self.assertIn("READY_FOR_REVIEW", lifecycle)
        self.assertNotIn(
            "all Task stages complete + stage acceptance satisfied",
            lifecycle,
        )
        self.assertNotIn(
            "task-level final required tests satisfy acceptance → READY_FOR_REVIEW",
            lifecycle,
        )
        self.assertEqual(
            lifecycle.count("the Task Completion Decision is SATISFIED and current"),
            1,
        )
        self.assertIn(
            "the Task Completion Decision is `SATISFIED` and current for the "
            "actual candidate",
            constitution,
        )


def _high_level_lifecycle() -> str:
    raw = CONSTITUTION.read_text(encoding="utf-8")
    heading = "### High-level lifecycle (normative order)"
    start = raw.index(heading)
    rest = raw[start:]
    end = rest.find("\n---")
    block = rest if end < 0 else rest[:end]
    return " ".join(block.split())


if __name__ == "__main__":
    unittest.main()
