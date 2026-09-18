from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, init_git
from p7_support import (
    TASK_A,
    TASK_B,
    develop_engine,
    write_active_host,
    write_task,
)
from p8_support import (
    init_submit_git,
    run_submit,
    write_submit_host,
)
from support import REPO, write

from scaffold_p5.io_util import read_yaml
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.develop_authority import (
    authorize_mutation_paths,
    observe_authorized_mutation,
    record_pending_mutation,
    resolve_current_develop_authority,
)
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.session import MUTATION_OBSERVED, file_sha256, load_files_yaml
from scaffold_p5.schemas import CURRENT_PROJECT_CONTRACT_GENERATION
from scaffold_p7.unexplained import (
    CLASS_INHERITED_INIT,
    CLASS_UNEXPLAINED,
    PROJECT_YAML_REL,
    SCHEMA_VERSION,
    STATE_AUTHORITY_UNUSABLE,
    STATE_NEVER_INITIALIZED,
    STATE_VALID_INITIALIZED,
    UNEXPLAINED_REL,
    establish_compatibility_boundary,
    initialization_completed,
    inspect_drift_authority,
    reconcile_unexplained_drift,
    resolve_accepted_anchor,
    unexplained_matches_current,
    unexplained_path_map,
)
from scaffold_p8.cleanup import cleanup_sessions
from scaffold_p8.delta import classify_delta, load_sealed_sessions as load_p8_sealed_sessions


SRC = REPO / "src"
APP = "src/app.py"
OTHER = "src/other.py"
B_FILE = "src/b.py"


