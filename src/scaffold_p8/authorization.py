"""S6 candidate-bound human authorization. Never synthesized. Never persisted as a grant."""

from __future__ import annotations

import secrets
from typing import Any

from scaffold_p8.authorization_provider import (
    OPERATION_PUSH,
    OPERATION_S10,
    AuthorizationProvider,
)
from scaffold_p8.schemas import parse_authorization


def caller_dictionary_is_not_authority(value: Any) -> bool:
    if value in (None, False, ""):
        return False
    return True


def check_submit_authorized(
    value: Any, *, current_digest: str
) -> tuple[bool, str]:
    del current_digest
    if value in (None, False, ""):
        return False, "SUBMIT_AUTHORIZED is missing"
    return False, "caller SUBMIT_AUTHORIZED dictionary is not trusted authority"


def check_push_authorized(
    value: Any, *, current_digest: str
) -> tuple[bool, str]:
    del current_digest
    if value in (None, False, ""):
        return False, "Push authorization is missing"
    return False, "caller Push authorization dictionary is not trusted authority"


def inspect_legacy_authorization(value: Any) -> tuple[bool, str, str | None]:
    """Parse the retired caller dictionary. Never treats it as a grant."""
    ok, reason, digest = parse_authorization(value)
    if ok:
        return False, "caller SUBMIT_AUTHORIZED dictionary is not trusted authority", digest
    return False, reason, digest


def new_authorization_attempt_id(operation: str) -> str:
    return f"auth-{operation}-{secrets.token_hex(8)}"


def caller_attempt_id(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def validate_trusted_grant(
    provider: AuthorizationProvider | None,
    *,
    operation: str,
    grant_ref: Any,
    attempt_id: Any,
    candidate_digest: str,
) -> dict[str, Any]:
    if provider is None:
        return {
            "ok": False,
            "reason": (
                "SUBMIT_AUTHORIZED is missing"
                if operation == OPERATION_S10
                else "Push authorization is missing"
            ),
            "consumed": False,
        }
    ref = grant_ref if isinstance(grant_ref, str) else ""
    return provider.validate(
        operation=operation,
        grant_ref=ref,
        attempt_id=caller_attempt_id(attempt_id),
        candidate_digest=candidate_digest,
    )


def consume_trusted_grant(
    provider: AuthorizationProvider | None,
    *,
    operation: str,
    grant_ref: Any,
    attempt_id: Any,
    candidate_digest: str,
) -> dict[str, Any]:
    if provider is None:
        return {
            "ok": False,
            "reason": (
                "SUBMIT_AUTHORIZED is missing"
                if operation == OPERATION_S10
                else "Push authorization is missing"
            ),
            "consumed": False,
        }
    ref = grant_ref if isinstance(grant_ref, str) else ""
    return provider.consume(
        operation=operation,
        grant_ref=ref,
        attempt_id=caller_attempt_id(attempt_id),
        candidate_digest=candidate_digest,
    )


def authorization_request(
    *,
    operation: str,
    candidate_digest: str,
    authorization_attempt_id: str,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "operation": operation,
        "candidate_digest": candidate_digest,
        "authorization_attempt_id": authorization_attempt_id,
    }
    if task and task.get("record_id"):
        request["task_id"] = str(task.get("record_id"))
    return request
