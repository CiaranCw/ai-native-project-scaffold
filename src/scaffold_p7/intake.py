"""P7-owned bounded Task Intake. Publishes Task authority; never writes source."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import sha256_text
from scaffold_p5.ownership import normalize_project_path
from scaffold_p7.mutation import supporting_path_declaration_issues
from scaffold_p7.schemas import execution_binding_issues, validate_task_book
from scaffold_p7.tasks import (
    allocate_task_id,
    publish_initial_task,
    publish_task,
    task_intake_lock,
    task_revision,
    valid_tasks,
)


MATERIAL_FIELDS = frozenset({"goal", "scope", "acceptance", "stages", "tests"})
KNOWLEDGE_FIELDS = frozenset({"scope", "rules", "ownership", "tests"})


@dataclass
class IntakeDecision:
    outcome: str
    blockers: list[str] = field(default_factory=list)
    task: dict[str, Any] | None = None
    task_path: str = ""
    mutation: str = "none"
    reused: bool = False
    proposal: dict[str, Any] | None = None
    proposal_digest: str = ""
    grounding: dict[str, Any] = field(default_factory=dict)
    human_gate: dict[str, Any] = field(default_factory=dict)


def prepare_proposal(
    value: Any, root: Path | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, dict):
        return None, ["Task proposal must be a structured mapping"]
    issues: list[str] = []
    title = _text(value.get("title"))
    goal = _text(value.get("goal"))
    acceptance = _text(value.get("acceptance"))
    if not title:
        issues.append("Task proposal title is required")
    if not goal:
        issues.append("Task proposal goal is required")
    if not acceptance:
        issues.append("Task proposal acceptance is required")

    scope, scope_issues = _scope(value.get("scope"), root)
    issues.extend(scope_issues)
    stages, stage_issues = _stages(value.get("stages"))
    issues.extend(stage_issues)
    final_tests, final_issues = _tests(value.get("final_tests"), "final_tests")
    issues.extend(final_issues)
    if issues:
        return None, sorted(set(issues))
    assert scope is not None
    return {
        "title": title,
        "goal": goal,
        "acceptance": acceptance,
        "scope": scope,
        "stages": stages,
        "final_tests": final_tests,
    }, []


def assess_grounding(
    structured_intent: Any,
    grounding: Any,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(structured_intent, dict):
        issues.append("Agent interpretation must provide structured intent")
        return _grounding_result(False, False, issues, [], [])
    if structured_intent.get("kind") != "develop":
        issues.append("Task Intake requires structured intent kind=develop")
    action = structured_intent.get("action")
    if action not in {"implement", "plan", "activate"}:
        issues.append("structured Develop intent action is missing or unsupported")
    if not _text(structured_intent.get("request")):
        issues.append("current human request text is missing from structured intent")
    if not isinstance(grounding, dict):
        issues.append("Task proposal grounding is missing")
        return _grounding_result(False, False, issues, [], [])

    intent_fields = _string_set(grounding.get("intent_fields"))
    knowledge_fields = _string_set(grounding.get("knowledge_fields"))
    uncertainties = _string_list(grounding.get("uncertainties"))
    material_decisions = _string_list(grounding.get("material_decisions"))
    missing_intent = sorted(MATERIAL_FIELDS - intent_fields)
    missing_knowledge = sorted(KNOWLEDGE_FIELDS - knowledge_fields)
    if missing_intent:
        issues.append(
            "human intent does not ground material proposal fields: "
            + ", ".join(missing_intent)
        )
    if missing_knowledge:
        issues.append(
            "project authority does not ground material proposal fields: "
            + ", ".join(missing_knowledge)
        )
    if uncertainties:
        issues.append("material uncertainty remains: " + "; ".join(uncertainties))
    if material_decisions:
        issues.append(
            "material inferred decisions require human review: "
            + "; ".join(material_decisions)
        )
    grounded = not issues
    direct_issues: list[str] = []
    if action == "implement":
        if structured_intent.get("explicit_implementation") is not True:
            direct_issues.append("current intent does not explicitly request implementation")
        authorized, authorized_issues = prepare_proposal(
            structured_intent.get("authorized_proposal")
        )
        if authorized_issues or authorized is None:
            direct_issues.append(
                "structured human intent does not contain a complete authorized proposal"
            )
        elif authorized != proposal:
            direct_issues.append(
                "Task proposal materially exceeds or differs from structured human intent"
            )
    else:
        direct_issues.append("current intent does not request direct implementation")
    direct = bool(grounded and not direct_issues)
    result = _grounding_result(
        grounded,
        direct,
        issues,
        uncertainties,
        material_decisions,
    )
    result["direct_activation_issues"] = sorted(set(direct_issues))
    return result


def proposal_digest(proposal: dict[str, Any]) -> str:
    return sha256_text(yaml_lite.dump(proposal))


def task_proposal(task: dict[str, Any]) -> dict[str, Any]:
    stages = []
    for index, stage in enumerate(task.get("stages") or []):
        if not isinstance(stage, dict):
            continue
        stages.append(
            {
                "stage_id": str(stage.get("stage_id") or f"stage-{index + 1}"),
                "goal": _text(stage.get("goal")),
                "acceptance": _text(stage.get("acceptance")),
                "required_tests": _semantic_tests(stage.get("required_tests")),
            }
        )
    return {
        "title": _text(task.get("title")),
        "goal": _text(task.get("goal")),
        "acceptance": _text(task.get("acceptance")),
        "scope": {
            "paths": _semantic_paths((task.get("scope") or {}).get("paths")),
            "modules": sorted(_string_set((task.get("scope") or {}).get("modules"))),
            "exclude": _semantic_paths((task.get("scope") or {}).get("exclude")),
            "supporting_paths": _semantic_paths(
                (task.get("scope") or {}).get("supporting_paths")
            ),
        },
        "stages": stages,
        "final_tests": _semantic_tests(task.get("final_tests")),
    }


def intake_task(
    root: Path,
    *,
    proposal: dict[str, Any],
    baseline: dict[str, Any],
    grounding: dict[str, Any],
) -> IntakeDecision:
    digest = proposal_digest(proposal)
    direct = grounding.get("direct_activation") is True
    grounded = grounding.get("fully_grounded") is True
    if not grounded:
        return IntakeDecision(
            outcome="NEEDS_HUMAN",
            blockers=list(grounding.get("issues") or ["Task proposal is not fully grounded"]),
            proposal=proposal,
            proposal_digest=digest,
            grounding=grounding,
            human_gate=_gate(
                observed="A development request was interpreted, but material plan authority is incomplete.",
                stopped="Task activation would exceed established human/project authority.",
                action="Clarify the listed scope, acceptance, stages, tests, or design decisions.",
                approved="A grounded proposal can be published as DRAFT or IN_PROGRESS.",
            ),
        )

    with task_intake_lock(root):
        tasks, task_blockers = valid_tasks(root)
        if task_blockers:
            return IntakeDecision(
                outcome="NEEDS_HUMAN",
                blockers=task_blockers,
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
                human_gate=_gate(
                    observed="Existing Task Book authority is malformed or ambiguous.",
                    stopped="Task Intake cannot safely compare or publish canonical authority.",
                    action="Resolve the reported Task Book conflict.",
                    approved="Task Intake can be retried without overwriting existing Tasks.",
                ),
            )
        matches = [
            task
            for task in tasks
            if proposal_digest(task_proposal(task)) == digest
        ]
        if len(matches) > 1:
            return IntakeDecision(
                outcome="NEEDS_HUMAN",
                blockers=["multiple authoritative Task Books match this proposal"],
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
                human_gate=_gate(
                    observed="Multiple canonical Tasks describe the same proposed work.",
                    stopped="Choosing one would create authority ambiguity.",
                    action="Select or reconcile the intended Task explicitly.",
                    approved="The selected Task can be reused without altering the others.",
                ),
            )
        if matches:
            return _reuse_match(
                root,
                matches[0],
                proposal,
                digest,
                grounding,
                direct,
                baseline,
            )

        status = "IN_PROGRESS" if direct else "DRAFT"
        task = _build_task(
            root,
            proposal=proposal,
            baseline=baseline,
            status=status,
        )
        publication = publish_initial_task(root, task)
        if not publication.ok or publication.task is None:
            return IntakeDecision(
                outcome="BLOCKED",
                blockers=list(publication.blockers),
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
                human_gate=_gate(
                    observed="The bounded Task proposal was ready for publication.",
                    stopped="Atomic canonical Task publication failed or conflicted.",
                    action="Retry after resolving the publication conflict.",
                    approved="No existing Task will be overwritten.",
                ),
            )
        path = f".scaffold/tasks/{publication.task['record_id']}.yaml"
        if status == "IN_PROGRESS":
            return IntakeDecision(
                outcome="COMPLETED",
                task=publication.task,
                task_path=path,
                mutation="task_book",
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
                human_gate=_gate(
                    observed="The explicit implementation request fully grounds the bounded Task.",
                    stopped="Work has not stopped; source mutation has not started yet.",
                    action="No additional Task-creation approval is required.",
                    approved="Normal Develop may consume the canonical IN_PROGRESS Task.",
                ),
            )
        return IntakeDecision(
            outcome="NEEDS_HUMAN",
            task=publication.task,
            task_path=path,
            mutation="task_book",
            proposal=proposal,
            proposal_digest=digest,
            grounding=grounding,
            human_gate=_gate(
                observed="A grounded Task proposal was published as DRAFT.",
                stopped="The proposal is not yet accepted as the active development plan.",
                action="Explicitly activate this DRAFT if it matches the intended work.",
                approved="Activation publishes DRAFT to IN_PROGRESS via expected revision.",
            ),
        )


def _reuse_match(
    root: Path,
    task: dict[str, Any],
    proposal: dict[str, Any],
    digest: str,
    grounding: dict[str, Any],
    direct: bool,
    baseline: dict[str, Any],
) -> IntakeDecision:
    status = task.get("status")
    path = f".scaffold/tasks/{task['record_id']}.yaml"
    if status == "IN_PROGRESS":
        return IntakeDecision(
            outcome="COMPLETED",
            task=task,
            task_path=path,
            reused=True,
            proposal=proposal,
            proposal_digest=digest,
            grounding=grounding,
            human_gate=_gate(
                observed="A matching canonical Task is already IN_PROGRESS.",
                stopped="Work has not stopped.",
                action="Reuse the existing Task identity.",
                approved="Normal Develop may consume the existing Task.",
            ),
        )
    if status == "DRAFT" and direct:
        planned = task.get("baseline") if isinstance(task.get("baseline"), dict) else {}
        current = {
            "kind": baseline.get("kind") or "unavailable",
            "value": baseline.get("revision", baseline.get("value")),
        }
        if {
            "kind": planned.get("kind"),
            "value": planned.get("value"),
        } != current:
            return IntakeDecision(
                outcome="NEEDS_HUMAN",
                blockers=[
                    "matching DRAFT baseline differs from the current repository basis"
                ],
                task=task,
                task_path=path,
                reused=True,
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
                human_gate=_gate(
                    observed="A matching DRAFT was planned against another repository basis.",
                    stopped="Current intent cannot activate stale planning authority silently.",
                    action="Review or regenerate the Task proposal against current project truth.",
                    approved="A current proposal may then be activated by expected revision.",
                ),
            )
        expected = task_revision(task)
        if expected is None:
            return IntakeDecision(
                outcome="BLOCKED",
                blockers=["matching DRAFT has no usable record_revision"],
                task=task,
                task_path=path,
                reused=True,
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
            )
        updated = dict(task)
        updated["status"] = "IN_PROGRESS"
        updated["updated_at"] = _now()
        publication = publish_task(
            root / path,
            updated,
            expected_revision=expected,
        )
        if not publication.ok or publication.task is None:
            return IntakeDecision(
                outcome="BLOCKED",
                blockers=list(publication.blockers),
                task=publication.task or task,
                task_path=path,
                reused=True,
                proposal=proposal,
                proposal_digest=digest,
                grounding=grounding,
            )
        return IntakeDecision(
            outcome="COMPLETED",
            task=publication.task,
            task_path=path,
            mutation="task_book",
            reused=True,
            proposal=proposal,
            proposal_digest=digest,
            grounding=grounding,
            human_gate=_gate(
                observed="A matching canonical DRAFT was found.",
                stopped="The current explicit implementation request validly activates it.",
                action="No further Task activation action is required.",
                approved="Normal Develop may consume the activated Task.",
            ),
        )
    if status == "DRAFT":
        reason = "matching Task is DRAFT and is not accepted as active"
        action = "Explicitly request implementation or activation of this bounded DRAFT."
    elif status == "READY_FOR_REVIEW":
        reason = "matching Task is already READY_FOR_REVIEW and cannot be reopened silently"
        action = "Review the existing Task state or explicitly define new work."
    else:
        reason = "matching Task is CANCELED and cannot be resurrected silently"
        action = "Explicitly define new work under a new Task identity."
    return IntakeDecision(
        outcome="NEEDS_HUMAN",
        blockers=[reason],
        task=task,
        task_path=path,
        reused=True,
        proposal=proposal,
        proposal_digest=digest,
        grounding=grounding,
        human_gate=_gate(
            observed=f"A matching canonical Task exists with status {status}.",
            stopped=reason,
            action=action,
            approved="Existing historical/state authority remains unchanged until then.",
        ),
    )


def _build_task(
    root: Path,
    *,
    proposal: dict[str, Any],
    baseline: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    now = _now()
    task = {
        "record_type": "task_book",
        "schema_version": "1",
        "record_id": allocate_task_id(root),
        "record_revision": 1,
        "created_at": now,
        "updated_at": now,
        "title": proposal["title"],
        "goal": proposal["goal"],
        "acceptance": proposal["acceptance"],
        "baseline": {
            "kind": baseline.get("kind") or "unavailable",
            "value": baseline.get("revision", baseline.get("value")),
        },
        "scope": dict(proposal["scope"]),
        "status": status,
        "stages": [
            {
                "stage_id": stage["stage_id"],
                "goal": stage["goal"],
                "acceptance": stage["acceptance"],
                "status": "PENDING",
                "required_tests": list(stage["required_tests"]),
            }
            for stage in proposal["stages"]
        ],
        "final_tests": list(proposal["final_tests"]),
        "develop_session_ids": [],
    }
    issues = validate_task_book(task, expected_id=str(task["record_id"]))
    if issues:
        raise ValueError("invalid normalized Task proposal: " + "; ".join(issues))
    return task


def _scope(
    value: Any, root: Path | None = None
) -> tuple[dict[str, list[str]] | None, list[str]]:
    if not isinstance(value, dict):
        return None, ["Task proposal scope must be a mapping"]
    issues: list[str] = []
    out: dict[str, list[str]] = {}
    for field in ("paths", "modules", "exclude", "supporting_paths"):
        raw = value.get(field, [])
        if not isinstance(raw, list) or any(not _text(item) for item in raw):
            issues.append(f"Task proposal scope.{field} must be a string list")
            out[field] = []
        elif field == "modules":
            out[field] = sorted(set(str(item).strip() for item in raw))
        else:
            normalized = [
                normalize_project_path(item, area=None)
                for item in raw
            ]
            if any(not item for item in normalized):
                issues.append(
                    f"Task proposal scope.{field} contains an invalid project path"
                )
            out[field] = sorted(set(item for item in normalized if item))
    if not out["paths"] and not out["modules"]:
        issues.append("Task proposal scope requires at least one path or module")
    overlap = sorted(set(out["paths"]).intersection(out["exclude"]))
    if overlap:
        issues.append("Task proposal scope includes and excludes: " + ", ".join(overlap))
    issues.extend(
        supporting_path_declaration_issues(
            out.get("supporting_paths") or [],
            out.get("paths") or [],
            root,
        )
    )
    return out, issues


def _stages(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list) or not value:
        return [], ["Task proposal requires at least one stage"]
    out: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            issues.append(f"Task proposal stage {index} must be a mapping")
            continue
        stage_id = _text(item.get("stage_id")) or f"stage-{index + 1}"
        goal = _text(item.get("goal"))
        acceptance = _text(item.get("acceptance"))
        tests, test_issues = _tests(
            item.get("required_tests", []),
            f"stage {stage_id} required_tests",
        )
        issues.extend(test_issues)
        if stage_id in seen:
            issues.append(f"duplicate Task proposal stage_id {stage_id}")
        seen.add(stage_id)
        if not goal:
            issues.append(f"Task proposal stage {stage_id} goal is required")
        if not acceptance:
            issues.append(f"Task proposal stage {stage_id} acceptance is required")
        out.append(
            {
                "stage_id": stage_id,
                "goal": goal,
                "acceptance": acceptance,
                "required_tests": tests,
            }
        )
    return out, issues


def _tests(value: Any, field: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list):
        return [], [f"Task proposal {field} must be a list"]
    out: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    by_requirement: dict[str, dict[str, Any]] = {}
    for item in value:
        row, item_issues = _normalize_test_ref(item, field)
        if item_issues:
            issues.extend(item_issues)
            continue
        if row is None:
            return [], [f"Task proposal {field} contains an invalid test id"]
        requirement_id = str(row["requirement_id"])
        key = _test_identity_key(row)
        prior = by_requirement.get(requirement_id)
        if prior is not None and prior != row:
            issues.append(
                f"Task proposal {field} has conflicting execution_binding "
                f"for {requirement_id}"
            )
            continue
        if key in seen:
            continue
        seen[key] = row
        by_requirement[requirement_id] = row
        out.append(row)
    out.sort(key=_test_sort_key)
    return out, issues


def _semantic_tests(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value or []:
        row, issues = _normalize_test_ref(item, "required_tests")
        if row is None or issues:
            continue
        key = _test_identity_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=_test_sort_key)
    return out


def _normalize_test_ref(
    item: Any,
    field: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    identifier = item.get("requirement_id") if isinstance(item, dict) else item
    text = _text(identifier)
    if not text:
        return None, []
    if not isinstance(item, dict):
        return {"requirement_id": text}, []
    if "execution_binding" not in item or item.get("execution_binding") is None:
        return {"requirement_id": text}, []
    binding = item.get("execution_binding")
    issues = execution_binding_issues(binding, field)
    if issues:
        return None, issues
    profile_id = str(binding.get("profile_id")).strip()
    return {
        "requirement_id": text,
        "execution_binding": {
            "kind": "test_profile",
            "profile_id": profile_id,
        },
    }, []


def _test_identity_key(row: dict[str, Any]) -> tuple[str, str]:
    binding = row.get("execution_binding")
    profile_id = ""
    if isinstance(binding, dict):
        profile_id = _text(binding.get("profile_id"))
    return str(row.get("requirement_id") or ""), profile_id


def _test_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return _test_identity_key(row)


def _semantic_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [
        normalize_project_path(item, area=None)
        for item in value
        if _text(item)
    ]
    return sorted(set(item for item in normalized if item))


def _grounding_result(
    grounded: bool,
    direct: bool,
    issues: list[str],
    uncertainties: list[str],
    material_decisions: list[str],
) -> dict[str, Any]:
    return {
        "fully_grounded": grounded,
        "direct_activation": direct,
        "issues": sorted(set(issues)),
        "uncertainties": uncertainties,
        "material_decisions": material_decisions,
    }


def _gate(
    *,
    observed: str,
    stopped: str,
    action: str,
    approved: str,
) -> dict[str, Any]:
    return {
        "observed": observed,
        "why_stopped": stopped,
        "human_action_required": action,
        "if_approved": approved,
        "remains_unchanged": (
            "No source, Commit, Push, Submit authorization, or project governance "
            "is changed by this Task Intake result."
        ),
    }


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({_text(item) for item in value if _text(item)})


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


INTAKE_B64_RE = re.compile(r"^[A-Za-z0-9+/_-]+=*$")

# Non-authoritative pre-Develop transport. This path stays Scaffold authority
# for every ordinary mutation check. The first-use gate's exact-file Write
# exception does not reclassify it as product, Task, Session, or evidence.
INTAKE_STAGING_REL = ".scaffold/transport/develop-intake.json"


def canonical_intake_file_argument(raw: str | None) -> str | None:
    """Return the staging path when ``raw`` is that exact relative token."""
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or text.startswith("~"):
        return None
    if len(text) >= 2 and text[1] == ":":
        return None
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if text != INTAKE_STAGING_REL:
        return None
    return text


def _path_is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    try:
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _intake_staging_destination(host: str | Path) -> tuple[Path | None, str | None]:
    """Resolve the canonical staging file without following an escaping link."""
    try:
        host_root = Path(host).resolve()
    except OSError:
        return None, "intake staging path escapes the host"
    current = host_root
    for part in INTAKE_STAGING_REL.split("/"):
        if _path_is_link(current):
            return None, "intake staging path must not be a symlink"
        current = current / part
        if _path_is_link(current):
            return None, "intake staging path must not be a symlink"
    if current.exists():
        try:
            resolved = current.resolve()
            relative = resolved.relative_to(host_root).as_posix()
        except (OSError, ValueError):
            return None, "intake staging path escapes the host"
        if relative != INTAKE_STAGING_REL:
            return None, "intake staging path escapes the host"
    return current, None


def read_intake_staging_file(
    host: str | Path,
    raw_argument: str | None,
) -> tuple[str | None, str | None]:
    """Read UTF-8 JSON text from the canonical staging file only."""
    if canonical_intake_file_argument(raw_argument) is None:
        return None, (
            "intake file must be the canonical relative staging path "
            f"{INTAKE_STAGING_REL}"
        )
    destination, error = _intake_staging_destination(host)
    if error or destination is None:
        return None, error or "intake staging path escapes the host"
    if not destination.is_file():
        return None, "intake staging file is missing"
    try:
        text = destination.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, "intake staging file is not UTF-8 text"
    except OSError:
        return None, "intake staging file is not readable"
    return text, None


def consume_intake_staging_file(host: str | Path) -> None:
    """Remove the staging file after a Task record has been published.

    A symlink, an escaped path, or a delete failure leaves the file in place.
    The file is not lifecycle authority either way.
    """
    destination, error = _intake_staging_destination(host)
    if error or destination is None or not destination.is_file():
        return
    if _path_is_link(destination):
        return
    try:
        destination.unlink()
    except OSError:
        return
    parent = destination.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        return


def load_intake_envelope_flags(
    json_text: str | None,
    b64_text: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse installed-CLI intake flags. Missing flags return (None, None)."""
    json_raw = (json_text or "").strip() or None
    b64_raw = (b64_text or "").strip() or None
    if json_raw and b64_raw:
        return None, "provide only one of --intake-json or --intake-json-b64"
    if not json_raw and not b64_raw:
        return None, None
    if b64_raw:
        if not INTAKE_B64_RE.fullmatch(b64_raw):
            return None, "intake JSON base64 is malformed"
        padded = b64_raw + ("=" * ((4 - len(b64_raw) % 4) % 4))
        try:
            decoded = base64.b64decode(padded, validate=False)
            json_raw = decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            try:
                json_raw = base64.urlsafe_b64decode(padded).decode("utf-8")
            except (ValueError, UnicodeDecodeError, binascii.Error):
                return None, "intake JSON base64 could not be decoded"
    try:
        payload = json.loads(json_raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "intake JSON is not parseable"
    return parse_intake_envelope(payload)


def parse_intake_envelope(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "Develop intake envelope must be a JSON object"
    structured_intent = payload.get("structured_intent")
    proposal = payload.get("proposal")
    grounding = payload.get("grounding")
    if not isinstance(structured_intent, dict):
        return None, "Develop intake structured_intent must be a mapping"
    if structured_intent.get("kind") != "develop":
        return None, "Develop intake structured_intent.kind must be develop"
    if not isinstance(proposal, dict):
        return None, "Develop intake proposal must be a mapping"
    if not isinstance(grounding, dict):
        return None, "Develop intake grounding must be a mapping"
    return {
        "structured_intent": structured_intent,
        "proposal": proposal,
        "grounding": grounding,
    }, None
