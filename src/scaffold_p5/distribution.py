from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scaffold_p5.models import CORE_SKILLS, LoadedPackage, PackageRef, SelectedRelease
from scaffold_p5.packages import (
    PackageIndex,
    capability_owner,
    is_digest,
    is_format_version,
    is_semver,
    load_package,
)
from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import read_text

SUPPORTED_PACKAGE_FORMATS = {"1"}

class Distribution:
    """Client-neutral package/release index. Not a fifth Skill."""

    def __init__(
        self,
        *,
        releases: dict[str, SelectedRelease],
        index: PackageIndex,
        selected_release_id: str | None,
        actual_understand: LoadedPackage,
        release_errors: dict[str, list[str]] | None = None,
        supported_package_formats: set[str] | None = None,
        runtime_facts: dict[str, Any] | None = None,
        client_capabilities: set[str] | None = None,
    ):
        self.releases = releases
        self.index = index
        self.selected_release_id = selected_release_id
        self.actual_understand = actual_understand
        self.release_errors = release_errors or {}
        self.supported_package_formats = supported_package_formats or set(SUPPORTED_PACKAGE_FORMATS)
        self.runtime_facts = runtime_facts or {
            "language": "python",
            "language_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }
        self.client_capabilities = client_capabilities

    @property
    def selected_release(self) -> SelectedRelease | None:
        if not self.selected_release_id:
            return None
        return self.releases.get(self.selected_release_id)

    def release(self, release_id: str) -> SelectedRelease | None:
        return self.releases.get(release_id)

    def satisfies(
        self,
        capability: str,
        applicable_packages: dict[str, LoadedPackage] | None = None,
    ) -> bool:
        if not capability:
            return True
        packages = (
            self.selected_packages()
            if applicable_packages is None
            else applicable_packages
        )
        for pkg in packages.values():
            provides = pkg.manifest.get("provides") or []
            if capability in provides and pkg.validity == "VALID":
                return True
        return False

    def selected_packages(self) -> dict[str, LoadedPackage]:
        release = self.selected_release
        if release is None:
            return {}
        resolved: dict[str, LoadedPackage] = {}
        for skill_id in CORE_SKILLS:
            pinned = release.core.get(skill_id)
            package = self.index.resolve_exact(pinned) if pinned else None
            if package is not None:
                resolved[skill_id] = package
        return resolved

    def graph_issues(
        self,
        packages: dict[str, LoadedPackage],
    ) -> list[str]:
        edges: dict[str, set[str]] = {skill: set() for skill in CORE_SKILLS}
        issues: list[str] = []
        for skill_id, package in sorted(packages.items()):
            for requirement in package.manifest.get("requires") or []:
                owner = capability_owner(str(requirement))
                if owner in CORE_SKILLS:
                    edges.setdefault(skill_id, set()).add(owner)
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(node: str) -> None:
            if node in visiting:
                start = stack.index(node)
                cycle = stack[start:] + [node]
                message = "core dependency cycle: " + " -> ".join(cycle)
                if message not in issues:
                    issues.append(message)
                return
            if node in visited:
                return
            visiting.add(node)
            stack.append(node)
            for dependency in sorted(edges.get(node) or []):
                visit(dependency)
            stack.pop()
            visiting.remove(node)
            visited.add(node)

        for skill_id in CORE_SKILLS:
            visit(skill_id)
        return sorted(issues)

    def release_issues(self, release: SelectedRelease) -> list[str]:
        issues = list(self.release_errors.get(release.release_id, []))
        if set(release.core) != set(CORE_SKILLS):
            issues.append("release must independently pin exactly four core Skills")
            return issues
        resolved: dict[str, LoadedPackage] = {}
        for skill_id in CORE_SKILLS:
            pinned = release.core[skill_id]
            if pinned.skill_id != skill_id:
                issues.append(f"release member key/id mismatch for {skill_id}")
                continue
            package = self.index.resolve_exact(pinned)
            if package is None:
                issues.append(
                    f"release-pinned package unavailable or integrity mismatch: "
                    f"{skill_id}@{pinned.skill_version}"
                )
                continue
            if package.validity != "VALID":
                issues.append(
                    f"release member {skill_id}@{pinned.skill_version} is INVALID: "
                    + "; ".join(package.validity_reasons)
                )
            resolved[skill_id] = package
        if len(resolved) == len(CORE_SKILLS):
            issues.extend(self.graph_issues(resolved))
        return issues

    def environment_issues(
        self,
        package: LoadedPackage,
        applicable_packages: dict[str, LoadedPackage] | None = None,
    ) -> tuple[str | None, list[str]]:
        reasons: list[str] = []
        result: str | None = None
        if package.ref.package_format_version not in self.supported_package_formats:
            reasons.append(
                f"package format {package.ref.package_format_version} is unsupported by this Distribution"
            )
            result = "INCOMPATIBLE"
        for requirement in package.manifest.get("requires") or []:
            if not self.satisfies(requirement, applicable_packages):
                reasons.append(f"required capability is unavailable: {requirement}")
                result = result or "INCOMPATIBLE"
        runtime = package.manifest.get("runtime") or {}
        language = runtime.get("language")
        known_language = self.runtime_facts.get("language")
        if language:
            if known_language is None:
                reasons.append("required runtime language is unknown")
                result = result or "UNKNOWN"
            elif str(language).lower() != str(known_language).lower():
                reasons.append(f"required runtime language {language} is unavailable")
                result = result or "INCOMPATIBLE"
        minimum = runtime.get("min_language_version")
        known_version = self.runtime_facts.get("language_version")
        if minimum:
            if known_version is None:
                reasons.append("runtime version capability is unknown")
                result = result or "UNKNOWN"
            elif _version_tuple(str(known_version)) < _version_tuple(str(minimum)):
                reasons.append(
                    f"runtime {known_version} does not satisfy minimum {minimum}"
                )
                result = result or "INCOMPATIBLE"
        required_client = runtime.get("client_capabilities") or []
        if required_client:
            if self.client_capabilities is None:
                reasons.append("required client capability facts are unknown")
                result = result or "UNKNOWN"
            else:
                missing = sorted(set(required_client) - self.client_capabilities)
                if missing:
                    reasons.append("missing client capabilities: " + ",".join(missing))
                    result = result or "INCOMPATIBLE"
        return result, reasons


def load_distribution(
    *,
    package_dirs: list[Path],
    releases: dict[str, dict[str, dict[str, str]]],
    selected_release_id: str | None,
    actual_understand_dir: Path | None = None,
) -> Distribution:
    packages = [load_package(path) for path in package_dirs]
    index = PackageIndex(packages)
    built: dict[str, SelectedRelease] = {}
    release_errors: dict[str, list[str]] = {}
    for release_id, pins in releases.items():
        core: dict[str, PackageRef] = {}
        errors: list[str] = []
        if not isinstance(pins, dict) or set(pins) != set(CORE_SKILLS):
            errors.append("release core must contain exactly understand/develop/test/submit")
        for skill_id, raw in (pins.items() if isinstance(pins, dict) else []):
            if skill_id not in CORE_SKILLS or not isinstance(raw, dict):
                errors.append(f"malformed release member: {skill_id}")
                continue
            declared_id = raw.get("skill_id")
            version = str(raw.get("skill_version") or "")
            digest = str(raw.get("package_digest") or "")
            package_format = str(raw.get("package_format_version") or "")
            if declared_id != skill_id:
                errors.append(f"release member {skill_id} has mismatched skill_id")
            if not is_semver(version):
                errors.append(f"release member {skill_id} has invalid exact version")
            if not is_digest(digest):
                errors.append(f"release member {skill_id} has invalid package digest")
            if not is_format_version(package_format):
                errors.append(f"release member {skill_id} has invalid package format")
            core[skill_id] = PackageRef(
                skill_id=str(declared_id or ""),
                skill_version=version,
                package_digest=digest,
                package_format_version=package_format,
            )
        built[release_id] = SelectedRelease(release_id=release_id, core=core)
        release_errors[release_id] = errors
    if actual_understand_dir is not None:
        actual = load_package(actual_understand_dir)
    else:
        actual = _unavailable_package("actual Understand package is not resolvable")
        if selected_release_id and selected_release_id in built:
            pinned = built[selected_release_id].core.get("understand")
            if pinned is not None:
                actual = index.resolve_exact(pinned) or actual
    return Distribution(
        releases=built,
        index=index,
        selected_release_id=selected_release_id,
        actual_understand=actual,
        release_errors=release_errors,
    )


def load_fixture_distribution(
    fixture_root: Path,
    *,
    selected_release_id: str,
    actual_understand_version: str | None = None,
    extra_package_dirs: list[Path] | None = None,
    repo_understand: Path | None = None,
) -> Distribution:
    packages_root = fixture_root / "packages"
    package_dirs = [p for p in packages_root.iterdir() if p.is_dir()]
    if repo_understand is not None:
        package_dirs.append(repo_understand)
    if extra_package_dirs:
        package_dirs.extend(extra_package_dirs)
    releases: dict[str, dict[str, dict[str, str]]] = {}
    for rel_file in (fixture_root / "releases").glob("*.yaml"):
        data = yaml_lite.load(read_text(rel_file))
        releases[str(data["release_id"])] = dict(data.get("core") or {})
    actual_dir = None
    if actual_understand_version:
        if repo_understand is not None and actual_understand_version == "2.0.0":
            actual_dir = repo_understand
        else:
            actual_dir = packages_root / f"understand-{actual_understand_version}"
    return load_distribution(
        package_dirs=package_dirs,
        releases=releases,
        selected_release_id=selected_release_id,
        actual_understand_dir=actual_dir,
    )


def _unavailable_package(reason: str) -> LoadedPackage:
    return LoadedPackage(
        ref=PackageRef("", "", "", ""),
        path="",
        manifest={},
        skill_md="",
        validity="INVALID",
        validity_reasons=[reason],
    )


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            return (0,)
    return tuple(parts)
