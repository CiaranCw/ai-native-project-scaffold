"""Test-owned Scenario-Aware Verification supporting plans. Not a canonical record."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import file_digest, read_yaml, sha256_text, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.sufficiency import (
    evaluate_sav_coverage as _evaluate_sav_coverage,
    structured_assertion_eligible,
    suite_strategy,
)


PLANS_ROOT = ".scaffold/runtime/test-plans"
HEADS_ROOT = ".scaffold/runtime/test-plans/heads"
RECORD_TYPE = "test_scenario_aware_plan"
HEAD_RECORD_TYPE = "test_scenario_aware_plan_head"
SCHEMA_VERSION = "1"
PRODUCER_SKILL = "test"
PLAN_ID_RE = re.compile(r"^sav-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
OBSERVABILITY = frozenset(
    {"SUFFICIENT", "INSUFFICIENT_OBSERVABILITY", "UNKNOWN"}
)
PO_STATUSES = frozenset({"SATISFIED", "UNSATISFIED", "INSUFFICIENT_OBSERVABILITY", "UNKNOWN"})


def task_contract_projection(task: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministic Task verification-authority projection for SAV currentness.

    Included: Task identity, scope, Task-level acceptance, Test-relevant
    constraints, Stage identities, Stage acceptance, requirement identities,
    and each requirement execution_binding.

    Excluded: record_revision, status, Develop Session IDs, Stage status,
    Stage/Task Completion Decisions, READY/control timestamps, and
    result-side Evidence/observed-outcome fields.
    """
    data = task if isinstance(task, dict) else {}
    stages = []
    for stage in data.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        stages.append(
            {
                "acceptance": str(stage.get("acceptance") or ""),
                "required_tests": _requirement_contracts(stage.get("required_tests")),
                "stage_id": str(stage.get("stage_id") or ""),
            }
        )
    stages.sort(key=lambda row: row["stage_id"])
    return {
        "acceptance": str(data.get("acceptance") or ""),
        "constraints": _constraint_contract(data.get("constraints")),
        "final_tests": _requirement_contracts(data.get("final_tests")),
        "record_id": str(data.get("record_id") or ""),
        "scope": _scope_contract(data.get("scope")),
        "stages": stages,
    }


def task_contract_digest(task: dict[str, Any] | None) -> str:
    """SHA-256 of the canonical YAML dump of task_contract_projection."""
    return sha256_text(yaml_lite.dump(task_contract_projection(task)))


def plan_locator(plan_id: str) -> str:
    return f"test-plans/{plan_id}/plan.yaml"


def head_locator(task_id: str, requirement_id: str) -> str:
    return f"test-plans/heads/{task_id}/{requirement_id}/head.yaml"


