from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP
from p7_support import TASK_A, develop_engine, write_active_host, write_task
from support import write
from test_pc_consumer_003 import _install_marker, _knowledge
from test_pc_r3_final_blockers import (
    VAULT_EVIDENCE,
    VAULT_PRODUCT,
    VAULT_TEST,
    _session_dir,
)
from test_task_supporting_delta import VAULT_SCOPE

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import read_yaml
from scaffold_p7.develop_authority import (
    EXECUTION_POINTER_REL,
    observe_authorized_mutation,
    record_pending_mutation,
)
from scaffold_p7.session import (
    MUTATION_ATTEMPTS_NAME,
    MUTATION_OBSERVED,
    MUTATION_PENDING,
    load_files_yaml,
    load_mutation_attempts,
)


# Observed Cursor tool_use_id shape: two physical tokens joined by a real newline.
NEWLINE_TOOL_USE_ID = "call-example-95\nfc_example_0"
NEWLINE_TOOL_USE_ID_B = "call-example-96\nfc_example_1"
CR_TOOL_USE_ID = "call-example-95\rfc_example_0"


class R4Crit004YamlLiteRoundTripTests(unittest.TestCase):
    def test_fixture_uses_a_real_newline_not_backslash_n(self):
        self.assertIn("\n", NEWLINE_TOOL_USE_ID)
        self.assertEqual(NEWLINE_TOOL_USE_ID, "call-example-95" + chr(10) + "fc_example_0")
        self.assertNotEqual(NEWLINE_TOOL_USE_ID, r"call-example-95\nfc_example_0")

    def test_ordinary_scalar_round_trip(self):
        sample = {"name": "vault", "count": 2, "flag": True, "missing": None}
        self.assertEqual(yaml_lite.load(yaml_lite.dump(sample)), sample)

    def test_quote_and_backslash_round_trip(self):
        value = 'he said "hi" \\ already'
        loaded = yaml_lite.load(yaml_lite.dump({"s": value}))
        self.assertEqual(loaded["s"], value)

    def test_literal_backslash_n_is_not_converted_into_a_newline(self):
        value = "call-example-95" + "\\" + "n" + "fc_example_0"
        loaded = yaml_lite.load(yaml_lite.dump({"tool_use_id": value}))
        self.assertEqual(loaded["tool_use_id"], value)
        self.assertNotIn("\n", loaded["tool_use_id"])

    def test_newline_bearing_scalar_round_trips_exactly(self):
        dumped = yaml_lite.dump({"tool_use_id": NEWLINE_TOOL_USE_ID})
        loaded = yaml_lite.load(dumped)
        self.assertEqual(loaded["tool_use_id"], NEWLINE_TOOL_USE_ID)
        self.assertEqual(dumped.count("\n"), 1)

    def test_carriage_return_scalar_round_trips_exactly(self):
        dumped = yaml_lite.dump({"tool_use_id": CR_TOOL_USE_ID})
        loaded = yaml_lite.load(dumped)
        self.assertEqual(loaded["tool_use_id"], CR_TOOL_USE_ID)
        self.assertEqual(loaded["tool_use_id"], "call-example-95" + chr(13) + "fc_example_0")

    def test_crlf_scalar_round_trips_exactly(self):
        value = "call-example-95\r\nfc_example_0"
        loaded = yaml_lite.load(yaml_lite.dump({"tool_use_id": value}))
        self.assertEqual(loaded["tool_use_id"], value)

    def test_nested_mapping_list_durable_record_round_trips(self):
        record = {
            "schema_version": "1",
            "record_type": "develop_mutation_attempts",
            "attempts": [
                {
                    "attempt_id": "abc123",
                    "tool_use_id": NEWLINE_TOOL_USE_ID,
                    "paths": [VAULT_PRODUCT],
                    "state": MUTATION_PENDING,
                    "before": {VAULT_PRODUCT: {"kind": "file", "digest": "aa"}},
                    "after": {},
                    "scope_roles": {VAULT_PRODUCT: "product"},
                }
            ],
        }
        self.assertEqual(yaml_lite.load(yaml_lite.dump(record)), record)

    def test_historical_split_quoted_scalar_remains_unreadable(self):
        broken = 'tool_use_id: "call-example-95\nfc_example_0"\n'
        with self.assertRaises(ValueError):
            yaml_lite.load(broken)


