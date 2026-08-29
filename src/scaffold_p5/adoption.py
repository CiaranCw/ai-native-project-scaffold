from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.discovery import facts_as_dicts
from scaffold_p5.distribution import Distribution
from scaffold_p5.host_state import (
    AGENTS_MD,
    ARCHITECTURE_MD,
    COMMANDS_YAML,
    DEVELOPMENT_MD,
    MODULES_YAML,
    MODULE_DOCS,
    OVERVIEW_MD,
    PROJECT_YAML,
    SKILLS_LOCK,
    TESTING_MD,
    TESTS_YAML,
    durable_inventory,
    inspect_lock,
    scm_baseline,
    workspace_fingerprint,
)
from scaffold_p5.io_util import (
    file_digest,
    read_yaml,
    write_text_atomic,
    write_yaml_atomic,
)
from scaffold_p5.models import AdoptionPlan, DiscoveryFact, PackageRef, PlanAction
from scaffold_p5.preflight import PreflightDecision
from scaffold_p5.schemas import (
    ADOPTION_PLAN_SCHEMA_VERSION,
    adoption_plan_digest,
    validate_adoption_plan_data,
)


STANDARD_TARGETS = (
    PROJECT_YAML,
    MODULES_YAML,
    COMMANDS_YAML,
    TESTS_YAML,
    SKILLS_LOCK,
    AGENTS_MD,
    OVERVIEW_MD,
    ARCHITECTURE_MD,
    DEVELOPMENT_MD,
    TESTING_MD,
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}-{utc_stamp()}-{secrets.token_hex(4)}"


