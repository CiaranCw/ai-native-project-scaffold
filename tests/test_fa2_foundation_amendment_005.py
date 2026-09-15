from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "docs/contracts/CONSTITUTION.md"
RECORDS = ROOT / "docs/contracts/RECORDS_CONTRACT.md"
PROJECT = ROOT / "docs/contracts/PROJECT_CONTRACT.md"
LIFECYCLES = ROOT / "docs/architecture/RECORD_LIFECYCLES.md"
NOTE = ROOT / "docs/implementation/FA2_FND_005_CROSS_SESSION_DEVELOP_AUTHORITY.md"
P7_NOTE = ROOT / "docs/implementation/P7_DEVELOP.md"
P8_NOTE = ROOT / "docs/implementation/P8_SUBMIT.md"


def text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class FA2FoundationAmendment005Tests(unittest.TestCase):
    def test_FND5_E01_abort_must_not_launder_unexplained_drift(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn("Abort MUST NOT launder unexplained drift", note)
        self.assertIn("Abort MUST NOT launder unexplained drift", records)
        self.assertIn(
            "ABORT does NOT mean current workspace bytes are accepted",
            constitution,
        )
        self.assertIn(
            "ABORT does NOT mean current workspace bytes are accepted",
            note,
        )
        self.assertIn(
            "ABORT does NOT mean current workspace bytes are accepted",
            p7,
        )
        self.assertIn(
            "abort and later Session overlays MUST NOT launder it into ordinary "
            "inherited baseline",
            constitution,
        )
        self.assertIn("FND5-E01", records)
        self.assertIn("FND5-E01", note)

    def test_FND5_E02_aborted_observed_success_is_attribution_not_develop_known(
        self,
    ):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        p8 = text(P8_NOTE)
        self.assertIn(
            "ABORTED `observed_success` may remain attribution but is not "
            "`DEVELOP_KNOWN`",
            note,
        )
        self.assertIn(
            "ABORTED `observed_success` may remain attribution but is not "
            "`DEVELOP_KNOWN`",
            p8,
        )
        self.assertIn(
            "`observed_success` provenance remains attribution after abort and "
            "is not `DEVELOP_KNOWN`",
            constitution,
        )
        self.assertIn(
            "`observed_success` provenance remains attribution after abort and "
            "is not `DEVELOP_KNOWN`",
            p7,
        )
        self.assertIn(
            "ABORTED sessions MUST NOT be used as DEVELOP_KNOWN evidence",
            records,
        )
        self.assertIn(
            "They MUST NOT become UNEXPLAINED merely because S1 was aborted",
            note,
        )
        self.assertIn("FND5-E02", records)
        self.assertIn("FND5-E02", note)

    def test_FND5_E03_session_open_snapshot_is_observation_not_acceptance(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn(
            "The Session open snapshot is physical starting observation, not "
            "acceptance",
            note,
        )
        self.assertIn(
            "The Session open snapshot is physical starting observation, not "
            "acceptance",
            p7,
        )
        self.assertIn(
            "Session-S0 / open-inventory are physical starting observation, not "
            "acceptance",
            records,
        )
        self.assertIn("MUST NOT mint a new accepted anchor", note)
        self.assertIn("MUST NOT mint a new accepted anchor", records)
        self.assertIn("MUST NOT mint a new accepted anchor", p7)
        self.assertIn("FND5-E03", records)
        self.assertIn("FND5-E03", note)

    def test_FND5_E04_multi_task_physical_truth_is_host_level(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn("host/workspace-level, Task-agnostic", note)
        self.assertIn("host/workspace-level, Task-agnostic", p7)
        self.assertIn(
            "MUST NOT introduce per-Task full-workspace accepted baselines",
            note,
        )
        self.assertIn(
            "MUST NOT introduce per-Task full-workspace accepted baselines",
            records,
        )
        self.assertIn(
            "MUST NOT introduce per-Task full-workspace accepted baselines",
            p7,
        )
        self.assertIn(
            "MUST NOT become Task A rogue drift merely because Task A did not "
            "produce it",
            note,
        )
        self.assertIn("FND5-E04", records)
        self.assertIn("FND5-E04", note)

    def test_FND5_E05_unexplained_cannot_become_inherited_baseline_via_overlays(
        self,
    ):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        lifecycles = text(LIFECYCLES)
        note = text(NOTE)
        p8 = text(P8_NOTE)
        self.assertIn(
            "MUST NOT become `inherited_baseline` merely because",
            note,
        )
        self.assertIn(
            "MUST NOT become `inherited_baseline` merely because",
            records,
        )
        self.assertIn(
            "MUST NOT become `inherited_baseline` merely because",
            p8,
        )
        self.assertIn(
            "MUST NOT become inherited_baseline merely because the earlier Session "
            "was aborted or cleaned up",
            lifecycles,
        )
        self.assertIn(
            "`PREEXISTING_CHANGE` / `inherited_baseline` MUST NOT be inferred "
            "from later Session overlays when a durable unexplained-drift fact "
            "contradicts that inference",
            constitution,
        )
        self.assertIn("physical Diff authority", note)
        self.assertIn("They NEVER replace actual physical Diff", p8)
        self.assertIn("FND5-E05", records)
        self.assertIn("FND5-E05", note)

    def test_FND5_E06_normal_cleanup_must_not_erase_durable_unexplained_truth(
        self,
    ):
        records = text(RECORDS)
        lifecycles = text(LIFECYCLES)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        p8 = text(P8_NOTE)
        self.assertIn(
            "MUST NOT depend indefinitely on walking the full historical Session "
            "directory chain",
            note,
        )
        self.assertIn(
            "MUST NOT depend indefinitely on walking the full historical Session "
            "directory chain",
            p7,
        )
        self.assertIn(
            "Normal cleanup MUST NOT erase durable unexplained truth",
            note,
        )
        self.assertIn(
            "MUST NOT erase durable unexplained truth living outside ephemeral "
            "Session runtime",
            records,
        )
        self.assertIn(
            "MUST NOT erase durable unexplained truth living outside ephemeral "
            "Session runtime",
            lifecycles,
        )
        self.assertIn(
            "S12 / normal Session cleanup MUST NOT erase "
            "`.scaffold/ext/develop/unexplained.yaml`",
            p8,
        )
        self.assertIn("FND5-E06", records)
        self.assertIn("FND5-E06", note)

    def test_FND5_E07_no_new_normal_path_agent_ceremony(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn("MUST NOT require a longer abort/reopen ritual", note)
        self.assertIn("MUST NOT require a longer abort/reopen ritual", p7)
        self.assertIn(
            "No new normal-path Agent command, flag, or abort/reopen ritual is "
            "introduced",
            note,
        )
        self.assertIn(
            "No new normal-path Agent command, flag, or abort/reopen ritual is "
            "introduced",
            p7,
        )
        self.assertIn("implementation strategy is not constrained", note)
        self.assertIn("source exploration order is not constrained", note)
        self.assertIn(
            "Implementation strategy and source exploration order are not "
            "constrained",
            p7,
        )
        self.assertIn("FND5-E07", records)
        self.assertIn("FND5-E07", note)

    def test_FND5_E08_generic_human_clear_accept_is_forbidden(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        p8 = text(P8_NOTE)
        self.assertIn(
            "Generic human clear of unexplained bytes is forbidden", note
        )
        self.assertIn(
            "Generic human clear of unexplained bytes is forbidden", records
        )
        self.assertIn(
            "Generic human clear of unexplained bytes is forbidden", p7
        )
        self.assertIn(
            "Generic human clear of unexplained bytes is forbidden", p8
        )
        self.assertIn(
            'generic “human clear = accept bytes” operation',
            note,
        )
        self.assertIn("OUT OF SCOPE for FA2-FND-005", note)
        self.assertIn("FND5-E08", records)
        self.assertIn("FND5-E08", note)

    def test_FND5_E09_s10_remains_existing_acceptance_boundary(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        p8 = text(P8_NOTE)
        self.assertIn("S10 remains the existing acceptance boundary", note)
        self.assertIn("S10 remains the existing acceptance boundary", records)
        self.assertIn("S10 remains the existing acceptance boundary", p7)
        self.assertIn("S10 remains the existing acceptance boundary", p8)
        self.assertIn("Session seal is NOT acceptance", note)
        self.assertIn("Session seal is not acceptance", constitution)
        self.assertIn("Do NOT introduce a second hidden acceptance path", note)
        self.assertIn("FND5-E09", records)
        self.assertIn("FND5-E09", note)

    def test_FND5_E10_path_scoped_develop_does_not_hide_submit_drift(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn("path-scoped Develop permissiveness", note)
        self.assertIn("Path-scoped Develop permissiveness", p7)
        self.assertIn(
            "does NOT mean Submit may ignore known unexplained drift",
            note,
        )
        self.assertIn(
            "does NOT mean Submit may ignore known unexplained drift",
            p7,
        )
        self.assertIn("FND5-E10", records)
        self.assertIn("FND5-E10", note)

    def test_FND5_E11_imperfect_client_coverage_still_preserves_physical_fact(
        self,
    ):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn(
            "MUST NOT assume perfect pre-write interception", note
        )
        self.assertIn(
            "later Scaffold observation MUST still detect and preserve that "
            "physical fact",
            note,
        )
        self.assertIn(
            "MAJ-008 correctness MUST NOT depend on solving MAJ-007",
            note,
        )
        self.assertIn("MAJ-008 MUST NOT depend on solving MAJ-007", p7)
        self.assertIn("MAJ-008 MUST NOT depend on solving MAJ-007", records)
        self.assertIn("FND5-E11", records)
        self.assertIn("FND5-E11", note)

    def test_FND5_E12_noscm_unknown_and_existing_host_initialization(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn("Do NOT fabricate an anchor", note)
        self.assertIn("Do NOT fabricate an anchor", records)
        self.assertIn("Do NOT fabricate an anchor", p7)
        self.assertIn("pre-upgrade physical divergence", note)
        self.assertIn("pre-upgrade physical divergence", p7)
        self.assertIn("inherited-at-initialization", note)
        self.assertIn("inherited-at-initialization", records)
        self.assertIn("inherited-at-initialization", p7)
        self.assertIn("one-time compatibility initialization", note)
        self.assertIn("one-time compatibility initialization", records)
        self.assertIn("one-time compatibility initialization", p7)
        self.assertIn("durable initialization boundary", note)
        self.assertIn("durable initialization boundary", records)
        self.assertIn("durable initialization boundary", p7)
        self.assertIn(
            "MUST NOT fall back to inherited-at-initialization", note
        )
        self.assertIn(
            "MUST NOT fall back to inherited-at-initialization", records
        )
        self.assertIn(
            "MUST NOT fall back to inherited-at-initialization", p7
        )
        self.assertIn(
            "MUST NOT be downgraded to inherited-at-initialization", note
        )
        self.assertIn(
            "MUST NOT be downgraded to inherited-at-initialization", records
        )
        self.assertIn(
            "MUST NOT be downgraded to inherited-at-initialization", p7
        )
        self.assertIn("Do NOT fabricate historical certainty", note)
        self.assertIn("FND5-E12", records)
        self.assertIn("FND5-E12", note)

    def test_FND5_support_artifact_is_not_a_fourth_canonical_record(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn(".scaffold/ext/develop/unexplained.yaml", note)
        self.assertIn(".scaffold/ext/develop/unexplained.yaml", records)
        self.assertIn(".scaffold/ext/develop/unexplained.yaml", p7)
        self.assertIn("not a fourth canonical development record", note)
        self.assertIn("not a fourth canonical development record", records)
        self.assertIn("not a fourth canonical development record", constitution)
        self.assertIn("not a fourth canonical development record", p7)
        self.assertIn("MINIMUM NECESSARY CONSTRAINT", note)
        self.assertIn("MAXIMUM MODEL AUTONOMY", note)
        self.assertIn("42. Cross-session unexplained drift (FA2-FND-005)", records)
        self.assertIn(
            "later overlays cannot mint `inherited_baseline` against a durable "
            "unexplained fact",
            records,
        )
        self.assertIn(
            "Records Contract §§15, 16, 19.3, 20, 39, 40, and 42",
            note,
        )
        self.assertNotIn(
            "Records Contract §§14–16, 39, 40, and 42",
            note,
        )
        self.assertIn(
            "FA2-FND-005 places host-level unexplained-drift support under "
            "`.scaffold/ext/develop/`",
            text(PROJECT),
        )

    def test_FND5_drift_retirement_is_limited_to_three_safe_cases(self):
        records = text(RECORDS)
        note = text(NOTE)
        p7 = text(P7_NOTE)
        self.assertIn(
            "Path returns to accepted anchor",
            note,
        )
        self.assertIn(
            "Trustworthy attribution becomes available",
            note,
        )
        self.assertIn(
            "Accepted anchor advances through successful S10",
            note,
        )
        self.assertIn("attributed-but-unaccepted", note)
        self.assertIn("FND5-E13", records)
        self.assertIn(
            "current physical state / current bytes of that path are proven "
            "consistent with the durable trustworthy mutation provenance being "
            "used",
            note,
        )
        self.assertIn(
            "current physical state / current bytes of that path are proven "
            "consistent with the durable trustworthy mutation provenance being "
            "used",
            records,
        )
        self.assertIn(
            "current physical state / current bytes of that path are proven "
            "consistent with the durable trustworthy mutation provenance being "
            "used",
            p7,
        )
        self.assertIn(
            "Historical provenance for a different byte/digest state MUST NOT "
            "clear a newer unexplained mutation",
            note,
        )
        self.assertIn(
            "Historical provenance for a different byte/digest state MUST NOT "
            "clear a newer unexplained mutation",
            records,
        )
        self.assertIn(
            "Historical provenance for a different byte/digest state MUST NOT "
            "clear a newer unexplained mutation",
            p7,
        )
        self.assertNotIn(
            "trustworthy attribution becomes available (attributed-but-unaccepted, "
            "not accepted), or successful S10 advances the accepted anchor",
            records,
        )
        self.assertNotIn("human clears drift and thereby accepts current bytes", note)

    def test_FND5_does_not_claim_runtime_implementation_or_closed_fa2(self):
        note = text(NOTE)
        self.assertIn(
            "does not implement runtime behavior",
            note,
        )
        self.assertIn(
            "does not claim FA-2 PASS or FA-2 CLOSED",
            note,
        )
        self.assertIn("Status: candidate Foundation amendment", note)


if __name__ == "__main__":
    unittest.main()
