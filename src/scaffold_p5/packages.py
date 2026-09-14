from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import read_text, sha256_text
from scaffold_p5.models import (
    CORE_SKILLS,
    DEVELOP_MODES,
    UNDERSTAND_MODES,
    LoadedPackage,
    PackageRef,
)

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
FORMAT_RE = re.compile(r"^[1-9][0-9]*$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_FIELDS = {
    "can_commit",
    "can_push",
    "commit_permission",
    "push_permission",
    "submit_authorized",
    "submission_permission",
    "user_identity",
    "model_identity",
    "chat_state",
    "secrets",
}
ALLOWED_CORE_DEPENDENCY_EDGES = {
    ("develop", "test"),
    ("submit", "test"),
    ("submit", "understand"),
}

def package_digest(skill_yaml: str, skill_md: str) -> str:
    return sha256_text("skill.yaml\n", skill_yaml, "\nSKILL.md\n", skill_md)


def load_package(path: str | Path) -> LoadedPackage:
    root = Path(path)
    reasons: list[str] = []
    manifest_text = ""
    skill_md = ""
    manifest: dict = {}
    try:
        manifest_text = read_text(root / "skill.yaml")
    except (OSError, UnicodeError) as exc:
        reasons.append(f"required manifest skill.yaml is unavailable: {type(exc).__name__}")
    if manifest_text:
        try:
            parsed = yaml_lite.load(manifest_text)
            if isinstance(parsed, dict):
                manifest = parsed
            else:
                reasons.append("skill.yaml must contain a mapping")
        except (ValueError, TypeError) as exc:
            reasons.append(f"skill.yaml is malformed: {type(exc).__name__}")

    entry_value = manifest.get("entry")
    entry = entry_value if isinstance(entry_value, str) else ""
    entry_path = root / entry if entry else root / "__missing_entry__"
    if not entry:
        reasons.append("required entry declaration is missing or malformed")
    elif Path(entry).is_absolute() or ".." in Path(entry).parts:
        reasons.append("entry must be a package-relative path")
    elif not entry_path.is_file():
        reasons.append(f"declared entry does not exist: {entry}")
    else:
        try:
            skill_md = read_text(entry_path)
        except (OSError, UnicodeError) as exc:
            reasons.append(f"declared entry is not interpretable text: {type(exc).__name__}")

    digest = package_digest(manifest_text, skill_md)
    skill_id_value = manifest.get("skill_id")
    skill_id = skill_id_value if isinstance(skill_id_value, str) else ""
    version_value = manifest.get("skill_version")
    version = str(version_value) if isinstance(version_value, (str, int, float)) else ""
    format_value = manifest.get("package_format_version")
    package_format = str(format_value) if isinstance(format_value, (str, int)) else ""
    modes_value = manifest.get("modes")
    modes = list(modes_value) if isinstance(modes_value, list) else []

    if skill_id not in CORE_SKILLS:
        reasons.append("required core skill_id is missing or invalid")
    if not is_semver(version):
        reasons.append("skill_version must be numeric MAJOR.MINOR.PATCH")
    if not is_format_version(package_format):
        reasons.append("package_format_version must be a present positive integer string")
    if not isinstance(modes_value, list) or any(not isinstance(mode, str) for mode in modes):
        reasons.append("modes must be a list of strings")
    elif len(modes) != len(set(modes)):
        reasons.append("modes must not contain duplicates")

    if skill_id == "understand":
        if set(modes) != set(UNDERSTAND_MODES):
            reasons.append("Understand modes must be exactly bootstrap/full/refresh/compatibility")
        for required in UNDERSTAND_MODES:
            if required not in modes:
                reasons.append(f"understand missing mode {required}")
        md_lower = skill_md.lower()
        for token in UNDERSTAND_MODES:
            if token not in md_lower:
                reasons.append(f"SKILL.md omits {token}")
    elif isinstance(modes_value, list) and all(isinstance(mode, str) for mode in modes):
        reasons.extend(_mode_ownership_issues(skill_id, modes))

    forbidden = sorted(_find_forbidden_fields(manifest))
    if forbidden:
        reasons.append("forbidden permission/identity fields: " + ",".join(forbidden))

    provides = manifest.get("provides")
    if not isinstance(provides, list) or any(
        not isinstance(value, str) or not CAPABILITY_RE.fullmatch(value) for value in provides
    ):
        reasons.append("provides must be a list of legal capability ids")
    else:
        for capability in provides:
            owner = capability_owner(capability)
            if owner != skill_id:
                reasons.append(
                    f"provided capability is not owned by {skill_id}: {capability}"
                )

    requires = manifest.get("requires")
    if not isinstance(requires, list) or any(
        not isinstance(value, str) or not CAPABILITY_RE.fullmatch(value) for value in requires
    ):
        reasons.append("requires must be a list of legal capability ids")
        requires = []
    else:
        for requirement in requires:
            owner = capability_owner(requirement)
            if owner not in CORE_SKILLS:
                reasons.append(
                    f"required capability has no core owner: {requirement}"
                )
                continue
            if owner == skill_id:
                reasons.append(f"cyclic self capability requirement: {requirement}")
            elif (skill_id, owner) not in ALLOWED_CORE_DEPENDENCY_EDGES:
                reasons.append(
                    f"forbidden core dependency edge {skill_id}->{owner}: {requirement}"
                )

    runtime = manifest.get("runtime")
    if "runtime" in manifest and not isinstance(runtime, dict):
        reasons.append("runtime must be a mapping when declared")
    elif isinstance(runtime, dict):
        if "language" in runtime and not isinstance(runtime.get("language"), str):
            reasons.append("runtime.language must be a string")
        minimum = runtime.get("min_language_version")
        if minimum is not None and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", str(minimum)):
            reasons.append("runtime.min_language_version must be numeric dotted form")
        clients = runtime.get("client_capabilities")
        if clients is not None and (
            not isinstance(clients, list)
            or any(
                not isinstance(value, str) or not CAPABILITY_RE.fullmatch(value)
                for value in clients
            )
        ):
            reasons.append("runtime.client_capabilities must contain capability ids")
    if "contracts" in manifest and not isinstance(manifest.get("contracts"), dict):
        reasons.append("contracts must be a mapping when declared")

    substitutions = manifest.get("may_substitute_for")
    if substitutions is not None:
        if not isinstance(substitutions, list):
            reasons.append("may_substitute_for must be a list")
        else:
            for substitution in substitutions:
                if not isinstance(substitution, dict):
                    reasons.append("may_substitute_for entries must be mappings")
                    continue
                target_id = substitution.get("skill_id", skill_id)
                target_version = str(substitution.get("skill_version") or "")
                if target_id != skill_id or not is_semver(target_version):
                    reasons.append("may_substitute_for has an invalid Skill identity")
    incompatible = manifest.get("incompatible_with")
    if incompatible is not None and (
        not isinstance(incompatible, list)
        or any(not is_semver(str(value)) for value in incompatible)
    ):
        reasons.append("incompatible_with must contain exact semantic versions")

    contradiction = _entry_identity_contradiction(skill_md, skill_id, version)
    if contradiction:
        reasons.append(contradiction)

    validity = "INVALID" if reasons else "VALID"
    ref = PackageRef(
        skill_id=skill_id,
        skill_version=version,
        package_digest=digest,
        package_format_version=package_format,
    )
    return LoadedPackage(
        ref=ref,
        path=str(root),
        manifest=manifest,
        skill_md=skill_md,
        validity=validity,
        validity_reasons=reasons,
        may_substitute_for=list(manifest.get("may_substitute_for") or [])
        if isinstance(manifest.get("may_substitute_for") or [], list)
        else [],
    )


