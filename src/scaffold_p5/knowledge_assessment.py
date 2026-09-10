"""P5-owned Knowledge Assessment supporting artifact. Not a canonical record."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import (
    ARCHITECTURE_MD,
    DEVELOPMENT_MD,
    MODULE_DOCS,
    OVERVIEW_MD,
    TESTING_MD,
)
from scaffold_p5.io_util import file_digest, read_yaml, sha256_text, write_yaml_atomic
from scaffold_p5 import yaml_lite


AGENTS_MD = "AGENTS.md"
ASSESSMENT_ROOT = ".scaffold/runtime/understand-assessments"
HEADS_ROOT = ".scaffold/runtime/understand-assessments/heads"
RECORD_TYPE = "knowledge_assessment"
HEAD_RECORD_TYPE = "knowledge_assessment_head"
SCHEMA_VERSION = "1"
PRODUCER_SKILL = "understand"
PRODUCER_MODES = ("refresh", "full")
ASSESSMENT_OUTCOMES = ("SATISFIED", "NEEDS_REFRESH", "NEEDS_HUMAN", "UNKNOWN")
ASSESSMENT_ID_RE = re.compile(r"^ka-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LOCATOR_RE = re.compile(
    r"^understand-assessments/ka-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}/assessment\.yaml$"
)
HEAD_LOCATOR_RE = re.compile(
    r"^understand-assessments/heads/[0-9a-f]{64}/head\.yaml$"
)

IMPACT_SURFACES: dict[str, tuple[str, ...]] = {
    "MODULE_STRUCTURE": (ARCHITECTURE_MD, MODULE_DOCS),
    "PUBLIC_INTERFACE": (ARCHITECTURE_MD, MODULE_DOCS),
    "DEPENDENCY": (ARCHITECTURE_MD, DEVELOPMENT_MD),
    "COMMAND": (DEVELOPMENT_MD,),
    "TEST_CONFIGURATION": (TESTING_MD,),
    "PROJECT_CONFIGURATION": (OVERVIEW_MD, ARCHITECTURE_MD, AGENTS_MD),
    "SCAFFOLD_STRUCTURE": (OVERVIEW_MD,),
}

KNOWLEDGE_RELEVANT_CLASSES = frozenset(IMPACT_SURFACES)
STATUS_UNKNOWN = "UNKNOWN"


def project_knowledge_impact(row: Any) -> dict[str, str] | None:
    """Canonical S3 impact projection used by Knowledge Assessment / S4."""
    if not isinstance(row, dict):
        return None
    kind = str(row.get("class") or "").strip()
    path = str(row.get("path") or "").replace("\\", "/").strip()
    status = str(row.get("status") or "").strip()
    if not kind or not path:
        return None
    projected: dict[str, str] = {
        "class": kind,
        "path": path,
        "status": status,
    }
    detail = row.get("detail")
    if detail not in (None, ""):
        projected["detail"] = str(detail)
    return projected


def knowledge_relevant_impacts(impacts: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in impacts or []:
        projected = project_knowledge_impact(item)
        if projected is None:
            continue
        if projected["class"] not in KNOWLEDGE_RELEVANT_CLASSES:
            continue
        if projected["status"] == STATUS_UNKNOWN:
            continue
        key = (
            projected["class"],
            projected["path"],
            projected["status"],
            projected.get("detail") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(projected)
    rows.sort(key=lambda row: (
        row["class"],
        row["path"],
        row["status"],
        row.get("detail") or "",
    ))
    return rows


def impact_id_for(row: Any) -> str:
    projected = project_knowledge_impact(row)
    if projected is None:
        return ""
    return sha256_text(yaml_lite.dump(projected))


def knowledge_impact_digest(impacts: Any) -> str:
    rows = knowledge_relevant_impacts(impacts)
    if not rows:
        return sha256_text("")
    return sha256_text(yaml_lite.dump(rows))


def mapped_surface_paths(impact: Any) -> list[str]:
    projected = project_knowledge_impact(impact)
    if projected is None:
        return []
    surfaces = IMPACT_SURFACES.get(projected["class"]) or ()
    out: list[str] = []
    for surface in surfaces:
        target = _surface_path(surface, projected)
        if target and target not in out:
            out.append(target)
    return out


def assessment_locator(record_id: str) -> str:
    return f"understand-assessments/{record_id}/assessment.yaml"


def assessment_path(root: Path, locator: str) -> Path | None:
    if not isinstance(locator, str) or not LOCATOR_RE.fullmatch(locator):
        return None
    if ".." in locator.replace("\\", "/"):
        return None
    return Path(root) / ".scaffold/runtime" / locator


def publish_knowledge_assessment(
    root: str | Path,
    *,
    mode: str,
    impacts: list[Any],
    outcomes: list[Any] | None = None,
    candidate_digest: str | None = None,
) -> dict[str, Any]:
    """Publish one Understand-owned Knowledge Assessment for the current candidate."""
    host = Path(root)
    if mode not in PRODUCER_MODES:
        return {
            "ok": False,
            "blockers": [f"Knowledge Assessment producer mode is not allowed: {mode}"],
        }
    observed = _observe_digest(host)
    if not observed:
        return {
            "ok": False,
            "blockers": [
                "Knowledge Assessment requires a usable current P6 candidate"
            ],
        }
    if candidate_digest and candidate_digest != observed:
        return {
            "ok": False,
            "blockers": [
                "Knowledge Assessment cannot bind a non-current candidate digest"
            ],
        }
    relevant = knowledge_relevant_impacts(impacts)
    digest = knowledge_impact_digest(relevant)
    offered = _index_outcomes(outcomes)
    assessments: list[dict[str, Any]] = []
    for row in relevant:
        iid = impact_id_for(row)
        offered_row = offered.get((row["class"], row["path"]))
        outcome: Any = "UNKNOWN"
        rationale = "Understand did not supply a current semantic outcome"
        surfaces = mapped_surface_paths(row)
        if offered_row is not None:
            raw_outcome = offered_row.get("outcome")
            if raw_outcome is False or raw_outcome is True:
                outcome = raw_outcome
            elif raw_outcome in (None, ""):
                outcome = "UNKNOWN"
            else:
                outcome = str(raw_outcome)
            if offered_row.get("rationale"):
                rationale = str(offered_row.get("rationale"))
            if isinstance(offered_row.get("surfaces"), list) and offered_row["surfaces"]:
                surfaces = [str(item) for item in offered_row["surfaces"] if item]
        assessments.append(
            {
                "impact_id": iid,
                "class": row["class"],
                "path": row["path"],
                "outcome": outcome,
                "surfaces": surfaces,
                "rationale": rationale,
            }
        )
    record_id = _allocate_assessment_id(host)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "created_at": created_at,
        "producer": {"skill_id": PRODUCER_SKILL, "mode": mode},
        "candidate": {"candidate_digest": observed},
        "impact_digest": digest,
        "assessments": assessments,
    }
    issues = validate_knowledge_assessment(payload)
    if issues:
        return {"ok": False, "blockers": issues, "assessment": payload}
    locator = assessment_locator(record_id)
    path = assessment_path(host, locator)
    if path is None:
        return {"ok": False, "blockers": ["Knowledge Assessment locator is illegal"]}
    write_yaml_atomic(path, payload)
    assessment_digest = file_digest(path)
    head = _publish_current_head(
        host,
        candidate_digest=observed,
        impact_digest=digest,
        locator=locator,
        record_id=record_id,
        assessment_digest=assessment_digest,
    )
    if not head.get("ok"):
        return {
            "ok": False,
            "blockers": list(head.get("blockers") or ["current-head publication failed"]),
            "locator": locator,
            "assessment": payload,
        }
    return {
        "ok": True,
        "locator": locator,
        "assessment": payload,
        "candidate_digest": observed,
        "impact_digest": digest,
        "assessment_digest": assessment_digest,
        "current_head": head.get("head"),
        "current_head_locator": head.get("locator"),
        "blockers": [],
    }


def resolve_knowledge_assessment(
    root: str | Path, locator: Any
) -> dict[str, Any]:
    if not isinstance(locator, str):
        return {
            "ok": False,
            "blockers": [
                "Knowledge Assessment locator must be a P5-published path string"
            ],
        }
    path = assessment_path(Path(root), locator)
    if path is None:
        return {
            "ok": False,
            "blockers": ["Knowledge Assessment locator is not an allowed runtime path"],
        }
    if not path.is_file():
        return {
            "ok": False,
            "blockers": [f"Knowledge Assessment is not resolvable: {locator}"],
        }
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "blockers": ["Knowledge Assessment is malformed or unreadable"],
        }
    issues = validate_knowledge_assessment(data)
    if issues:
        return {"ok": False, "blockers": issues, "assessment": data}
    assert isinstance(data, dict)
    if assessment_locator(str(data.get("record_id") or "")) != locator:
        return {
            "ok": False,
            "blockers": ["Knowledge Assessment locator does not match record identity"],
            "assessment": data,
        }
    return {"ok": True, "locator": locator, "assessment": data, "blockers": []}


def binding_digest_for(candidate_digest: str, impact_digest: str) -> str:
    return sha256_text(
        yaml_lite.dump(
            {
                "candidate_digest": str(candidate_digest or ""),
                "impact_digest": str(impact_digest or ""),
            }
        )
    )


def current_head_locator(candidate_digest: str, impact_digest: str) -> str:
    return (
        "understand-assessments/heads/"
        + binding_digest_for(candidate_digest, impact_digest)
        + "/head.yaml"
    )


def current_head_path(root: Path, locator: str) -> Path | None:
    if not isinstance(locator, str) or not HEAD_LOCATOR_RE.fullmatch(locator):
        return None
    if ".." in locator.replace("\\", "/"):
        return None
    return Path(root) / ".scaffold/runtime" / locator


def resolve_current_head(
    root: str | Path,
    *,
    candidate_digest: str,
    impact_digest: str,
) -> dict[str, Any]:
    if not candidate_digest or not impact_digest:
        return {
            "ok": False,
            "reason": "missing",
            "blockers": ["Knowledge Assessment current head binding is incomplete"],
        }
    locator = current_head_locator(candidate_digest, impact_digest)
    path = current_head_path(Path(root), locator)
    if path is None or not path.is_file():
        return {
            "ok": False,
            "reason": "missing",
            "blockers": [
                "Knowledge Assessment current head is missing for this "
                "candidate/impact binding"
            ],
        }
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "reason": "malformed",
            "blockers": ["Knowledge Assessment current head is malformed or unreadable"],
        }
    issues = validate_current_head(data)
    if issues:
        return {
            "ok": False,
            "reason": "malformed",
            "blockers": issues,
            "head": data,
        }
    assert isinstance(data, dict)
    if str(data.get("candidate_digest") or "") != candidate_digest:
        return {
            "ok": False,
            "reason": "candidate_mismatch",
            "blockers": [
                "Knowledge Assessment current head candidate binding is stale"
            ],
            "head": data,
        }
    if str(data.get("impact_digest") or "") != impact_digest:
        return {
            "ok": False,
            "reason": "impact_mismatch",
            "blockers": [
                "Knowledge Assessment current head impact binding is stale"
            ],
            "head": data,
        }
    return {
        "ok": True,
        "locator": locator,
        "head": data,
        "blockers": [],
    }


def resolve_current_knowledge_assessment(
    root: str | Path,
    *,
    candidate_digest: str,
    impact_digest: str,
    locator: Any = None,
) -> dict[str, Any]:
    """Resolve the unique current Assessment head for one (C, I) binding."""
    head_state = resolve_current_head(
        root,
        candidate_digest=candidate_digest,
        impact_digest=impact_digest,
    )
    if not head_state.get("ok"):
        diagnosed = _diagnose_explicit_locator_when_head_missing(
            root,
            locator=locator,
            candidate_digest=candidate_digest,
            impact_digest=impact_digest,
            head_reason=str(head_state.get("reason") or "missing"),
        )
        if diagnosed is not None:
            return diagnosed
        return {
            "ok": False,
            "satisfied": False,
            "reason": head_state.get("reason") or "missing",
            "blockers": list(
                head_state.get("blockers")
                or ["Knowledge Assessment current head is UNKNOWN"]
            ),
        }
    head = head_state.get("head") or {}
    current_locator = str(head.get("locator") or "")
    if locator not in (None, ""):
        if not isinstance(locator, str) or locator != current_locator:
            return {
                "ok": False,
                "satisfied": False,
                "reason": "superseded",
                "locator": current_locator,
                "head": head,
                "blockers": [
                    "Knowledge Assessment locator is superseded for the current "
                    "candidate/impact binding"
                ],
            }
    loaded = resolve_knowledge_assessment(root, current_locator)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "satisfied": False,
            "reason": "unresolvable",
            "head": head,
            "blockers": list(loaded.get("blockers") or ["current Assessment is unresolvable"]),
        }
    assessment = loaded.get("assessment") or {}
    loaded_id = str(assessment.get("record_id") or "")
    head_id = str(head.get("record_id") or "")
    if not loaded_id or loaded_id != head_id:
        return {
            "ok": False,
            "satisfied": False,
            "reason": "identity_mismatch",
            "locator": current_locator,
            "assessment": assessment,
            "head": head,
            "blockers": [
                "Knowledge Assessment current head record_id does not match "
                "the loaded Assessment identity"
            ],
        }
    expected_locator = assessment_locator(loaded_id)
    if current_locator != expected_locator:
        return {
            "ok": False,
            "satisfied": False,
            "reason": "identity_mismatch",
            "locator": current_locator,
            "assessment": assessment,
            "head": head,
            "blockers": [
                "Knowledge Assessment current head locator does not match "
                "the loaded Assessment identity"
            ],
        }
    path = assessment_path(Path(root), current_locator)
    if path is None or not path.is_file():
        return {
            "ok": False,
            "satisfied": False,
            "reason": "unresolvable",
            "head": head,
            "blockers": ["current Knowledge Assessment bytes are missing"],
        }
    actual_digest = file_digest(path)
    expected_digest = str(head.get("assessment_digest") or "")
    if actual_digest != expected_digest:
        return {
            "ok": False,
            "satisfied": False,
            "reason": "integrity_mismatch",
            "locator": current_locator,
            "assessment": loaded.get("assessment"),
            "head": head,
            "blockers": [
                "Knowledge Assessment bytes do not match the current-head integrity binding"
            ],
        }
    return {
        "ok": True,
        "locator": current_locator,
        "assessment": loaded.get("assessment"),
        "head": head,
        "assessment_digest": actual_digest,
        "blockers": [],
    }


def _diagnose_explicit_locator_when_head_missing(
    root: str | Path,
    *,
    locator: Any,
    candidate_digest: str,
    impact_digest: str,
    head_reason: str,
) -> dict[str, Any] | None:
    """Classify an explicit locator against current C/I when no current-head exists.

    This does not treat the locator as S4 authority. It only preserves precise
    candidate/impact mismatch reasons when the current-head for (C, I) is missing.
    """
    if head_reason != "missing" or locator in (None, ""):
        return None
    loaded = resolve_knowledge_assessment(root, locator)
    if not loaded.get("ok"):
        return None
    assessment = loaded.get("assessment") or {}
    bound = ""
    candidate = assessment.get("candidate")
    if isinstance(candidate, dict):
        bound = str(candidate.get("candidate_digest") or "")
    bound_impact = str(assessment.get("impact_digest") or "")
    if bound != candidate_digest:
        return {
            "ok": False,
            "satisfied": False,
            "reason": "candidate_mismatch",
            "locator": locator,
            "assessment": assessment,
            "blockers": [
                "Knowledge Assessment candidate binding is stale for the "
                "current P6 candidate"
            ],
        }
    if bound_impact != impact_digest:
        return {
            "ok": False,
            "satisfied": False,
            "reason": "impact_mismatch",
            "locator": locator,
            "assessment": assessment,
            "blockers": [
                "Knowledge Assessment impact binding is stale for the "
                "current S3 knowledge-relevant impact set"
            ],
        }
    return None


def validate_current_head(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["Knowledge Assessment current head is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != HEAD_RECORD_TYPE:
        issues.append("record_type must be knowledge_assessment_head")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        issues.append("Knowledge Assessment current head schema_version must be 1")
    if not isinstance(data.get("candidate_digest"), str) or not data.get("candidate_digest"):
        issues.append("current head candidate_digest is required")
    if not isinstance(data.get("impact_digest"), str) or not data.get("impact_digest"):
        issues.append("current head impact_digest is required")
    locator = data.get("locator")
    if not isinstance(locator, str) or not LOCATOR_RE.fullmatch(locator):
        issues.append("current head locator is missing or not an allowed Assessment path")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not ASSESSMENT_ID_RE.fullmatch(record_id):
        issues.append("current head record_id is missing or malformed")
    digest = data.get("assessment_digest")
    if not isinstance(digest, str) or not HEX64_RE.fullmatch(digest):
        issues.append("current head assessment_digest must be the published Assessment digest")
    if (
        isinstance(record_id, str)
        and ASSESSMENT_ID_RE.fullmatch(record_id)
        and isinstance(locator, str)
        and LOCATOR_RE.fullmatch(locator)
        and locator != assessment_locator(record_id)
    ):
        issues.append(
            "current head record_id does not identify the same Assessment as locator"
        )
    return issues


def _publish_current_head(
    root: Path,
    *,
    candidate_digest: str,
    impact_digest: str,
    locator: str,
    record_id: str,
    assessment_digest: str,
) -> dict[str, Any]:
    payload = {
        "record_type": HEAD_RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "candidate_digest": candidate_digest,
        "impact_digest": impact_digest,
        "locator": locator,
        "record_id": record_id,
        "assessment_digest": assessment_digest,
    }
    issues = validate_current_head(payload)
    if issues:
        return {"ok": False, "blockers": issues}
    head_locator = current_head_locator(candidate_digest, impact_digest)
    path = current_head_path(root, head_locator)
    if path is None:
        return {"ok": False, "blockers": ["current-head locator is illegal"]}
    write_yaml_atomic(path, payload)
    return {"ok": True, "locator": head_locator, "head": payload, "blockers": []}


def validate_knowledge_assessment(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["Knowledge Assessment is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != RECORD_TYPE:
        issues.append("record_type must be knowledge_assessment")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        issues.append("Knowledge Assessment schema_version must be 1")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not ASSESSMENT_ID_RE.fullmatch(record_id):
        issues.append("Knowledge Assessment record_id is missing or malformed")
    if not _nonempty_text(data.get("created_at")):
        issues.append("Knowledge Assessment created_at is required")
    producer = data.get("producer")
    if not isinstance(producer, dict):
        issues.append("Knowledge Assessment producer is required")
    else:
        if producer.get("skill_id") != PRODUCER_SKILL:
            issues.append("Knowledge Assessment producer.skill_id must be understand")
        if producer.get("mode") not in PRODUCER_MODES:
            issues.append("Knowledge Assessment producer.mode must be refresh or full")
    candidate = data.get("candidate")
    digest = (
        (candidate or {}).get("candidate_digest")
        if isinstance(candidate, dict)
        else None
    )
    if not isinstance(digest, str) or not digest.strip():
        issues.append("Knowledge Assessment candidate.candidate_digest is required")
    if not isinstance(data.get("impact_digest"), str) or not data.get("impact_digest"):
        issues.append("Knowledge Assessment impact_digest is required")
    rows = data.get("assessments")
    if not isinstance(rows, list):
        issues.append("Knowledge Assessment assessments must be a list")
        return issues
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"assessments[{index}] must be a mapping")
            continue
        iid = row.get("impact_id")
        if not isinstance(iid, str) or not iid.strip():
            issues.append(f"assessments[{index}].impact_id is required")
        elif iid in seen:
            issues.append(f"duplicate Knowledge Assessment impact_id {iid}")
        else:
            seen.add(iid)
        if not _nonempty_text(row.get("class")):
            issues.append(f"assessments[{index}].class is required")
        if not _nonempty_text(row.get("path")):
            issues.append(f"assessments[{index}].path is required")
        outcome = row.get("outcome")
        if outcome is False or outcome is True:
            issues.append(
                f"assessments[{index}].outcome must not use boolean false for UNKNOWN"
            )
        elif outcome not in ASSESSMENT_OUTCOMES:
            issues.append(
                f"assessments[{index}].outcome must be SATISFIED, NEEDS_REFRESH, "
                "NEEDS_HUMAN, or UNKNOWN"
            )
        if "surfaces" in row and not isinstance(row.get("surfaces"), list):
            issues.append(f"assessments[{index}].surfaces must be a list")
        if "rationale" in row and row.get("rationale") is not None:
            if not isinstance(row.get("rationale"), str):
                issues.append(f"assessments[{index}].rationale must be text")
    return issues


def _observe_digest(root: Path) -> str:
    from scaffold_p6.candidate import observe_candidate

    candidate = observe_candidate(root)
    if not candidate.usable:
        return ""
    return candidate.digest


def _allocate_assessment_id(root: Path) -> str:
    used = {
        path.parent.name
        for path in (root / ASSESSMENT_ROOT).glob("ka-*/assessment.yaml")
    }
    for _ in range(64):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = f"ka-{stamp}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
    raise RuntimeError("unable to allocate unique Knowledge Assessment identity")


def _index_outcomes(outcomes: list[Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in outcomes or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("class") or "").strip()
        path = str(row.get("path") or "").replace("\\", "/").strip()
        if kind and path:
            out[(kind, path)] = row
    return out


def _surface_path(surface: str, impact: dict[str, str]) -> str | None:
    if surface == MODULE_DOCS:
        module_id = _module_id_from_impact(impact)
        if not module_id:
            return None
        return f"{MODULE_DOCS}/{module_id}.md"
    return surface


def _module_id_from_impact(impact: dict[str, str]) -> str:
    detail = str(impact.get("detail") or "")
    if detail.startswith("module "):
        return detail.split()[1].strip()
    return ""


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
