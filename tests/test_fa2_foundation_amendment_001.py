from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "docs/contracts/CONSTITUTION.md"
PROJECT = ROOT / "docs/contracts/PROJECT_CONTRACT.md"
RECORDS = ROOT / "docs/contracts/RECORDS_CONTRACT.md"
SKILLS = ROOT / "docs/contracts/SKILL_CONTRACT.md"
LAYOUT = ROOT / "docs/architecture/PROJECT_LAYOUT.md"
LIFECYCLES = ROOT / "docs/architecture/RECORD_LIFECYCLES.md"
ARCHITECTURE = ROOT / "docs/architecture/V2_ARCHITECTURE.md"
NOTE = ROOT / "docs/implementation/FA2_FOUNDATION_AMENDMENT_001.md"


def text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class FA2FoundationAmendment001Tests(unittest.TestCase):
    def test_FND_E01_deterministic_referenced_support_is_s9_exempt(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        architecture = text(ARCHITECTURE)
        lifecycles = text(LIFECYCLES)
        self.assertIn("The sole S9 exception is the deterministic", constitution)
        self.assertIn("S9 FINALIZATION BUNDLE", records)
        self.assertIn("already validated before S6", records)
        self.assertIn("does not invalidate the authorization", constitution)
        self.assertIn("FND-E01", records)
        self.assertIn("S9 Finalize Bundle", architecture)
        self.assertIn("Submit-S9 deterministic Finalization Bundle", lifecycles)

    def test_FND_E02_unrelated_s9_mutation_requires_review(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        self.assertIn(
            "Any other S9 mutation is a candidate change and MUST return",
            constitution,
        )
        self.assertIn("MUST return through S3–S6", records)
        self.assertIn("MUST NOT mutate Task Books", records)

    def test_FND_E03_nondeterministic_support_is_not_exempt(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        self.assertIn(
            "Additional substantive or non-deterministic content is a",
            constitution,
        )
        self.assertIn(
            "support content that cannot be deterministically derived",
            records,
        )

    def test_FND_E04_git_tree_must_contain_referenced_support(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        self.assertIn("MUST belong to that exact Commit tree", constitution)
        self.assertIn(
            "points to a tracked support artifact absent from that Commit tree",
            records,
        )
        self.assertIn("finalization mismatch and MUST fail closed", constitution)
        self.assertIn("FND-E04", records)
        self.assertIn("SCM: exact staged/normalized bundle in Commit", text(LIFECYCLES))

    def test_FND_E05_failed_s10_support_is_candidate_only(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        self.assertIn(
            "Candidate-only support artifacts require deterministic cleanup or recovery",
            constitution,
        )
        self.assertIn(
            "Temporary coordination state MAY live under `.scaffold/runtime/`",
            records,
        )
        self.assertIn("it is not durable Evidence authority", records)

    def test_FND_E06_durable_locator_survives_runtime_expiry(self):
        records = text(RECORDS)
        project = text(PROJECT)
        layout = text(LAYOUT)
        self.assertIn(
            "resolution remains possible after ordinary `.scaffold/runtime/` expiry",
            records,
        )
        self.assertIn(
            "MUST NOT require its originating `.scaffold/runtime/test-runs/`",
            records,
        )
        self.assertIn("`.scaffold/ext/<namespace>/`", project)
        self.assertIn("public P6 locator resolvable after normal runtime expiry", project)
        self.assertIn("FND-E06", records)
        self.assertIn("owned durable support artifacts", layout)
        self.assertIn("Agents MUST NOT treat runtime as handoff truth", layout)

    def test_FND_E07_no_new_record_skill_stage_permission_or_ownership_mode(self):
        constitution = text(CONSTITUTION)
        project = text(PROJECT)
        records = text(RECORDS)
        skills = text(SKILLS)
        note = text(NOTE)
        for record in ("Task Book", "Develop Session", "Change Record"):
            self.assertIn(record, constitution)
        self.assertIn("P1 modes remain the **only** three", project)
        self.assertIn(
            "No S13, second permission, fourth canonical record, fifth Skill, or fourth "
            "ownership mode is introduced.",
            note,
        )
        self.assertIn("P6 gains no Commit or Submit authority", note)
        self.assertIn("FND-E07", records)
        self.assertIn("MUST NOT invent a fifth top-level Skill", skills)
        self.assertIn("these semantics do not add a thirteenth stage", constitution)


if __name__ == "__main__":
    unittest.main()
