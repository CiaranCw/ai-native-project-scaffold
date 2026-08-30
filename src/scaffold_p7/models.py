"""P7 Develop constants. Not Foundation lifecycle states. Not a fifth Skill."""

from __future__ import annotations

SKILL_ID = "develop"
SKILL_VERSION = "2.0.0"
DEVELOP_MODES = ("normal_task", "repair")
PROVIDES = ("develop.implement", "develop.repair")
REQUIRES: tuple[str, ...] = ()

TASK_RECORD_TYPE = "task_book"
SESSION_RECORD_TYPE = "develop_session"
RECORD_SCHEMA_VERSION = "1"

TASK_STATUSES = ("DRAFT", "IN_PROGRESS", "READY_FOR_REVIEW", "CANCELED")
STAGE_STATUSES = ("PENDING", "IN_PROGRESS", "BLOCKED", "COMPLETE")
SESSION_STATES = ("OPEN", "SEALED", "ABORTED")
EXECUTABLE_COMPAT = frozenset({"EXACT", "COMPATIBLE"})

TASKS_DIR = ".scaffold/tasks"
SESSIONS_DIR = ".scaffold/runtime/develop-sessions"
PROJECT_YAML = ".scaffold/project.yaml"
MODULES_YAML = ".scaffold/modules.yaml"

DIGEST_PREFIX = "sha256:"
