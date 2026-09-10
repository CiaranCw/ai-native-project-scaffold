"""Local Test support-artifact storage. Not a canonical development record."""

from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from scaffold_p5.io_util import (
    file_digest,
    read_text,
    read_yaml,
    sha256_bytes,
    sha256_text,
    write_text_atomic,
    write_yaml_atomic,
)
from scaffold_p5 import yaml_lite
from scaffold_p5.ownership import resolve_ownership
from scaffold_p5.schemas import whole_file_mutation_allowed

from scaffold_p6.models import (
    DURABLE_EVIDENCE_ROOT,
    DURABLE_EVIDENCE_SCHEMA_VERSION,
    MATERIALIZATIONS_DIR,
    PROJECT_YAML,
    TEST_RUNS,
)
from scaffold_p6.schemas import validate_report, yaml_safe
from scaffold_p6.trace import retention_allows_s9


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"testrun-{stamp}-{secrets.token_hex(4)}"


def run_dir(root: Path, run_id: str) -> Path:
    return root / TEST_RUNS / run_id


def durable_capsule_path(root: Path, locator: str) -> Path:
    run_id = published_locator_run_id(locator)
    if not run_id:
        raise ValueError("locator is not a P6 test-run locator")
    return (
        root
        / DURABLE_EVIDENCE_ROOT
        / run_id
        / f"{sha256_text(locator)}.yaml"
    )


def materialization_path(root: Path, coordination_id: str) -> Path:
    return (
        root
        / MATERIALIZATIONS_DIR
        / f"{sha256_text(str(coordination_id))}.yaml"
    )


def prepare_run(root: Path, run_id: str, draft: dict[str, Any]) -> Path:
    dest = run_dir(root, run_id)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "evidence").mkdir(exist_ok=True)
    (dest / "incomplete").mkdir(exist_ok=True)
    write_yaml_atomic(dest / "incomplete" / "run.yaml", draft)
    return dest


def write_evidence_blobs(dest: Path, artifacts: dict[str, str]) -> None:
    for name, text in artifacts.items():
        write_text_atomic(dest / "evidence" / name, text)


def write_summary(dest: Path, summary: str) -> None:
    write_text_atomic(dest / "incomplete" / "summary.md", summary)


def publish_completed_report(
    dest: Path,
    report: dict[str, Any],
    summary: str,
) -> tuple[bool, list[str]]:
    write_summary(dest, summary)
    status, issues = validate_report(report)
    if status != "VALID":
        write_yaml_atomic(
            dest / "incomplete" / "validation.yaml",
            {"status": status, "issues": issues},
        )
        return False, issues
    write_text_atomic(dest / "summary.md", summary)
    write_yaml_atomic(dest / "report.yaml", yaml_safe(report))
    incomplete = dest / "incomplete"
    if incomplete.exists():
        for child in incomplete.iterdir():
            child.unlink()
        incomplete.rmdir()
    return True, []


def publication_incomplete(dest: Path) -> bool:
    return (dest / "incomplete" / "run.yaml").exists()


def load_completed_report(root: Path, run_id: str) -> dict[str, Any] | None:
    if not valid_test_run_id(run_id):
        return None
    dest = run_dir(root, run_id)
    if publication_incomplete(dest):
        return None
    path = dest / "report.yaml"
    if not path.exists():
        return None
    try:
        data = yaml_lite.load(read_text(path))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("report_status") != "COMPLETED":
        return None
    if data.get("report_id") != run_id:
        return None
    try:
        status, _issues = validate_report(data)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None
    if status != "VALID":
        return None
    try:
        intact = _local_refs_intact(root, data)
    except (TypeError, ValueError, AttributeError, KeyError, OSError):
        return None
    if not intact:
        return None
    return data


def list_completed_reports(root: Path) -> list[dict[str, Any]]:
    base = root / TEST_RUNS
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(base.iterdir(), key=lambda path: path.name):
        if child.is_dir():
            report = load_completed_report(root, child.name)
            if report:
                out.append(report)
    return out