class R4Crit004MutationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, VAULT_PRODUCT, "export const vault = true\n")
        write(self.host, VAULT_TEST, "assert(true)\n")
        write(self.host, VAULT_EVIDENCE, "ok\n")
        write(self.host, "legacy/dirty.txt", "inherited\n")
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope=dict(VAULT_SCOPE),
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Vault.",
                    "acceptance": "Vault.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        _install_marker(self.host)
        _knowledge(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _open(self) -> Path:
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        return _session_dir(self.host)

    def _pointer_session_id(self) -> str:
        return str(read_yaml(self.host / EXECUTION_POINTER_REL)["session_id"])

    def test_record_pending_newline_tool_use_id_round_trips(self):
        directory = self._open()
        record_pending_mutation(
            self.host,
            [VAULT_PRODUCT],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID,
        )
        durable = directory / MUTATION_ATTEMPTS_NAME
        self.assertTrue(durable.is_file())
        attempts, issues = load_mutation_attempts(directory)
        self.assertFalse(issues, issues)
        self.assertIsNotNone(attempts)
        self.assertEqual(len(attempts or []), 1)
        row = (attempts or [])[0]
        self.assertEqual(row.get("tool_use_id"), NEWLINE_TOOL_USE_ID)
        self.assertEqual(row.get("state"), MUTATION_PENDING)

    def test_observe_terminal_records_observed_success_and_files_yaml(self):
        directory = self._open()
        record_pending_mutation(
            self.host,
            [VAULT_PRODUCT],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID,
        )
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        ok, detail = observe_authorized_mutation(
            self.host,
            [VAULT_PRODUCT],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID,
            event="postToolUse",
        )
        self.assertTrue(ok, detail)
        attempts, issues = load_mutation_attempts(directory)
        self.assertFalse(issues, issues)
        self.assertEqual((attempts or [])[0].get("state"), MUTATION_OBSERVED)
        self.assertEqual((attempts or [])[0].get("tool_use_id"), NEWLINE_TOOL_USE_ID)
        files, file_issues = load_files_yaml(directory)
        self.assertFalse(file_issues, file_issues)
        by_path = {row["path"]: row for row in files or []}
        self.assertIn(VAULT_PRODUCT, by_path)
        self.assertEqual(by_path[VAULT_PRODUCT].get("mutation_state"), MUTATION_OBSERVED)
        self.assertTrue(by_path[VAULT_PRODUCT].get("after_digest"))

    def test_same_session_two_sequential_newline_mutations(self):
        directory = self._open()
        session_id = self._pointer_session_id()

        record_pending_mutation(
            self.host,
            [VAULT_PRODUCT],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID,
        )
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        ok_a, detail_a = observe_authorized_mutation(
            self.host,
            [VAULT_PRODUCT],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID,
            event="postToolUse",
        )
        self.assertTrue(ok_a, detail_a)
        self.assertEqual(self._pointer_session_id(), session_id)

        record_pending_mutation(
            self.host,
            [VAULT_TEST],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID_B,
        )
        write(self.host, VAULT_TEST, "assert(false)\n")
        ok_b, detail_b = observe_authorized_mutation(
            self.host,
            [VAULT_TEST],
            tool_name="Write",
            tool_use_id=NEWLINE_TOOL_USE_ID_B,
            event="postToolUse",
        )
        self.assertTrue(ok_b, detail_b)

        self.assertEqual(self._pointer_session_id(), session_id)
        self.assertEqual(_session_dir(self.host), directory)

        attempts, issues = load_mutation_attempts(directory)
        self.assertFalse(issues, issues)
        self.assertEqual(len(attempts or []), 2)
        self.assertTrue(all(row.get("state") == MUTATION_OBSERVED for row in attempts or []))
        self.assertTrue(all(row.get("session_id") == session_id for row in attempts or []))
        self.assertEqual((attempts or [])[0].get("tool_use_id"), NEWLINE_TOOL_USE_ID)
        self.assertEqual((attempts or [])[1].get("tool_use_id"), NEWLINE_TOOL_USE_ID_B)
        self.assertFalse(
            any(row.get("state") == MUTATION_PENDING for row in attempts or [])
        )

        files, file_issues = load_files_yaml(directory)
        self.assertFalse(file_issues, file_issues)
        by_path = {row["path"]: row for row in files or []}
        self.assertEqual(len(by_path), 2)
        self.assertIn(VAULT_PRODUCT, by_path)
        self.assertIn(VAULT_TEST, by_path)
        self.assertTrue(by_path[VAULT_PRODUCT].get("after_digest"))
        self.assertTrue(by_path[VAULT_TEST].get("after_digest"))
        self.assertEqual(by_path[VAULT_PRODUCT].get("mutation_state"), MUTATION_OBSERVED)
        self.assertEqual(by_path[VAULT_TEST].get("mutation_state"), MUTATION_OBSERVED)


if __name__ == "__main__":
    unittest.main()
