"""Project-local consumer installation. Distribution lifecycle, not a Skill."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.agents import (
    CONSUMER_INSTALL_REGION,
    CONSUMER_REGION_END,
    CONSUMER_REGION_START,
    apply_consumer_install_region,
    classify_agents_text,
    compose_consumer_agents_inner,
    has_consumer_install_region,
    parse_managed_regions,
)
from scaffold_p5.adapter_profiles import (
    CURSOR_PROFILE,
    PROFILE_KEY,
    AdapterProfile,
    declared_profiles,
    gitattributes_lines,
    profile_ids,
    required_paths,
    resolve_profiles,
)
from scaffold_p5.distribution import Distribution, load_distribution, load_fixture_distribution
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.first_use import (
    FIRST_USE_RULE_REL,
    FIRST_USE_RULE_TEXT,
    FRAGMENT_ID,
    HOOK_COMMAND,
    HOOK_EVENTS,
    HOOK_SCRIPT_REL,
    HOOK_SCRIPT_TEXT,
    HOOKS_JSON_REL,
    OWNERSHIP_MANAGED_JSON_FRAGMENT,
    dumps_hooks_json,
    expected_hook_fragment_digest,
    first_use_decision,
    inspect_scaffold_hook_fragment,
    is_scaffold_hook_command,
    merge_scaffold_hooks,
    parse_always_apply_rule,
)
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.inventory import project_relative_path
from scaffold_p5.io_util import file_digest, read_text, sha256_bytes
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p5.result import result_dict


INSTALL_FORMAT_VERSION = "1"
RUNTIME_REPRESENTATION_VERSION = "1"
SCHEMA_VERSION = "1"
SELECTED_RELEASE_ID = "installed"
KIND = "scaffold_consumer_install"
PRODUCT_NAME = "ai-native-project-scaffold"

INSTALL_DIR = ".scaffold/install"
INSTALL_MANIFEST = ".scaffold/install/install.yaml"
RUNTIME_DIR = ".scaffold/install/runtime"
PACKAGES_DIR = ".scaffold/install/packages"
RELEASES_DIR = ".scaffold/install/releases"
RUNNER_REL = ".scaffold/install/run.py"
INSTALL_GITIGNORE_REL = ".scaffold/install/.gitignore"
AGENTS_MD = "AGENTS.md"
GITATTRIBUTES = ".gitattributes"
GITATTR_REGION = "scaffold-consumer-git"
GITATTR_START = f"# scaffold:managed:{GITATTR_REGION}:start"
GITATTR_END = f"# scaffold:managed:{GITATTR_REGION}:end"
GITATTR_INNER = """# Scaffold MANAGED consumer bytes are hash-authoritative.
# Git must not convert EOL. VERIFY records raw SHA-256.
.scaffold/install/** -text
.cursor/skills/scaffold-understand/** -text
.cursor/skills/scaffold-develop/** -text
.cursor/skills/scaffold-test/** -text
.cursor/skills/scaffold-submit/** -text
.cursor/rules/scaffold-first-use.mdc -text
.cursor/hooks.json -text
AGENTS.md -text
.gitattributes -text
"""
GITATTR_REQUIRED_LINES = (
    ".scaffold/install/** -text",
    ".cursor/skills/scaffold-understand/** -text",
    ".cursor/skills/scaffold-develop/** -text",
    ".cursor/skills/scaffold-test/** -text",
    ".cursor/skills/scaffold-submit/** -text",
    ".cursor/rules/scaffold-first-use.mdc -text",
    ".cursor/hooks.json -text",
    "AGENTS.md -text",
    ".gitattributes -text",
)
GITATTR_PROBE_PATHS = (
    ".scaffold/install/run.py",
    ".scaffold/install/install.yaml",
    ".scaffold/install/.gitignore",
    ".scaffold/install/packages/understand/SKILL.md",
    ".scaffold/install/packages/understand/skill.yaml",
    ".scaffold/install/runtime/scaffold_p5/engine.py",
    ".scaffold/install/cursor_first_use_hook.py",
    ".cursor/skills/scaffold-understand/SKILL.md",
    ".cursor/skills/scaffold-develop/SKILL.md",
    ".cursor/skills/scaffold-test/SKILL.md",
    ".cursor/skills/scaffold-submit/SKILL.md",
    ".cursor/rules/scaffold-first-use.mdc",
    ".cursor/hooks.json",
    "AGENTS.md",
    ".gitattributes",
)
RC2_GITATTR_INNER = """# Scaffold MANAGED consumer bytes are hash-authoritative.
# Git must not convert EOL. VERIFY records raw SHA-256.
.scaffold/install/** -text
.cursor/skills/scaffold-understand/** -text
.cursor/skills/scaffold-develop/** -text
.cursor/skills/scaffold-test/** -text
.cursor/skills/scaffold-submit/** -text
AGENTS.md -text
.gitattributes -text
"""
RC2_CONSUMER_AGENTS_INNER = """## Scaffold installation

This managed AGENTS region is first-contact routing for a Scaffold-enabled repository.

Scaffold is installed. Installation is not Adoption. Do not treat `.scaffold/install` as completed project understanding.

Exactly four Skills exist: Understand, Develop, Test, and Submit. Repair is a Develop mode. There is no fifth Skill and no generic Cursor Skill named scaffold.

On a never-adopted host, ordinary business work starts with Understand bootstrap. Preview is not approval. Stop for explicit human approval of that exact plan before any persistent Adoption mutation.

Launcher: `python .scaffold/install/run.py`
First-use: `python .scaffold/install/run.py understand bootstrap`

Canonical Skill packages: `.scaffold/install/packages/{understand,develop,test,submit}/`
Runtime: `.scaffold/install/runtime/`

Cursor adapters exist only for those four Skills:
`.cursor/skills/scaffold-understand/`
`.cursor/skills/scaffold-develop/`
`.cursor/skills/scaffold-test/`
`.cursor/skills/scaffold-submit/`

Do not clone a second Scaffold repository and do not set PYTHONPATH to a developer checkout.
"""
_GITATTR_MARKER = re.compile(
    r"^#\s*scaffold:managed:([a-z][a-z0-9-]*):(start|end)\s*$",
    re.MULTILINE,
)
OWNERSHIP_WHOLE_FILE = "MANAGED"
OWNERSHIP_MANAGED_REGION = "MANAGED_REGION"
REGION_HOST_PATHS = {
    AGENTS_MD: CONSUMER_INSTALL_REGION,
    GITATTRIBUTES: GITATTR_REGION,
}
FRAGMENT_HOST_PATHS = {
    HOOKS_JSON_REL: FRAGMENT_ID,
}

SRC_PACKAGES = ("scaffold_p5", "scaffold_p6", "scaffold_p7", "scaffold_p8")
SRC_MODULES = ("scaffold_entry.py", "scaffold_consumer.py")
SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".tmp"}
SKIP_DIR_NAMES = {"__pycache__", ".git", ".pytest_cache"}

CURSOR_ADAPTERS = (
    "scaffold-understand",
    "scaffold-develop",
    "scaffold-test",
    "scaffold-submit",
)
GENERIC_CURSOR_ADAPTER = ".cursor/skills/scaffold/SKILL.md"
CURSOR_ADAPTER_PATHS = tuple(
    f".cursor/skills/{name}/SKILL.md" for name in CURSOR_ADAPTERS
)

VERIFY_VALID = "VALID"
VERIFY_DRIFTED = "DRIFTED"
VERIFY_INCOMPLETE = "INCOMPLETE"
VERIFY_INCOMPATIBLE = "INCOMPATIBLE"
VERIFY_UNKNOWN = "UNKNOWN"

IMPORT_READY = "PROJECT_SCAFFOLD_READY"
IMPORT_ALREADY_READY = "ALREADY_READY"
IMPORT_FAILED = "PROJECT_SCAFFOLD_IMPORT_FAILED"
IMPORT_PROBLEM_MANAGED_DRIFT = "MANAGED_DRIFT"
IMPORT_PROBLEM_OWNERSHIP = "OWNERSHIP_CONFLICT"
IMPORT_PROBLEM_INCOMPATIBLE = "INCOMPATIBLE_INSTALLATION"
IMPORT_PROBLEM_UNKNOWN = "UNKNOWN_STATE"
IMPORT_PROBLEM_INSTALL = "INSTALL_FAILURE"
IMPORT_PROBLEM_VERIFY = "VERIFY_FAILURE"
IMPORT_SKILL_LABELS = ("Understand", "Develop", "Test", "Submit")

ABS_SCAFFOLD_CHECKOUT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:Users|home|opt|var|tmp|NewResearch)[\\/])"
    r"[^\r\n\"']*ai-native-project-scaffold"
)

RUNNER_TEXT = '''#!/usr/bin/env python3
"""Project-local Scaffold runtime launcher. Not a fifth Skill."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
INSTALL_ROOT = Path(__file__).resolve().parent
RUNTIME = INSTALL_ROOT / "runtime"
sys.path.insert(0, str(RUNTIME))

from scaffold_p5.consumer_install import installed_main

if __name__ == "__main__":
    raise SystemExit(installed_main(INSTALL_ROOT, sys.argv[1:]))
'''

INSTALL_GITIGNORE_TEXT = """**/__pycache__/
*.pyc
*.pyo
*.tmp
"""

CURSOR_BODIES = {
    "scaffold-understand": """---
name: scaffold-understand
description: >-
  Scaffold Understand. Use for adopt/bootstrap, full normalize, refresh,
  compatibility, zero-context resume, and first-use on a never-adopted
  Scaffold-enabled repository. Ordinary feature work on a never-adopted host
  starts here. On NOT_ADOPTED hosts this is a mandatory authorization
  boundary, not optional guidance. Not a fifth Skill; this is a Cursor
  adapter to the canonical understand package.
---

# Understand (Cursor adapter)

Canonical package: `.scaffold/install/packages/understand/SKILL.md`

Run:

```text
python .scaffold/install/run.py understand bootstrap
python .scaffold/install/run.py understand full
python .scaffold/install/run.py understand refresh
python .scaffold/install/run.py understand compatibility
```

