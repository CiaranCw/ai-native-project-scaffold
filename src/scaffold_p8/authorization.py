"""Caller dictionaries are not Commit/Push authority.

Submit S1-S12 is Agent-autonomous machine-gated work. Git Commit and Git Push
require a current explicit user instruction at the Agent execution boundary.
Core does not consume a grant object or a caller dictionary as that instruction.
"""

from __future__ import annotations

from typing import Any

from scaffold_p8.schemas import parse_authorization

__all__ = [
    "caller_dictionary_is_not_authority",
    "check_push_authorized",
    "check_submit_authorized",
    "inspect_legacy_authorization",
]


def caller_dictionary_is_not_authority(value: Any) -> bool:
    if value in (None, False, ""):
        return False
    return True


def check_submit_authorized(
    value: Any, *, current_digest: str
) -> tuple[bool, str]:
    del current_digest
    if value in (None, False, ""):
        return False, "caller SUBMIT_AUTHORIZED dictionary is not Commit/Push authority"
    return False, "caller SUBMIT_AUTHORIZED dictionary is not Commit/Push authority"


def check_push_authorized(
    value: Any, *, current_digest: str
) -> tuple[bool, str]:
    del current_digest
    if value in (None, False, ""):
        return False, "caller Push dictionary is not Push authority"
    return False, "caller Push dictionary is not Push authority"


def inspect_legacy_authorization(value: Any) -> tuple[bool, str, str | None]:
    """Parse a retired caller dictionary. Never treats it as a grant."""
    _ok, _reason, digest = parse_authorization(value)
    return False, "caller SUBMIT_AUTHORIZED dictionary is not Commit/Push authority", digest