def _git_develop_host(
    host: Path,
    *,
    extra_files: dict[str, str] | None = None,
    generation: str | None = None,
) -> None:
    project: dict = {
        "ownership": {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
        "source_areas": ["src"],
    }
    if generation is not None:
        project["project_contract_generation"] = generation
    write_active_host(host, **project)
    write(host, APP, "value = 0\n")
    for rel, content in (extra_files or {}).items():
        write(host, rel, content)
    write_task(
        host,
        TASK_A,
        status="IN_PROGRESS",
        scope={"paths": ["src"], "modules": [], "exclude": []},
        stages=[
            {
                "stage_id": "stage-1",
                "goal": "Write the fixture source.",
                "acceptance": "src/app.py has the expected content.",
                "status": "IN_PROGRESS",
                "required_tests": [],
            }
        ],
    )
    init_git(host)


def _open(host: Path, task_id: str = TASK_A) -> str:
    opened = develop_engine(host).open_develop_session(task_id=task_id)
    if opened.outcome != "COMPLETED":
        raise AssertionError(opened.blockers)
    session_id = str((opened.extras or {}).get("session", {}).get("record_id") or "")
    if not session_id:
        raise AssertionError("open did not bind a Session")
    return session_id


def _abort(host: Path, task_id: str = TASK_A):
    result = develop_engine(host).abort_develop_execution(task_id=task_id)
    if result.outcome != "COMPLETED":
        raise AssertionError(result.blockers)
    return result


def _record_write(host: Path, rel: str, content: str, *, token: str) -> None:
    allowed, reason = authorize_mutation_paths(host, [rel])
    if not allowed:
        raise AssertionError(reason)
    record_pending_mutation(
        host, [rel], tool_name="Write", tool_use_id=token
    )
    write(host, rel, content)
    ok, detail = observe_authorized_mutation(
        host, [rel], tool_name="Write", tool_use_id=token
    )
    if not ok:
        raise AssertionError(detail)


def _row(host: Path, rel: str) -> dict:
    rows = unexplained_path_map(host)
    if rel not in rows:
        raise AssertionError(f"{rel} missing from {rows}")
    return rows[rel]


class R4Maj008UnexplainedDriftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_abort_cannot_launder_unexplained_drift(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = rogue\n")
        _abort(self.host)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        _open(self.host)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        self.assertTrue(unexplained_matches_current(self.host, APP))

    def test_02_new_session_cannot_absorb_prior_unexplained_drift(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = rogue\n")
        _abort(self.host)
        second = _open(self.host)
        session = read_yaml(self.host / SESSIONS_DIR / second / "session.yaml")
        overlay = session.get("workspace_overlay_s0") or {}
        self.assertEqual(overlay.get("coverage"), "complete")
        self.assertTrue(
            any(item.get("path") == APP for item in overlay.get("paths") or [])
        )
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        delta = classify_delta(
            self.host,
            real_paths=[APP],
            sessions=[
                {
                    "session": {
                        "workspace_overlay_s0": overlay,
                        "workspace_overlay_s1": overlay,
                    },
                    "files": [],
                }
            ],
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertEqual(delta["classes"][APP], "UNATTRIBUTED")
        self.assertNotEqual(delta["task_delta_classes"][APP], "inherited_baseline")

    def test_03_aborted_observed_success_remains_attribution(self):
        _git_develop_host(self.host, extra_files={OTHER: "other = 0\n"})
        first = _open(self.host)
        _record_write(self.host, APP, "value = 1\n", token="a1")
        _record_write(self.host, OTHER, "other = 1\n", token="b1")
        _abort(self.host)
        session = read_yaml(self.host / SESSIONS_DIR / first / "session.yaml")
        self.assertEqual(session["status"], "ABORTED")
        files, issues = load_files_yaml(self.host / SESSIONS_DIR / first)
        self.assertFalse(issues)
        states = {row["path"]: row.get("mutation_state") for row in files or []}
        self.assertEqual(states[APP], MUTATION_OBSERVED)
        self.assertEqual(states[OTHER], MUTATION_OBSERVED)
        _open(self.host)
        rows = unexplained_path_map(self.host)
        self.assertNotIn(APP, rows)
        self.assertNotIn(OTHER, rows)
        self.assertFalse(unexplained_matches_current(self.host, APP))

    def test_04_aborted_session_is_not_develop_known(self):
        _git_develop_host(self.host)
        first = _open(self.host)
        _record_write(self.host, APP, "value = 1\n", token="a1")
        _abort(self.host)
        sealed = load_p8_sealed_sessions(self.host)
        self.assertFalse(any(row["session"].get("record_id") == first for row in sealed))
        delta = classify_delta(
            self.host,
            real_paths=[APP],
            sessions=sealed,
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertNotEqual(delta["classes"].get(APP), "DEVELOP_KNOWN")

    def test_05_multi_task_attributed_work_is_not_rogue(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, APP, "value = 0\n")
        write(self.host, B_FILE, "b = 0\n")
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope={"paths": [APP], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write A.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        write_task(
            self.host,
            TASK_B,
            status="IN_PROGRESS",
            scope={"paths": [B_FILE], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write B.",
                    "acceptance": "src/b.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        init_git(self.host)
        _open(self.host, TASK_B)
        _record_write(self.host, B_FILE, "b = 1\n", token="b1")
        _abort(self.host, TASK_B)
        _open(self.host, TASK_A)
        self.assertNotIn(B_FILE, unexplained_path_map(self.host))
        authority = resolve_current_develop_authority(self.host)
        self.assertTrue(authority.ok, authority.reason)
        allowed, reason = authorize_mutation_paths(self.host, [B_FILE])
        self.assertTrue(allowed, reason)

    def test_06_external_no_hook_mutation_detected_at_next_boundary(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = external\n")
        _abort(self.host)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)

    def test_07_process_restart_preserves_durable_facts(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = external\n")
        _abort(self.host)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        script = (
            "from pathlib import Path\n"
            "from scaffold_p7.unexplained import unexplained_path_map\n"
            f"rows = unexplained_path_map(Path({str(self.host)!r}))\n"
            "print(rows['src/app.py']['classification'])\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), CLASS_UNEXPLAINED)

    def test_08_stale_provenance_cannot_explain_newer_bytes(self):
        _git_develop_host(self.host)
        _open(self.host)
        _record_write(self.host, APP, "value = 1\n", token="v1")
        write(self.host, APP, "value = 2\n")
        _abort(self.host)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        self.assertEqual(_row(self.host, APP)["digest"], file_sha256(self.host / APP))

    def test_09_return_to_anchor_retires_unexplained(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = rogue\n")
        _abort(self.host)
        self.assertIn(APP, unexplained_path_map(self.host))
        write(self.host, APP, "value = 0\n")
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result["ok"])
        self.assertNotIn(APP, unexplained_path_map(self.host))

    def test_10_current_byte_attribution_retires_unexplained(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = 1\n")
        _abort(self.host)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        _open(self.host)
        _record_write(self.host, APP, "value = 1\n", token="attr")
        reconcile_unexplained_drift(self.host, boundary="resume")
        self.assertNotIn(APP, unexplained_path_map(self.host))
        self.assertFalse(unexplained_matches_current(self.host, APP))

    def test_11_s10_anchor_advance_retires_unexplained(self):
        write_submit_host(self.host)
        write(self.host, APP, "value = 0\n")
        init_submit_git(self.host)
        first = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(first["ok"], first)
        write(self.host, APP, "value = 1\n")
        second = reconcile_unexplained_drift(self.host, boundary="submit_s2")
        self.assertTrue(second["ok"])
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue((result.extras or {}).get("s10_durable") or (result.extras or {}).get("s10", {}).get("durable"))
        self.assertNotIn(APP, unexplained_path_map(self.host))

    def test_12_one_time_existing_host_initialization(self):
        _legacy_git_host(self.host)
        write(self.host, APP, "value = historic\n")
        result = _migrate_to_current(self.host)
        self.assertTrue(result.get("established"), result)
        self.assertTrue(initialization_completed(self.host))
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_INHERITED_INIT)

    def test_13_initialization_cannot_recur_as_runtime_fallback(self):
        _legacy_git_host(self.host)
        write(self.host, APP, "value = historic\n")
        _migrate_to_current(self.host)
        write(self.host, OTHER, "other = new\n")
        later = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(later.get("initialized"))
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_INHERITED_INIT)
        self.assertEqual(_row(self.host, OTHER)["classification"], CLASS_UNEXPLAINED)
        write(self.host, APP, "value = later\n")
        changed = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(changed.get("initialized"))
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)

    def test_14_noscms_missing_anchor_fail_closed(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, APP, "value = 0\n")
        write_task(self.host)
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        anchor = resolve_accepted_anchor(self.host)
        self.assertFalse(anchor.get("ok"))
        self.assertEqual(anchor.get("observation_state"), "UNKNOWN")
        skipped = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(skipped.get("skipped"))
        self.assertEqual(unexplained_path_map(self.host), {})

    def test_14b_noscms_accepted_anchor_comes_from_publication_authority(self):
        write_submit_host(self.host, noscms_working_diff=False)
        first = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(first.get("ok"), first)
        self.assertTrue(initialization_completed(self.host))
        anchor = resolve_accepted_anchor(self.host)
        self.assertTrue(anchor.get("ok"), anchor)
        self.assertEqual(anchor.get("kind"), "none")
        write(self.host, APP, "value = drifted\n")
        result = reconcile_unexplained_drift(self.host, boundary="submit_s2")
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        self.assertEqual(_row(self.host, APP)["accepted_kind"], "none")

    def test_15_cleanup_cannot_erase_durable_drift(self):
        _git_develop_host(self.host)
        session_id = _open(self.host)
        write(self.host, APP, "value = rogue\n")
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        self.assertIn(APP, unexplained_path_map(self.host))
        session = read_yaml(self.host / SESSIONS_DIR / session_id / "session.yaml")
        session["status"] = "SEALED"
        from scaffold_p5.io_util import write_yaml_atomic

        write_yaml_atomic(
            self.host / SESSIONS_DIR / session_id / "session.yaml", session
        )
        cleanup = cleanup_sessions(
            self.host,
            task={
                "record_id": TASK_A,
                "develop_session_ids": [session_id],
            },
            s10_ok=True,
            target_session_ids=[session_id],
        )
        self.assertTrue(cleanup.get("ok"), cleanup)
        self.assertFalse((self.host / SESSIONS_DIR / session_id).is_dir())
        self.assertTrue((self.host / UNEXPLAINED_REL).is_file())
        self.assertTrue(initialization_completed(self.host))
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)

    def test_16_path_scoped_develop_continues_for_unrelated_authorized_path(self):
        _git_develop_host(self.host, extra_files={OTHER: "other = 0\n"})
        _open(self.host)
        write(self.host, OTHER, "other = rogue\n")
        allowed, reason = authorize_mutation_paths(self.host, [APP])
        self.assertTrue(allowed, reason)
        x_allowed, x_reason = authorize_mutation_paths(self.host, [OTHER])
        self.assertTrue(x_allowed, x_reason)
        _abort(self.host)
        self.assertEqual(_row(self.host, OTHER)["classification"], CLASS_UNEXPLAINED)
        self.assertNotIn(APP, unexplained_path_map(self.host))

    def test_17_known_drift_remains_visible_through_submit(self):
        _git_develop_host(self.host, extra_files={OTHER: "other = 0\n"})
        _open(self.host)
        write(self.host, APP, "value = rogue\n")
        _abort(self.host)
        _open(self.host)
        _record_write(self.host, OTHER, "other = 1\n", token="y1")
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        sessions = load_p8_sealed_sessions(self.host)
        self.assertTrue(sessions)
        delta = classify_delta(
            self.host,
            real_paths=[APP, OTHER],
            sessions=sessions,
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertEqual(delta["classes"][APP], "UNATTRIBUTED")
        self.assertNotEqual(delta["task_delta_classes"][APP], "inherited_baseline")
        self.assertTrue(unexplained_matches_current(self.host, APP))

    def test_18_submit_is_not_permanently_deadlocked_by_known_drift(self):
        write_submit_host(self.host)
        write(self.host, APP, "value = 0\n")
        init_submit_git(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        write(self.host, APP, "value = 1\n")
        reconcile_unexplained_drift(self.host, boundary="submit_s2")
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        extras = result.extras or {}
        self.assertNotEqual(
            (extras.get("delta") or {}).get("task_delta_classes", {}).get(APP),
            "inherited_baseline",
        )
        self.assertTrue(extras.get("s10_durable") or (extras.get("s10") or {}).get("durable"))
        self.assertNotIn(APP, unexplained_path_map(self.host))

    def test_19_support_artifact_excluded_from_candidate_identity(self):
        _git_develop_host(self.host)
        before = observe_candidate(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        write(self.host, APP, "value = rogue\n")
        after_bytes = observe_candidate(self.host)
        reconcile_unexplained_drift(self.host, boundary="abort")
        after_fact = observe_candidate(self.host)
        self.assertNotEqual(before.digest, after_bytes.digest)
        self.assertEqual(after_bytes.digest, after_fact.digest)
        self.assertTrue((self.host / UNEXPLAINED_REL).is_file())

    def test_20_existing_commands_remain_sufficient(self):
        _git_develop_host(self.host)
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        reopened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(reopened.outcome, "COMPLETED", reopened.blockers)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)

    def test_21_out_of_scope_drift_does_not_block_in_scope_edit(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, "lib/secret.py", "nope\n")
        allowed, reason = authorize_mutation_paths(self.host, [APP])
        self.assertTrue(allowed, reason)
        discovered, discovered_reason = authorize_mutation_paths(
            self.host, ["lib/secret.py"]
        )
        self.assertTrue(discovered, discovered_reason)


class R4Maj008FocusedCorrectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _corrupt_payload(self, text: str) -> bytes:
        path = self.host / UNEXPLAINED_REL
        raw = text.encode("utf-8")
        path.write_bytes(raw)
        return raw

    def test_c1_current_generation_host_is_already_post_boundary(self):
        _git_develop_host(self.host)
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_VALID_INITIALIZED
        )
        self.assertTrue(initialization_completed(self.host))
        self.assertEqual(unexplained_path_map(self.host), {})
        first = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(first.get("ok"), first)
        self.assertFalse(first.get("initialized"))
        second = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(second.get("initialized"))

    def test_c2_zero_path_initialized_host_survives_restart(self):
        _git_develop_host(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        self.assertEqual(unexplained_path_map(self.host), {})
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        script = (
            "from pathlib import Path\n"
            "from scaffold_p7.unexplained import inspect_drift_authority, initialization_completed\n"
            f"host = Path({str(self.host)!r})\n"
            "print(inspect_drift_authority(host)['state'])\n"
            "print(initialization_completed(host))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(lines[0], STATE_VALID_INITIALIZED)
        self.assertEqual(lines[1], "True")

    def test_c3_malformed_payload_fails_closed_without_reinit(self):
        _git_develop_host(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        write(self.host, APP, "value = rogue\n")
        reconcile_unexplained_drift(self.host, boundary="abort")
        raw = self._corrupt_payload("this is not yaml: [[[")
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(result.get("ok"))
        self.assertFalse(result.get("initialized"))
        self.assertTrue(result.get("unusable"))
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        self.assertEqual((self.host / UNEXPLAINED_REL).read_bytes(), raw)
        self.assertNotEqual(
            unexplained_path_map(self.host).get(APP, {}).get("classification"),
            CLASS_INHERITED_INIT,
        )

    def test_c4_foreign_record_type_fails_closed(self):
        _git_develop_host(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        from scaffold_p5.io_util import write_yaml_atomic

        write_yaml_atomic(
            self.host / UNEXPLAINED_REL,
            {"record_type": "task_book", "schema_version": "1", "paths": []},
        )
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("unusable"))
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        self.assertFalse(result.get("initialized"))

    def test_c5_missing_payload_after_init_fails_closed(self):
        _git_develop_host(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        write(self.host, APP, "value = rogue\n")
        reconcile_unexplained_drift(self.host, boundary="abort")
        (self.host / UNEXPLAINED_REL).unlink()
        self.assertTrue(initialization_completed(self.host))
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("unusable"))
        self.assertFalse(result.get("initialized"))
        self.assertFalse((self.host / UNEXPLAINED_REL).is_file())
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )

    def test_c6_malformed_cannot_become_inherited_or_preexisting(self):
        _git_develop_host(self.host)
        _open(self.host)
        write(self.host, APP, "value = rogue\n")
        _abort(self.host)
        overlay = {
            "coverage": "complete",
            "paths": [
                {
                    "path": APP,
                    "kind": "regular_file",
                    "digest": file_sha256(self.host / APP),
                }
            ],
        }
        raw = self._corrupt_payload("{not: [yaml")
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        delta = classify_delta(
            self.host,
            real_paths=[APP],
            sessions=[
                {
                    "session": {
                        "workspace_overlay_s0": overlay,
                        "workspace_overlay_s1": overlay,
                    },
                    "files": [],
                }
            ],
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertNotEqual(delta["classes"][APP], "PREEXISTING_CHANGE")
        self.assertNotEqual(delta["task_delta_classes"][APP], "inherited_baseline")
        self.assertEqual((self.host / UNEXPLAINED_REL).read_bytes(), raw)
        self.assertNotEqual(
            unexplained_path_map(self.host).get(APP, {}).get("classification"),
            CLASS_INHERITED_INIT,
        )

    def test_c7_abort_while_unusable_then_mutation_denied(self):
        _git_develop_host(self.host)
        _open(self.host)
        raw = self._corrupt_payload("{{{{")
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        self.assertEqual((self.host / UNEXPLAINED_REL).read_bytes(), raw)
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        allowed, reason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(allowed)
        self.assertTrue(reason)
        self.assertEqual((self.host / UNEXPLAINED_REL).read_bytes(), raw)

    def test_m1_unknown_anchor_denies_clean_and_drifted_mutation(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, APP, "value = 0\n")
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope={"paths": ["src"], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        self.assertFalse(resolve_accepted_anchor(self.host).get("ok"))
        allowed, _reason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(allowed)
        write(self.host, OTHER, "other = 1\n")
        drifted, _dreason = authorize_mutation_paths(self.host, [OTHER])
        self.assertFalse(drifted)
        unrelated, _ureason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(unrelated)
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "BLOCKED", sealed.blockers)
        from p8_support import run_submit

        submitted = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(submitted.outcome, "BLOCKED", submitted.blockers)

    def test_m1_valid_noscms_anchor_restores_mutation(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, APP, "value = 0\n")
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope={"paths": ["src"], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        _open(self.host)
        denied, _reason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(denied)
        _abort(self.host)
        from scaffold_p8.noscms import initialize_noscms_baseline

        initialized = initialize_noscms_baseline(self.host)
        self.assertTrue(initialized.get("ok"), initialized)
        _open(self.host)
        allowed, reason = authorize_mutation_paths(self.host, [APP])
        self.assertTrue(allowed, reason)

    def test_m1_unusable_denies_mutation_when_anchor_known(self):
        _git_develop_host(self.host)
        _open(self.host)
        self._corrupt_payload("not-yaml")
        allowed, _reason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(allowed)
        self.assertTrue(resolve_accepted_anchor(self.host).get("ok"))

    def test_n1_task_book_write_is_not_unexplained(self):
        _git_develop_host(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            record_revision=2,
            scope={"paths": ["src"], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        reconcile_unexplained_drift(self.host, boundary="open")
        rows = unexplained_path_map(self.host)
        self.assertFalse(any(path.startswith(".scaffold/tasks/") for path in rows))
        write(self.host, APP, "value = rogue\n")
        reconcile_unexplained_drift(self.host, boundary="abort")
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)

    def test_n1_ext_test_evidence_is_not_broadly_hidden(self):
        _git_develop_host(self.host)
        reconcile_unexplained_drift(self.host, boundary="open")
        write(self.host, ".scaffold/ext/test/evidence/run.log", "evidence\n")
        reconcile_unexplained_drift(self.host, boundary="open")
        self.assertIn(".scaffold/ext/test/evidence/run.log", unexplained_path_map(self.host))

    def test_n2_fixture_gitignore_does_not_ignore_develop_ext(self):
        from p6_support import init_git as init_git_fn
        import inspect

        source = inspect.getsource(init_git_fn)
        self.assertNotIn(".scaffold/ext/develop/", source)

    def test_n2_unignored_host_excludes_support_from_diff_candidate_and_s10(self):
        from p6_support import git
        from scaffold_p8.delta import observe_real_diff

        write_submit_host(self.host)
        write(self.host, APP, "value = 0\n")
        init_submit_git(self.host)
        self.assertNotIn(
            ".scaffold/ext/develop/",
            (self.host / ".gitignore").read_text(encoding="utf-8"),
        )
        write(self.host, APP, "value = 1\n")
        before = observe_candidate(self.host)
        reconcile_unexplained_drift(self.host, boundary="submit_s2")
        porcelain = git(self.host, "status", "--porcelain").replace("\\", "/")
        self.assertIn(".scaffold/ext/develop", porcelain)
        diff = observe_real_diff(self.host)
        self.assertTrue(diff.get("ok"), diff)
        self.assertIn(APP, diff.get("paths") or [])
        self.assertNotIn(UNEXPLAINED_REL, diff.get("paths") or [])
        after = observe_candidate(self.host)
        self.assertEqual(before.digest, after.digest)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        names = git(self.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        self.assertNotIn(UNEXPLAINED_REL, names)
        self.assertNotIn(".scaffold/ext/develop/", names)


def _remove_develop_support(host: Path) -> None:
    folder = host / ".scaffold/ext/develop"
    if folder.exists():
        shutil.rmtree(folder)


def _restart_inspect(host: Path) -> list[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    script = (
        "from pathlib import Path\n"
        "from scaffold_p7.unexplained import inspect_drift_authority, "
        "initialization_completed, reconcile_unexplained_drift\n"
        f"host = Path({str(host)!r})\n"
        "print(inspect_drift_authority(host)['state'])\n"
        "print(initialization_completed(host))\n"
        "result = reconcile_unexplained_drift(host, boundary='open')\n"
        "print(bool(result.get('initialized')))\n"
        "print(inspect_drift_authority(host)['state'])\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _set_generation(host: Path, generation: str) -> None:
    from scaffold_p5.io_util import write_yaml_atomic

    project = read_yaml(host / PROJECT_YAML_REL)
    project["project_contract_generation"] = generation
    write_yaml_atomic(host / PROJECT_YAML_REL, project)


def _legacy_git_host(host: Path, *, extra_files: dict[str, str] | None = None) -> None:
    """Established legacy host whose tracked project.yaml predates the boundary.

    The Git baseline is committed while the host is still generation 1, so
    project.yaml is tracked and the later support payload is not. That is the
    real shape a bare `git clean -fd` has to be tested against.
    """
    _git_develop_host(host, extra_files=extra_files, generation="1")


def _migrate_to_current(host: Path) -> dict:
    """Stand in for the approved bounded migration's durable generation advance."""
    from scaffold_p5.migration import consume_compatibility_boundary

    _set_generation(host, CURRENT_PROJECT_CONTRACT_GENERATION)
    return consume_compatibility_boundary(host, classify_inherited=True)


class R4Maj008DurableBoundaryTests(unittest.TestCase):
    """The boundary is tracked project authority, not a disposable support file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_legacy_host_is_never_initialized_and_develop_cannot_consume(self):
        _legacy_git_host(self.host)
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_NEVER_INITIALIZED
        )
        self.assertFalse(initialization_completed(self.host))
        first = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertFalse(first.get("initialized"))
        self.assertTrue(first.get("skipped"))
        self.assertFalse((self.host / UNEXPLAINED_REL).is_file())
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_NEVER_INITIALIZED
        )

    def test_b_migration_consumes_the_boundary_exactly_once(self):
        _legacy_git_host(self.host)
        write(self.host, APP, "value = pre-upgrade\n")
        consumed = _migrate_to_current(self.host)
        self.assertTrue(consumed.get("ok"), consumed)
        self.assertTrue(consumed.get("established"))
        self.assertTrue(initialization_completed(self.host))
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_VALID_INITIALIZED
        )
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_INHERITED_INIT)
        again = establish_compatibility_boundary(self.host, classify_inherited=True)
        self.assertTrue(again.get("ok"), again)
        self.assertFalse(again.get("established"))

    def test_c_payload_loss_after_boundary_is_unusable(self):
        _legacy_git_host(self.host)
        _migrate_to_current(self.host)
        (self.host / UNEXPLAINED_REL).unlink()
        self.assertTrue(initialization_completed(self.host))
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("unusable"))
        self.assertFalse(result.get("initialized"))
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )

    def test_d_whole_ext_loss_is_unusable_not_never_initialized(self):
        _legacy_git_host(self.host)
        _migrate_to_current(self.host)
        shutil.rmtree(self.host / ".scaffold/ext")
        self.assertFalse((self.host / ".scaffold/ext").exists())
        self.assertTrue(initialization_completed(self.host))
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("unusable"))
        self.assertFalse((self.host / UNEXPLAINED_REL).is_file())

    def test_e_bare_git_clean_fd_without_pathspec_cannot_reissue_amnesty(self):
        """The mandatory regression: real bare cleanup, no protective pathspec."""
        from p6_support import git

        _legacy_git_host(self.host)
        _migrate_to_current(self.host)
        write(self.host, APP, "value = post-boundary\n")
        reconcile_unexplained_drift(self.host, boundary="abort")
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)

        dry_run = git(self.host, "clean", "-nd").replace("\\", "/")
        self.assertIn(".scaffold/ext", dry_run)
        git(self.host, "clean", "-fd")

        self.assertFalse((self.host / ".scaffold/ext").exists())
        self.assertTrue((self.host / PROJECT_YAML_REL).is_file())
        self.assertEqual(
            read_yaml(self.host / PROJECT_YAML_REL)["project_contract_generation"],
            CURRENT_PROJECT_CONTRACT_GENERATION,
        )
        self.assertTrue(initialization_completed(self.host))
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("unusable"))
        self.assertFalse(result.get("initialized"))
        allowed, _reason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(allowed)
        self.assertNotEqual(
            unexplained_path_map(self.host).get(APP, {}).get("classification"),
            CLASS_INHERITED_INIT,
        )

    def test_f_restart_after_bare_clean_never_returns_never_initialized(self):
        from p6_support import git

        _legacy_git_host(self.host)
        _migrate_to_current(self.host)
        git(self.host, "clean", "-fd")
        lines = _restart_inspect(self.host)
        self.assertEqual(lines[0], STATE_AUTHORITY_UNUSABLE)
        self.assertEqual(lines[1], "True")
        self.assertEqual(lines[2], "False")
        self.assertEqual(lines[3], STATE_AUTHORITY_UNUSABLE)
        self.assertNotIn(STATE_NEVER_INITIALIZED, lines)

    def test_g_original_laundering_chain_after_bare_clean(self):
        """W0 → S1 → W1 → abort → bare clean → restart → S2 stays fail-closed."""
        from p6_support import git

        _legacy_git_host(self.host)
        _migrate_to_current(self.host)
        _open(self.host)
        write(self.host, APP, "value = rogue\n")
        _abort(self.host)
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        overlay = {
            "coverage": "complete",
            "paths": [
                {
                    "path": APP,
                    "kind": "regular_file",
                    "digest": file_sha256(self.host / APP),
                }
            ],
        }
        git(self.host, "clean", "-fd")
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        self.assertFalse((self.host / UNEXPLAINED_REL).is_file())
        delta = classify_delta(
            self.host,
            real_paths=[APP],
            sessions=[
                {
                    "session": {
                        "workspace_overlay_s0": overlay,
                        "workspace_overlay_s1": overlay,
                    },
                    "files": [],
                }
            ],
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertNotEqual(delta["classes"][APP], "PREEXISTING_CHANGE")
        self.assertNotEqual(delta["task_delta_classes"][APP], "inherited_baseline")
        self.assertNotEqual(
            unexplained_path_map(self.host).get(APP, {}).get("classification"),
            CLASS_INHERITED_INIT,
        )

    def test_h_abort_succeeds_under_authority_loss(self):
        _git_develop_host(self.host)
        _open(self.host)
        _remove_develop_support(self.host)
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )

    def test_i_ordinary_mutation_denied_under_authority_loss(self):
        _git_develop_host(self.host)
        _open(self.host)
        _remove_develop_support(self.host)
        allowed, reason = authorize_mutation_paths(self.host, [APP])
        self.assertFalse(allowed)
        self.assertTrue(reason)

    def test_j_submit_fail_closed_under_authority_loss(self):
        write_submit_host(self.host)
        write(self.host, APP, "value = 0\n")
        init_submit_git(self.host)
        write(self.host, APP, "value = 1\n")
        reconcile_unexplained_drift(self.host, boundary="abort")
        _remove_develop_support(self.host)
        submitted = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(submitted.outcome, "BLOCKED", submitted.blockers)
        self.assertEqual((submitted.extras or {}).get("stage"), "S2")
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )

    def test_k_fresh_current_generation_host_never_receives_amnesty(self):
        _git_develop_host(self.host)
        self.assertEqual(
            read_yaml(self.host / PROJECT_YAML_REL)["project_contract_generation"],
            CURRENT_PROJECT_CONTRACT_GENERATION,
        )
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_VALID_INITIALIZED
        )
        self.assertEqual(unexplained_path_map(self.host), {})
        write(self.host, APP, "value = rogue\n")
        reconcile_unexplained_drift(self.host, boundary="open")
        self.assertEqual(_row(self.host, APP)["classification"], CLASS_UNEXPLAINED)
        self.assertNotEqual(
            _row(self.host, APP)["classification"], CLASS_INHERITED_INIT
        )

    def test_l_legacy_generation_carrying_a_payload_is_unusable(self):
        _git_develop_host(self.host)
        self.assertTrue((self.host / UNEXPLAINED_REL).is_file())
        _set_generation(self.host, "1")
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("unusable"))

    def test_m_unreadable_project_authority_is_unusable_not_never_initialized(self):
        _git_develop_host(self.host)
        (self.host / PROJECT_YAML_REL).unlink()
        state = inspect_drift_authority(self.host)
        self.assertEqual(state["state"], STATE_AUTHORITY_UNUSABLE)
        self.assertFalse(initialization_completed(self.host))
        (self.host / PROJECT_YAML_REL).write_text(": not yaml\n", encoding="utf-8")
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_AUTHORITY_UNUSABLE
        )

    def test_n_boundary_cannot_be_established_before_the_generation_advances(self):
        _legacy_git_host(self.host)
        refused = establish_compatibility_boundary(self.host, classify_inherited=True)
        self.assertFalse(refused.get("ok"))
        self.assertFalse(refused.get("established"))
        self.assertFalse((self.host / UNEXPLAINED_REL).is_file())
        self.assertEqual(
            inspect_drift_authority(self.host)["state"], STATE_NEVER_INITIALIZED
        )


class R4Maj008BoundaryCandidateBindingTests(unittest.TestCase):
    """project.yaml stays candidate-significant but out of product drift."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_generation_advance_changes_candidate_identity(self):
        _legacy_git_host(self.host)
        before = observe_candidate(self.host)
        _migrate_to_current(self.host)
        after = observe_candidate(self.host)
        self.assertTrue(before.digest)
        self.assertTrue(after.digest)
        self.assertNotEqual(before.digest, after.digest)

    def test_stale_pre_migration_binding_cannot_authorize_a_second_apply(self):
        from scaffold_p6.candidate import report_usable_for

        _legacy_git_host(self.host)
        stale = observe_candidate(self.host)
        _migrate_to_current(self.host)
        current = observe_candidate(self.host)
        stale_report = {"candidate": {"candidate_digest": stale.digest}}
        self.assertFalse(report_usable_for(stale_report, current))
        second = establish_compatibility_boundary(self.host, classify_inherited=True)
        self.assertTrue(second.get("ok"), second)
        self.assertFalse(second.get("established"))

    def test_project_yaml_is_candidate_significant_but_not_product_drift(self):
        from scaffold_p6.candidate import excluded_from_candidate

        _git_develop_host(self.host)
        self.assertFalse(
            excluded_from_candidate(PROJECT_YAML_REL, [], tracked=True),
            "project.yaml must remain candidate-significant",
        )
        before = observe_candidate(self.host)
        _set_generation(self.host, "3")
        after = observe_candidate(self.host)
        self.assertNotEqual(before.digest, after.digest)
        anchor = resolve_accepted_anchor(self.host)
        self.assertTrue(anchor.get("ok"), anchor)
        from scaffold_p7.unexplained import accepted_physical_diffs

        drifted = [row["path"] for row in accepted_physical_diffs(self.host, anchor)]
        self.assertNotIn(
            PROJECT_YAML_REL,
            drifted,
            "project.yaml must stay excluded from unexplained product drift",
        )
