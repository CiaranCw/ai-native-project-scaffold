"""Local Test support-artifact storage. Not a canonical development record."""

from __future__ import annotations

import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import file_digest, read_text, write_text_atomic, write_yaml_atomic
from scaffold_p5 import yaml_lite

from scaffold_p6.models import TEST_RUNS
from scaffold_p6.schemas import validate_report, yaml_safe


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"testrun-{stamp}-{secrets.token_hex(4)}"


def run_dir(root: Path, run_id: str) -> Path:
    return root / TEST_RUNS / run_id


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
    if not valid_test_run_id(run_id):
        return False
    base = (root / TEST_RUNS).resolve()
    dest = (base / run_id).resolve()
    try:
        dest.relative_to(base)
    except ValueError:
        return False
    if dest.parent != base or dest == base:
        return False
    if not dest.is_dir():
        return False
    shutil.rmtree(dest)
    return True


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
