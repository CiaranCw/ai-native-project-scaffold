"""Observational Develop host / package / lock gate. Does not mutate project or lock."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scaffold_p5.compatibility import evaluate_package
from scaffold_p5.distribution import Distribution
from scaffold_p5.host_state import SKILLS_LOCK, inspect_lock, inspect_project, snapshot_host
from scaffold_p5.models import PackageRef
from scaffold_p5.packages import PackageIndex, load_package

from scaffold_p7.models import EXECUTABLE_COMPAT, PROJECT_YAML, SKILL_ID


@dataclass
class DevelopPreflight:
    allowed: bool
    skill_version: str
    validity: str
    compatibility: str | None = None
    expected: dict[str, str] | None = None
    actual: dict[str, str] | None = None
    blockers: list[str] = field(default_factory=list)
    route: str = "understand.compatibility"
    reasons: list[str] = field(default_factory=list)
    host_lifecycle: str | None = None
    maintenance: list[str] = field(default_factory=list)

    def extras(self) -> dict[str, Any]:
        return {
            "expected_package": self.expected,
            "actual_package": self.actual,
            "package_validity": self.validity,
            "compatibility": self.compatibility,
            "execution_gate": "allow" if self.allowed else "block",
            "host_lifecycle": self.host_lifecycle,
            "maintenance": list(self.maintenance),
        }


def inspect_host_project(root: Path) -> tuple[str, list[str], dict[str, Any] | None]:
    path = root / PROJECT_YAML
    if not path.exists():
        return "ABSENT", [], None
    view = inspect_project(path)
    return view.status, list(view.reasons), view.data


def evaluate_host_execution_gate(
    root: Path,
    *,
    project: dict[str, Any] | None,
    project_status: str,
) -> tuple[bool, list[str], str, str | None, list[str]]:
    """Observational ordinary-Develop host gate. Does not Refresh or Migrate."""
    if project_status == "ABSENT":
        return (
            False,
            [
                "host is not adopted; Develop cannot execute without an "
                "authoritative project.yaml"
            ],
            "understand.bootstrap",
            None,
            [],
        )
    if project_status != "VALID" or project is None:
        return (
            False,
            [f"project.yaml is {project_status} and non-executable"],
            "understand.refresh",
            None,
            [],
        )
    lifecycle = project.get("lifecycle")
    maintenance = [
        item for item in (project.get("maintenance") or []) if isinstance(item, str)
    ]
    if lifecycle == "ADOPTING":
        return (
            False,
            ["ADOPTING host cannot run ordinary Develop"],
            "understand.bootstrap",
            "ADOPTING",
            maintenance,
        )
    if lifecycle == "RECOVERY_REQUIRED":
        return (
            False,
            ["RECOVERY_REQUIRED host cannot run ordinary Develop"],
            _recovery_route(root),
            "RECOVERY_REQUIRED",
            maintenance,
        )
    if lifecycle != "ACTIVE":
        return (
            False,
            [f"lifecycle {lifecycle!r} cannot run ordinary Develop"],
            "understand.bootstrap",
            str(lifecycle) if lifecycle is not None else None,
            maintenance,
        )
    if "NEEDS_MIGRATION" in maintenance:
        return (
            False,
            ["ACTIVE host has NEEDS_MIGRATION; ordinary Develop is blocked"],
            "understand.compatibility",
            "ACTIVE",
            maintenance,
        )
    if "NEEDS_REFRESH" in maintenance:
        return (
            False,
            [
                "ACTIVE host has NEEDS_REFRESH; stale host knowledge is not "
                "authoritative for ordinary Develop"
            ],
            "understand.refresh",
            "ACTIVE",
            maintenance,
        )
    return True, [], "", "ACTIVE", maintenance


def evaluate_develop_preflight(
    root: Path,
    *,
    package_root: Path | None,
    project: dict[str, Any] | None,
    project_status: str,
) -> DevelopPreflight:
    actual_pkg = load_package(package_root) if package_root else None
    actual_ref = actual_pkg.ref if actual_pkg else None
    actual_identity = _identity(actual_ref) if actual_ref else None
    actual_version = (actual_ref.skill_version if actual_ref else "") or ""
    observed_validity = (
        str(actual_pkg.validity) if actual_pkg is not None else "UNRESOLVED"
    )

    host_ok, host_blockers, host_route, lifecycle, maintenance = (
        evaluate_host_execution_gate(
            root,
            project=project,
            project_status=project_status,
        )
    )
    if not host_ok:
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity=observed_validity,
            actual=actual_identity,
            blockers=host_blockers,
            reasons=list(actual_pkg.validity_reasons) if actual_pkg is not None else [],
            route=host_route,
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )

    if actual_pkg is None:
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity="UNRESOLVED",
            actual=actual_identity,
            blockers=["actual Develop package is unresolved"],
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )
    if actual_pkg.ref.skill_id != SKILL_ID:
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity="INVALID",
            actual=actual_identity,
            blockers=["actual package is not the Develop Skill"],
            reasons=list(actual_pkg.validity_reasons),
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )
    if actual_pkg.validity != "VALID":
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity="INVALID",
            actual=actual_identity,
            blockers=["actual Develop package is INVALID"]
            + list(actual_pkg.validity_reasons),
            reasons=list(actual_pkg.validity_reasons),
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )

    lock = inspect_lock(root / SKILLS_LOCK)
    if not lock.complete_authoritative or not lock.data:
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity="VALID",
            actual=actual_identity,
            blockers=[
                "ACTIVE host lacks a complete authoritative skills.lock"
            ]
            + list(lock.reasons),
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )
    skills = lock.data.get("skills") or {}
    entry = skills.get(SKILL_ID)
    if not isinstance(entry, dict):
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity="VALID",
            actual=actual_identity,
            blockers=["authoritative lock lacks a Develop entry"],
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )
    expected = PackageRef(
        skill_id=SKILL_ID,
        skill_version=str(entry.get("skill_version") or ""),
        package_digest=str(entry.get("package_digest") or ""),
        package_format_version=str(entry.get("package_format_version") or "1"),
    )
    evaluation = evaluate_package(
        expected,
        actual_pkg,
        project=project,
        distribution=_readonly_distribution(actual_pkg),
        applicable_packages={SKILL_ID: actual_pkg},
    )
    validity = str(evaluation.get("validity") or "INVALID")
    compatibility = evaluation.get("result")
    expected_identity = _identity(expected)
    if validity != "VALID":
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity=validity,
            compatibility=compatibility if isinstance(compatibility, str) else None,
            expected=expected_identity,
            actual=actual_identity,
            blockers=["actual Develop package is INVALID"]
            + list(evaluation.get("reasons") or []),
            reasons=list(evaluation.get("reasons") or []),
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )
    if compatibility not in EXECUTABLE_COMPAT:
        return DevelopPreflight(
            allowed=False,
            skill_version=actual_version,
            validity=validity,
            compatibility=compatibility if isinstance(compatibility, str) else None,
            expected=expected_identity,
            actual=actual_identity,
            blockers=[
                f"Develop Host Compatibility is {compatibility or 'unresolved'}; "
                "normal Develop execution is blocked"
            ]
            + list(evaluation.get("reasons") or []),
            reasons=list(evaluation.get("reasons") or []),
            route="understand.compatibility",
            host_lifecycle=lifecycle,
            maintenance=maintenance,
        )
    return DevelopPreflight(
        allowed=True,
        skill_version=actual_version,
        validity=validity,
        compatibility=compatibility if isinstance(compatibility, str) else None,
        expected=expected_identity,
        actual=actual_identity,
        reasons=list(evaluation.get("reasons") or []),
        host_lifecycle=lifecycle,
        maintenance=maintenance,
    )


def _recovery_route(root: Path) -> str:
    snapshot = snapshot_host(root)
    adopt = (snapshot.adoption_recovery or {}).get("classification") or "NONE"
    migr = (snapshot.migration_recovery or {}).get("classification") or "NONE"
    if adopt != "NONE" and migr == "NONE":
        return "understand.bootstrap"
    if migr != "NONE" and adopt == "NONE":
        return "understand.compatibility"
    return "understand"


def _identity(ref: PackageRef | None) -> dict[str, str] | None:
    if ref is None:
        return None
    return {
        "skill_id": ref.skill_id,
        "skill_version": ref.skill_version,
        "package_digest": ref.package_digest,
        "package_format_version": ref.package_format_version,
    }


def _readonly_distribution(actual: Any) -> Distribution:
    return Distribution(
        releases={},
        index=PackageIndex([actual]),
        selected_release_id=None,
        actual_understand=actual,
    )