def valid_test_run_id(run_id: Any) -> bool:
    """True only for one concrete Test-run directory name under test-runs/."""
    if not isinstance(run_id, str) or not run_id.strip():
        return False
    if run_id in {".", ".."}:
        return False
    if "/" in run_id or "\\" in run_id:
        return False
    path = Path(run_id)
    if path.is_absolute() or bool(path.anchor):
        return False
    if len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        return False
    return True


def published_locator_run_id(locator: Any) -> str | None:
    if not isinstance(locator, str) or not locator:
        return None
    path_part = locator.partition("#evidence/")[0]
    parts = Path(path_part).parts
    if (
        len(parts) < 3
        or parts[0] != "test-runs"
        or not valid_test_run_id(parts[1])
    ):
        return None
    return parts[1]


def resolve_evidence_ref(root: Path, ref: dict[str, Any]) -> tuple[bool, str, list[str]]:
    locator = str(ref.get("locator") or "")
    if not locator.startswith("test-runs/"):
        return False, "", ["evidence locator is not a local test-run path"]
    path = root / ".scaffold/runtime" / locator
    if not path.is_file():
        return False, "", [f"evidence artifact is not resolvable: {locator}"]
    expected = ref.get("digest")
    if not (isinstance(expected, str) and expected.strip()):
        return False, "", ["resolvable evidence ref requires a digest"]
    text = read_text(path)
    actual = _text_digest(text)
    if expected != actual and file_digest(path) != expected:
        return False, text, ["evidence digest does not match the stored artifact"]
    return True, text, []


_SUPPORTING_ONLY_KINDS = frozenset({"log_text", "file_artifact"})
_RESULT_BEARING_KINDS = frozenset(
    {
        "command_result",
        "structured_assertion",
        "structured_state",
        "event_trace",
        "human_observation",
        "visual_checkpoint",
        "external_ci",
    }
)


def _item_bears_profile_result(item: Any, profile: dict[str, Any]) -> bool:
    """True when the Evidence item itself bears the profile result.

    Profile association and supporting logs/files are not proof.
    """
    if not isinstance(item, dict) or not isinstance(profile, dict):
        return False
    kind = str(item.get("kind") or "")
    if kind in _SUPPORTING_ONLY_KINDS or kind not in _RESULT_BEARING_KINDS:
        return False
    if item.get("usable") is False:
        return False
    profile_result = profile.get("result")
    if item.get("result") == profile_result:
        return True
    if profile_result == "PASS" and (item.get("pass") is True or item.get("result") == "PASS"):
        return True
    if profile_result == "FAIL" and (item.get("pass") is False or item.get("result") == "FAIL"):
        return True
    return False


def build_published_evidence_refs(root: Path, run_id: str) -> list[dict[str, str]]:
    """Mint locator-only references to result-bearing published P6 Evidence."""
    report = load_completed_report(root, run_id)
    if report is None:
        return []
    refs_by_id = {
        str(ref.get("ref_id")): ref
        for ref in report.get("evidence_refs") or []
        if isinstance(ref, dict) and ref.get("ref_id")
    }
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in report.get("evidence") or []
        if isinstance(item, dict) and item.get("evidence_id")
    }
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for profile in report.get("profiles") or []:
        if (
            not isinstance(profile, dict)
            or profile.get("result") not in {"PASS", "FAIL"}
            or profile.get("evidence_complete") is not True
        ):
            continue
        evidence_ids = [
            str(value) for value in profile.get("evidence_ids") or []
            if isinstance(value, str) and value
        ]
        locator = ""
        for evidence_id in evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if not _item_bears_profile_result(item, profile):
                continue
            allowed, _reason = retention_allows_s9(item or {})
            if not allowed:
                continue
            ref = refs_by_id.get(evidence_id)
            if isinstance(ref, dict) and ref.get("resolvable") is True:
                candidate = str(ref.get("locator") or "")
                ok, _text, _issues = resolve_evidence_ref(root, ref)
                if candidate and ok:
                    locator = candidate
                    break
            if (
                isinstance(item, dict)
                and item.get("usable") is True
            ):
                locator = (
                    f"test-runs/{run_id}/report.yaml#evidence/"
                    f"{quote(evidence_id, safe='')}"
                )
                break
        if locator and locator not in seen:
            seen.add(locator)
            out.append({"locator": locator})
    return out


