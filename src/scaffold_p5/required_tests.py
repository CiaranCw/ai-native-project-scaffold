"""Understand publication of a project-declared Required Test Set.

The Agent proposal and its plan digest are transport. They do not approve
the required set. Authority comes from ``docs/project/required-test-policy.yaml``,
which Understand does not write. Publication binds that file's digest, each
declared source, the effective command definition, and the profile execution
fields.

Discovery confidence on ``tests.yaml`` is left unchanged. HUMAN_OBSERVATION
publication and task_fact evidence hardening are not part of this authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import COMMANDS_YAML, PROJECT_YAML, TESTS_YAML
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.policy_authority import POLICY_REL, evaluate_policy_acceptance
from scaffold_p5.schemas import (
    REQUIRED_AUTHORITY_FORMAT,
    REQUIRED_AUTHORITY_FORMAT_KEY,
    resolve_ownership,
    whole_file_mutation_allowed,
)
from scaffold_p6.contract import command_execution_allowed


ACTION = "required_tests"
GROUNDING_SCHEMA = "required-tests-1"
STAGING_REL = ".scaffold/transport/required-tests.json"
IDENTITY_BOUNDARY = (
    "argv, source locator, package.json script body or the declared source "
    "file bytes, and profile execution fields; transitive dependencies and "
    "the package-manager binary are outside this boundary"
)
_PROPOSAL_KEYS = frozenset({"publish", "required_profile_ids", "zero_required"})
_POLICY_KEYS = frozenset({"schema_version", "kind", "policy", "required_sources"})


def establish_required_tests(
    root: str | Path,
    *,
    proposal: dict[str, Any] | None,
    plan_digest: str | None = None,
    staging_path: str | None = None,
) -> dict[str, Any]:
    """Preview, or apply when ``plan_digest`` matches the live plan.

    Apply does not read a Test report and does not change discovery confidence.
    """
    host = Path(root)
    parsed, error = parse_proposal(proposal)
    if error:
        return _blocked(error)
    ownership_error = _tests_write_allowed(host)
    if ownership_error:
        return _blocked(ownership_error)
    current, current_error = _load_contract(host)
    if current_error:
        return _blocked(current_error)
    commands, command_error = _load_commands(host)
    if command_error:
        return _blocked(command_error)
    plan, plan_error = build_plan(host, current, commands, parsed)
    if plan_error:
        return _blocked(plan_error)
    digest = plan_digest_of(plan)
    preview = {
        "ok": True,
        "action": ACTION,
        "mode": "preview",
        "plan_digest": digest,
        "plan": plan,
        "wrote": False,
        "artifacts": [],
        "blockers": [],
        "evidence_currentness": (
            "required-tests apply does not consume a Test report; "
            "rerun official Test after publication before TEST_COMPLETE"
        ),
    }
    if not plan_digest:
        return preview
    supplied = str(plan_digest).strip().lower()
    if supplied != digest:
        return _blocked(
            "plan digest does not match the current required-tests plan; "
            "preview again and apply that exact digest"
        )
    identity_error = record_required_format_identity(host)
    if identity_error:
        return _blocked(identity_error)
    published = publish_plan(current, plan, digest)
    try:
        write_yaml_atomic(host / TESTS_YAML, published)
    except OSError as exc:
        return _blocked(
            "required authority publication did not finish writing "
            f"{TESTS_YAML} ({type(exc).__name__}). The {REQUIRED_AUTHORITY_FORMAT} "
            "format identity is already recorded, so this project cannot fall "
            "back to a legacy VERIFIED contract. Retry understand refresh "
            "--action required_tests."
        )
    _retire_staging(host, staging_path)
    return {
        **preview,
        "mode": "apply",
        "wrote": True,
        "artifacts": [TESTS_YAML],
    }


def parse_proposal(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "required-tests proposal must be a JSON object"
    unknown = sorted(set(raw) - _PROPOSAL_KEYS)
    if unknown:
        return None, "required-tests proposal has unknown fields: " + ", ".join(unknown)
    if raw.get("publish") is not True:
        return None, (
            "required-tests proposal must set publish true; "
            "the proposal is transport and is not required-set approval"
        )
    zero = raw.get("zero_required", None)
    if zero is not None and not isinstance(zero, bool):
        return None, "zero_required must be a boolean"
    ids = raw.get("required_profile_ids", None)
    normalized: list[str] | None = None
    if ids is not None:
        if not isinstance(ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in ids
        ):
            return None, "required_profile_ids must be a list of nonempty strings"
        normalized = [item.strip() for item in ids]
        if len(normalized) != len(set(normalized)):
            return None, "required_profile_ids contains a duplicate profile id"
    if zero is True and normalized:
        return None, "zero_required conflicts with a non-empty required_profile_ids list"
    return {
        "publish": True,
        "zero_required": zero,
        "required_profile_ids": None if normalized is None else sorted(normalized),
    }, None


def build_plan(
    root: Path,
    tests_doc: dict[str, Any],
    commands_doc: dict[str, Any],
    proposal: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if str(tests_doc.get("confidence") or "") == "CONFLICTING":
        return None, (
            "discovery confidence CONFLICTING cannot establish required authority. "
            "UNKNOWN and INFERRED discovery confidence remain separate from "
            "required-set authority."
        )
    applicability = str(tests_doc.get("applicability") or "")
    if applicability not in {"APPLICABLE", "NOT_APPLICABLE"}:
        return None, (
            "tests.yaml applicability must be APPLICABLE or NOT_APPLICABLE "
            "before required authority can be published; run understand refresh"
        )
    profiles = _profile_index(tests_doc)
    if profiles is None:
        return None, "tests.yaml profiles must be a list of mappings"
    policy, policy_error = load_policy(root)
    if policy_error:
        return None, policy_error
    assert policy is not None
    acceptance = evaluate_policy_acceptance(root)
    if not acceptance.get("ok"):
        return None, str((acceptance.get("blockers") or ["policy is not accepted"])[0])
    policy["binding"]["acceptance"] = {
        "source": acceptance["source"],
        "version": acceptance["version"],
        "digest": acceptance["digest"],
    }
    if policy["policy"] == "zero_required":
        if applicability == "NOT_APPLICABLE" and policy["required_sources"]:
            return None, "zero-required policy must not name required sources"
        plan = {
            "action": ACTION,
            "identity_boundary": IDENTITY_BOUNDARY,
            "policy": policy["binding"],
            "zero_required": True,
            "required_profile_ids": [],
            "profiles": [],
        }
        return _echo_proposal(plan, proposal)
    if applicability == "NOT_APPLICABLE":
        return None, (
            "NOT_APPLICABLE tests.yaml cannot publish required profiles; "
            "the project policy names required sources that are not applicable"
        )
    specs: list[dict[str, Any]] = []
    errors: list[str] = []
    for source in policy["required_sources"]:
        spec, spec_error = _resolve_source(root, source, profiles, commands_doc)
        if spec_error:
            errors.append(spec_error)
        elif spec is not None:
            specs.append(spec)
    if errors:
        return None, "; ".join(errors)
    specs.sort(key=lambda row: row["id"])
    plan = {
        "action": ACTION,
        "identity_boundary": IDENTITY_BOUNDARY,
        "policy": policy["binding"],
        "zero_required": False,
        "required_profile_ids": [row["id"] for row in specs],
        "profiles": specs,
    }
    return _echo_proposal(plan, proposal)


def load_policy(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / POLICY_REL
    if not path.is_file():
        return None, (
            f"{POLICY_REL} is absent, so the required set stays UNKNOWN. "
            "The project owner places a regular policy file outside a Develop "
            "session: policy required_set with required_sources, or policy "
            "zero_required. On Git, that file must be committed at HEAD. On a "
            "no-SCM host, its digest must be in the accepted baseline "
            "(explicit no-SCM baseline initialization, or a COMPLETE "
            "publication inventory). Understand does not invent or write that "
            "declaration. Then preview understand refresh --action required_tests."
        )
    if path.is_symlink():
        return None, f"{POLICY_REL} must be a regular project file"
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, f"{POLICY_REL} is unreadable; required authority was not published"
    if not isinstance(raw, dict):
        return None, f"{POLICY_REL} must be a mapping"
    unknown = sorted(set(raw) - _POLICY_KEYS)
    if unknown:
        return None, f"{POLICY_REL} has unknown fields: " + ", ".join(unknown)
    if str(raw.get("schema_version") or "") != "1" or raw.get("kind") != "required_test_policy":
        return None, (
            f"{POLICY_REL} must declare schema_version 1 and kind required_test_policy"
        )
    policy = raw.get("policy")
    sources = raw.get("required_sources", [])
    if not isinstance(sources, list) or any(not isinstance(item, str) or not item.strip() for item in sources):
        return None, f"{POLICY_REL} required_sources must be a list of source locators"
    normalized = [item.strip() for item in sources]
    if len(normalized) != len(set(normalized)):
        return None, f"{POLICY_REL} required_sources contains a duplicate locator"
    if policy == "zero_required":
        if normalized:
            return None, (
                f"{POLICY_REL} says zero_required and also names required sources; "
                "that policy is contradictory and stays UNKNOWN"
            )
    elif policy == "required_set":
        if not normalized:
            return None, (
                f"{POLICY_REL} policy required_set names no sources. "
                "An empty list is not an authoritative empty required set; "
                "use policy zero_required for that declaration."
            )
    else:
        return None, f"{POLICY_REL} policy must be required_set or zero_required"
    digest = file_digest(path)
    binding = {
        "path": POLICY_REL,
        "digest": digest,
        "policy": policy,
        "required_sources": normalized,
    }
    return {
        "policy": policy,
        "required_sources": normalized,
        "binding": binding,
    }, None


def publish_plan(
    tests_doc: dict[str, Any],
    plan: dict[str, Any],
    digest: str,
) -> dict[str, Any]:
    published = json.loads(json.dumps(tests_doc))
    discovery_confidence = published.get("confidence")
    _clear_required_claims(published)
    if "confidence" in tests_doc:
        published["confidence"] = discovery_confidence
    grounding = {
        "schema": GROUNDING_SCHEMA,
        "plan_digest": digest,
        "plan": plan,
    }
    by_id = _profile_index(published) or {}
    for spec in plan["profiles"]:
        profile = by_id[spec["id"]]
        profile["required"] = True
        profile["required_authority"] = "VERIFIED"
        profile["required_grounding"] = {
            "kind": "project_policy",
            "source": spec["source"],
            "command_ref": spec["command_ref"],
            "argv_digest": spec["argv_digest"],
            "definition_digest": spec["definition_digest"],
            "policy_digest": plan["policy"]["digest"],
            "plan_digest": digest,
        }
    published["required_authority"] = "VERIFIED"
    published["required_grounding"] = grounding
    return published


def reconcile_required_authority(
    root: Path,
    tests_data: dict[str, Any],
    prior: dict[str, Any] | None,
    commands_doc: dict[str, Any] | None,
) -> list[str]:
    """Restore a consistent published set, or downgrade the whole set."""
    discovery_confidence = tests_data.get("confidence")
    _clear_required_claims(tests_data)
    tests_data["confidence"] = discovery_confidence
    if not isinstance(prior, dict) or prior.get("required_authority") != "VERIFIED":
        return []
    problem = _prior_record_problem(prior)
    if problem:
        return [problem]
    commands = commands_doc if isinstance(commands_doc, dict) else {"commands": []}
    plan, plan_error = build_plan(
        root,
        tests_data,
        commands,
        {"publish": True, "zero_required": None, "required_profile_ids": None},
    )
    stored = prior["required_grounding"]["plan"]
    stored_digest = str(prior["required_grounding"].get("plan_digest") or "")
    if plan_error or plan is None:
        return [
            "required authority downgraded to UNKNOWN: current project policy "
            f"does not still ground the published set ({plan_error})"
        ]
    if plan_digest_of(plan) != stored_digest or plan != stored:
        return [
            "required authority downgraded to UNKNOWN: the published grounding "
            "no longer matches the current policy, command definition, or "
            "profile execution identity"
        ]
    merged = publish_plan(tests_data, plan, stored_digest)
    tests_data.clear()
    tests_data.update(merged)
    return []


def format_identity_state(root: str | Path) -> str:
    """``recorded``, ``absent``, ``conflict``, or ``unreadable``.

    The identity lives on ``project.yaml``, which Develop cannot write.
    A missing policy file or missing grounding does not clear it.
    """
    path = Path(root) / PROJECT_YAML
    if not path.is_file() or path.is_symlink():
        return "absent"
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return "unreadable"
    if not isinstance(data, dict):
        return "unreadable"
    if REQUIRED_AUTHORITY_FORMAT_KEY not in data:
        return "absent"
    if data.get(REQUIRED_AUTHORITY_FORMAT_KEY) == REQUIRED_AUTHORITY_FORMAT:
        return "recorded"
    return "conflict"


def record_required_format_identity(root: str | Path) -> str | None:
    """Persist required-tests-1 before tests.yaml publication. Idempotent.

    Returns a blocker when the record cannot be made durable. A later
    tests.yaml failure then cannot be read as a legacy contract.
    """
    path = Path(root) / PROJECT_YAML
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return (
            f"{PROJECT_YAML} could not be read. Required authority was not "
            "published, and no format identity was changed."
        )
    if not isinstance(data, dict):
        return f"{PROJECT_YAML} is not a mapping. Required authority was not published."
    if data.get(REQUIRED_AUTHORITY_FORMAT_KEY) == REQUIRED_AUTHORITY_FORMAT:
        return None
    if REQUIRED_AUTHORITY_FORMAT_KEY in data:
        return (
            f"{PROJECT_YAML} {REQUIRED_AUTHORITY_FORMAT_KEY} conflicts with "
            f"{REQUIRED_AUTHORITY_FORMAT}. Required authority was not published."
        )
    data[REQUIRED_AUTHORITY_FORMAT_KEY] = REQUIRED_AUTHORITY_FORMAT
    try:
        write_yaml_atomic(path, data)
        written = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return (
            f"{PROJECT_YAML} format identity could not be recorded. "
            "Required authority was not published."
        )
    if (
        not isinstance(written, dict)
        or written.get(REQUIRED_AUTHORITY_FORMAT_KEY) != REQUIRED_AUTHORITY_FORMAT
    ):
        return (
            f"{PROJECT_YAML} format identity did not persist. "
            "Required authority was not published."
        )
    return None


def published_required_format(root: str | Path, tests_doc: dict[str, Any] | None) -> bool:
    """True when this host must not use the legacy required-set rule.

    The durable witness is ``project.yaml`` ``required_authority_format``.
    A top-level or per-profile ``required_grounding`` field, including a
    partial field, is publication evidence when that identity is missing and
    also must not fall back to legacy. Policy-file presence is not publication.
    """
    if format_identity_state(root) != "absent":
        return True
    if not isinstance(tests_doc, dict):
        return False
    if "required_grounding" in tests_doc:
        return True
    profiles = tests_doc.get("profiles")
    return isinstance(profiles, list) and any(
        isinstance(row, dict) and "required_grounding" in row for row in profiles
    )


def live_grounding_problems(
    root: str | Path,
    tests_doc: dict[str, Any] | None,
    commands_doc: dict[str, Any] | None = None,
) -> list[str]:
    """Reject a claimed VERIFIED required set whose grounding is not current.

    A file that does not claim ``required_authority: VERIFIED`` is left to the
    historical confidence fallback. Claiming VERIFIED requires a self-consistent
    grounding record, an accepted policy, and a plan that still matches the
    current policy, commands, profiles, and execution identity.
    """
    if not isinstance(tests_doc, dict) or tests_doc.get("required_authority") != "VERIFIED":
        return []
    if str(tests_doc.get("confidence") or "") == "CONFLICTING":
        return [
            "discovery confidence CONFLICTING cannot authorize the required set"
        ]
    problem = _prior_record_problem(tests_doc)
    if problem:
        return [problem]
    for row in tests_doc.get("profiles") or []:
        if isinstance(row, dict) and row.get("required") is True and row.get("confidence") == "CONFLICTING":
            return [
                f"profile {row.get('id')} discovery confidence CONFLICTING "
                "cannot be consumed as required authority"
            ]
    host = Path(root)
    commands = commands_doc if isinstance(commands_doc, dict) else _read_commands(host)
    if not isinstance(commands, dict):
        return ["commands.yaml is missing, so required grounding cannot be checked"]
    acceptance = evaluate_policy_acceptance(host)
    if not acceptance.get("ok"):
        return list(acceptance.get("blockers") or ["required-test policy is not accepted"])
    plan, plan_error = build_plan(
        host,
        tests_doc,
        commands,
        {"publish": True, "zero_required": None, "required_profile_ids": None},
    )
    stored = tests_doc["required_grounding"]["plan"]
    stored_digest = str(tests_doc["required_grounding"].get("plan_digest") or "")
    if plan_error or plan is None or plan_digest_of(plan) != stored_digest or plan != stored:
        detail = plan_error or "the stored plan does not match the current policy, command definition, or profile execution identity"
        return [
            "required authority is not current: " + detail
        ]
    return []


def _read_commands(root: Path) -> dict[str, Any] | None:
    path = root / COMMANDS_YAML
    if not path.is_file():
        return None
    try:
        loaded = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def plan_digest_of(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()


def argv_digest(argv: list[str]) -> str:
    return hashlib.sha256(canonical_json(argv).encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _echo_proposal(
    plan: dict[str, Any],
    proposal: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    echoed_zero = proposal.get("zero_required")
    if echoed_zero is not None and echoed_zero is not plan["zero_required"]:
        if echoed_zero is True:
            return None, (
                "the proposal requests zero_required, but "
                f"{POLICY_REL} does not establish an empty required set"
            )
        return None, (
            "the proposal requests a non-empty required set, but "
            f"{POLICY_REL} establishes zero_required"
        )
    echoed_ids = proposal.get("required_profile_ids")
    if echoed_ids is not None and echoed_ids != plan["required_profile_ids"]:
        return None, (
            "the proposal's required_profile_ids do not match the project "
            f"policy {POLICY_REL}; an Agent selection cannot narrow or widen "
            "the authoritative required set. Policy resolves to "
            + (", ".join(plan["required_profile_ids"]) or "(none)")
            + "."
        )
    return plan, None


def _resolve_source(
    root: Path,
    source: str,
    profiles: dict[str, dict[str, Any]],
    commands_doc: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    matches = [
        row
        for row in commands_doc.get("commands") or []
        if isinstance(row, dict) and row.get("source") == source
    ]
    if len(matches) != 1:
        return None, (
            f"required source {source} matches {len(matches)} declared commands; "
            "expected one. Run understand refresh after the project declaration "
            "is visible, or correct the policy locator."
        )
    command = matches[0]
    allowed, reason = command_execution_allowed(command)
    if not allowed:
        return None, (
            f"required source {source} is not an executable command ({reason}). "
            "A declared command is not required-set authority, and a "
            "non-executable command cannot be published as required."
        )
    command_id = str(command.get("id") or "")
    bound = [
        profile
        for profile in profiles.values()
        if profile.get("command_ref") == command_id
    ]
    if len(bound) != 1:
        return None, (
            f"required source {source} matches {len(bound)} test profiles; expected one"
        )
    profile = bound[0]
    if profile.get("confidence") == "CONFLICTING":
        return None, (
            f"profile {profile.get('id')} discovery confidence is CONFLICTING "
            "and cannot be published as required"
        )
    if not isinstance(profile.get("command_ref"), str) or not profile.get("command_ref"):
        return None, f"profile {profile.get('id')} has no command_ref"
    definition, definition_error = definition_digest(root, source)
    if definition_error:
        return None, definition_error
    argv = [str(part) for part in command["argv"]]
    success = profile.get("success") if isinstance(profile.get("success"), dict) else {}
    exit_code = success.get("exit_code") if isinstance(success, dict) else None
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        return None, f"profile {profile.get('id')} success.exit_code is not an integer"
    timeout = profile.get("timeout_seconds")
    if timeout is not None and (
        isinstance(timeout, bool) or not isinstance(timeout, (int, float))
    ):
        return None, f"profile {profile.get('id')} timeout_seconds is not a number"
    evidence = profile.get("evidence_required")
    if evidence is not None and (
        not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence)
    ):
        return None, f"profile {profile.get('id')} evidence_required is not a string list"
    return {
        "id": str(profile.get("id")),
        "command_ref": command_id,
        "source": source,
        "argv_digest": argv_digest(argv),
        "definition_digest": definition,
        "adapter": profile.get("adapter"),
        "working_directory": profile.get("working_directory"),
        "timeout_seconds": timeout,
        "success_exit_code": exit_code,
        "evidence_required": list(evidence) if isinstance(evidence, list) else None,
    }, None


def definition_digest(root: Path, source: str) -> tuple[str | None, str | None]:
    """Digest the declared command body. Does not follow transitive dependencies."""
    script = _package_script(root, source)
    if script is not None:
        body, error = script
        if error:
            return None, error
        return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest(), None
    relative = source.strip().replace("\\", "/")
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None, f"required source {source} is not a project-relative declaration"
    path = root / relative
    if not path.is_file() or path.is_symlink():
        return None, (
            f"required source {source} has no verifiable project definition file"
        )
    try:
        payload = {
            "path": relative,
            "bytes": file_digest(path),
        }
    except OSError:
        return None, f"required source {source} could not be read"
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(), None


def _package_script(root: Path, source: str) -> tuple[dict[str, Any], str | None] | None:
    marker = "#scripts."
    if marker not in source:
        return None
    path_text, script = source.split(marker, 1)
    relative = path_text.strip().replace("\\", "/")
    if not script or not relative or ".." in Path(relative).parts:
        return {}, f"required source {source} is not a package script locator"
    path = root / relative
    if path.suffix.lower() != ".json" or not path.is_file() or path.is_symlink():
        return {}, f"required source {source} does not name a readable package script"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, f"required source {source} package file is unreadable"
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, dict) or script not in scripts:
        return {}, f"required source {source} script is absent"
    body = scripts.get(script)
    if not isinstance(body, str):
        return {}, f"required source {source} script body is not a string"
    return {"path": relative, "script": script, "body": body}, None


def _prior_record_problem(prior: dict[str, Any]) -> str | None:
    grounding = prior.get("required_grounding")
    if not isinstance(grounding, dict) or grounding.get("schema") != GROUNDING_SCHEMA:
        return (
            "prior required authority is VERIFIED without a usable grounding "
            "record; downgraded to UNKNOWN"
        )
    plan = grounding.get("plan")
    digest = grounding.get("plan_digest")
    if not isinstance(plan, dict) or not isinstance(digest, str):
        return (
            "prior required grounding is malformed; downgraded to UNKNOWN"
        )
    if plan_digest_of(plan) != digest:
        return (
            "prior required grounding plan digest does not match its content; "
            "downgraded to UNKNOWN"
        )
    profiles = prior.get("profiles")
    if not isinstance(profiles, list):
        return "prior tests.yaml profiles are unusable; downgraded to UNKNOWN"
    required_rows = [
        row for row in profiles if isinstance(row, dict) and row.get("required") is True
    ]
    zero = plan.get("zero_required") is True
    plan_ids = plan.get("required_profile_ids")
    if not isinstance(plan_ids, list):
        return "prior required plan names no profile list; downgraded to UNKNOWN"
    if zero:
        if plan_ids or plan.get("profiles") or required_rows:
            return (
                "prior grounding claims zero_required while required profiles "
                "are present; downgraded to UNKNOWN"
            )
        if plan.get("policy", {}).get("policy") != "zero_required":
            return (
                "prior zero-required grounding does not cite a zero_required "
                "policy; downgraded to UNKNOWN"
            )
        return None
    if plan.get("policy", {}).get("policy") != "required_set":
        return (
            "prior required grounding does not cite a required_set policy; "
            "downgraded to UNKNOWN"
        )
    row_ids = sorted(str(row.get("id") or "") for row in required_rows)
    if row_ids != list(plan_ids):
        return (
            "prior required profiles do not match the grounding plan; "
            "downgraded to UNKNOWN"
        )
    specs = plan.get("profiles")
    if not isinstance(specs, list):
        return "prior required plan profiles are malformed; downgraded to UNKNOWN"
    by_id = {str(row.get("id") or ""): row for row in required_rows}
    for spec in specs:
        if not isinstance(spec, dict):
            return "prior required plan profile is malformed; downgraded to UNKNOWN"
        row = by_id.get(str(spec.get("id") or ""))
        if row is None or row.get("required_authority") != "VERIFIED":
            return (
                "prior required profile lacks VERIFIED required_authority; "
                "downgraded to UNKNOWN"
            )
        detail = row.get("required_grounding")
        if not isinstance(detail, dict):
            return "prior required profile has no grounding detail; downgraded to UNKNOWN"
        if (
            detail.get("source") != spec.get("source")
            or detail.get("command_ref") != spec.get("command_ref")
            or detail.get("argv_digest") != spec.get("argv_digest")
            or detail.get("definition_digest") != spec.get("definition_digest")
            or detail.get("plan_digest") != digest
        ):
            return (
                "prior required profile grounding does not match the plan; "
                "downgraded to UNKNOWN"
            )
    return None


def _profile_index(tests_doc: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    rows = tests_doc.get("profiles")
    if not isinstance(rows, list):
        return None
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row.get("id"):
            return None
        if row["id"] in index:
            return None
        index[row["id"]] = row
    return index


def _clear_required_claims(tests_data: dict[str, Any]) -> None:
    tests_data["required_authority"] = "UNKNOWN"
    tests_data.pop("required_grounding", None)
    profiles = tests_data.get("profiles")
    if not isinstance(profiles, list):
        return
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        profile["required"] = False
        profile["required_authority"] = "UNKNOWN"
        profile.pop("required_grounding", None)


def _tests_write_allowed(root: Path) -> str | None:
    try:
        project = read_yaml(root / PROJECT_YAML)
    except (OSError, ValueError, TypeError, UnicodeError):
        return "project.yaml is unreadable; required authority was not published"
    if not isinstance(project, dict):
        return "project.yaml is unreadable; required authority was not published"
    allowed, reason = whole_file_mutation_allowed(project.get("ownership"), TESTS_YAML)
    if not allowed:
        return f"{TESTS_YAML} is not an Understand-owned GENERATED file; {reason}"
    resolved = resolve_ownership(project.get("ownership"), TESTS_YAML)
    if resolved.mode != "GENERATED":
        return f"{TESTS_YAML} is not GENERATED; Develop and Submit cannot hand-edit it"
    return None


def _load_contract(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / TESTS_YAML
    if not path.is_file():
        return None, "tests.yaml is absent; run understand refresh before required-tests"
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, "tests.yaml is unreadable; required authority was not published"
    if not isinstance(raw, dict):
        return None, "tests.yaml is not a mapping; required authority was not published"
    if str(raw.get("schema_version") or "") != "1":
        return None, "tests.yaml schema_version is unsupported"
    return raw, None


def _load_commands(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / COMMANDS_YAML
    if not path.is_file():
        return None, "commands.yaml is absent; required authority was not published"
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, "commands.yaml is unreadable; required authority was not published"
    if not isinstance(raw, dict) or not isinstance(raw.get("commands"), list):
        return None, "commands.yaml commands must be a list"
    return raw, None


def _retire_staging(root: Path, staging_path: str | None) -> None:
    if not staging_path:
        return
    raw = str(staging_path).strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return
    else:
        relative = raw
    if relative != STAGING_REL:
        return
    destination = root / STAGING_REL
    if not destination.is_file() or destination.is_symlink():
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


def _blocked(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": ACTION,
        "mode": "blocked",
        "wrote": False,
        "artifacts": [],
        "blockers": [message],
        "recovery": (
            "correct the project required-test policy or rerun understand "
            "refresh, then preview required_tests again"
        ),
    }
