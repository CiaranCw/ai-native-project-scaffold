"""P6 Test support-artifact constants. Not Foundation lifecycle states."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SKILL_ID = "test"
SKILL_VERSION = "2.0.0"
TEST_MODES = ("scoped_verification",)
PROVIDES = ("test.scoped_verification",)
REQUIRES: tuple[str, ...] = ()

REPORT_SCHEMA_VERSION = "1"
EVIDENCE_SCHEMA_VERSION = "1"
CANDIDATE_SCHEMA_VERSION = "1"

SUPPORT_KIND = "test_report"
RECORD_CLASS = "support_artifact"

PROVENANCE = (
    "LOCAL_EXECUTION",
    "EXTERNAL_RESULT",
    "HUMAN_OBSERVATION",
    "CI_RESULT",
)
EVIDENCE_KINDS = (
    "command_result",
    "structured_assertion",
    "log_text",
    "structured_state",
    "event_trace",
    "file_artifact",
    "visual_checkpoint",
    "human_observation",
    "external_ci",
)
SCENARIO_RESULTS = ("PASS", "FAIL", "BLOCKED", "NOT_RUN")
TERMINAL_USABLE = frozenset({"PASS", "FAIL"})
FACT_CLASSES = ("VERIFIED", "INFERRED", "UNKNOWN", "CONFLICTING")
APPLICABILITY = ("APPLICABLE", "NOT_APPLICABLE", "UNKNOWN", "CONFLICTING")
ADAPTERS = ("local",)
INLINE_LOG_LIMIT = 4096

TEST_RUNS = ".scaffold/runtime/test-runs"
TESTS_YAML = ".scaffold/tests.yaml"
COMMANDS_YAML = ".scaffold/commands.yaml"
PROJECT_YAML = ".scaffold/project.yaml"
TASKS_DIR = ".scaffold/tasks"
SESSIONS_DIR = ".scaffold/runtime/develop-sessions"
CHANGES_DIR = ".scaffold/changes"

CANONICAL_DEVELOPMENT_RECORDS = ("task_book", "develop_session", "change_record")


@dataclass
class CandidateIdentity:
    data: dict[str, Any]

    @property
    def digest(self) -> str:
        return str(self.data.get("candidate_digest") or "")

    @property
    def kind(self) -> str:
        return str(self.data.get("kind") or "")


@dataclass
class Profile:
    data: dict[str, Any]

    @property
    def profile_id(self) -> str:
        return str(self.data.get("id") or "")

    @property
    def required(self) -> bool:
        return self.data.get("required") is True

    @property
    def adapter(self) -> str:
        return str(self.data.get("adapter") or "")

    @property
    def command_ref(self) -> str:
        return str(self.data.get("command_ref") or "")

    @property
    def provenance(self) -> str:
        value = self.data.get("provenance")
        return str(value) if value else "LOCAL_EXECUTION"

    @property
    def applicability(self) -> str:
        return str(self.data.get("applicability") or "")


@dataclass
class ContractResolution:
    status: str
    applicability: str
    confidence: str
    profiles: list[Profile] = field(default_factory=list)
    required: list[Profile] = field(default_factory=list)
    optional: list[Profile] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    route: str = ""
    verified_no_required: bool = False
    required_set_authoritative: bool = False
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


@dataclass
class ExecutionObservation:
    adapter_id: str
    command: list[str]
    working_directory: str
    started_at: str
    ended_at: str
    duration_ms: int
    exit_code: int | None
    stdout: str
    stderr: str
    termination: str
    error: str = ""


@dataclass
class ScenarioResult:
    profile_id: str
    required: bool
    result: str
    provenance: str
    adapter: str
    command_ref: str
    blockers: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    evidence_complete: bool = False
    observation: dict[str, Any] | None = None