def resolve_published_evidence(
    root: Path,
    locator: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve one P6-minted locator through its owning completed report."""
    if isinstance(locator, str) and published_locator_run_id(locator):
        capsule = durable_capsule_path(root, locator)
        if capsule.exists():
            prepared, prepared_issues = _locator_has_prepared_materialization(
                root, locator
            )
            if prepared:
                runtime, runtime_issues = _resolve_runtime_evidence(root, locator)
                if runtime is not None:
                    return runtime, []
                return None, prepared_issues + runtime_issues
            return _resolve_durable_evidence(root, locator, capsule)
    return _resolve_runtime_evidence(root, locator)


def _resolve_runtime_evidence(
    root: Path,
    locator: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(locator, str) or not locator:
        return None, ["published Evidence locator is missing"]
    path_part, marker, encoded_evidence_id = locator.partition("#evidence/")
    parts = Path(path_part).parts
    run_id = published_locator_run_id(locator)
    if not run_id:
        return None, ["published Evidence locator is not a P6 test-run locator"]
    report = load_completed_report(root, run_id)
    if report is None:
        return None, ["owning completed Test report is unavailable or invalid"]

    item: dict[str, Any] | None = None
    full_ref: dict[str, Any] | None = None
    if marker:
        if tuple(parts[2:]) != ("report.yaml",) or not encoded_evidence_id:
            return None, ["embedded Evidence locator is malformed"]
        evidence_id = unquote(encoded_evidence_id)
        item = next(
            (
                row for row in report.get("evidence") or []
                if isinstance(row, dict) and row.get("evidence_id") == evidence_id
            ),
            None,
        )
        if item is None:
            return None, ["embedded Evidence item is absent from its report"]
    else:
        if len(parts) < 4 or parts[2] != "evidence":
            return None, ["published Evidence locator does not identify Evidence"]
        full_ref = next(
            (
                row for row in report.get("evidence_refs") or []
                if isinstance(row, dict) and row.get("locator") == locator
            ),
            None,
        )
        if full_ref is None:
            return None, ["Evidence locator is not declared by its report"]
        ok, _text, issues = resolve_evidence_ref(root, full_ref)
        if not ok:
            return None, issues
        ref_id = str(full_ref.get("ref_id") or "")
        item = next(
            (
                row for row in report.get("evidence") or []
                if isinstance(row, dict) and row.get("evidence_id") == ref_id
            ),
            None,
        )
        if item is None:
            return None, ["Evidence Ref does not resolve to a report Evidence item"]

    from scaffold_p6.evidence import evidence_item_usable

    usable, reason = evidence_item_usable(item)
    if item.get("usable") is not True or not usable:
        return None, [reason or "resolved Evidence item is not usable"]
    profile_id = str(item.get("profile_id") or "")
    profile = next(
        (
            row for row in report.get("profiles") or []
            if isinstance(row, dict) and row.get("id") == profile_id
        ),
        None,
    )
    if profile is None:
        return None, ["resolved Evidence has no report profile accounting"]
    if item.get("evidence_id") not in (profile.get("evidence_ids") or []):
        return None, ["resolved Evidence is not bound to its report profile"]
    return {
        "locator": locator,
        "report": report,
        "report_id": run_id,
        "evidence": item,
        "evidence_ref": full_ref,
        "profile": profile,
        "profile_id": profile_id,
        "result": profile.get("result"),
        "evidence_complete": profile.get("evidence_complete") is True,
        "candidate_digest": ((report.get("candidate") or {}).get("candidate_digest")),
        "resolution_source": "runtime",
    }, []


def _resolve_durable_evidence(
    root: Path,
    locator: str,
    capsule_path: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        capsule = read_yaml(capsule_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, ["durable P6 Evidence capsule is malformed or unreadable"]
    issues = _durable_capsule_issues(capsule, locator=locator)
    if issues:
        return None, issues
    payload = capsule["payload"]
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        name = str(artifact.get("name") or "")
        sidecar = capsule_path.parent / name
        if (
            Path(name).name != name
            or not sidecar.is_file()
            or file_digest(sidecar) != artifact.get("digest")
        ):
            return None, ["durable P6 Evidence sidecar integrity does not hold"]
        ref = payload.get("evidence_ref")
        if not isinstance(ref, dict) or not _evidence_bytes_match(
            sidecar.read_bytes(), str(ref.get("digest") or "")
        ):
            return None, ["durable P6 Evidence does not match its Evidence Ref"]

    item = payload["evidence"]
    from scaffold_p6.evidence import evidence_item_usable

    usable, reason = evidence_item_usable(item)
    if item.get("usable") is not True or not usable:
        return None, [reason or "durable P6 Evidence item is not usable"]
    profile = payload["profile"]
    candidate_digest = str(payload.get("candidate_digest") or "")
    return {
        "locator": locator,
        "report": {
            "report_id": payload["report_id"],
            "report_status": "COMPLETED",
            "candidate": {"candidate_digest": candidate_digest},
            "durable_evidence": True,
        },
        "report_id": payload["report_id"],
        "evidence": item,
        "evidence_ref": payload.get("evidence_ref"),
        "profile": profile,
        "profile_id": str(profile.get("id") or ""),
        "result": profile.get("result"),
        "evidence_complete": profile.get("evidence_complete") is True,
        "candidate_digest": candidate_digest,
        "resolution_source": "durable",
    }, []


def materialize_published_evidence(
    root: Path,
    locators: list[Any],
    *,
    coordination_id: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    normalized = sorted({
        str(item.get("locator") if isinstance(item, dict) else item)
        for item in locators
        if str(item.get("locator") if isinstance(item, dict) else item)
    })
    if not coordination_id or not normalized:
        return None, ["durable P6 Evidence materialization input is incomplete"]
    run_ids = sorted({
        run_id for locator in normalized
        if (run_id := published_locator_run_id(locator))
    })
    if len(run_ids) == 0 or any(
        published_locator_run_id(locator) is None for locator in normalized
    ):
        return None, ["durable P6 Evidence includes a non-P6 locator"]

    descriptor = {
        "schema_version": DURABLE_EVIDENCE_SCHEMA_VERSION,
        "kind": "p6_evidence_materialization",
        "record_class": "support_artifact",
        "status": "PREPARED",
        "coordination_id": coordination_id,
        "locators": normalized,
        "run_ids": run_ids,
        "artifacts": [],
    }
    prepared = materialization_path(root, coordination_id)
    if prepared.exists():
        try:
            existing = read_yaml(prepared)
        except (OSError, ValueError, TypeError, UnicodeError):
            return None, ["existing P6 PREPARED materialization is malformed"]
        if existing != descriptor and _materialization_issues(existing):
            return None, ["existing P6 PREPARED materialization is malformed"]
        if isinstance(existing, dict) and (
            existing.get("coordination_id") != coordination_id
            or existing.get("locators") != normalized
        ):
            return None, ["P6 PREPARED materialization conflicts with this request"]
        descriptor = existing
    write_yaml_atomic(prepared, descriptor)

    created: list[dict[str, Any]] = list(descriptor.get("artifacts") or [])
    try:
        project = read_yaml(root / PROJECT_YAML)
    except (OSError, ValueError, TypeError, UnicodeError):
        release_materialization(root, coordination_id)
        return None, ["project ownership registry is unavailable"]
    ownership = project.get("ownership") if isinstance(project, dict) else None

    for locator in normalized:
        resolved, issues = _resolve_runtime_evidence(root, locator)
        if resolved is None:
            _abort_materialization_data(root, descriptor)
            return None, [
                f"cannot materialize {locator}: {issue}" for issue in issues
            ]
        evidence_item = resolved.get("evidence") if isinstance(resolved.get("evidence"), dict) else {}
        allowed, retention_reason = retention_allows_s9(evidence_item)
        if not allowed:
            _abort_materialization_data(root, descriptor)
            return None, [f"cannot materialize {locator}: {retention_reason}"]
        report_path = run_dir(root, resolved["report_id"]) / "report.yaml"
        capsule_path = durable_capsule_path(root, locator)
        full_ref = resolved.get("evidence_ref")
        artifact_bytes: bytes | None = None
        artifact_data: dict[str, str] | None = None
        if isinstance(full_ref, dict) and full_ref.get("resolvable") is True:
            source = root / ".scaffold/runtime" / str(full_ref.get("locator") or "")
            if not source.is_file():
                _abort_materialization_data(root, descriptor)
                return None, [f"materialized Evidence source is missing: {locator}"]
            artifact_bytes = source.read_bytes()
            artifact_data = {
                "name": capsule_path.with_suffix(".bin").name,
                "digest": sha256_bytes(artifact_bytes),
            }

        payload = {
            "locator": locator,
            "report_id": resolved["report_id"],
            "source_report_digest": file_digest(report_path),
            "candidate_digest": resolved["candidate_digest"],
            "profile": _durable_profile(resolved["profile"]),
            "evidence": _without_capsule_ephemera(
                yaml_safe(resolved["evidence"])
            ),
            "evidence_ref": yaml_safe(full_ref) if isinstance(full_ref, dict) else None,
            "artifact": artifact_data,
        }
        capsule = {
            "schema_version": DURABLE_EVIDENCE_SCHEMA_VERSION,
            "kind": "p6_durable_evidence",
            "record_class": "support_artifact",
            "payload": payload,
            "payload_digest": sha256_text(yaml_lite.dump(payload)),
        }
        capsule_issues = _durable_capsule_issues(capsule, locator=locator)
        if capsule_issues:
            _abort_materialization_data(root, descriptor)
            return None, capsule_issues

        targets: list[tuple[Path, bytes]] = []
        if artifact_bytes is not None:
            targets.append((capsule_path.with_suffix(".bin"), artifact_bytes))
        targets.append((capsule_path, yaml_lite.dump(capsule).encode("utf-8")))
        for target, content in targets:
            rel = target.relative_to(root).as_posix()
            allowed, reason = whole_file_mutation_allowed(ownership, rel)
            resolution = resolve_ownership(ownership, rel)
            if (
                not allowed
                or resolution.status != "RESOLVED"
                or resolution.mode != "GENERATED"
            ):
                _abort_materialization_data(root, descriptor)
                return None, [
                    f"durable P6 Evidence ownership is not writable for {rel}: {reason}"
                ]
            digest = sha256_bytes(content)
            prior = next(
                (
                    item for item in created
                    if isinstance(item, dict) and item.get("path") == rel
                ),
                None,
            )
            if prior is not None and prior.get("digest") != digest:
                _abort_materialization_data(root, descriptor)
                return None, [
                    f"P6 PREPARED materialization conflicts with {rel}"
                ]
            was_created = not target.exists()
            if target.exists() and file_digest(target) != digest:
                _abort_materialization_data(root, descriptor)
                return None, [
                    f"existing durable P6 Evidence conflicts with {rel}"
                ]
            if was_created:
                _write_bytes_atomic(target, content)
            row = {
                "path": rel,
                "digest": digest,
                "created": was_created or bool((prior or {}).get("created")),
            }
            if prior != row:
                created = [
                    item for item in created
                    if not isinstance(item, dict) or item.get("path") != rel
                ]
                created.append(row)
                descriptor["artifacts"] = sorted(created, key=lambda item: item["path"])
                write_yaml_atomic(prepared, descriptor)

    descriptor["artifacts"] = sorted(created, key=lambda item: item["path"])
    write_yaml_atomic(prepared, descriptor)
    return descriptor, []


def list_prepared_materializations(root: Path) -> list[dict[str, Any]]:
    base = root / MATERIALIZATIONS_DIR
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.yaml")):
        try:
            data = read_yaml(path)
        except (OSError, ValueError, TypeError, UnicodeError):
            out.append({"malformed": True, "path": path.relative_to(root).as_posix()})
            continue
        issues = _materialization_issues(data)
        if issues:
            out.append({
                "malformed": True,
                "path": path.relative_to(root).as_posix(),
                "issues": issues,
            })
        else:
            out.append(data)
    return out


def _locator_has_prepared_materialization(
    root: Path,
    locator: str,
) -> tuple[bool, list[str]]:
    prepared = list_prepared_materializations(root)
    if any(item.get("malformed") for item in prepared):
        return True, [
            "candidate Evidence support coordination is malformed; "
            "P8 durability reconciliation is required"
        ]
    holders = [
        item
        for item in prepared
        if locator in (item.get("locators") or [])
    ]
    if holders:
        return True, [
            "candidate Evidence support is PREPARED; "
            "P8 durability reconciliation is required"
        ]
    return False, []


def release_materialization(root: Path, coordination_id: str) -> dict[str, Any]:
    path = materialization_path(root, coordination_id)
    if not path.exists():
        return {"ok": True, "released": False, "blockers": []}
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "released": False,
            "blockers": ["P6 PREPARED materialization is malformed"],
        }
    issues = _materialization_issues(data)
    if issues or data.get("coordination_id") != coordination_id:
        return {"ok": False, "released": False, "blockers": issues or [
            "P6 PREPARED materialization identity conflicts"
        ]}
    path.unlink()
    _remove_empty_parents(path.parent, root / MATERIALIZATIONS_DIR)
    return {"ok": True, "released": True, "blockers": []}


def abort_materialization(root: Path, coordination_id: str) -> dict[str, Any]:
    path = materialization_path(root, coordination_id)
    if not path.exists():
        return {"ok": True, "aborted": False, "blockers": []}
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "aborted": False,
            "blockers": ["P6 PREPARED materialization is malformed; reconciliation required"],
        }
    issues = _materialization_issues(data)
    if issues or data.get("coordination_id") != coordination_id:
        return {"ok": False, "aborted": False, "blockers": issues or [
            "P6 PREPARED materialization identity conflicts"
        ]}
    blockers = _abort_materialization_data(root, data)
    return {"ok": not blockers, "aborted": not blockers, "blockers": blockers}


def cleanup_test_run_result(root: Path, run_id: str) -> dict[str, Any]:
    if not valid_test_run_id(run_id):
        return {"performed": False, "blockers": ["Test-run identity is invalid"]}
    for prepared in list_prepared_materializations(root):
        if prepared.get("malformed"):
            return {
                "performed": False,
                "blockers": [
                    "P6 PREPARED materialization is malformed; P8 reconciliation is required"
                ],
            }
        if run_id in (prepared.get("run_ids") or []):
            return {
                "performed": False,
                "blockers": [
                    "Test-run has a PREPARED durable materialization; "
                    "P8 reconciliation is required before cleanup"
                ],
            }
    base = (root / TEST_RUNS).resolve()
    dest = (base / run_id).resolve()
    try:
        dest.relative_to(base)
    except ValueError:
        return {"performed": False, "blockers": ["Test-run path is outside storage"]}
    if dest.parent != base or dest == base or not dest.is_dir():
        return {"performed": False, "blockers": ["Test-run is unavailable"]}
    shutil.rmtree(dest)
    return {"performed": True, "blockers": []}


def _durable_capsule_issues(data: Any, *, locator: str) -> list[str]:
    if not isinstance(data, dict):
        return ["durable P6 Evidence capsule is not a mapping"]
    required = {
        "schema_version", "kind", "record_class", "payload", "payload_digest"
    }
    issues: list[str] = []
    if set(data) != required:
        issues.append("durable P6 Evidence capsule fields are malformed")
    if data.get("schema_version") != DURABLE_EVIDENCE_SCHEMA_VERSION:
        issues.append("durable P6 Evidence capsule schema is unsupported")
    if data.get("kind") != "p6_durable_evidence":
        issues.append("durable P6 Evidence capsule kind is invalid")
    if data.get("record_class") != "support_artifact":
        issues.append("durable P6 Evidence record class is invalid")
    payload = data.get("payload")
    payload_fields = {
        "locator", "report_id", "source_report_digest", "candidate_digest",
        "profile", "evidence", "evidence_ref", "artifact",
    }
    if not isinstance(payload, dict) or set(payload) != payload_fields:
        return issues + ["durable P6 Evidence payload is malformed"]
    if payload.get("locator") != locator:
        issues.append("durable P6 Evidence locator binding does not match")
    run_id = published_locator_run_id(locator)
    if not run_id or payload.get("report_id") != run_id:
        issues.append("durable P6 Evidence report identity does not match")
    for field in ("source_report_digest", "candidate_digest"):
        value = payload.get(field)
        if not _is_sha256(value):
            issues.append(f"durable P6 Evidence {field} is malformed")
    profile = payload.get("profile")
    item = payload.get("evidence")
    if not isinstance(profile, dict) or not isinstance(item, dict):
        issues.append("durable P6 Evidence accounting is malformed")
    else:
        if item.get("profile_id") != profile.get("id"):
            issues.append("durable P6 Evidence profile binding does not match")
        if item.get("evidence_id") not in (profile.get("evidence_ids") or []):
            issues.append("durable P6 Evidence item is not bound to its profile")
    ref = payload.get("evidence_ref")
    artifact = payload.get("artifact")
    if ref is not None and not isinstance(ref, dict):
        issues.append("durable P6 Evidence Ref is malformed")
    if artifact is not None:
        if (
            not isinstance(artifact, dict)
            or set(artifact) != {"name", "digest"}
            or Path(str(artifact.get("name") or "")).name != artifact.get("name")
            or not _is_sha256(artifact.get("digest"))
        ):
            issues.append("durable P6 Evidence sidecar declaration is malformed")
    expected_payload = sha256_text(yaml_lite.dump(payload))
    if data.get("payload_digest") != expected_payload:
        issues.append("durable P6 Evidence payload digest does not match")
    return issues


def _materialization_issues(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["P6 PREPARED materialization is not a mapping"]
    required = {
        "schema_version", "kind", "record_class", "status", "coordination_id",
        "locators", "run_ids", "artifacts",
    }
    issues: list[str] = []
    if set(data) != required:
        issues.append("P6 PREPARED materialization fields are malformed")
    if data.get("schema_version") != DURABLE_EVIDENCE_SCHEMA_VERSION:
        issues.append("P6 PREPARED materialization schema is unsupported")
    if data.get("kind") != "p6_evidence_materialization":
        issues.append("P6 PREPARED materialization kind is invalid")
    if data.get("record_class") != "support_artifact":
        issues.append("P6 PREPARED materialization record class is invalid")
    if data.get("status") != "PREPARED":
        issues.append("P6 materialization status must be PREPARED")
    if not isinstance(data.get("coordination_id"), str) or not data["coordination_id"]:
        issues.append("P6 PREPARED materialization identity is missing")
    if not isinstance(data.get("locators"), list) or not isinstance(
        data.get("run_ids"), list
    ) or not isinstance(data.get("artifacts"), list):
        issues.append("P6 PREPARED materialization lists are malformed")
    for row in data.get("artifacts") or []:
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "digest", "created"}
            or not isinstance(row.get("path"), str)
            or not row["path"].startswith(DURABLE_EVIDENCE_ROOT + "/")
            or not _is_sha256(row.get("digest"))
            or type(row.get("created")) is not bool
        ):
            issues.append("P6 PREPARED materialization artifact is malformed")
    return issues


def _abort_materialization_data(root: Path, data: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    own_path = materialization_path(root, str(data.get("coordination_id") or ""))
    other_paths = {
        row.get("path")
        for other in list_prepared_materializations(root)
        if not other.get("malformed")
        and other.get("coordination_id") != data.get("coordination_id")
        for row in other.get("artifacts") or []
        if isinstance(row, dict)
    }
    for row in reversed(data.get("artifacts") or []):
        if not isinstance(row, dict) or row.get("created") is not True:
            continue
        rel = str(row.get("path") or "")
        if rel in other_paths:
            continue
        target = root / rel
        if not target.is_file():
            continue
        if file_digest(target) != row.get("digest"):
            blockers.append(
                f"candidate durable support changed; reconciliation required: {rel}"
            )
            continue
        target.unlink()
        _remove_empty_parents(target.parent, root / DURABLE_EVIDENCE_ROOT)
    if not blockers and own_path.exists():
        own_path.unlink()
        _remove_empty_parents(own_path.parent, root / MATERIALIZATIONS_DIR)
    return blockers


def _evidence_bytes_match(data: bytes, expected: str) -> bool:
    if expected == sha256_bytes(data):
        return True
    try:
        return expected == sha256_text(data.decode("utf-8"))
    except UnicodeDecodeError:
        return False


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _without_capsule_ephemera(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_capsule_ephemera(item)
            for key, item in value.items()
            if key not in {
                "observed_at",
                "started_at",
                "ended_at",
                "working_directory",
            }
        }
    if isinstance(value, list):
        return [_without_capsule_ephemera(item) for item in value]
    return value


def _durable_profile(profile: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "required",
        "result",
        "provenance",
        "evidence_ids",
        "evidence_complete",
        "blockers",
    )
    return {
        field: yaml_safe(profile.get(field))
        for field in fields
        if field in profile
    }


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop.parent and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        if current == stop:
            return
        current = current.parent


def is_completed_pass_report(path: Path) -> bool:
    if path.name != "report.yaml" or not path.exists():
        return False
    dest = path.parent
    try:
        root = dest.parents[3]
    except IndexError:
        return False
    report = load_completed_report(root, dest.name)
    return bool(report) and report.get("verification", {}).get("test_pass") is True


def cleanup_test_run(root: Path, run_id: str) -> bool:
    return cleanup_test_run_result(root, run_id)["performed"] is True


def cleanup_incomplete_test_runs(root: Path) -> list[str]:
    base = root / TEST_RUNS
    if not base.is_dir():
        return []
    removed: list[str] = []
    for child in list(base.iterdir()):
        if not child.is_dir() or not valid_test_run_id(child.name):
            continue
        if publication_incomplete(child):
            shutil.rmtree(child)
            removed.append(child.name)
    return removed


def _local_refs_intact(root: Path, report: dict[str, Any]) -> bool:
    for ref in report.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            return False
        if ref.get("resolvable") is not True:
            continue
        ok, _text, _issues = resolve_evidence_ref(root, ref)
        if not ok:
            return False
    return True


def _text_digest(text: str) -> str:
    from scaffold_p5.io_util import sha256_text

    return sha256_text(text)