def exact_match(pinned: PackageRef, actual: LoadedPackage) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if actual.validity != "VALID":
        reasons.append("actual package INVALID")
    if actual.ref.skill_id != pinned.skill_id:
        reasons.append("skill_id mismatch")
    if actual.ref.skill_version != pinned.skill_version:
        reasons.append("skill_version mismatch")
    if actual.ref.package_digest != pinned.package_digest:
        reasons.append("package/release identity mismatch")
    if actual.ref.package_format_version != pinned.package_format_version:
        reasons.append("package_format_version mismatch")
    return (len(reasons) == 0, reasons)


class PackageIndex:
    def __init__(self, packages: Iterable[LoadedPackage]):
        self.packages = list(packages)

    def find(self, skill_id: str, version: str | None = None, digest: str | None = None) -> list[LoadedPackage]:
        out = []
        for pkg in self.packages:
            if pkg.ref.skill_id != skill_id:
                continue
            if version and pkg.ref.skill_version != version:
                continue
            if digest and pkg.ref.package_digest != digest:
                continue
            out.append(pkg)
        return out

    def resolve_exact(self, pinned: PackageRef) -> LoadedPackage | None:
        hits = [
            package
            for package in self.find(pinned.skill_id, pinned.skill_version, pinned.package_digest)
            if package.ref.package_format_version == pinned.package_format_version
        ]
        if len(hits) == 1:
            return hits[0]
        return None

    def available_understand(self) -> list[LoadedPackage]:
        return self.find("understand")