def build_adoption_plan(
    root: Path,
    *,
    facts: list[DiscoveryFact],
    distribution: Distribution,
    preflight: PreflightDecision,
    derived_copy: bool = False,
) -> AdoptionPlan:
    release = distribution.selected_release
    if release is None:
        raise ValueError("Adoption Plan requires a Selected Distribution Release")
    pinned = preflight.pinned_understand or release.pinned("understand")
    intended = preflight.intended_lock or _intended_from_release(release)
    baseline = scm_baseline(root)
    baseline["workspace"] = workspace_fingerprint(root, _baseline_paths(root))
    baseline["inventory"] = durable_inventory(root)
    actions: list[PlanAction] = []
    existing_agents = (root / AGENTS_MD).exists()
    if existing_agents:
        bridge = next(
            (fact for fact in facts if fact.name == "agents_scaffold_bridge"),
            None,
        )
        genuine_bridge = bool(
            bridge and bridge.confidence == "VERIFIED" and bridge.value is True
        )
        actions.append(
            PlanAction(
                "PRESERVE",
                AGENTS_MD,
                "HUMAN_OWNED",
                "Existing Agent router remains human text"
                if genuine_bridge
                else "Existing Agent router is not a proven Scaffold bridge; human resolution required",
                "file bytes unchanged",
                "THIN_BRIDGE" if genuine_bridge else "DEFER",
            )
        )
        actions.append(
            _create_or_preserve(
                root,
                OVERVIEW_MD,
                "Canonical overview rather than rewriting AGENTS.md",
                "create docs/project/overview.md",
            )
        )
    else:
        actions.append(
            PlanAction(
                "CREATE",
                AGENTS_MD,
                "GENERATED",
                "No existing router; create thin Scaffold router",
                "create AGENTS.md",
            )
        )
        actions.append(
            _create_or_preserve(
                root,
                OVERVIEW_MD,
                "Required project start document",
                "create docs/project/overview.md",
            )
        )
    for target in (PROJECT_YAML, MODULES_YAML, COMMANDS_YAML, TESTS_YAML, SKILLS_LOCK):
        actions.append(
            _create_or_preserve(
                root,
                target,
                f"Required Active-host artifact {target}",
                f"create {target}",
            )
        )
    architecture = _fact(facts, "architecture")
    if (
        architecture
        and architecture.confidence == "VERIFIED"
        and architecture.value
        and architecture.value != ARCHITECTURE_MD
    ):
        actions.append(
            _create_or_preserve(
                root,
                ARCHITECTURE_MD,
                "P2 canonical architecture entry points to verified HUMAN_OWNED authority",
                f"create pointer to {architecture.value}",
            )
        )
    elif (root / ARCHITECTURE_MD).exists():
        actions.append(
            _create_or_preserve(
                root,
                ARCHITECTURE_MD,
                "Existing canonical architecture remains human authority",
                "file bytes unchanged",
            )
        )
    else:
        actions.append(
            PlanAction(
                "DEFER",
                ARCHITECTURE_MD,
                "GENERATED",
                "Architecture is not established; do not invent it",
                "omit architecture entry until evidence exists",
            )
        )
    build = _fact(facts, "declared_build_surface")
    if build and build.value:
        actions.append(
            _create_or_preserve(
                root,
                DEVELOPMENT_MD,
                "P2 development entry is required for an observed workflow surface",
                "create development knowledge entry",
            )
        )
    tests = _fact(facts, "test_tree")
    if tests and tests.confidence == "VERIFIED" and tests.value:
        actions.append(
            _create_or_preserve(
                root,
                TESTING_MD,
                "P2 testing entry is required when tests are observed",
                "create testing knowledge entry",
            )
        )
    source = _fact(facts, "source_tree")
    for module in (source.value if source and source.value else []):
        actions.append(
            _create_or_preserve(
                root,
                f"{MODULE_DOCS}/{module}.md",
                "Important indexed module requires a canonical knowledge entry",
                f"create verified-path module entry for {module}",
            )
        )
    known_targets = {action.target for action in actions}
    for path in _preserve_human_paths(root):
        if path in known_targets:
            continue
        actions.append(
            PlanAction(
                "PRESERVE",
                path,
                "HUMAN_OWNED",
                "Existing human documentation or source remains untouched",
                "bytes unchanged",
            )
        )
    clients = next((f.value for f in facts if f.name == "existing_ai_clients"), [])
    for client in clients or []:
        if client == AGENTS_MD:
            continue
        actions.append(
            PlanAction(
                "PRESERVE",
                client,
                "HUMAN_OWNED",
                "Existing client entry is not blindly replaced",
                "bytes unchanged",
                "PRESERVE",
            )
        )
    if derived_copy:
        actions.append(
            PlanAction(
                "CREATE",
                ".scaffold/derived/understand.md",
                "GENERATED",
                "Optional one-way non-authoritative derived copy",
                "create derived copy with source identity",
                "THIN_BRIDGE",
            )
        )
    if (root / ".env").exists():
        actions.append(
            PlanAction(
                "LOCAL_ONLY",
                ".env",
                "HUMAN_OWNED",
                "Machine-local secrets stay local",
                "not copied into shared knowledge",
            )
        )
    envelope = [a.target for a in actions if a.action_class in {"CREATE", "MANAGED_UPDATE"}]
    blockers = [
        f.name + ":" + f.confidence
        for f in facts
        if f.critical and f.confidence in {"UNKNOWN", "CONFLICTING"}
    ]
    body = {
        "schema_version": ADOPTION_PLAN_SCHEMA_VERSION,
        "release_id": release.release_id,
        "pinned_understand": _ref_dict(pinned),
        "intended_lock": intended,
        "target_contract_generation": "1",
        "mutation_envelope": envelope,
        "actions": [_action_dict(a) for a in actions],
        "facts": facts_as_dicts(facts),
        "baseline": baseline,
        "activation_blockers": blockers,
    }
    digest = adoption_plan_digest(body)
    plan_id = f"plan-{digest[:16]}"
    return AdoptionPlan(
        plan_id=plan_id,
        digest=digest,
        release_id=release.release_id,
        pinned_understand=pinned,
        intended_lock=intended,
        target_contract_generation="1",
        mutation_envelope=envelope,
        actions=actions,
        facts=facts,
        baseline=baseline,
        activation_blockers=blockers,
    )


