from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "docs/contracts/CONSTITUTION.md"
RECORDS = ROOT / "docs/contracts/RECORDS_CONTRACT.md"
SKILLS = ROOT / "docs/contracts/SKILL_CONTRACT.md"
LIFECYCLES = ROOT / "docs/architecture/RECORD_LIFECYCLES.md"
ARCHITECTURE = ROOT / "docs/architecture/V2_ARCHITECTURE.md"
NOTE = ROOT / "docs/implementation/FA2_FND_003_TASK_CONTROL_PLANE_CURRENTNESS.md"


def text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class FA2FoundationAmendment003Tests(unittest.TestCase):
    def test_FND3_E01_completion_publication_does_not_self_invalidate(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        note = text(NOTE)
        self.assertIn("P6 remains the **single owner** of candidate identity", constitution)
        self.assertIn(
            "the single P6 candidate remains C and the stored decision does not "
            "immediately stale itself",
            records,
        )
        self.assertIn(
            "Remaining on C does not prove the write was P3/P7 CAS-authorized.",
            records,
        )
        self.assertIn("Decision(C) is immediately stale", note)
        self.assertIn("FND3-E01", records)

    def test_FND3_E02_source_mutation_stales_old_authority(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        architecture = text(ARCHITECTURE)
        self.assertIn(
            "A source, business, project, configuration", constitution
        )
        self.assertIn(
            "Source/business/project mutation or a substantive Task authority "
            "mutation yields C2 and makes C Evidence stale.",
            records,
        )
        self.assertIn(
            "Evidence(C), Decision(C), review(C), authorization(C) are stale",
            architecture,
        )
        self.assertIn("FND3-E02", records)

    def test_FND3_E03_substantive_task_mutation_is_not_neutral(self):
        records = text(RECORDS)
        constitution = text(CONSTITUTION)
        self.assertIn(
            "goal, acceptance, scope, baseline, Stage plan, requirement identity, "
            "or execution-binding change is candidate-changing",
            records,
        )
        self.assertIn(
            "Goal, acceptance, scope, baseline, Stage identity/goal/acceptance",
            constitution,
        )
        self.assertIn("FND3-E03", records)

    def test_FND3_E04_ready_publication_is_representable(self):
        records = text(RECORDS)
        lifecycles = text(LIFECYCLES)
        self.assertIn(
            "READY publication does not self-invalidate", records
        )
        self.assertIn(
            "substantive projection unchanged → P6 candidate remains C",
            lifecycles,
        )
        self.assertIn("FND3-E04", records)
        self.assertIn(
            "Remaining on C does not prove the write was P3/P7 CAS-authorized.",
            records,
        )

    def test_FND3_E05_real_diff_keeps_task_control_plane_bytes(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        architecture = text(ARCHITECTURE)
        self.assertIn(
            "The real workspace/SCM Diff MUST retain the complete Task Book byte "
            "change.",
            constitution,
        )
        self.assertIn(
            "neutrality affects only P6 candidate currentness, not "
            "review/provenance visibility, write permission, or publication "
            "authorization",
            records,
        )
        self.assertIn(
            "still visible in the complete physical Diff",
            architecture,
        )
        self.assertIn("FND3-E05", records)

    def test_FND3_E06_different_requirement_and_profile_ids_bind_explicitly(self):
        records = text(RECORDS)
        skills = text(SKILLS)
        note = text(NOTE)
        self.assertIn("requirement_id: \"task-required/check-save\"", records)
        self.assertIn("profile_id: \"unit-save-check\"", records)
        self.assertIn(
            "Task requirement R → P6 Test profile P", skills
        )
        self.assertIn(
            "Task R explicitly binds P + resolved locator was produced by P",
            note,
        )
        self.assertIn("FND3-E06", records)

    def test_FND3_E07_no_binding_means_no_name_matching_or_guessing(self):
        records = text(RECORDS)
        skills = text(SKILLS)
        lifecycles = text(LIFECYCLES)
        self.assertIn(
            "matching names, selection order, or a sole result MUST NOT be used "
            "to guess",
            records,
        )
        self.assertIn(
            "Equal strings, list order, a sole selected result, or caller prose "
            "MUST NOT create the association.",
            skills,
        )
        self.assertIn(
            "No explicit binding means no fresh-execution attachment by equal "
            "names",
            lifecycles,
        )
        self.assertIn("FND3-E07", records)

    def test_FND3_E08_mismatched_binding_cannot_satisfy_requirement(self):
        records = text(RECORDS)
        architecture = text(ARCHITECTURE)
        self.assertIn(
            "A wrong or mismatched binding cannot satisfy another requirement.",
            records,
        )
        self.assertIn(
            "Missing or mismatched binding remains unresolved",
            architecture,
        )
        self.assertIn("FND3-E08", records)

    def test_FND3_E09_project_profiles_and_task_requirements_stay_distinct(self):
        records = text(RECORDS)
        note = text(NOTE)
        self.assertIn(
            "Project-required Test profiles remain a separate obligation set",
            records,
        )
        self.assertIn(
            "Task requirement proof is:", note
        )
        self.assertIn(
            "equal `requirement_id` and P6 `profile_id` strings do not create an "
            "association",
            note,
        )
        self.assertIn("FND3-E09", records)

    def test_FND3_E10_manual_ci_external_evidence_uses_explicit_locator(self):
        records = text(RECORDS)
        constitution = text(CONSTITUTION)
        skills = text(SKILLS)
        self.assertIn(
            "HUMAN, CI, or EXTERNAL Evidence directly through its opaque locator",
            records,
        )
        self.assertIn(
            "Existing legitimate HUMAN, CI, or EXTERNAL P6 Evidence may satisfy",
            constitution,
        )
        self.assertIn(
            "without an automated profile binding",
            skills,
        )
        self.assertIn("FND3-E10", records)

    def test_FND3_R01_candidate_identity_is_not_publication_provenance(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        skills = text(SKILLS)
        lifecycles = text(LIFECYCLES)
        architecture = text(ARCHITECTURE)
        note = text(NOTE)
        contracts = " ".join(
            [
                constitution,
                records,
                skills,
                lifecycles,
                architecture,
            ]
        )

        # A. P6 candidate semantic projection is content-deterministic.
        self.assertIn("P6 `candidate_digest` is content-deterministic", records)
        self.assertIn("It MUST be content-deterministic", constitution)
        self.assertIn("content-deterministic from currently observed", architecture)
        self.assertIn("P6 `candidate_digest` is content-deterministic", note)

        # B. Neutrality is not conditioned on post-hoc writer/process knowledge.
        self.assertIn(
            "P6 MUST NOT condition that omission on unverifiable historical facts "
            "such as which process wrote the identical current bytes",
            records,
        )
        self.assertIn(
            "which process wrote identical current Task bytes",
            constitution,
        )
        self.assertIn(
            "not writer-path knowledge",
            lifecycles,
        )
        self.assertIn(
            "because of their content class, not writer provenance",
            architecture,
        )
        self.assertIn(
            "candidate neutrality is not conditioned on post-hoc "
            "writer/process knowledge",
            records,
        )

        # C. P3 CAS remains mandatory for authorized Task publication.
        self.assertIn(
            "§31 expected-revision atomic conditional publication remains "
            "mandatory for every authorized semantic Task mutation performed "
            "by Scaffold",
            records,
        )
        self.assertIn(
            "Authorized Scaffold publication of them still MUST use Task "
            "CAS",
            skills,
        )
        self.assertIn(
            "Authorized Scaffold Task mutation still requires P3 "
            "expected-revision CAS",
            architecture,
        )

        # D. candidate-equivalent != publication-authorized.
        self.assertIn(
            "candidate-equivalent != publication-authorized", constitution
        )
        self.assertIn(
            "candidate-equivalent != publication-authorized", records
        )
        self.assertIn(
            "candidate-equivalent != publication-authorized", skills
        )
        self.assertIn(
            "candidate-equivalent != publication-authorized", lifecycles
        )
        self.assertIn(
            "candidate-equivalent != publication-authorized", architecture
        )
        self.assertIn(
            "candidate-equivalent != publication-authorized", note
        )
        self.assertIn(
            "A direct/manual/non-CAS write is not converted into an authorized "
            "P7 publication merely because it changes only candidate-neutral "
            "fields",
            records,
        )

        # E. Complete physical Diff remains visible.
        self.assertIn(
            "The real workspace/SCM Diff MUST retain the complete Task Book "
            "byte change",
            constitution,
        )
        self.assertIn(
            "Git status/Diff and no-SCM physical inventory continue to observe "
            "the complete Task Book bytes",
            records,
        )
        self.assertIn("Complete physical Diff remains visible", records)

        # F. Substantive Task mutation remains candidate-changing.
        self.assertIn(
            "goal, acceptance, scope, baseline, Stage plan, requirement "
            "identity, or execution-binding change is candidate-changing",
            records,
        )
        self.assertIn(
            "Creating or removing a Task Book, or changing any projected fact "
            "above, changes the candidate",
            records,
        )

        self.assertIn("FND3-R01", records)
        self.assertIn("FND3-R01", note)

        # Forbidden representability claims must be absent from current
        # normative wording. These are specific contradictions, not a
        # generic search for the token "CAS".
        self.assertNotIn(
            "MAY be candidate-neutral only when the substantive Task "
            "authority projection is unchanged and the mutation is a legal "
            "P3 conditional publication",
            contracts,
        )
        self.assertNotIn(
            "Omission is legal only for a canonical lifecycle mutation whose "
            "before/after substantive Task authority projection is identical "
            "and whose transition is published through §31 expected-revision "
            "conditional publication",
            contracts,
        )
        self.assertNotIn(
            "candidate-neutral under P3 only when the substantive Task "
            "projection is unchanged and P7 publishes it through Task CAS",
            contracts,
        )
        self.assertNotIn(
            "An illegal, malformed, non-CAS, or substantively mixed Task "
            "mutation is not a neutral publication",
            contracts,
        )
        self.assertNotIn(
            "non-CAS identical control-plane bytes necessarily produce a "
            "different candidate",
            contracts,
        )
        self.assertNotIn(
            "candidate digest proves Task mutation authorization",
            contracts,
        )
        self.assertNotIn(
            "legal CAS-only lifecycle delta",
            contracts,
        )


if __name__ == "__main__":
    unittest.main()