def is_semver(value: str) -> bool:
    return bool(SEMVER_RE.fullmatch(value))


def is_format_version(value: str) -> bool:
    return bool(FORMAT_RE.fullmatch(value))


def is_digest(value: str) -> bool:
    return bool(DIGEST_RE.fullmatch(value))


def capability_owner(capability: str) -> str:
    return capability.split(".", 1)[0] if "." in capability else ""


SUBMIT_STAGE_MODE_RE = re.compile(r"^s(?:[1-9]|1[0-2])$", re.I)
MODE_HOME = {
    "bootstrap": "understand",
    "full": "understand",
    "refresh": "understand",
    "compatibility": "understand",
    "normal_task": "develop",
    "repair": "develop",
    "scoped_verification": "test",
}


def _is_submit_stage_mode(mode: str) -> bool:
    return bool(SUBMIT_STAGE_MODE_RE.fullmatch(mode))


def _mode_ownership_issues(skill_id: str, modes: list[str]) -> list[str]:
    issues: list[str] = []
    for mode in modes:
        if _is_submit_stage_mode(mode):
            issues.append(
                f"{skill_id} must not declare Submit stage {mode} as a top-level mode"
            )
            continue
        home = MODE_HOME.get(mode)
        if home and home != skill_id:
            issues.append(f"{skill_id} must not declare {home}-owned mode {mode}")
            continue
        if skill_id == "develop" and mode not in DEVELOP_MODES:
            issues.append(f"Develop must not declare unknown mode {mode}")
        elif skill_id == "submit":
            issues.append("Submit must not declare top-level modes")
    return issues


def _find_forbidden_fields(value, path: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in FORBIDDEN_FIELDS:
                found.add(path + key_text)
            found.update(_find_forbidden_fields(child, path + key_text + "."))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_fields(child, path))
    return found


_CANONICAL_SKILL_ID_RE = re.compile(
    r"(?m)^-\s*`skill_id`\s*:\s*`([a-z][a-z0-9_-]*)`\s*$",
    re.I,
)
_CANONICAL_SKILL_VERSION_RE = re.compile(
    r"(?m)^-\s*`skill_version`\s*:\s*`"
    r"((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))`\s*$",
    re.I,
)


def _entry_identity_contradiction(skill_md: str, skill_id: str, version: str) -> str | None:
    if not skill_md:
        return None
    ids = [match.group(1) for match in _CANONICAL_SKILL_ID_RE.finditer(skill_md)]
    if ids and any(value.lower() != skill_id for value in ids):
        return "skill.yaml / entry skill_id contradiction"
    versions = [
        match.group(1) for match in _CANONICAL_SKILL_VERSION_RE.finditer(skill_md)
    ]
    if versions and any(value != version for value in versions):
        return "skill.yaml / entry skill_version contradiction"
    return None


def installed_package_dir(host: str | Path, skill_id: str) -> Path:
    return Path(host) / ".scaffold" / "install" / "packages" / skill_id


def resolve_skill_package(
    skill_id: str,
    *,
    host: str | Path | None = None,
    runtime_file: Path | None = None,
) -> Path:
    """Resolve a Skill package from published install/packages, then vendor skills/.

    Published Consumer layout is `.scaffold/install/packages/{skill}/`.
    Vendor Distribution checkout layout is `skills/{skill}/`.
    Do not invent a duplicate installed `skills/` tree.
    """
    if host is not None:
        installed = installed_package_dir(host, skill_id)
        if installed.is_dir():
            return installed
    origin = Path(runtime_file or __file__).resolve()
    try:
        base = origin.parents[2]
    except IndexError:
        base = origin.parent
    packages = base / "packages" / skill_id
    if packages.is_dir():
        return packages
    skills = base / "skills" / skill_id
    if skills.is_dir():
        return skills
    return Path(__file__).resolve().parents[2] / "skills" / skill_id