def rebuild_adoption_plan(
    root: Path,
    old: AdoptionPlan,
    facts: list[DiscoveryFact],
    session: dict[str, Any],
) -> AdoptionPlan:
    """Create a new human-review candidate from current durable state."""
    actions: list[PlanAction] = []
    bridge = _fact(facts, "agents_scaffold_bridge")
    proven_generated = _proven_session_targets(root, old, session)
    for previous in old.actions:
        action = previous
        if previous.target == AGENTS_MD and previous.ownership == "HUMAN_OWNED":
            genuine = bool(
                bridge and bridge.confidence == "VERIFIED" and bridge.value is True
            )
            action = PlanAction(
                "PRESERVE",
                AGENTS_MD,
                "HUMAN_OWNED",
                "Replacement Plan revalidated the existing Agent router"
                if genuine
                else "Existing Agent router remains unresolved and requires human action",
                "file bytes unchanged",
                "THIN_BRIDGE" if genuine else "DEFER",
            )
        elif (
            previous.action_class in {"CREATE", "MANAGED_UPDATE"}
            and (root / previous.target).exists()
            and previous.ownership in {"GENERATED", "MANAGED"}
        ):
            if previous.target in proven_generated:
                action = PlanAction(
                    "MANAGED_UPDATE",
                    previous.target,
                    "GENERATED",
                    "Current Session proves Scaffold produced this artifact",
                    previous.expected,
                    previous.client_strategy,
                )
            else:
                genuine = bool(
                    previous.target == AGENTS_MD
                    and bridge
                    and bridge.confidence == "VERIFIED"
                    and bridge.value is True
                )
                action = PlanAction(
                    "PRESERVE",
                    previous.target,
                    "HUMAN_OWNED",
                    "Existing target lacks current Session generation provenance",
                    "file bytes unchanged",
                    (
                        "THIN_BRIDGE"
                        if genuine
                        else ("DEFER" if previous.target == AGENTS_MD else None)
                    ),
                )
        actions.append(action)

    architecture = _fact(facts, "architecture")
    actions = [
        action
        for action in actions
        if not (
            action.target == ARCHITECTURE_MD
            and action.action_class == "DEFER"
            and architecture
            and architecture.confidence == "VERIFIED"
            and architecture.value
            and architecture.value != ARCHITECTURE_MD
        )
    ]
    if (
        architecture
        and architecture.confidence == "VERIFIED"
        and architecture.value
        and architecture.value != ARCHITECTURE_MD
        and not any(action.target == ARCHITECTURE_MD for action in actions)
    ):
        actions.append(
            _replacement_target(
                root,
                ARCHITECTURE_MD,
                "Replacement Plan creates a canonical pointer to verified architecture",
                f"point to {architecture.value}",
                proven_generated,
            )
        )
    build = _fact(facts, "declared_build_surface")
    if build and build.value and not any(
        action.target == DEVELOPMENT_MD for action in actions
    ):
        actions.append(
            _replacement_target(
                root,
                DEVELOPMENT_MD,
                "Replacement Plan covers the now-observed development workflow",
                "create/update development knowledge entry",
                proven_generated,
            )
        )
    tests = _fact(facts, "test_tree")
    if (
        tests
        and tests.confidence == "VERIFIED"
        and tests.value
        and not any(action.target == TESTING_MD for action in actions)
    ):
        actions.append(
            _replacement_target(
                root,
                TESTING_MD,
                "Replacement Plan covers the now-observed test structure",
                "create/update testing knowledge entry",
                proven_generated,
            )
        )
    source = _fact(facts, "source_tree")
    for module in (source.value if source and source.value else []):
        target = f"{MODULE_DOCS}/{module}.md"
        if not any(action.target == target for action in actions):
            actions.append(
                _replacement_target(
                    root,
                    target,
                    "Replacement Plan covers an observed important module",
                    f"create/update verified-path module entry for {module}",
                    proven_generated,
                )
            )

    known = {action.target for action in actions}
    for path in durable_inventory(root):
        if path.startswith(".scaffold/runtime/") or path in known:
            continue
        actions.append(
            PlanAction(
                "PRESERVE",
                path,
                "HUMAN_OWNED",
                "Current durable state is explicitly preserved by the replacement Plan",
                "file bytes unchanged",
            )
        )
    baseline = scm_baseline(root)
    baseline["workspace"] = workspace_fingerprint(root, _baseline_paths(root))
    baseline["inventory"] = durable_inventory(root)
    envelope = [
        action.target
        for action in actions
        if action.action_class in {"CREATE", "MANAGED_UPDATE"}
    ]
    blockers = [
        f"{fact.name}:{fact.confidence}"
        for fact in facts
        if fact.critical and fact.confidence in {"UNKNOWN", "CONFLICTING"}
    ]
    body = {
        "schema_version": ADOPTION_PLAN_SCHEMA_VERSION,
        "release_id": old.release_id,
        "pinned_understand": _ref_dict(old.pinned_understand),
        "intended_lock": old.intended_lock,
        "target_contract_generation": old.target_contract_generation,
        "mutation_envelope": envelope,
        "actions": [_action_dict(action) for action in actions],
        "facts": facts_as_dicts(facts),
        "baseline": baseline,
        "activation_blockers": blockers,
    }
    digest = adoption_plan_digest(body)
    return AdoptionPlan(
        plan_id=f"plan-{digest[:16]}",
        digest=digest,
        release_id=old.release_id,
        pinned_understand=old.pinned_understand,
        intended_lock=old.intended_lock,
        target_contract_generation=old.target_contract_generation,
        mutation_envelope=envelope,
        actions=actions,
        facts=facts,
        baseline=baseline,
        activation_blockers=blockers,
    )