Do not use an external Distribution checkout.
""",
    "scaffold-develop": """---
name: scaffold-develop
description: >-
  Scaffold Develop. Use to implement a Task, continue work, or repair under
  Develop. Repair is a Develop mode, not a fifth Skill. Do not start Develop on
  a never-adopted host; Understand bootstrap comes first. On an ACTIVE host,
  ordinary HUMAN_OWNED business mutation is unauthorized until Develop has a
  current Task Book, OPEN Session, and current execution pointer.
---

# Develop (Cursor adapter)

Canonical package: `.scaffold/install/packages/develop/SKILL.md`

On an ACTIVE host, do not edit project source until Task authority exists,
a Develop execution Session is OPEN, and the current execution pointer is
bound. Establish or continue a Task through
the installed Develop intake channel. Intake creates no Session. Then begin
execution with `develop session --task-id`, mutate only inside that Task's
product or supporting scope, and close with `develop seal` or `develop abort`.

Run:

```text
python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>
python .scaffold/install/run.py develop session --task-id <task-id>
python .scaffold/install/run.py develop seal --task-id <task-id>
```

`--intake-json-b64` carries the structured Task proposal required by
Develop intake. Do not write `.scaffold/tasks/` directly. Repair is a
Develop mode. Supporting scope is Task affiliation, not ownership override.

Do not use an external Distribution checkout.
""",
    "scaffold-test": """---
name: scaffold-test
description: >-
  Scaffold Test. Use to run scoped verification and record what was actually
  verified. Not a fifth Skill; this is a Cursor adapter to the canonical test
  package.
---

# Test (Cursor adapter)

Canonical package: `.scaffold/install/packages/test/SKILL.md`

Run:

```text
python .scaffold/install/run.py test
```

Do not use an external Distribution checkout.
""",
    "scaffold-submit": """---
name: scaffold-submit
description: >-
  Scaffold Submit. Use to review the real working tree and prepare submission.
  Submit does not become Develop. Commit and Push remain separately authorized.
---

# Submit (Cursor adapter)

Canonical package: `.scaffold/install/packages/submit/SKILL.md`

Run:

```text
python .scaffold/install/run.py submit
```

