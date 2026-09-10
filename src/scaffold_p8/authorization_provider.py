"""Trusted host-bound one-shot authorization. Not Agent-callable through run opts."""

from __future__ import annotations

import threading
from typing import Any, Protocol

OPERATION_S10 = "S10"
OPERATION_PUSH = "PUSH"
VALID_OPERATIONS = {OPERATION_S10, OPERATION_PUSH}


class AuthorizationProvider(Protocol):
    def validate(
        self,
        *,
        operation: str,
        grant_ref: str,
        attempt_id: str,
        candidate_digest: str,
    ) -> dict[str, Any]:
        ...

    def consume(
        self,
        *,
        operation: str,
        grant_ref: str,
        attempt_id: str,
        candidate_digest: str,
    ) -> dict[str, Any]:
        ...


class EphemeralAuthorizationProvider:
    """Process-local grant store. Submit may only validate and consume."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._grants: dict[str, dict[str, Any]] = {}

    def validate(
        self,
        *,
        operation: str,
        grant_ref: str,
        attempt_id: str,
        candidate_digest: str,
    ) -> dict[str, Any]:
        with self._lock:
            return dict(
                self._inspect_locked(
                    operation, grant_ref, attempt_id, candidate_digest
                )
            )

    def consume(
        self,
        *,
        operation: str,
        grant_ref: str,
        attempt_id: str,
        candidate_digest: str,
    ) -> dict[str, Any]:
        with self._lock:
            inspected = self._inspect_locked(
                operation, grant_ref, attempt_id, candidate_digest
            )
            if not inspected.get("ok"):
                return inspected
            self._grants[str(grant_ref)]["consumed"] = True
            inspected["consumed"] = True
            return inspected

    def _insert(
        self,
        *,
        grant_ref: str,
        operation: str,
        attempt_id: str,
        candidate_digest: str,
    ) -> None:
        with self._lock:
            self._grants[grant_ref] = {
                "operation": operation,
                "attempt_id": attempt_id,
                "candidate_digest": candidate_digest,
                "consumed": False,
            }

    def _inspect_locked(
        self,
        operation: str,
        grant_ref: str,
        attempt_id: str,
        candidate_digest: str,
    ) -> dict[str, Any]:
        missing = (
            "SUBMIT_AUTHORIZED is missing"
            if operation == OPERATION_S10
            else "Push authorization is missing"
        )
        if not grant_ref:
            return {
                "ok": False,
                "reason": missing,
                "consumed": False,
            }
        grant = self._grants.get(grant_ref)
        if grant is None:
            return {
                "ok": False,
                "reason": missing,
                "consumed": False,
            }
        if grant.get("consumed"):
            return {
                "ok": False,
                "reason": "authorization grant has already been consumed",
                "consumed": True,
                "operation": grant.get("operation"),
                "attempt_id": grant.get("attempt_id"),
            }
        if grant.get("operation") != operation:
            return {
                "ok": False,
                "reason": "authorization grant operation does not match",
                "consumed": False,
                "operation": grant.get("operation"),
                "attempt_id": grant.get("attempt_id"),
            }
        if not attempt_id:
            return {
                "ok": False,
                "reason": "authorization attempt identity is missing",
                "consumed": False,
                "operation": grant.get("operation"),
                "attempt_id": grant.get("attempt_id"),
            }
        if grant.get("attempt_id") != attempt_id:
            return {
                "ok": False,
                "reason": "authorization grant attempt does not match",
                "consumed": False,
                "operation": grant.get("operation"),
                "attempt_id": grant.get("attempt_id"),
            }
        if grant.get("candidate_digest") != candidate_digest:
            return {
                "ok": False,
                "reason": (
                    "C1 authorization is unusable for C2"
                    if operation == OPERATION_S10
                    else "Push authorization is bound to a different candidate; "
                    "C1 authorization is unusable for C2"
                ),
                "consumed": False,
                "operation": grant.get("operation"),
                "attempt_id": grant.get("attempt_id"),
            }
        return {
            "ok": True,
            "reason": "",
            "consumed": False,
            "operation": grant.get("operation"),
            "attempt_id": grant.get("attempt_id"),
            "grant_ref": grant_ref,
            "candidate_digest": grant.get("candidate_digest"),
        }