def plan_to_dict(plan: AdoptionPlan) -> dict[str, Any]:
    return {
        "schema_version": ADOPTION_PLAN_SCHEMA_VERSION,
        "plan_id": plan.plan_id,
        "digest": plan.digest,
        "release_id": plan.release_id,
        "pinned_understand": _ref_dict(plan.pinned_understand),
        "intended_lock": plan.intended_lock,
        "target_contract_generation": plan.target_contract_generation,
        "mutation_envelope": plan.mutation_envelope,
        "actions": [_action_dict(a) for a in plan.actions],
        "facts": facts_as_dicts(plan.facts),
        "baseline": plan.baseline,
        "activation_blockers": plan.activation_blockers,
    }


def plan_from_dict(data: dict[str, Any]) -> AdoptionPlan:
    u = data["pinned_understand"]
    return AdoptionPlan(
        plan_id=str(data["plan_id"]),
        digest=str(data["digest"]),
        release_id=str(data["release_id"]),
        pinned_understand=PackageRef(
            skill_id=str(u["skill_id"]),
            skill_version=str(u["skill_version"]),
            package_digest=str(u["package_digest"]),
            package_format_version=str(u.get("package_format_version") or "1"),
        ),
        intended_lock=dict(data["intended_lock"]),
        target_contract_generation=str(data.get("target_contract_generation") or "1"),
        mutation_envelope=list(data.get("mutation_envelope") or []),
        actions=[
            PlanAction(
                action_class=str(a["action_class"]),
                target=str(a["target"]),
                ownership=str(a["ownership"]),
                rationale=str(a["rationale"]),
                expected=str(a["expected"]),
                client_strategy=a.get("client_strategy"),
            )
            for a in data.get("actions") or []
        ],
        facts=[
            DiscoveryFact(
                name=str(f["name"]),
                value=f.get("value"),
                confidence=str(f["confidence"]),
                critical=bool(f.get("critical")),
            )
            for f in data.get("facts") or []
        ],
        baseline=dict(data.get("baseline") or {}),
        activation_blockers=list(data.get("activation_blockers") or []),
    )


def validate_plan_content(data: dict[str, Any]) -> list[str]:
    _, issues = validate_adoption_plan_data(data)
    return issues


def approval_matches(plan: AdoptionPlan, approval: dict[str, Any] | None) -> bool:
    if not approval:
        return False
    if not bool(approval.get("approved")):
        return False
    digest = approval.get("plan_digest") or approval.get("digest")
    return digest == plan.digest


def persist_session(root: Path, plan: AdoptionPlan, *, status: str, steps: list[str], checkpoints: list[str], mutations: list[dict[str, Any]], observed_approved: bool) -> Path:
    session_id = make_id("adopt")
    directory = root / ".scaffold" / "runtime" / "adoption-sessions" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    now = iso_now()
    session = {
        "record_type": "adoption_session",
        "schema_version": "1",
        "record_id": session_id,
        "created_at": now,
        "updated_at": now,
        "status": status,
        "baseline": plan.baseline,
        "plan": {
            "identity": plan.plan_id,
            "digest": plan.digest,
            "observed_approved": observed_approved,
        },
        "completed_steps": steps,
        "checkpoints": checkpoints,
        "applied_mutation_summary": mutations,
        "expected_mutations": {},
        "expected_mutations_plan_id": None,
        "pending_validation": ["B7"],
        "release_id": plan.release_id,
        "intended_lock": plan.intended_lock,
        "mutation_envelope": plan.mutation_envelope,
    }
    write_yaml_atomic(directory / "session.yaml", session)
    write_yaml_atomic(directory / "plan.yaml", plan_to_dict(plan))
    return directory


