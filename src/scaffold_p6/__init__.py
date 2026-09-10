"""P6 Test runtime. Not a fifth Skill. Not P7/P8."""

from scaffold_p6.models import SKILL_ID, SKILL_VERSION, TEST_MODES

__all__ = ["TestEngine", "SKILL_ID", "SKILL_VERSION", "TEST_MODES"]


def __getattr__(name: str):
    if name == "TestEngine":
        from scaffold_p6.engine import TestEngine

        return TestEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name}")
