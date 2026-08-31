"""P8 Submit constants. Not a fifth Skill. Not Foundation lifecycle states."""

from __future__ import annotations

SKILL_ID = "submit"
SKILL_VERSION = "2.0.0"
SUBMIT_MODES: tuple[str, ...] = ()
PROVIDES = ("submit.review",)
REQUIRES = (
    "test.scoped_verification",
    "understand.refresh",
    "understand.compatibility",
)

STAGES = (
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "S8",
    "S9",
    "S10",
    "S11",
    "S12",
)

PROVENANCE_CLASSES = (
    "MIXED_CHANGE",
    "PREEXISTING_CHANGE",
    "POST_DEVELOP_ADDITIONAL",
    "DEVELOP_KNOWN",
    "UNATTRIBUTED",
)

CHANGE_RECORD_TYPE = "change_record"
RECORD_SCHEMA_VERSION = "1"
EXECUTABLE_COMPAT = frozenset({"EXACT", "COMPATIBLE"})

TASKS_DIR = ".scaffold/tasks"
SESSIONS_DIR = ".scaffold/runtime/develop-sessions"
CHANGES_DIR = ".scaffold/changes"
FINALIZATIONS_DIR = ".scaffold/finalizations"
PROJECT_YAML = ".scaffold/project.yaml"
TESTS_YAML = ".scaffold/tests.yaml"