def update_session(directory: Path, **fields: Any) -> None:
    from scaffold_p5.io_util import read_yaml

    path = directory / "session.yaml"
    data = read_yaml(path)
    data.update(fields)
    data["updated_at"] = iso_now()
    write_yaml_atomic(path, data)


def replace_session_plan(directory: Path, plan: AdoptionPlan) -> None:
    existing = read_yaml(directory / "session.yaml")
    provenance = dict(existing.get("generated_provenance") or {})
    host_root = directory.parents[3]
    for action in plan.actions:
        path = host_root / action.target
        if action.ownership == "GENERATED" and path.is_file():
            provenance[action.target] = file_digest(path)
    write_yaml_atomic(directory / "plan.yaml", plan_to_dict(plan))
    update_session(
        directory,
        status="OPEN",
        baseline=plan.baseline,
        plan={
            "identity": plan.plan_id,
            "digest": plan.digest,
            "observed_approved": True,
        },
        release_id=plan.release_id,
        intended_lock=plan.intended_lock,
        mutation_envelope=plan.mutation_envelope,
        checkpoints=[],
        applied_mutation_summary=[],
        expected_mutations={},
        expected_mutations_plan_id=None,
        generated_provenance=provenance,
        pending_validation=["B7"],
    )


def delete_session(directory: Path) -> None:
    for child in directory.iterdir():
        child.unlink()
    directory.rmdir()
    parent = directory.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


def default_ownership(existing_agents_human: bool, derived_copy: bool, preserved: list[str]) -> dict[str, str]:
    ownership = {
        PROJECT_YAML: "GENERATED",
        MODULES_YAML: "GENERATED",
        COMMANDS_YAML: "GENERATED",
        TESTS_YAML: "GENERATED",
        SKILLS_LOCK: "GENERATED",
        OVERVIEW_MD: "GENERATED",
        AGENTS_MD: "HUMAN_OWNED" if existing_agents_human else "GENERATED",
    }
    if derived_copy:
        ownership[".scaffold/derived/understand.md"] = "GENERATED"
    for path in preserved:
        ownership.setdefault(path, "HUMAN_OWNED")
    return ownership


def write_lock(
    root: Path,
    intended: dict[str, Any],
    release_id: str,
    *,
    authoritative: bool = True,
) -> None:
    write_yaml_atomic(
        root / SKILLS_LOCK,
        lock_data(intended, release_id, authoritative=authoritative),
    )


def lock_data(
    intended: dict[str, Any],
    release_id: str,
    *,
    authoritative: bool,
) -> dict[str, Any]:
    return {
        "lock_format_version": "1",
        "schema_version": "1",
        "release_provenance": release_id,
        "authoritative": authoritative,
        "skills": {
            skill: {
                "skill_version": entry["skill_version"],
                "package_digest": entry["package_digest"],
                "package_format_version": entry.get("package_format_version") or "1",
            }
            for skill, entry in intended.items()
        },
    }


def publish_lock_authority(
    root: Path,
    intended: dict[str, Any],
    release_id: str,
) -> list[str]:
    before = inspect_lock(root / SKILLS_LOCK)
    if before.status != "complete_candidate" or not before.data:
        return ["initial lock is not a valid complete candidate"]
    if before.data.get("release_provenance") != release_id:
        return ["initial lock release provenance changed"]
    if before.data.get("skills") != intended:
        return ["initial lock candidate differs from approved intended lock"]
    write_lock(root, intended, release_id, authoritative=True)
    after = inspect_lock(root / SKILLS_LOCK)
    return [] if after.complete_authoritative else after.reasons


def write_partial_lock(root: Path, intended: dict[str, Any], release_id: str) -> None:
    write_yaml_atomic(root / SKILLS_LOCK, partial_lock_data(intended, release_id))


