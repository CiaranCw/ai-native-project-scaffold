"""Generic structured trace envelope, Evidence role, and retention class.

Policy and Evidence authority only. Not a Scenario canonical record.
Not a vision runner. Domain payload remains opaque.
"""

from __future__ import annotations

from typing import Any


EVIDENCE_ROLES = frozenset({"PRIMARY", "SECONDARY", "ESCALATION"})
RETENTION_CLASSES = frozenset(
    {
        "DURABLE_FINALIZATION",
        "TEMPORARY_RUNTIME",
        "DEBUG",
        "OPTIONAL_VISUAL",
    }
)
S9_FORBIDDEN_RETENTION = frozenset({"DEBUG", "TEMPORARY_RUNTIME"})
OPTIONAL_VISUAL_JUSTIFICATIONS = frozenset(
    {
        "inherently_visual",
        "conflict_with_human_observation",
        "no_reliable_nonvisual_oracle",
        "requirement_demands_visual",
        "structured_conflict_with_human_observation",
    }
)
VISUAL_JUSTIFICATION_FIELDS = (
    "retention_justification",
    "escalation_justification",
    "visual_justification",
)
TRACE_ENVELOPE_FIELDS = (
    "scenario_id",
    "candidate",
    "requirement_ids",
    "obligation_ids",
    "initial_state",
    "actions",
    "observations",
    "assertions",
    "artifacts",
    "result",
)
OPAQUE_PAYLOAD_KEYS = ("domain", "payload", "extension", "opaque")


def validate_role(role: Any) -> list[str]:
    if role in (None, ""):
        return []
    if role not in EVIDENCE_ROLES:
        return [f"unsupported evidence role: {role!r}"]
    return []


def validate_retention_class(retention_class: Any) -> list[str]:
    if retention_class in (None, ""):
        return []
    if retention_class not in RETENTION_CLASSES:
        return [f"unsupported evidence retention_class: {retention_class!r}"]
    return []


def effective_role(item: dict[str, Any]) -> str:
    """Legacy Evidence without role remains implicit PRIMARY."""
    role = item.get("role")
    if role in EVIDENCE_ROLES:
        return str(role)
    return "PRIMARY"


def role_can_directly_satisfy(item: dict[str, Any]) -> bool:
    role = effective_role(item)
    if role == "SECONDARY":
        return False
    if role in {"PRIMARY", "ESCALATION"}:
        return True
    return False


def retention_allows_s9(item: dict[str, Any]) -> tuple[bool, str]:
    """DEBUG and TEMPORARY_RUNTIME must never become durable finalization Evidence."""
    retention = item.get("retention_class")
    if retention in (None, ""):
        return True, ""
    if retention not in RETENTION_CLASSES:
        return False, f"unsupported evidence retention_class: {retention!r}"
    if retention in S9_FORBIDDEN_RETENTION:
        if retention == "DEBUG":
            return False, "DEBUG evidence cannot be included in durable Change Record materialization"
        return False, "TEMPORARY_RUNTIME evidence cannot become S9 durable finalization Evidence"
    if retention == "OPTIONAL_VISUAL":
        if _visual_retention_justified(item):
            return True, ""
        return False, (
            "OPTIONAL_VISUAL durable retention requires an explicit "
            "escalation/retention justification"
        )
    return True, ""


def visual_is_required_by_default() -> bool:
    return False


def visual_observation_justified(item: dict[str, Any], po: dict[str, Any] | None = None) -> bool:
    if _visual_retention_justified(item):
        return True
    if not isinstance(po, dict):
        return False
    reqs = _lower_list(po.get("evidence_requirements"))
    strategy = str(po.get("execution_strategy") or "").strip().lower()
    if "visual_checkpoint" in reqs or strategy in {"visual", "visual_checkpoint"}:
        return True
    return False


def validate_trace_envelope(trace: Any) -> list[str]:
    """Validate an optional generic event/state trace envelope.

    Absence of an envelope is legacy-compatible. Core validates only known
    generic fields and opaque extension namespaces. Unknown top-level keys are
    not Core authority and are not rejected by name.
    """
    if trace is None:
        return []
    if not isinstance(trace, dict):
        return ["trace envelope must be a mapping"]
    issues: list[str] = []
    scenario_id = trace.get("scenario_id")
    if scenario_id not in (None, "") and not isinstance(scenario_id, str):
        issues.append("trace.scenario_id must be a string when present")
    candidate = trace.get("candidate")
    if candidate not in (None, "") and not isinstance(candidate, (str, dict)):
        issues.append("trace.candidate must be a string or mapping when present")
    for list_field in (
        "requirement_ids",
        "obligation_ids",
        "actions",
        "observations",
        "assertions",
        "artifacts",
    ):
        value = trace.get(list_field)
        if value is None:
            continue
        if not isinstance(value, list):
            issues.append(f"trace.{list_field} must be a list when present")
    result = trace.get("result")
    if result not in (None, "") and not isinstance(result, (str, dict, bool)):
        issues.append("trace.result must be a string, mapping, or boolean when present")
    for key in OPAQUE_PAYLOAD_KEYS:
        payload = trace.get(key)
        if payload is None:
            continue
        if not isinstance(payload, dict):
            issues.append(f"trace.{key} must be a mapping when present")
    return issues


def envelope_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("trace", "state", "content", "envelope"):
        value = item.get(key)
        if isinstance(value, dict) and (
            any(field in value for field in TRACE_ENVELOPE_FIELDS)
            or any(field in value for field in OPAQUE_PAYLOAD_KEYS)
        ):
            return value
    if any(field in item for field in TRACE_ENVELOPE_FIELDS):
        return {field: item.get(field) for field in TRACE_ENVELOPE_FIELDS if field in item}
    return None


def envelope_candidate_digest(candidate: Any) -> str | None:
    """Normalize a generic envelope candidate to a digest string.

    Opaque domain payload is not inspected.
    """
    if candidate in (None, ""):
        return None
    if isinstance(candidate, str):
        digest = candidate.strip()
        return digest or None
    if isinstance(candidate, dict):
        digest = str(candidate.get("candidate_digest") or candidate.get("digest") or "").strip()
        return digest or None
    return None


def assertions_from_trace(item: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    envelope = envelope_from_evidence(item)
    sources = [item]
    if envelope is not None:
        sources.append(envelope)
        for key in ("observations", "assertions"):
            rows = envelope.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        found.append(row)
    for source in sources:
        assertion = source.get("assertion")
        if isinstance(assertion, dict):
            found.append(assertion)
        rows = source.get("assertions")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    found.append(row)
    return found


def _visual_retention_justified(item: dict[str, Any]) -> bool:
    for field in VISUAL_JUSTIFICATION_FIELDS:
        value = item.get(field)
        if value in OPTIONAL_VISUAL_JUSTIFICATIONS:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _lower_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]