Do not use an external Distribution checkout.
""",
}


@dataclass
class InstallFile:
    rel: str
    data: bytes
    ownership: str = OWNERSHIP_WHOLE_FILE
    region_id: str | None = None


@dataclass
class InstallPlan:
    mode: str
    host: Path
    distribution: Path
    blockers: list[str] = field(default_factory=list)
    files: list[InstallFile] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    preserved_unmanaged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skills: dict[str, dict[str, str]] = field(default_factory=dict)
    source: dict[str, str] = field(default_factory=dict)
    bridges: dict[str, Any] = field(default_factory=dict)
    existing_manifest: dict[str, Any] | None = None
    profiles: tuple[AdapterProfile, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.blockers


def is_live_distribution_root(path: str | Path) -> bool:
    root = Path(path)
    if not (root / "src" / "scaffold_entry.py").is_file():
        return False
    for pkg in SRC_PACKAGES:
        if not (root / "src" / pkg).is_dir():
            return False
    for skill_id in CORE_SKILLS:
        if not (root / "skills" / skill_id / "skill.yaml").is_file():
            return False
    return True


def is_install_managed_path(rel: str) -> bool:
    normalized = str(rel or "").replace("\\", "/").strip("/")
    if normalized == INSTALL_DIR or normalized.startswith(INSTALL_DIR + "/"):
        return True
    if normalized in {AGENTS_MD, GITATTRIBUTES, HOOKS_JSON_REL}:
        return False
    if normalized == FIRST_USE_RULE_REL:
        return True
    if normalized.startswith(".cursor/skills/scaffold"):
        return True
    return False


def load_live_distribution(dist_root: str | Path) -> Distribution:
    root = Path(dist_root)
    package_dirs = [root / "skills" / skill_id for skill_id in CORE_SKILLS]
    releases: dict[str, dict[str, dict[str, str]]] = {}
    selected = SELECTED_RELEASE_ID
    releases_dir = root / "releases"
    if releases_dir.is_dir():
        for rel_file in sorted(releases_dir.glob("*.yaml")):
            data = yaml_lite.load(read_text(rel_file))
            release_id = str(data.get("release_id") or "")
            releases[release_id] = dict(data.get("core") or {})
            selected = release_id
    else:
        core: dict[str, dict[str, str]] = {}
        for skill_id, path in zip(CORE_SKILLS, package_dirs):
            pkg = load_package(path)
            core[skill_id] = {
                "skill_id": skill_id,
                "skill_version": pkg.ref.skill_version,
                "package_digest": pkg.ref.package_digest,
                "package_format_version": pkg.ref.package_format_version,
            }
        releases[SELECTED_RELEASE_ID] = core
    return load_distribution(
        package_dirs=package_dirs,
        releases=releases,
        selected_release_id=selected,
        actual_understand_dir=root / "skills" / "understand",
    )


def load_installed_distribution(host: str | Path) -> Distribution:
    install = Path(host) / ".scaffold" / "install"
    return load_fixture_distribution(
        install,
        selected_release_id=SELECTED_RELEASE_ID,
        actual_understand_dir=install / "packages" / "understand",
    )


def source_identity(dist_root: Path) -> dict[str, str]:
    identity = {"product": PRODUCT_NAME}
    commit = _git_output(dist_root, ["rev-parse", "HEAD"])
    tree = _git_output(dist_root, ["rev-parse", "HEAD^{tree}"])
    if commit:
        identity["git_commit"] = commit
    if tree:
        identity["git_tree"] = tree
    return identity


def _git_output(root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def live_source_issues(dist_root: Path) -> list[str]:
    issues: list[str] = []
    if not is_live_distribution_root(dist_root):
        issues.append("target is not a Scaffold Distribution root")
        return issues
    packages = []
    for skill_id in CORE_SKILLS:
        pkg = load_package(dist_root / "skills" / skill_id)
        packages.append(pkg)
        if pkg.validity != "VALID":
                issues.append(
                f"source package {skill_id} is {pkg.validity}: "
                + "; ".join(pkg.validity_reasons or [])
            )
        if pkg.ref.skill_id != skill_id:
            issues.append(f"source package directory {skill_id} has mismatched skill_id")
    if [pkg.ref.skill_id for pkg in packages] != list(CORE_SKILLS):
        issues.append("source Distribution does not expose exactly four core Skills")
    releases_dir = dist_root / "releases"
    if releases_dir.is_dir():
        dist = load_live_distribution(dist_root)
        release = dist.selected_release
        if release is None:
            issues.append("source Distribution release is not uniquely determined")
        else:
            issues.extend(dist.release_issues(release))
            for skill_id in CORE_SKILLS:
                pinned = release.pinned(skill_id)
                actual = load_package(dist_root / "skills" / skill_id)
                if pinned.package_digest != actual.ref.package_digest:
                    issues.append(
                        f"source release pin digest mismatch for {skill_id}"
                    )
                if pinned.skill_version != actual.ref.skill_version:
                    issues.append(
                        f"source release pin version mismatch for {skill_id}"
                    )
    return issues


def host_target_issues(host: Path, dist_root: Path) -> list[str]:
    issues: list[str] = []
    try:
        resolved_host = host.resolve()
        resolved_dist = dist_root.resolve()
    except OSError as exc:
        return [f"cannot resolve host/distribution path: {type(exc).__name__}"]
    if not host.exists():
        issues.append("host path does not exist")
        return issues
    if not host.is_dir():
        issues.append("host path is not a directory")
        return issues
    if resolved_host == resolved_dist:
        issues.append("refusing to install into the Distribution root")
    try:
        resolved_host.relative_to(resolved_dist)
        issues.append("host path is inside the Distribution root")
    except ValueError:
        pass
    try:
        resolved_dist.relative_to(resolved_host)
        issues.append("Distribution path is inside the host project")
    except ValueError:
        pass
    return issues


def current_manifest(host: Path) -> dict[str, Any] | None:
    path = host / INSTALL_MANIFEST
    if not path.is_file():
        return None
    try:
        data = yaml_lite.load(read_text(path))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def manifest_file_map(manifest: dict[str, Any] | None) -> dict[str, str]:
    """Whole-file MANAGED path → SHA-256. Mixed-ownership host files are excluded."""
    out: dict[str, str] = {}
    if not isinstance(manifest, dict):
        return out
    for row in manifest.get("files") or []:
        if not isinstance(row, dict) or not row.get("path") or not row.get("digest"):
            continue
        rel = str(row["path"]).replace("\\", "/")
        if rel in REGION_HOST_PATHS or rel in FRAGMENT_HOST_PATHS:
            continue
        if str(row.get("ownership") or OWNERSHIP_WHOLE_FILE) == OWNERSHIP_MANAGED_REGION:
            continue
        if str(row.get("ownership") or "") == OWNERSHIP_MANAGED_JSON_FRAGMENT:
            continue
        out[rel] = str(row["digest"])
    return out


def manifest_region_records(manifest: dict[str, Any] | None) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not isinstance(manifest, dict):
        return records
    for row in manifest.get("regions") or []:
        if not isinstance(row, dict):
            continue
        rel = str(row.get("path") or "").replace("\\", "/")
        region_id = str(row.get("region_id") or "")
        digest = str(row.get("digest") or "")
        ownership = str(row.get("ownership") or "")
        if rel and region_id and digest and ownership == OWNERSHIP_MANAGED_REGION:
            records.append(
                {
                    "path": rel,
                    "region_id": region_id,
                    "digest": digest,
                    "ownership": ownership,
                }
            )
    return records


def manifest_fragment_records(manifest: dict[str, Any] | None) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not isinstance(manifest, dict):
        return records
    for row in manifest.get("json_fragments") or []:
        if not isinstance(row, dict):
            continue
        rel = str(row.get("path") or "").replace("\\", "/")
        fragment_id = str(row.get("fragment_id") or "")
        digest = str(row.get("digest") or "")
        ownership = str(row.get("ownership") or "")
        if (
            rel
            and fragment_id
            and digest
            and ownership == OWNERSHIP_MANAGED_JSON_FRAGMENT
        ):
            records.append(
                {
                    "path": rel,
                    "fragment_id": fragment_id,
                    "digest": digest,
                    "ownership": ownership,
                }
            )
    return records


def expected_region_text(
    rel: str,
    profiles: tuple[AdapterProfile, ...] | None = None,
) -> str | None:
    if profiles is None:
        profiles, _issues = resolve_profiles(None)
    if rel == AGENTS_MD:
        inner = compose_consumer_agents_inner(_agents_adapter_block(profiles))
        return (
            f"{CONSUMER_REGION_START}\n"
            f"{inner}\n"
            f"{CONSUMER_REGION_END}"
        )
    if rel == GITATTRIBUTES:
        return f"{GITATTR_START}\n{GITATTR_INNER.strip()}\n{GITATTR_END}"
    return None


def expected_region_digest(
    rel: str,
    profiles: tuple[AdapterProfile, ...] | None = None,
) -> str | None:
    text = expected_region_text(rel, profiles)
    if text is None:
        return None
    return sha256_bytes(text.encode("utf-8"))


def predecessor_region_digests(rel: str) -> set[str]:
    if rel == AGENTS_MD:
        text = (
            f"{CONSUMER_REGION_START}\n"
            f"{RC2_CONSUMER_AGENTS_INNER.strip()}\n"
            f"{CONSUMER_REGION_END}"
        )
        return {sha256_bytes(text.encode("utf-8"))}
    if rel == GITATTRIBUTES:
        text = f"{GITATTR_START}\n{RC2_GITATTR_INNER.strip()}\n{GITATTR_END}"
        return {sha256_bytes(text.encode("utf-8"))}
    return set()


def _ownership_for_rel(rel: str) -> tuple[str, str | None]:
    region_id = REGION_HOST_PATHS.get(rel)
    if region_id:
        return OWNERSHIP_MANAGED_REGION, region_id
    return OWNERSHIP_WHOLE_FILE, None


def plan_consumer_install(
    host: str | Path,
    distribution: str | Path,
    *,
    mode: str = "install",
    adapter_profiles: list[str] | tuple[str, ...] | None = None,
) -> InstallPlan:
    host_path = Path(host)
    dist_path = Path(distribution)
    plan = InstallPlan(mode=mode, host=host_path, distribution=dist_path)
    if mode not in {"install", "update"}:
        plan.blockers.append(f"unsupported install mode {mode}")
        return plan
    profiles, profile_issues = resolve_profiles(adapter_profiles)
    if profile_issues:
        plan.blockers.extend(profile_issues)
        return plan
    plan.profiles = profiles
    plan.blockers.extend(host_target_issues(host_path, dist_path))
    plan.blockers.extend(live_source_issues(dist_path))
    if plan.blockers:
        return plan
    existing = current_manifest(host_path)
    plan.existing_manifest = existing
    install_present = (host_path / INSTALL_DIR).exists()
    if mode == "install" and existing and _manifest_format_ok(existing):
        verify = verify_consumer_install(host_path)
        if not _status_allows_apply(mode, verify, existing):
            if verify["status"] == VERIFY_DRIFTED:
                plan.blockers.append(
                    "managed installation has unexpected drift; refusing silent overwrite"
                )
            else:
                plan.blockers.append(
                    f"existing installation status {verify['status']} cannot be reinstalled"
                )
            return plan
    if mode == "update":
        if not existing or not _manifest_format_ok(existing):
            plan.blockers.append("update requires a previous managed installation manifest")
            return plan
        verify = verify_consumer_install(host_path)
        if not _status_allows_apply(mode, verify, existing):
            if verify["status"] == VERIFY_DRIFTED:
                plan.blockers.append(
                    "managed installation has unexpected drift; refusing silent overwrite"
                )
            else:
                plan.blockers.append(
                    f"update requires VALID or INCOMPLETE installation, not {verify['status']}"
                )
            return plan
    if install_present and existing is None:
        plan.blockers.append(
            "unmanaged .scaffold/install exists without a supported install manifest"
        )
        return plan

    dist = load_live_distribution(dist_path)
    release = dist.selected_release
    if release is None:
        plan.blockers.append("Selected Distribution Release is not uniquely determined")
        return plan
    selected = dist.selected_packages()
    for skill_id in CORE_SKILLS:
        pkg = selected.get(skill_id)
        if pkg is None or pkg.validity != "VALID":
            plan.blockers.append(f"selected package {skill_id} is not VALID")
            continue
        plan.skills[skill_id] = {
            "skill_id": skill_id,
            "skill_version": pkg.ref.skill_version,
            "package_digest": pkg.ref.package_digest,
            "package_format_version": pkg.ref.package_format_version,
            "path": f"packages/{skill_id}",
        }
    if plan.blockers:
        return plan
    if mode == "install" and existing and _manifest_format_ok(existing):
        old_skills = existing.get("skills") or {}
        if old_skills and old_skills != plan.skills:
            plan.blockers.append(
                "existing managed installation identity differs; use update"
            )
            return plan

    payloads: dict[str, bytes] = {}
    _add_runtime_payloads(dist_path, payloads)
    _add_package_payloads(dist_path, payloads)
    payloads[f"{RELEASES_DIR}/installed.yaml"] = _release_yaml_bytes(plan.skills)
    payloads[RUNNER_REL] = RUNNER_TEXT.encode("utf-8")
    payloads[INSTALL_GITIGNORE_REL] = INSTALL_GITIGNORE_TEXT.encode("utf-8")
    if _has_cursor_profile(profiles):
        for adapter in CURSOR_ADAPTERS:
            rel = f".cursor/skills/{adapter}/SKILL.md"
            payloads[rel] = CURSOR_BODIES[adapter].encode("utf-8")
        payloads[FIRST_USE_RULE_REL] = FIRST_USE_RULE_TEXT.encode("utf-8")
        payloads[HOOK_SCRIPT_REL] = HOOK_SCRIPT_TEXT.encode("utf-8")
    agents_text, agents_issue = _planned_agents_text(host_path, profiles)
    if agents_issue:
        plan.blockers.append(agents_issue)
        return plan
    if agents_text is not None:
        payloads[AGENTS_MD] = agents_text.encode("utf-8")
    gitattr_text, gitattr_issue = _planned_gitattributes_text(host_path)
    if gitattr_issue:
        plan.blockers.append(gitattr_issue)
        return plan
    if gitattr_text is not None:
        payloads[GITATTRIBUTES] = gitattr_text.encode("utf-8")

    for rel in sorted(payloads):
        safe, reason = project_relative_path(host_path, rel)
        if safe is None:
            plan.blockers.append(f"planned path rejected: {rel} ({reason})")
    if plan.blockers:
        return plan

    managed = manifest_file_map(existing)
    generic_path = host_path / GENERIC_CURSOR_ADAPTER
    if generic_path.exists() and GENERIC_CURSOR_ADAPTER not in managed:
        plan.blockers.append(
            "refusing to coexist with unmanaged .cursor/skills/scaffold"
        )
        return plan
    plan.removed = _planned_removals(managed, payloads)
    for rel, data in sorted(payloads.items()):
        dest = host_path / rel
        collision = _unmanaged_collision(host_path, rel, dest, managed)
        if collision:
            plan.blockers.append(collision)
            continue
        digest = sha256_bytes(data)
        if dest.is_file():
            current = dest.read_bytes()
            if current == data:
                plan.unchanged.append(rel)
            else:
                plan.modified.append(rel)
        elif dest.exists():
            plan.blockers.append(f"refusing to replace non-file path {rel}")
            continue
        else:
            plan.added.append(rel)
        ownership, region_id = _ownership_for_rel(rel)
        plan.files.append(
            InstallFile(rel=rel, data=data, ownership=ownership, region_id=region_id)
        )
    if plan.blockers:
        return plan
    if _has_cursor_profile(profiles):
        hooks_issue = _plan_hooks_json(plan)
        if hooks_issue:
            plan.blockers.append(hooks_issue)
            return plan

    plan.source = source_identity(dist_path)
    plan.bridges = {
        PROFILE_KEY: profile_ids(profiles),
        "agents_md_region": CONSUMER_INSTALL_REGION if AGENTS_MD in payloads else None,
        "gitattributes_region": GITATTR_REGION if GITATTRIBUTES in payloads else None,
    }
    if _has_cursor_profile(profiles):
        plan.bridges.update(
            {
                "cursor": list(CURSOR_ADAPTER_PATHS),
                "cursor_first_use_rule": FIRST_USE_RULE_REL,
                "cursor_hooks_fragment": FRAGMENT_ID,
                "cursor_hook_command": HOOK_COMMAND,
            }
        )
    manifest = _manifest_from_plan(plan)
    manifest_bytes = yaml_lite.dump(manifest).encode("utf-8")
    _replace_or_add_file(plan, INSTALL_MANIFEST, manifest_bytes)
    return plan


def apply_consumer_install(plan: InstallPlan) -> dict[str, Any]:
    if not plan.allowed:
        return {
            "outcome": "BLOCKED",
            "mode": plan.mode,
            "blockers": list(plan.blockers),
        }
    host = plan.host
    (host / ".scaffold").mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix="install.staging-",
            dir=str(host / ".scaffold"),
        )
    )
    try:
        _write_payloads(host, plan.files, staging_hint=staging)
        _apply_removals(host, plan.removed)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _clean_install_caches(host)
    verify = verify_consumer_install(host)
    return {
        "outcome": "COMPLETED" if verify["status"] == VERIFY_VALID else "FAILED",
        "mode": plan.mode,
        "added": list(plan.added),
        "modified": list(plan.modified),
        "unchanged": list(plan.unchanged),
        "removed": list(plan.removed),
        "verify": verify,
        "blockers": [] if verify["status"] == VERIFY_VALID else list(
            verify.get("reasons") or ["installed bytes failed verify"]
        ),
    }


def plan_to_public_dict(plan: InstallPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "host": str(plan.host),
        "allowed": plan.allowed,
        "blockers": list(plan.blockers),
        "added": list(plan.added),
        "modified": list(plan.modified),
        "unchanged": list(plan.unchanged),
        "removed": list(plan.removed),
        "preserved_unmanaged": list(plan.preserved_unmanaged),
        "skills": dict(plan.skills),
        "source": dict(plan.source),
        "bridges": dict(plan.bridges),
        "agents_md": _agents_preservation_note(plan),
        "gitattributes": _gitattributes_preservation_note(plan),
        "hooks_json": _hooks_json_preservation_note(plan),
        "regions": [
            {
                "path": row.rel,
                "ownership": row.ownership,
                "region_id": row.region_id,
            }
            for row in plan.files
            if row.ownership == OWNERSHIP_MANAGED_REGION
        ],
        "json_fragments": [
            {
                "path": row.rel,
                "ownership": row.ownership,
                "fragment_id": row.region_id,
            }
            for row in plan.files
            if row.ownership == OWNERSHIP_MANAGED_JSON_FRAGMENT
        ],
        "file_count": len(plan.files),
    }


def verify_consumer_install(host: str | Path) -> dict[str, Any]:
    root = Path(host)
    manifest_path = root / INSTALL_MANIFEST
    reasons: list[str] = []
    if not manifest_path.is_file():
        if (root / INSTALL_DIR).exists():
            return {
                "status": VERIFY_INCOMPLETE,
                "reasons": ["install directory exists without install.yaml"],
            }
        return {
            "status": VERIFY_UNKNOWN,
            "reasons": ["no project-local installation"],
            "missing": [],
            "drifted": [],
            "skills": {},
            "source": {},
        }
    try:
        manifest = yaml_lite.load(read_text(manifest_path))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return {
            "status": VERIFY_INCOMPATIBLE,
            "reasons": [f"install.yaml is unreadable: {type(exc).__name__}"],
        }
    if not isinstance(manifest, dict) or not _manifest_format_ok(manifest):
        return {
            "status": VERIFY_INCOMPATIBLE,
            "reasons": ["install.yaml schema/format is unsupported"],
        }
    files = manifest.get("files") or []
    if not isinstance(files, list) or not files:
        return {
            "status": VERIFY_INCOMPLETE,
            "reasons": ["install.yaml file set is empty"],
        }
    profiles = declared_profiles(manifest)
    expected = manifest_file_map(manifest)
    missing: list[str] = []
    drifted: list[str] = []
    for rel, digest in expected.items():
        safe, reason = project_relative_path(root, rel)
        if safe is None:
            reasons.append(f"manifest path rejected: {rel} ({reason})")
            continue
        path = root / rel
        if not path.is_file():
            missing.append(rel)
            continue
        if file_digest(path) != digest:
            drifted.append(rel)
    region_missing, region_drifted, region_incompat = _managed_region_issues(
        root, manifest, profiles
    )
    missing.extend(region_missing)
    drifted.extend(region_drifted)
    reasons.extend(region_incompat)
    if any(p.profile_id == CURSOR_PROFILE for p in profiles):
        frag_missing, frag_drifted, frag_incompat = _hook_fragment_issues(root, manifest)
        missing.extend(frag_missing)
        drifted.extend(frag_drifted)
        reasons.extend(frag_incompat)
    for required in (
        RUNNER_REL,
        f"{RUNTIME_DIR}/scaffold_entry.py",
        f"{RUNTIME_DIR}/scaffold_p5/engine.py",
        f"{RUNTIME_DIR}/scaffold_p6/engine.py",
        f"{RUNTIME_DIR}/scaffold_p7/engine.py",
        f"{RUNTIME_DIR}/scaffold_p8/engine.py",
        *(f"{PACKAGES_DIR}/{skill}/skill.yaml" for skill in CORE_SKILLS),
        *(f"{PACKAGES_DIR}/{skill}/SKILL.md" for skill in CORE_SKILLS),
        *required_paths(profiles),
    ):
        if required not in expected:
            missing.append(required)
            reasons.append(f"manifest omits required path {required}")
        elif not (root / required).is_file():
            missing.append(required)
    extra: list[str] = []
    install_root = root / INSTALL_DIR
    if install_root.is_dir():
        for path in install_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() in SKIP_FILE_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            if rel not in expected and rel != INSTALL_MANIFEST:
                extra.append(rel)
    if extra:
        drifted.extend(extra)
        reasons.extend(f"unexpected extra install file {rel}" for rel in extra)
    skill_issues = _installed_skill_issues(root, manifest)
    cursor_declared = any(p.profile_id == CURSOR_PROFILE for p in profiles)
    adapter_issues = _cursor_adapter_issues(root, manifest) if cursor_declared else []
    rule_issues = _first_use_rule_issues(root) if cursor_declared else []
    gitattr_missing, gitattr_incompat = _git_attr_policy_issues(root, manifest, profiles)
    abs_hits = absolute_runtime_path_hits(root, expected)
    reasons.extend(skill_issues)
    reasons.extend(adapter_issues)
    reasons.extend(rule_issues)
    reasons.extend(gitattr_incompat)
    reasons.extend(abs_hits)
    missing.extend(gitattr_missing)
    if missing:
        status = VERIFY_INCOMPLETE
    elif drifted:
        status = VERIFY_DRIFTED
    elif skill_issues or adapter_issues or rule_issues or gitattr_incompat or abs_hits or reasons:
        status = VERIFY_INCOMPATIBLE
    else:
        status = VERIFY_VALID
    return {
        "status": status,
        "reasons": sorted(
            set(
                reasons
                + [f"missing {path}" for path in missing]
                + [f"drift {path}" for path in drifted]
            )
        ),
        "missing": sorted(set(missing)),
        "drifted": sorted(set(drifted)),
        "skills": dict(manifest.get("skills") or {}),
        "source": dict(manifest.get("source") or {}),
    }


def absolute_runtime_path_hits(host: Path, expected: dict[str, str]) -> list[str]:
    hits: list[str] = []
    for rel in expected:
        if rel == INSTALL_MANIFEST:
            continue
        path = host / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if ABS_SCAFFOLD_CHECKOUT_RE.search(text):
            hits.append(f"operational absolute Distribution path in {rel}")
    for rel in REGION_HOST_PATHS:
        path = host / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        slice_text, issues = _live_region_slice(rel, text)
        if issues or not slice_text:
            continue
        if ABS_SCAFFOLD_CHECKOUT_RE.search(slice_text):
            hits.append(f"operational absolute Distribution path in {rel} managed region")
    return hits


def import_project(
    host: str | Path,
    distribution: str | Path | None = None,
) -> dict[str, Any]:
    """User-facing orchestration over INSTALL / UPDATE / VERIFY / STATUS.

    `--host` is an operation-time locator only. It is not durable project
    authority. Import is not Adoption and is not a fifth Skill.
    """
    host_path = Path(host).expanduser().resolve()
    dist_path = (
        Path(distribution).expanduser().resolve()
        if distribution is not None
        else _default_distribution()
    )
    decision = classify_project_import(host_path)
    action = decision["action"]
    verify = decision["verify"]
    if action is None:
        return _import_failure(
            host_path,
            classification=decision["classification"],
            problem=decision["problem"],
            verify=verify,
            blockers=list(decision.get("blockers") or verify.get("reasons") or []),
        )
    if action == "noop":
        return _import_success(
            host_path,
            outcome=IMPORT_ALREADY_READY,
            classification=decision["classification"],
            action="noop",
            verify=verify_consumer_install(host_path),
        )
    plan = plan_consumer_install(host_path, dist_path, mode=action)
    if not plan.allowed:
        return _import_failure(
            host_path,
            classification=decision["classification"],
            problem=_import_problem(verify, plan.blockers),
            verify=verify,
            blockers=list(plan.blockers),
        )
    applied = apply_consumer_install(plan)
    final_verify = applied.get("verify") or verify_consumer_install(host_path)
    if applied.get("outcome") != "COMPLETED" or final_verify.get("status") != VERIFY_VALID:
        return _import_failure(
            host_path,
            classification=decision["classification"],
            problem=IMPORT_PROBLEM_VERIFY
            if applied.get("outcome") == "COMPLETED"
            else IMPORT_PROBLEM_INSTALL,
            verify=final_verify if isinstance(final_verify, dict) else verify,
            blockers=list(applied.get("blockers") or []),
        )
    return _import_success(
        host_path,
        outcome=IMPORT_READY,
        classification=decision["classification"],
        action=action,
        verify=final_verify,
    )


def classify_project_import(host: str | Path) -> dict[str, Any]:
    """Deterministic import action from existing VERIFY / UPDATE authority."""
    host_path = Path(host)
    verify = verify_consumer_install(host_path)
    existing = current_manifest(host_path)
    status = verify.get("status")
    install_present = (host_path / INSTALL_DIR).exists()
    if status == VERIFY_VALID:
        return {
            "classification": "CURRENT_VALID_INSTALLATION",
            "action": "noop",
            "problem": None,
            "verify": verify,
        }
    if status == VERIFY_UNKNOWN and not install_present:
        return {
            "classification": "NO_SCAFFOLD_INSTALLATION",
            "action": "install",
            "problem": None,
            "verify": verify,
        }
    if status == VERIFY_DRIFTED:
        return {
            "classification": "MANAGED_DRIFT",
            "action": None,
            "problem": IMPORT_PROBLEM_MANAGED_DRIFT,
            "verify": verify,
            "blockers": list(verify.get("reasons") or []),
        }
    if status in {VERIFY_INCOMPLETE, VERIFY_INCOMPATIBLE}:
        if existing is not None and _status_allows_apply("update", verify, existing):
            return {
                "classification": "SUPPORTED_UPGRADE_STATE",
                "action": "update",
                "problem": None,
                "verify": verify,
            }
        return {
            "classification": "INCOMPATIBLE_INSTALLATION"
            if status == VERIFY_INCOMPATIBLE
            else "UNKNOWN_STATE",
            "action": None,
            "problem": IMPORT_PROBLEM_INCOMPATIBLE
            if status == VERIFY_INCOMPATIBLE
            else IMPORT_PROBLEM_UNKNOWN,
            "verify": verify,
            "blockers": list(verify.get("reasons") or []),
        }
    return {
        "classification": "UNKNOWN_STATE",
        "action": None,
        "problem": IMPORT_PROBLEM_UNKNOWN,
        "verify": verify,
        "blockers": list(verify.get("reasons") or []),
    }


def format_import_report(result: dict[str, Any]) -> str:
    outcome = str(result.get("outcome") or IMPORT_FAILED)
    if outcome == IMPORT_FAILED:
        problem = str(result.get("problem") or IMPORT_PROBLEM_UNKNOWN)
        blockers = [str(item) for item in (result.get("blockers") or []) if item]
        lines = [
            IMPORT_FAILED,
            "",
            f"Problem: {problem}",
        ]
        if blockers:
            lines.append(blockers[0])
        return "\n".join(lines) + "\n"
    lifecycle = str(result.get("lifecycle") or result.get("host_class") or "UNKNOWN")
    return (
        f"{outcome}\n"
        "\n"
        f"Scaffold installation: {result.get('installation') or VERIFY_VALID}\n"
        f"Lifecycle: {lifecycle}\n"
        "Skills: Understand / Develop / Test / Submit\n"
        "\n"
        "Next:\n"
        "Open this project in Cursor and give the Agent your normal work request.\n"
        "No Scaffold-specific prompt is required.\n"
    )


def distribution_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold project-local consumer installation (not a fifth Skill)"
    )
    parser.add_argument(
        "command",
        choices=["import-project", "install", "update", "verify", "plan"],
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--distribution", default=None)
    args = parser.parse_args(argv)
    dist = Path(args.distribution) if args.distribution else _default_distribution()
    if args.command == "import-project":
        result = import_project(args.host, dist)
        print(format_import_report(result), end="")
        return 0 if result.get("outcome") in {IMPORT_READY, IMPORT_ALREADY_READY} else 1
    if args.command == "verify":
        payload = verify_consumer_install(args.host)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("status") == VERIFY_VALID else 1
    mode = "update" if args.command == "update" else "install"
    plan = plan_consumer_install(args.host, dist, mode=mode)
    public = plan_to_public_dict(plan)
    if args.command == "plan":
        print(json.dumps(public, indent=2))
        return 0 if plan.allowed else 1
    if not plan.allowed:
        print(json.dumps({"outcome": "BLOCKED", **public}, indent=2))
        return 1
    result = apply_consumer_install(plan)
    print(json.dumps({**result, "plan": public}, indent=2))
    return 0 if result.get("outcome") == "COMPLETED" else 1


def installed_main(install_root: Path, argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    host = install_root.parent.parent
    parser = argparse.ArgumentParser(description="Installed Scaffold runtime")
    parser.add_argument(
        "command",
        nargs="?",
        default="verify",
        choices=[
            "verify",
            "understand",
            "develop",
            "test",
            "submit",
            "status",
            "enter",
            "first-use",
        ],
    )
    parser.add_argument("mode", nargs="?", default=None)
    parser.add_argument("--host", default=str(host))
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--plan-digest", dest="plan_digest", default=None)
    parser.add_argument("--intake-json", default=None)
    parser.add_argument("--intake-json-b64", default=None)
    args, _rest = parser.parse_known_args(argv)
    target = Path(args.host)
    intake_allowed = (
        (args.command == "enter" and (args.mode or "") == "develop")
        or (args.command == "develop" and (args.mode or "") == "intake")
    )
    if (args.intake_json or args.intake_json_b64) and not intake_allowed:
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "blockers": [
                        "--intake-json / --intake-json-b64 is only valid on "
                        "enter develop or develop intake"
                    ],
                },
                indent=2,
            )
        )
        return 1
    if args.command == "verify":
        payload = verify_consumer_install(target)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("status") == VERIFY_VALID else 1
    if args.command == "status":
        from scaffold_entry import project_status

        print(json.dumps(project_status(target), indent=2, default=str))
        return 0
    if args.command == "first-use":
        print(json.dumps(first_use_decision(target), indent=2, default=str))
        return 0
    if args.command == "enter":
        from scaffold_entry import enter_project
        from scaffold_p7.intake import load_intake_envelope_flags

        kind = args.mode or "status"
        envelope, envelope_error = load_intake_envelope_flags(
            args.intake_json, args.intake_json_b64
        )
        if envelope_error:
            print(
                json.dumps(
                    {"outcome": "BLOCKED", "blockers": [envelope_error]},
                    indent=2,
                )
            )
            return 1
        if envelope is not None:
            result = enter_project(
                target,
                structured_intent=envelope["structured_intent"],
                proposal=envelope["proposal"],
                grounding=envelope["grounding"],
            )
        else:
            structured = {"kind": kind}
            if args.task_id:
                structured["task_id"] = args.task_id
            result = enter_project(target, structured_intent=structured)
        print(json.dumps(result if isinstance(result, dict) else result_dict(result), indent=2, default=str))
        return 0
    dist = load_installed_distribution(target)
    if args.command == "understand":
        mode = args.mode or "bootstrap"
        opts: dict[str, Any] = {}
        if args.approved:
            # Subject selector only. It names which Plan is presented to the
            # human; it is never proof that the human approved it.
            opts["approval"] = {
                "approved": True,
                "plan_digest": args.plan_digest,
            }
        result = _run_understand(target, dist, mode, opts, args.plan_digest)
        print(json.dumps(result_dict(result), indent=2, default=str))
        return 0 if result.outcome in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"} else 1
    package = target / ".scaffold" / "install" / "packages" / args.command
    if args.command == "develop":
        from scaffold_p7.engine import DevelopEngine
        from scaffold_p7.intake import load_intake_envelope_flags

        engine = DevelopEngine(
            target,
            package if (package / "SKILL.md").is_file() else None,
        )
        mode = args.mode or "normal_task"
        if mode == "intake":
            envelope, envelope_error = load_intake_envelope_flags(
                args.intake_json, args.intake_json_b64
            )
            if envelope_error:
                print(
                    json.dumps(
                        {"outcome": "BLOCKED", "blockers": [envelope_error]},
                        indent=2,
                    )
                )
                return 1
            if envelope is None:
                print(
                    json.dumps(
                        {
                            "outcome": "BLOCKED",
                            "blockers": [
                                "develop intake requires --intake-json or "
                                "--intake-json-b64"
                            ],
                        },
                        indent=2,
                    )
                )
                return 1
            result = engine.intake(
                structured_intent=envelope["structured_intent"],
                proposal=envelope["proposal"],
                grounding=envelope["grounding"],
            )
        elif mode == "session":
            result = engine.open_develop_session(task_id=args.task_id)
        elif mode == "seal":
            result = engine.seal_develop_execution(task_id=args.task_id)
        elif mode == "abort":
            result = engine.abort_develop_execution(task_id=args.task_id)
        else:
            result = engine.run(mode, task_id=args.task_id)
        print(json.dumps(result_dict(result), indent=2, default=str))
        return 0 if result.outcome in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"} else 1
    if args.command == "test":
        from scaffold_p6.engine import TestEngine

        result = TestEngine(target, package).run(
            args.mode or "scoped_verification",
            task_id=args.task_id,
        )
        print(json.dumps(result_dict(result), indent=2, default=str))
        return 0 if result.outcome in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"} else 1
    from scaffold_p8.engine import SubmitEngine

    result = SubmitEngine(target, package).run(task_id=args.task_id)
    print(json.dumps(result_dict(result), indent=2, default=str))
    return 0 if result.outcome in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"} else 1


def _run_understand(
    target: Path,
    dist: Distribution,
    mode: str,
    opts: dict[str, Any],
    plan_digest: str | None,
):
    """Understand CLI entry. Adoption apply is Agent lifecycle work, not a grant."""
    del plan_digest
    return UnderstandEngine(target, dist).run(mode, **opts)


def never_adopted_after_install(host: str | Path) -> dict[str, Any]:
    snap = snapshot_host(host)
    project = Path(host) / ".scaffold" / "project.yaml"
    lock = Path(host) / ".scaffold" / "skills.lock"
    return {
        "host_class": snap.host_class,
        "lifecycle": snap.lifecycle,
        "project_yaml_present": project.is_file(),
        "skills_lock_present": lock.is_file(),
        "never_adopted": (
            snap.host_class == "NOT_ADOPTED"
            and not project.is_file()
            and not lock.is_file()
        ),
    }


def _import_lifecycle(host: Path) -> dict[str, Any]:
    snap = snapshot_host(host)
    return {
        "host_class": snap.host_class,
        "lifecycle": snap.host_class,
        "project_yaml": (host / ".scaffold" / "project.yaml").is_file(),
        "skills_lock": (host / ".scaffold" / "skills.lock").is_file(),
        "tasks": (host / ".scaffold" / "tasks").exists(),
        "sessions": (host / ".scaffold" / "sessions").exists(),
        "changes": (host / ".scaffold" / "changes").exists(),
    }


def _import_success(
    host: Path,
    *,
    outcome: str,
    classification: str,
    action: str,
    verify: dict[str, Any],
) -> dict[str, Any]:
    life = _import_lifecycle(host)
    return {
        "outcome": outcome,
        "classification": classification,
        "action": action,
        "problem": None,
        "installation": verify.get("status"),
        "lifecycle": life["host_class"],
        "host_class": life["host_class"],
        "skills": list(IMPORT_SKILL_LABELS),
        "verify": verify,
        "blockers": [],
        "project_yaml": life["project_yaml"],
        "skills_lock": life["skills_lock"],
        "task_book": life["tasks"],
        "develop_session": life["sessions"],
        "change_record": life["changes"],
    }


def _import_failure(
    host: Path,
    *,
    classification: str,
    problem: str,
    verify: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    life = _import_lifecycle(host) if host.exists() else {
        "host_class": "UNKNOWN",
        "lifecycle": "UNKNOWN",
        "project_yaml": False,
        "skills_lock": False,
        "tasks": False,
        "sessions": False,
        "changes": False,
    }
    return {
        "outcome": IMPORT_FAILED,
        "classification": classification,
        "action": None,
        "problem": problem,
        "installation": verify.get("status"),
        "lifecycle": life["host_class"],
        "host_class": life["host_class"],
        "skills": list(IMPORT_SKILL_LABELS),
        "verify": verify,
        "blockers": list(blockers),
        "project_yaml": life["project_yaml"],
        "skills_lock": life["skills_lock"],
        "task_book": life["tasks"],
        "develop_session": life["sessions"],
        "change_record": life["changes"],
    }


def _import_problem(verify: dict[str, Any], blockers: list[str]) -> str:
    text = " ".join(str(item) for item in blockers)
    reasons = " ".join(str(item) for item in (verify.get("reasons") or []))
    combined = f"{text} {reasons}".lower()
    if verify.get("status") == VERIFY_DRIFTED or "unexpected drift" in combined:
        return IMPORT_PROBLEM_MANAGED_DRIFT
    if any(
        token in combined
        for token in (
            "unmanaged",
            "collision",
            "refusing to coexist",
            "refusing to replace",
            "refusing to overwrite",
        )
    ):
        return IMPORT_PROBLEM_OWNERSHIP
    if verify.get("status") == VERIFY_INCOMPATIBLE:
        return IMPORT_PROBLEM_INCOMPATIBLE
    if verify.get("status") == VERIFY_UNKNOWN:
        return IMPORT_PROBLEM_UNKNOWN
    if blockers:
        return IMPORT_PROBLEM_INSTALL
    return IMPORT_PROBLEM_VERIFY


def _default_distribution() -> Path:
    return Path(__file__).resolve().parents[2]


def _manifest_format_ok(manifest: dict[str, Any]) -> bool:
    return (
        str(manifest.get("schema_version") or "") == SCHEMA_VERSION
        and str(manifest.get("install_format_version") or "") == INSTALL_FORMAT_VERSION
        and str(manifest.get("kind") or "") == KIND
        and str(manifest.get("ownership") or "") == "MANAGED"
    )


def _status_allows_apply(
    mode: str, verify: dict[str, Any], existing: dict[str, Any] | None
) -> bool:
    status = verify.get("status")
    if status in {VERIFY_VALID, VERIFY_INCOMPLETE}:
        return True
    if status == VERIFY_INCOMPATIBLE and _obsolete_fifth_adapter_repairable(
        verify, existing
    ):
        return True
    if status == VERIFY_INCOMPATIBLE and _gitattr_region_order_repairable(verify):
        return True
    return False


def _obsolete_fifth_adapter_repairable(
    verify: dict[str, Any], existing: dict[str, Any] | None
) -> bool:
    if not existing:
        return False
    managed = manifest_file_map(existing)
    if GENERIC_CURSOR_ADAPTER not in managed:
        return False
    drifted = [
        path
        for path in (verify.get("drifted") or [])
        if path != GENERIC_CURSOR_ADAPTER
    ]
    missing = [
        path
        for path in (verify.get("missing") or [])
        if path != GENERIC_CURSOR_ADAPTER
    ]
    if drifted or missing:
        return False
    reasons = " ".join(verify.get("reasons") or [])
    return (
        "exactly four Scaffold adapters" in reasons
        or GENERIC_CURSOR_ADAPTER in reasons
        or "generic Cursor Skill" in reasons
    )


def _gitattr_region_order_repairable(verify: dict[str, Any]) -> bool:
    if verify.get("drifted") or verify.get("missing"):
        return False
    reasons = list(verify.get("reasons") or [])
    if not any("later rules can override" in item for item in reasons):
        return False
    blocked_tokens = (
        "exactly four Scaffold adapters",
        "generic Cursor Skill",
        "package digest",
        "absolute Distribution path",
        "unpaired",
        "duplicate",
        "unreadable",
        "omits ",
        "region id is unsupported",
    )
    for item in reasons:
        if "later rules can override" in item:
            continue
        if "Git text attribute for " in item:
            continue
        if "git check-attr" in item:
            continue
        if any(token in item for token in blocked_tokens):
            return False
    return True


def _planned_removals(managed: dict[str, str], payloads: dict[str, bytes]) -> list[str]:
    removed: list[str] = []
    if GENERIC_CURSOR_ADAPTER in managed and GENERIC_CURSOR_ADAPTER not in payloads:
        removed.append(GENERIC_CURSOR_ADAPTER)
    return removed


def _apply_removals(host: Path, removed: list[str]) -> None:
    for rel in removed:
        path = host / rel
        if path.is_file():
            path.unlink()
        parent = path.parent
        if (
            parent.name == "scaffold"
            and parent.parent.name == "skills"
            and parent.is_dir()
            and not any(parent.iterdir())
        ):
            parent.rmdir()


def _cursor_adapter_issues(host: Path, manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    bridges = manifest.get("bridges") if isinstance(manifest.get("bridges"), dict) else {}
    declared = [
        str(item).replace("\\", "/")
        for item in (bridges.get("cursor") or [])
        if item
    ]
    expected = list(CURSOR_ADAPTER_PATHS)
    if sorted(declared) != sorted(expected) or len(declared) != len(expected):
        issues.append(
            "install.yaml Cursor adapter set must be exactly four Scaffold adapters"
        )
    if (host / GENERIC_CURSOR_ADAPTER).is_file():
        issues.append(
            "generic Cursor Skill .cursor/skills/scaffold/SKILL.md is not a supported Scaffold adapter"
        )
    present = [
        name
        for name in CURSOR_ADAPTERS
        if (host / ".cursor" / "skills" / name / "SKILL.md").is_file()
    ]
    if present != list(CURSOR_ADAPTERS):
        issues.append(
            "installed Cursor Scaffold adapters must be exactly "
            "scaffold-understand/develop/test/submit"
        )
    return issues


def _add_runtime_payloads(dist_root: Path, payloads: dict[str, bytes]) -> None:
    src_root = dist_root / "src"
    for pkg in SRC_PACKAGES:
        pkg_dir = src_root / pkg
        for path in sorted(pkg_dir.rglob("*")):
            if not path.is_file() or not _copyable(path):
                continue
            rel = f"{RUNTIME_DIR}/{path.relative_to(src_root).as_posix()}"
            payloads[rel] = path.read_bytes()
    for name in SRC_MODULES:
        path = src_root / name
        if path.is_file():
            payloads[f"{RUNTIME_DIR}/{name}"] = path.read_bytes()


def _add_package_payloads(dist_root: Path, payloads: dict[str, bytes]) -> None:
    for skill_id in CORE_SKILLS:
        src = dist_root / "skills" / skill_id
        for path in sorted(src.rglob("*")):
            if not path.is_file() or not _copyable(path):
                continue
            rel = f"{PACKAGES_DIR}/{skill_id}/{path.relative_to(src).as_posix()}"
            payloads[rel] = path.read_bytes()


def _copyable(path: Path) -> bool:
    if path.suffix.lower() in SKIP_FILE_SUFFIXES:
        return False
    return not any(part in SKIP_DIR_NAMES for part in path.parts)


def _release_yaml_bytes(skills: dict[str, dict[str, str]]) -> bytes:
    core = {
        skill_id: {
            "skill_id": skill_id,
            "skill_version": row["skill_version"],
            "package_digest": row["package_digest"],
            "package_format_version": row["package_format_version"],
        }
        for skill_id, row in skills.items()
    }
    data = {
        "release_id": SELECTED_RELEASE_ID,
        "schema_version": SCHEMA_VERSION,
        "core": core,
    }
    return yaml_lite.dump(data).encode("utf-8")


def _planned_gitattributes_text(host: Path) -> tuple[str | None, str | None]:
    path = host / GITATTRIBUTES
    if not path.exists():
        applied = apply_gitattributes_region("")
        return applied, None if applied is not None else "cannot create .gitattributes consumer region"
    if not path.is_file():
        return None, ".gitattributes exists and is not a file"
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, f".gitattributes is unreadable: {type(exc).__name__}"
    applied = apply_gitattributes_region(current)
    if applied is None:
        return None, "existing .gitattributes is unsafe to integrate; refusing overwrite"
    return applied, None


def parse_gitattributes_region(
    text: str,
) -> tuple[dict[str, tuple[int, int]], list[str]]:
    starts: dict[str, list[int]] = {}
    ends: dict[str, list[tuple[int, int]]] = {}
    for match in _GITATTR_MARKER.finditer(text):
        region_id, kind = match.group(1), match.group(2)
        if kind == "start":
            starts.setdefault(region_id, []).append(match.start())
        else:
            ends.setdefault(region_id, []).append((match.start(), match.end()))
    issues: list[str] = []
    spans: dict[str, tuple[int, int]] = {}
    for region_id in sorted(set(starts) | set(ends)):
        if region_id != GITATTR_REGION:
            issues.append(f"unapproved .gitattributes managed region {region_id}")
            continue
        start_hits = starts.get(region_id) or []
        end_hits = ends.get(region_id) or []
        if len(start_hits) != 1 or len(end_hits) != 1:
            issues.append(
                f"managed region {region_id} is missing, duplicate, or unpaired"
            )
            continue
        start = start_hits[0]
        end_token, end = end_hits[0]
        if end_token <= start:
            issues.append(f"managed region {region_id} end precedes start")
            continue
        spans[region_id] = (start, end)
    return spans, issues


def apply_gitattributes_region(text: str) -> str | None:
    """Insert or replace the clone-stability region at the end of the file."""
    spans, issues = parse_gitattributes_region(text)
    if issues:
        return None
    block = f"{GITATTR_START}\n{GITATTR_INNER.strip()}\n{GITATTR_END}"
    span = spans.get(GITATTR_REGION)
    if span is not None:
        without = text[: span[0]] + text[span[1] :]
    else:
        without = text
    prefix = without
    if prefix.endswith("\r\n"):
        while prefix.endswith("\r\n\r\n"):
            prefix = prefix[:-2]
        if prefix and not prefix.endswith("\r\n"):
            prefix += "\r\n"
        if prefix:
            prefix += "\r\n"
    else:
        while prefix.endswith("\n\n"):
            prefix = prefix[:-1]
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
    return prefix + block + "\n"


def has_gitattributes_region(text: str) -> bool:
    spans, issues = parse_gitattributes_region(text)
    return not issues and GITATTR_REGION in spans


def _live_region_slice(rel: str, text: str) -> tuple[str | None, list[str]]:
    if rel == AGENTS_MD:
        spans, parse_issues = parse_managed_regions(text)
        issues = [f"AGENTS.md {item}" for item in parse_issues]
        if parse_issues:
            return None, issues
        if CONSUMER_INSTALL_REGION not in spans:
            return None, issues
        return _slice_between_markers(
            text, CONSUMER_REGION_START, CONSUMER_REGION_END
        ), issues
    if rel == GITATTRIBUTES:
        spans, parse_issues = parse_gitattributes_region(text)
        issues = [f".gitattributes {item}" for item in parse_issues]
        if parse_issues:
            return None, issues
        if GITATTR_REGION not in spans:
            return None, issues
        return _slice_between_markers(text, GITATTR_START, GITATTR_END), issues
    return None, [f"unsupported region-managed path {rel}"]


def _slice_between_markers(text: str, start_marker: str, end_marker: str) -> str | None:
    start = text.find(start_marker)
    if start < 0:
        return None
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        return None
    return text[start : end + len(end_marker)]


def _managed_region_issues(
    host: Path,
    manifest: dict[str, Any],
    profiles: tuple[AdapterProfile, ...] = (),
) -> tuple[list[str], list[str], list[str]]:
    missing: list[str] = []
    drifted: list[str] = []
    incompat: list[str] = []
    recorded = {
        (row["path"], row["region_id"]): row for row in manifest_region_records(manifest)
    }
    for rel, region_id in REGION_HOST_PATHS.items():
        expected = expected_region_digest(rel, profiles)
        if not expected:
            incompat.append(f"canonical managed region for {rel} is undefined")
            continue
        rec = recorded.get((rel, region_id))
        if rec is not None and rec["digest"] != expected:
            path = host / rel
            live_ok = False
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                    slice_text, _parse_issues = _live_region_slice(rel, text)
                    live_digest = (
                        sha256_bytes(slice_text.encode("utf-8")) if slice_text else None
                    )
                    live_ok = live_digest in {
                        expected,
                        rec["digest"],
                        *predecessor_region_digests(rel),
                    }
                except (OSError, UnicodeError):
                    live_ok = False
            if not live_ok:
                incompat.append(
                    f"install.yaml MANAGED_REGION digest for {rel} is not the canonical region"
                )
        path = host / rel
        if not path.is_file():
            missing.append(rel)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            incompat.append(f"{rel} is unreadable")
            continue
        slice_text, parse_issues = _live_region_slice(rel, text)
        if parse_issues:
            if rel == AGENTS_MD:
                incompat.extend(parse_issues)
            continue
        if slice_text is None:
            missing.append(rel)
            continue
        live_digest = sha256_bytes(slice_text.encode("utf-8"))
        recorded_digest = rec["digest"] if rec is not None else None
        if live_digest == expected:
            if recorded_digest not in {None, expected}:
                missing.append(rel)
            continue
        if live_digest in predecessor_region_digests(rel) or (
            recorded_digest is not None and live_digest == recorded_digest
        ):
            missing.append(rel)
            continue
        drifted.append(rel)
    return missing, drifted, incompat


def _git_attr_policy_issues(
    host: Path,
    manifest: dict[str, Any],
    profiles: tuple[AdapterProfile, ...] = (),
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    incompat: list[str] = []
    bridges = manifest.get("bridges") if isinstance(manifest.get("bridges"), dict) else {}
    declared = bridges.get("gitattributes_region")
    path = host / GITATTRIBUTES
    if declared not in {GITATTR_REGION, None}:
        incompat.append("install.yaml Git-attributes region id is unsupported")
    if not path.is_file():
        missing.append(GITATTRIBUTES)
        return missing, incompat
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        incompat.append(".gitattributes is unreadable")
        return missing, incompat
    spans, parse_issues = parse_gitattributes_region(text)
    if parse_issues:
        incompat.extend(f".gitattributes {item}" for item in parse_issues)
        return missing, incompat
    span = spans.get(GITATTR_REGION)
    if span is None:
        missing.append(GITATTRIBUTES)
        return missing, incompat
    if declared != GITATTR_REGION:
        missing.append(GITATTRIBUTES)
        return missing, incompat
    inner = text[span[0] : span[1]]
    slice_text, _ = _live_region_slice(GITATTRIBUTES, text)
    stale = False
    if slice_text:
        live_digest = sha256_bytes(slice_text.encode("utf-8"))
        stale = live_digest in predecessor_region_digests(GITATTRIBUTES)
    for line in _required_gitattr_lines(profiles):
        if line not in inner and not stale:
            incompat.append(f".gitattributes managed region omits {line}")
    after = text[span[1] :]
    for raw in after.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        incompat.append(
            ".gitattributes managed clone-stability region is not last; later rules can override it"
        )
        break
    if (host / ".git").exists():
        incompat.extend(_git_check_attr_text_issues(host))
    return missing, incompat


def _git_check_attr_text_issues(host: Path) -> list[str]:
    issues: list[str] = []
    probes = [rel for rel in GITATTR_PROBE_PATHS if (host / rel).is_file()]
    if not probes:
        return ["Git clone-stability probes are missing from the working tree"]
    try:
        proc = subprocess.run(
            ["git", "check-attr", "text", "--", *probes],
            cwd=str(host),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        issues.append("git check-attr failed for managed consumer paths")
        return issues
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        if ": text: " not in line:
            continue
        path, value = line.rsplit(": text: ", 1)
        path = path.strip().replace("\\", "/").lstrip("./")
        value = value.strip()
        seen.add(path)
        if value != "unset":
            issues.append(
                f"Git text attribute for {path} is {value!r}; MANAGED bytes require -text"
            )
    for rel in probes:
        key = rel.replace("\\", "/").lstrip("./")
        if key not in seen:
            issues.append(f"git check-attr did not report text for {rel}")
    return issues


def _planned_agents_text(
    host: Path,
    profiles: tuple[AdapterProfile, ...] = (),
) -> tuple[str | None, str | None]:
    inner = compose_consumer_agents_inner(_agents_adapter_block(profiles))
    path = host / AGENTS_MD
    if not path.exists():
        applied = apply_consumer_install_region("", inner=inner)
        return applied, None if applied is not None else "cannot create AGENTS.md consumer region"
    if not path.is_file():
        return None, "AGENTS.md exists and is not a file"
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, f"AGENTS.md is unreadable: {type(exc).__name__}"
    state = classify_agents_text(current)
    if state == "unsafe":
        return None, "existing AGENTS.md is unsafe to integrate; refusing overwrite"
    applied = apply_consumer_install_region(current, inner=inner)
    if applied is None:
        return None, "existing AGENTS.md cannot receive a scaffold-consumer region"
    return applied, None


def _unmanaged_collision(
    host: Path, rel: str, dest: Path, managed: dict[str, str]
) -> str | None:
    if not dest.exists():
        return None
    if rel in {AGENTS_MD, GITATTRIBUTES, HOOKS_JSON_REL}:
        return None
    if rel == INSTALL_DIR or rel.startswith(INSTALL_DIR + "/"):
        return None
    if rel in managed:
        return None
    return f"refusing to overwrite unmanaged path {rel}"


def _replace_or_add_file(plan: InstallPlan, rel: str, data: bytes) -> None:
    dest = plan.host / rel
    plan.files = [row for row in plan.files if row.rel != rel]
    plan.added = [item for item in plan.added if item != rel]
    plan.modified = [item for item in plan.modified if item != rel]
    plan.unchanged = [item for item in plan.unchanged if item != rel]
    if dest.is_file() and dest.read_bytes() == data:
        plan.unchanged.append(rel)
    elif dest.exists():
        plan.modified.append(rel)
    else:
        plan.added.append(rel)
    ownership, region_id = _ownership_for_rel(rel)
    plan.files.append(
        InstallFile(rel=rel, data=data, ownership=ownership, region_id=region_id)
    )


def _manifest_from_plan(plan: InstallPlan) -> dict[str, Any]:
    files = []
    regions = []
    fragments = []
    for row in sorted(plan.files, key=lambda item: item.rel):
        if row.ownership == OWNERSHIP_MANAGED_REGION and row.region_id:
            digest = expected_region_digest(row.rel, plan.profiles)
            if not digest:
                continue
            regions.append(
                {
                    "path": row.rel,
                    "ownership": OWNERSHIP_MANAGED_REGION,
                    "region_id": row.region_id,
                    "digest": digest,
                }
            )
            continue
        if row.ownership == OWNERSHIP_MANAGED_JSON_FRAGMENT and row.region_id:
            fragments.append(
                {
                    "path": row.rel,
                    "ownership": OWNERSHIP_MANAGED_JSON_FRAGMENT,
                    "fragment_id": row.region_id,
                    "digest": expected_hook_fragment_digest(),
                    "command": HOOK_COMMAND,
                    "events": list(HOOK_EVENTS),
                }
            )
            continue
        files.append(
            {
                "path": row.rel,
                "digest": sha256_bytes(row.data),
                "ownership": OWNERSHIP_WHOLE_FILE,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "install_format_version": INSTALL_FORMAT_VERSION,
        "runtime_representation_version": RUNTIME_REPRESENTATION_VERSION,
        "ownership": "MANAGED",
        "release_id": SELECTED_RELEASE_ID,
        "source": dict(plan.source),
        "skills": dict(plan.skills),
        "bridges": dict(plan.bridges),
        "regions": regions,
        "json_fragments": fragments,
        "skills_lock_relationship": (
            "install.yaml is pre-Adoption product provenance; "
            "skills.lock is Adoption-time expected-identity authority"
        ),
        "files": files,
    }


def _write_payloads(
    host: Path, files: list[InstallFile], *, staging_hint: Path
) -> None:
    host.joinpath(".scaffold").mkdir(parents=True, exist_ok=True)
    install_files = [row for row in files if row.rel.startswith(INSTALL_DIR + "/") or row.rel == INSTALL_DIR]
    other_files = [row for row in files if row not in install_files]
    staging_install = staging_hint / "install"
    if staging_install.exists():
        shutil.rmtree(staging_install)
    for row in install_files:
        rel_inside = row.rel[len(INSTALL_DIR) + 1 :]
        dest = staging_install / rel_inside
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(row.data)
    final_install = host / INSTALL_DIR
    backup = None
    if final_install.exists():
        backup = host / ".scaffold" / f"install.bak-{staging_hint.name}"
        if backup.exists():
            shutil.rmtree(backup)
        final_install.rename(backup)
    shutil.move(str(staging_install), str(final_install))
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)
    for row in other_files:
        dest = host / row.rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(row.data)


def _clean_install_caches(host: Path) -> None:
    runtime = host / RUNTIME_DIR
    if not runtime.exists():
        return
    for path in runtime.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    for path in runtime.rglob("*.pyc"):
        try:
            path.unlink()
        except OSError:
            pass


def _installed_skill_issues(host: Path, manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    declared = manifest.get("skills") or {}
    if set(declared) != set(CORE_SKILLS):
        issues.append("install.yaml must record exactly the four core Skills")
        return issues
    for skill_id in CORE_SKILLS:
        pkg = load_package(host / PACKAGES_DIR / skill_id)
        if pkg.validity != "VALID":
            issues.append(f"installed package {skill_id} is {pkg.validity}")
            continue
        row = declared.get(skill_id) or {}
        if pkg.ref.package_digest != str(row.get("package_digest") or ""):
            issues.append(f"installed package digest mismatch for {skill_id}")
        if pkg.ref.skill_version != str(row.get("skill_version") or ""):
            issues.append(f"installed package version mismatch for {skill_id}")
    return issues


def _agents_preservation_note(plan: InstallPlan) -> dict[str, Any]:
    original = ""
    path = plan.host / AGENTS_MD
    if path.is_file():
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            original = ""
    new_text = ""
    for row in plan.files:
        if row.rel == AGENTS_MD:
            new_text = row.data.decode("utf-8")
            break
    preserved_body = True
    if original and new_text:
        from scaffold_p5.agents import parse_managed_regions

        new_spans, issues = parse_managed_regions(new_text)
        if issues:
            preserved_body = False
        else:
            old_spans, old_issues = parse_managed_regions(original)
            new_start = new_spans.get(CONSUMER_INSTALL_REGION, (len(new_text), len(new_text)))[0]
            if not old_issues and CONSUMER_INSTALL_REGION in old_spans:
                old_start, old_end = old_spans[CONSUMER_INSTALL_REGION]
                human = original[:old_start] + original[old_end:]
                new_human = new_text[:new_start] + new_text[new_spans[CONSUMER_INSTALL_REGION][1]:]
                preserved_body = human.strip() == new_human.strip() or not human.strip()
            else:
                preserved_body = original.rstrip("\n") in new_text[:new_start] or original in new_text
    return {
        "action": "create" if AGENTS_MD in plan.added else (
            "managed-region" if AGENTS_MD in plan.modified else "unchanged"
        ),
        "human_body_preserved": preserved_body,
        "region": CONSUMER_INSTALL_REGION if has_consumer_install_region(new_text or original) else None,
        "whole_file_replace": False,
    }


def _gitattributes_preservation_note(plan: InstallPlan) -> dict[str, Any]:
    original = ""
    path = plan.host / GITATTRIBUTES
    if path.is_file():
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            original = ""
    new_text = ""
    for row in plan.files:
        if row.rel == GITATTRIBUTES:
            new_text = row.data.decode("utf-8")
            break
    preserved_body = True
    if original and new_text:
        new_spans, issues = parse_gitattributes_region(new_text)
        if issues:
            preserved_body = False
        else:
            start = new_spans.get(GITATTR_REGION, (len(new_text), len(new_text)))[0]
            human = original
            old_spans, old_issues = parse_gitattributes_region(original)
            if not old_issues and GITATTR_REGION in old_spans:
                human = original[: old_spans[GITATTR_REGION][0]]
            preserved_body = (
                not human.strip()
                or human.rstrip("\n").rstrip("\r") in new_text[:start]
                or human in new_text
            )
    return {
        "action": "create" if GITATTRIBUTES in plan.added else (
            "managed-region" if GITATTRIBUTES in plan.modified else "unchanged"
        ),
        "human_body_preserved": preserved_body,
        "region": GITATTR_REGION if has_gitattributes_region(new_text or original) else None,
        "whole_file_replace": False,
    }


def _plan_hooks_json(plan: InstallPlan) -> str | None:
    path = plan.host / HOOKS_JSON_REL
    existing: Any = None
    if path.exists():
        if not path.is_file():
            return ".cursor/hooks.json exists and is not a file"
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return ".cursor/hooks.json is not valid JSON; refusing to overwrite"
    try:
        merged = merge_scaffold_hooks(existing)
    except ValueError as exc:
        return str(exc)
    _replace_or_add_file(plan, HOOKS_JSON_REL, dumps_hooks_json(merged).encode("utf-8"))
    for row in plan.files:
        if row.rel == HOOKS_JSON_REL:
            row.ownership = OWNERSHIP_MANAGED_JSON_FRAGMENT
            row.region_id = FRAGMENT_ID
    return None


def _hook_fragment_issues(
    host: Path, manifest: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    missing: list[str] = []
    drifted: list[str] = []
    incompat: list[str] = []
    recorded = {
        (row["path"], row["fragment_id"]): row
        for row in manifest_fragment_records(manifest)
    }
    rec = recorded.get((HOOKS_JSON_REL, FRAGMENT_ID))
    expected = expected_hook_fragment_digest()
    path = host / HOOKS_JSON_REL
    if rec is not None and rec["digest"] != expected:
        missing.append(HOOKS_JSON_REL)
    if not path.is_file():
        missing.append(HOOKS_JSON_REL)
        return sorted(set(missing)), drifted, incompat
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        incompat.append(".cursor/hooks.json is malformed")
        return missing, drifted, incompat
    fragment, frag_missing, frag_drifted, frag_incompat = inspect_scaffold_hook_fragment(
        data
    )
    missing.extend(frag_missing)
    drifted.extend(frag_drifted)
    incompat.extend(frag_incompat)
    if rec is None:
        missing.append(HOOKS_JSON_REL)
    if fragment is not None:
        live = json.dumps(
            fragment, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if sha256_bytes(live.encode("utf-8")) != expected:
            drifted.append(HOOKS_JSON_REL)
    return sorted(set(missing)), sorted(set(drifted)), incompat


def _has_cursor_profile(profiles: tuple[AdapterProfile, ...]) -> bool:
    return any(profile.profile_id == CURSOR_PROFILE for profile in profiles)


def _agents_adapter_block(profiles: tuple[AdapterProfile, ...]) -> str:
    """Declared-adapter AGENTS guidance. Empty when no adapter profile is installed."""
    dirs: list[str] = []
    for rel in required_paths(profiles):
        normalized = rel.replace("\\", "/")
        if "/skills/" not in normalized:
            continue
        directory = normalized.rsplit("/", 1)[0] + "/"
        if directory not in dirs:
            dirs.append(directory)
    if not dirs:
        return ""
    listed = "\n".join(f"`{item}`" for item in dirs)
    return (
        "Cursor adapters exist only for those four Skills:\n"
        f"{listed}"
    )


def _required_gitattr_lines(profiles: tuple[AdapterProfile, ...]) -> tuple[str, ...]:
    base = (
        ".scaffold/install/** -text",
        "AGENTS.md -text",
        ".gitattributes -text",
    )
    return base + gitattributes_lines(profiles)


def _first_use_rule_issues(host: Path) -> list[str]:
    path = host / FIRST_USE_RULE_REL
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ["Cursor first-use rule is unreadable"]
    meta = parse_always_apply_rule(text)
    issues: list[str] = []
    if not meta.get("alwaysApply"):
        issues.append("Cursor first-use rule is not represented as alwaysApply: true")
    if meta.get("is_skill"):
        issues.append("Cursor first-use rule must not be a Skill")
    if "alwaysApply: true" not in text:
        issues.append("Cursor first-use rule metadata omits alwaysApply: true")
    return issues


def _hooks_json_preservation_note(plan: InstallPlan) -> dict[str, Any]:
    original = ""
    path = plan.host / HOOKS_JSON_REL
    if path.is_file():
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            original = ""
    new_text = ""
    for row in plan.files:
        if row.rel == HOOKS_JSON_REL:
            new_text = row.data.decode("utf-8")
            break
    preserved = True
    if original:
        try:
            old = json.loads(original)
            new = json.loads(new_text) if new_text else {}
            old_hooks = old.get("hooks") if isinstance(old.get("hooks"), dict) else {}
            new_hooks = new.get("hooks") if isinstance(new.get("hooks"), dict) else {}
            for event, items in old_hooks.items():
                if not isinstance(items, list):
                    continue
                human = [item for item in items if not is_scaffold_hook_command(item)]
                live = new_hooks.get(event) if isinstance(new_hooks.get(event), list) else []
                live_human = [item for item in live if not is_scaffold_hook_command(item)]
                if human != live_human:
                    preserved = False
                    break
        except (json.JSONDecodeError, TypeError, ValueError):
            preserved = False
    return {
        "action": "create" if HOOKS_JSON_REL in plan.added else (
            "managed-fragment" if HOOKS_JSON_REL in plan.modified else "unchanged"
        ),
        "unrelated_hooks_preserved": preserved,
        "fragment_id": FRAGMENT_ID,
        "whole_file_replace": False,
        "ownership": OWNERSHIP_MANAGED_JSON_FRAGMENT,
    }