def partial_lock_data(
    intended: dict[str, Any],
    release_id: str,
) -> dict[str, Any]:
    understand = intended["understand"]
    return {
        "lock_format_version": "1",
        "schema_version": "1",
        "release_provenance": release_id,
        "authoritative": False,
        "skills": {
            "understand": {
                "skill_version": understand["skill_version"],
                "package_digest": understand["package_digest"],
                "package_format_version": understand.get("package_format_version") or "1",
            }
        },
    }


def write_text(root: Path, rel: str, text: str) -> None:
    write_text_atomic(root / rel, text)


def _intended_from_release(release) -> dict[str, Any]:
    return {
        skill: {
            "skill_version": release.pinned(skill).skill_version,
            "package_digest": release.pinned(skill).package_digest,
            "package_format_version": release.pinned(skill).package_format_version,
        }
        for skill in ("understand", "develop", "test", "submit")
    }


def _ref_dict(ref: PackageRef) -> dict[str, str]:
    return {
        "skill_id": ref.skill_id,
        "skill_version": ref.skill_version,
        "package_digest": ref.package_digest,
        "package_format_version": ref.package_format_version,
    }


def _action_dict(action: PlanAction) -> dict[str, Any]:
    data = {
        "action_class": action.action_class,
        "target": action.target,
        "ownership": action.ownership,
        "rationale": action.rationale,
        "expected": action.expected,
    }
    if action.client_strategy:
        data["client_strategy"] = action.client_strategy
    return data


def _create_or_preserve(
    root: Path,
    target: str,
    create_rationale: str,
    create_expected: str,
) -> PlanAction:
    if (root / target).exists():
        return PlanAction(
            "PRESERVE",
            target,
            "HUMAN_OWNED",
            "Pre-existing canonical target is not proven Scaffold-owned; preserve human authority",
            "file bytes unchanged",
        )
    return PlanAction(
        "CREATE",
        target,
        "GENERATED",
        create_rationale,
        create_expected,
    )


def _replacement_target(
    root: Path,
    target: str,
    rationale: str,
    expected: str,
    proven_generated: set[str],
) -> PlanAction:
    if not (root / target).exists():
        return PlanAction("CREATE", target, "GENERATED", rationale, expected)
    if target in proven_generated:
        return PlanAction(
            "MANAGED_UPDATE",
            target,
            "GENERATED",
            "Current Session proves Scaffold produced this artifact",
            expected,
        )
    return PlanAction(
        "PRESERVE",
        target,
        "HUMAN_OWNED",
        "Existing canonical target lacks current Session generation provenance",
        "file bytes unchanged",
    )


def _proven_session_targets(
    root: Path,
    old: AdoptionPlan,
    session: dict[str, Any],
) -> set[str]:
    original = old.baseline.get("inventory") or {}
    summaries = {
        str(row.get("target")): str(row.get("digest"))
        for row in session.get("applied_mutation_summary") or []
        if isinstance(row, dict) and row.get("target") and row.get("digest")
    }
    expected = session.get("expected_mutations") or {}
    lineage = session.get("generated_provenance") or {}
    proven: set[str] = set()
    for target in old.mutation_envelope:
        path = root / target
        if not path.is_file():
            continue
        digest = file_digest(path)
        expected_row = expected.get(target)
        has_proof = (
            lineage.get(target) == digest
            or summaries.get(target) == digest
            or (
            isinstance(expected_row, dict)
            and expected_row.get("digest") == digest
            )
        )
        if target in original and not has_proof:
            continue
        if has_proof:
            proven.add(target)
    return proven


def _preserve_human_paths(root: Path) -> list[str]:
    out = []
    for rel in ("README.md", "docs/notes.md", "docs/human.md"):
        if (root / rel).exists():
            out.append(rel)
    docs = root / "docs"
    if docs.exists():
        for path in docs.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(root)).replace("\\", "/")
                if rel not in out:
                    out.append(rel)
    return out


def _baseline_paths(root: Path) -> list[str]:
    paths = ["README.md", AGENTS_MD, "CLAUDE.md"]
    return [p for p in paths if (root / p).exists()]


def _fact(facts: list[DiscoveryFact], name: str) -> DiscoveryFact | None:
    return next((fact for fact in facts if fact.name == name), None)
