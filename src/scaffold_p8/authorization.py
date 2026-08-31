"""S6 candidate-bound human authorization. Never synthesized. Never persisted as a grant."""

from __future__ import annotations

from typing import Any

from scaffold_p8.schemas import parse_authorization, parse_push_authorization


def check_submit_authorized(
    value: Any, *, current_digest: str
) -> tuple[bool, str]:
    ok, reason, digest = parse_authorization(value)
    if not ok:
        return False, reason
    if digest != current_digest:
        return False, (
            "SUBMIT_AUTHORIZED is bound to a different candidate; "
            "C1 authorization is unusable for C2"
        )
    return True, reason


def check_push_authorized(
    value: Any, *, current_digest: str
) -> tuple[bool, str]:
    ok, reason, digest = parse_push_authorization(value)
    if not ok:
        return False, reason
    if digest != current_digest:
        return False, (
            "Push authorization is bound to a different candidate; "
            "C1 authorization is unusable for C2"
        )
    return True, reason
