"""P7 Develop runtime. Not a fifth Skill. Not P8 Submit."""

from scaffold_p7.models import DEVELOP_MODES, SKILL_ID, SKILL_VERSION

__all__ = ["DevelopEngine", "SKILL_ID", "SKILL_VERSION", "DEVELOP_MODES"]


def __getattr__(name: str):
    if name == "DevelopEngine":
        from scaffold_p7.engine import DevelopEngine

        return DevelopEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name}")