def reconstruct_sav_plan(
    root: str | Path,
    *,
    task_id: str,
    requirement_id: str,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fresh-Agent reconstruction from Test-owned head/locator authority."""
    host = Path(root)
    loaded_head = _load_head(host, task_id, requirement_id)
    if not loaded_head.get("ok"):
        return {
            "ok": False,
            "current": False,
            "blockers": list(loaded_head.get("blockers") or ["SAV plan head is missing"]),
            "task_id": task_id,
            "requirement_id": requirement_id,
        }
    head = loaded_head.get("head") or {}
    locator = str(head.get("locator") or "")
    loaded = load_sav_plan(host, locator)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "current": False,
            "blockers": list(loaded.get("blockers") or ["SAV plan is not reconstructable"]),
            "task_id": task_id,
            "requirement_id": requirement_id,
            "head": head,
        }
    plan = loaded.get("plan") or {}
    revalidated = revalidate_sav_plan(host, plan, task=task)
    if not revalidated.get("ok"):
        return {
            "ok": False,
            "current": False,
            "plan": plan,
            "head": head,
            "locator": locator,
            "plan_digest": loaded.get("plan_digest"),
            "task_id": plan.get("task_id") or task_id,
            "requirement_id": plan.get("requirement_id") or requirement_id,
            "profile_id": ((plan.get("binding") or {}).get("profile_id")),
            "scenario": plan.get("scenario") or {},
            "proof_obligations": list(plan.get("proof_obligations") or []),
            "blockers": list(revalidated.get("blockers") or ["SAV plan is not current applicable Test authority"]),
        }
    return {
        "ok": True,
        "current": True,
        "plan": plan,
        "head": head,
        "locator": locator,
        "plan_digest": loaded.get("plan_digest"),
        "task_id": plan.get("task_id"),
        "requirement_id": plan.get("requirement_id"),
        "profile_id": ((plan.get("binding") or {}).get("profile_id")),
        "scenario": plan.get("scenario") or {},
        "proof_obligations": list(plan.get("proof_obligations") or []),
        "blockers": [],
    }


def load_sav_plan(root: str | Path, locator: str) -> dict[str, Any]:
    host = Path(root)
    if not isinstance(locator, str) or ".." in locator.replace("\\", "/"):
        return {"ok": False, "blockers": ["SAV plan locator is illegal"]}
    if not locator.startswith("test-plans/") or not locator.endswith("/plan.yaml"):
        return {"ok": False, "blockers": ["SAV plan locator is illegal"]}
    path = host / ".scaffold/runtime" / locator
    if not path.is_file():
        return {"ok": False, "blockers": ["SAV plan is missing"]}
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"ok": False, "blockers": ["SAV plan is malformed or unreadable"]}
    issues = validate_sav_plan(data)
    if issues:
        return {"ok": False, "blockers": issues, "plan": data}
    assert isinstance(data, dict)
    if plan_locator(str(data.get("plan_id") or "")) != locator:
        return {
            "ok": False,
            "blockers": ["SAV plan locator does not match plan identity"],
            "plan": data,
        }
    return {
        "ok": True,
        "plan": data,
        "locator": locator,
        "plan_digest": file_digest(path),
        "blockers": [],
    }


def publish_sav_plan(
    root: str | Path,
    plan: dict[str, Any],
    *,
    bind_task_contract: bool = True,
) -> dict[str, Any]:
    host = Path(root)
    payload = dict(plan)
    payload.setdefault("record_type", RECORD_TYPE)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload["supporting"] = True
    payload["canonical"] = False
    payload.setdefault("producer", {"skill_id": PRODUCER_SKILL, "mode": "scoped_verification"})
    if not payload.get("plan_id"):
        payload["plan_id"] = _allocate_plan_id(host)
    payload.setdefault("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if bind_task_contract:
        live = load_task_book(host, str(payload.get("task_id") or ""))
        if live is not None:
            payload["task_contract_digest"] = task_contract_digest(live)
            if payload.get("task_revision") is None:
                revision = live.get("record_revision")
                if isinstance(revision, int):
                    payload["task_revision"] = revision
    issues = validate_sav_plan(payload)
    if issues:
        return {"ok": False, "blockers": issues, "plan": payload}
    locator = plan_locator(str(payload["plan_id"]))
    path = host / ".scaffold/runtime" / locator
    write_yaml_atomic(path, payload)
    digest = file_digest(path)
    task_id = str(payload.get("task_id") or "")
    requirement_id = str(payload.get("requirement_id") or "")
    revalidated = revalidate_sav_plan(host, payload)
    if not revalidated.get("ok"):
        return {
            "ok": False,
            "current": False,
            "locator": locator,
            "plan_id": payload["plan_id"],
            "plan_digest": digest,
            "plan": payload,
            "head": None,
            "blockers": list(
                revalidated.get("blockers")
                or ["SAV plan cannot become current-head without live Task authority"]
            ),
        }
    head = {
        "record_type": HEAD_RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "supporting": True,
        "canonical": False,
        "task_id": task_id,
        "requirement_id": requirement_id,
        "locator": locator,
        "plan_id": payload["plan_id"],
        "plan_digest": digest,
    }
    write_yaml_atomic(host / ".scaffold/runtime" / head_locator(task_id, requirement_id), head)
    return {
        "ok": True,
        "current": True,
        "locator": locator,
        "plan_id": payload["plan_id"],
        "plan_digest": digest,
        "plan": payload,
        "head": head,
        "blockers": [],
    }


def load_task_book(root: str | Path, task_id: str) -> dict[str, Any] | None:
    host = Path(root)
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    path = host / ".scaffold/tasks" / f"{task_id}.yaml"
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def revalidate_sav_plan(
    root: str | Path,
    plan: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    host = Path(root)
    blockers: list[str] = []
    task_id = str(plan.get("task_id") or "")
    if task is None:
        task = load_task_book(host, task_id)
    if task is None:
        blockers.append("SAV plan cannot be current without Task Book authority")
    else:
        if str(task.get("record_id") or "") != task_id:
            blockers.append("SAV plan task_id does not match the current Task Book")
        bound_contract = str(plan.get("task_contract_digest") or "").strip()
        if bound_contract:
            current_contract = task_contract_digest(task)
            if current_contract != bound_contract:
                blockers.append(
                    "SAV plan is stale versus current Task verification contract"
                )
        elif int(task.get("record_revision") or 0) != int(plan.get("task_revision") or 0):
            blockers.append("SAV plan is stale versus current Task revision")
        requirement_id = str(plan.get("requirement_id") or "")
        row = _requirement_row(task, requirement_id) if requirement_id else None
        if requirement_id and not row:
            blockers.append("SAV plan requirement_id is not in the current Task Book")
        binding = (plan.get("binding") or {}) if isinstance(plan.get("binding"), dict) else {}
        task_binding = (
            row.get("execution_binding")
            if isinstance(row, dict) and isinstance(row.get("execution_binding"), dict)
            else {}
        )
        if str(task_binding.get("kind") or "") != "test_profile":
            blockers.append("current requirement execution_binding.kind must be test_profile")
        plan_profile = str(binding.get("profile_id") or "")
        task_profile = str(task_binding.get("profile_id") or "")
        if not plan_profile or plan_profile != task_profile:
            blockers.append("SAV plan profile does not match Task execution_binding")
    if profile_id and str((plan.get("binding") or {}).get("profile_id") or "") not in {
        "",
        str(profile_id),
    }:
        blockers.append("SAV plan is not applicable to the selected Test profile")
    planned_candidate = str(plan.get("candidate_digest") or "")
    if planned_candidate:
        current = observe_candidate(host)
        if not current.usable or current.digest != planned_candidate:
            blockers.append(
                "SAV plan candidate digest does not match the current candidate; revalidation is required"
            )
    return {"ok": not blockers, "current": not blockers, "blockers": blockers}


def evaluate_sav_coverage(
    plan: dict[str, Any],
    *,
    evidence: list[dict[str, Any]],
    profile_results: dict[str, str],
    candidate_digest: str | None = None,
    caller_adequacy: Any = None,
) -> dict[str, Any]:
    """Map proof obligations to produced evidence. Names are not coverage."""
    return _evaluate_sav_coverage(
        plan,
        evidence=evidence,
        profile_results=profile_results,
        candidate_digest=candidate_digest,
        caller_adequacy=caller_adequacy,
    )


def validate_sav_plan(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["SAV plan is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != RECORD_TYPE:
        issues.append("record_type must be test_scenario_aware_plan")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        issues.append("SAV plan schema_version must be 1")
    if data.get("canonical") is True:
        issues.append("SAV plan must not claim canonical record authority")
    if data.get("supporting") is not True:
        issues.append("SAV plan must be marked supporting")
    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not PLAN_ID_RE.fullmatch(plan_id):
        issues.append("SAV plan_id is missing or malformed")
    for field in ("task_id", "requirement_id"):
        if not isinstance(data.get(field), str) or not str(data.get(field) or "").strip():
            issues.append(f"SAV plan {field} is missing")
    if data.get("task_revision") is None or not isinstance(data.get("task_revision"), int):
        issues.append("SAV plan task_revision must be an integer")
    contract = data.get("task_contract_digest")
    if contract not in (None, "") and (
        not isinstance(contract, str) or not HEX64_RE.fullmatch(str(contract))
    ):
        issues.append("SAV plan task_contract_digest must be a SHA-256 hex digest")
    binding = data.get("binding")
    if not isinstance(binding, dict):
        issues.append("SAV plan binding must be a mapping")
    else:
        if str(binding.get("kind") or "") != "test_profile":
            issues.append("SAV plan binding.kind must be test_profile")
        if not isinstance(binding.get("profile_id"), str) or not binding.get("profile_id"):
            issues.append("SAV plan binding.profile_id is missing")
    scenario = data.get("scenario")
    if not isinstance(scenario, dict):
        issues.append("SAV plan scenario must be a mapping")
    else:
        for field in ("initial_state", "action", "expected_result"):
            if not isinstance(scenario.get(field), str) or not str(scenario.get(field) or "").strip():
                issues.append(f"SAV plan scenario.{field} is missing")
    obligations = data.get("proof_obligations")
    if not isinstance(obligations, list) or not obligations:
        issues.append("SAV plan proof_obligations must be a non-empty list")
        return issues
    seen: set[str] = set()
    for index, item in enumerate(obligations):
        if not isinstance(item, dict):
            issues.append(f"SAV plan proof_obligations[{index}] must be a mapping")
            continue
        po_id = str(item.get("po_id") or "")
        if not po_id or po_id in seen:
            issues.append(f"SAV plan proof_obligations[{index}].po_id is missing or duplicated")
        seen.add(po_id)
        if not isinstance(item.get("obligation"), str) or not item.get("obligation"):
            issues.append(f"SAV plan proof_obligations[{index}].obligation is missing")
        if not isinstance(item.get("required"), bool):
            issues.append(f"SAV plan proof_obligations[{index}].required must be a boolean")
        if item.get("observability_status") not in OBSERVABILITY:
            issues.append(
                f"SAV plan proof_obligations[{index}].observability_status is unsupported"
            )
        if not isinstance(item.get("execution_strategy"), str) or not str(
            item.get("execution_strategy") or ""
        ).strip():
            issues.append(
                f"SAV plan proof_obligations[{index}].execution_strategy is missing"
            )
        for field in ("observable_signals", "assertions", "evidence_requirements"):
            value = item.get(field)
            if not isinstance(value, list) or not value:
                issues.append(
                    f"SAV plan proof_obligations[{index}].{field} is missing"
                )
        if item.get("candidate_digest") not in (None, "") and (
            not isinstance(item.get("candidate_digest"), str)
            or not HEX64_RE.fullmatch(str(item.get("candidate_digest")))
        ):
            issues.append(
                f"SAV plan proof_obligations[{index}].candidate_digest must be a SHA-256 digest"
            )
    candidate = data.get("candidate_digest")
    if candidate not in (None, "") and (
        not isinstance(candidate, str) or not HEX64_RE.fullmatch(str(candidate))
    ):
        issues.append("SAV plan candidate_digest must be a SHA-256 hex digest")
    return issues


def _load_head(host: Path, task_id: str, requirement_id: str) -> dict[str, Any]:
    path = host / ".scaffold/runtime" / head_locator(task_id, requirement_id)
    if not path.is_file():
        return {"ok": False, "blockers": ["SAV plan current-head is missing"]}
    try:
        head = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"ok": False, "blockers": ["SAV plan current-head is malformed or unreadable"]}
    if not isinstance(head, dict):
        return {"ok": False, "blockers": ["SAV plan current-head is not a mapping"]}
    if head.get("canonical") is True or head.get("supporting") is not True:
        return {"ok": False, "blockers": ["SAV plan current-head is not supporting authority"]}
    if str(head.get("task_id") or "") != task_id or str(head.get("requirement_id") or "") != requirement_id:
        return {"ok": False, "blockers": ["SAV plan current-head identity does not match the request"]}
    locator = str(head.get("locator") or "")
    loaded = load_sav_plan(host, locator)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "blockers": list(loaded.get("blockers") or ["SAV plan is not reconstructable"]),
            "head": head,
        }
    plan = loaded.get("plan") or {}
    if loaded.get("plan_digest") != str(head.get("plan_digest") or ""):
        return {
            "ok": False,
            "blockers": ["SAV plan current-head digest does not match published plan bytes"],
            "head": head,
        }
    if str(head.get("plan_id") or "") != str(plan.get("plan_id") or ""):
        return {
            "ok": False,
            "blockers": ["SAV plan current-head plan_id does not match published plan"],
            "head": head,
        }
    if str(head.get("task_id") or "") != str(plan.get("task_id") or "") or str(
        head.get("requirement_id") or ""
    ) != str(plan.get("requirement_id") or ""):
        return {
            "ok": False,
            "blockers": ["SAV plan current-head task/requirement identity does not match published plan"],
            "head": head,
        }
    return {"ok": True, "head": head, "blockers": []}


def _scope_contract(scope: Any) -> dict[str, list[str]]:
    data = scope if isinstance(scope, dict) else {}

    def _strs(key: str) -> list[str]:
        return sorted(
            str(item)
            for item in (data.get(key) or [])
            if item is not None and str(item)
        )

    return {
        "exclude": _strs("exclude"),
        "modules": _strs("modules"),
        "paths": _strs("paths"),
    }


def _constraint_contract(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return [{str(key): value[key] for key in sorted(value, key=str)}]
    return [str(value)]


def _requirement_contracts(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        binding = (
            item.get("execution_binding")
            if isinstance(item.get("execution_binding"), dict)
            else {}
        )
        out.append(
            {
                "execution_binding": {
                    "kind": str(binding.get("kind") or ""),
                    "profile_id": str(binding.get("profile_id") or ""),
                },
                "requirement_id": str(item.get("requirement_id") or ""),
            }
        )
    out.sort(key=lambda row: row["requirement_id"])
    return out


def _requirement_row(task: dict[str, Any], requirement_id: str) -> dict[str, Any] | None:
    for collection in ("final_tests",):
        for item in task.get(collection) or []:
            if isinstance(item, dict) and str(item.get("requirement_id") or "") == requirement_id:
                return item
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for item in stage.get("required_tests") or []:
            if isinstance(item, dict) and str(item.get("requirement_id") or "") == requirement_id:
                return item
    return None


def _suite_strategy(item: dict[str, Any]) -> bool:
    return suite_strategy(item)


def _structured_assertion_eligible(
    item: Any,
    *,
    candidate_digest: str | None = None,
) -> bool:
    return structured_assertion_eligible(item, candidate_digest=candidate_digest)


def _allocate_plan_id(root: Path) -> str:
    used = set()
    folder = root / PLANS_ROOT
    if folder.is_dir():
        used = {path.name for path in folder.iterdir() if path.is_dir()}
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(32):
        candidate = f"sav-{utc}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
        utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raise RuntimeError("unable to allocate unique SAV plan identity")
