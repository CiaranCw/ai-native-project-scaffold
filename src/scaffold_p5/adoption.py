from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.agents import (
    AGENTS_ROUTER_REGION,
    GENUINE,
    SAFE_INTEGRATE,
    classify_agents_file,
    has_managed_router_region,
)
from scaffold_p5.discovery import (
    facts_as_dicts,
    module_paths,
    observed_testing_surface,
    resolve_existing,
)
from scaffold_p5.discovery_context import DiscoverySession
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
from scaffold_p5.inventory import (
    EXCLUDED_DIR_NAMES,
    InventoryBudget,
    MetadataWalk,
    bounded_metadata_walk,
)
from scaffold_p5.io_util import (
    file_digest,
    read_yaml,
    write_text_atomic,
    write_yaml_atomic,
)
from scaffold_p5.models import AdoptionPlan, DiscoveryFact, PackageRef, PlanAction
from scaffold_p5.ownership import P6_DURABLE_EVIDENCE_AREA, source_area_key
from scaffold_p5.preflight import PreflightDecision
from scaffold_p5.schemas import (
    ADOPTION_PLAN_SCHEMA_VERSION,
    CURRENT_PROJECT_CONTRACT_GENERATION,
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

# F1 (R7 P1): persisted authorization basis for an Adoption apply request.
# `--approved --plan-digest` is a consistency-checked APPLY REQUEST, not human
# provenance. The basis records the real source that authorized the apply.
# No kind may be rendered as a human grant unless a human actually granted it.
AUTHORIZATION_KINDS = frozenset(
    {"standing_policy", "agent_asserted", "human_instruction", "client_confirmation"}
)

STANDING_POLICY_LOCATION = (
    "skills/understand/SKILL.md bootstrap standing pre-authorization "
    "(AGENTS.md managed router region mirrors the same clause)"
)


def normalize_authorization_basis(value: Any) -> dict[str, Any] | None:
    """Normalize an authorization basis. Never fabricates a human grant."""
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind") or "").strip()
    if kind not in AUTHORIZATION_KINDS:
        return None
    row: dict[str, Any] = {
        "kind": kind,
        "recorded_at": iso_now(),
    }
    location = str(value.get("location") or "").strip()
    if location:
        row["location"] = location
    note = str(value.get("note") or "").strip()
    if note:
        row["note"] = note
    return row


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}-{utc_stamp()}-{secrets.token_hex(4)}"


def adoption_target_generation(distribution: Distribution) -> str:
    """Adopt at the newest Project Contract generation the pinned package establishes.

    The shipped packages declare the current generation, so a fresh host is
    adopted post-boundary and never receives legacy compatibility amnesty.
    """
    actual = getattr(distribution, "actual_understand", None)
    manifest = getattr(actual, "manifest", None) or {}
    declared = (manifest.get("contracts") or {}).get("project_contract_generations") or []
    ranked = []
    for value in declared:
        text = str(value).strip()
        try:
            ranked.append((int(text), text))
        except ValueError:
            continue
    if not ranked:
        return CURRENT_PROJECT_CONTRACT_GENERATION
    return max(ranked)[1]


def build_adoption_plan(
    root: Path,
    *,
    facts: list[DiscoveryFact],
    distribution: Distribution,
    preflight: PreflightDecision,
    derived_copy: bool = False,
    budget: InventoryBudget | None = None,
) -> AdoptionPlan:
    release = distribution.selected_release
    if release is None:
        raise ValueError("Adoption Plan requires a Selected Distribution Release")
    pinned = preflight.pinned_understand or release.pinned("understand")
    intended = preflight.intended_lock or _intended_from_release(release)
    target_generation = adoption_target_generation(distribution)
    baseline = scm_baseline(root)
    baseline["workspace"] = workspace_fingerprint(root, _baseline_paths(root))
    actions: list[PlanAction] = []
    actions.append(_agents_plan_action(root, facts))
    existing_agents = (root / AGENTS_MD).exists()
    if existing_agents:
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
    actions.append(_p6_durable_evidence_area_action())
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
    if observed_testing_surface(facts):
        actions.append(
            _create_or_preserve(
                root,
                TESTING_MD,
                "P2 testing entry is required when a test surface is observed",
                "create testing knowledge entry",
            )
        )
    source = _fact(facts, "source_tree")
    for area in (source.value if source and source.value else []):
        area_key = source_area_key(area)
        if area_key and not any(action.target == area_key for action in actions):
            actions.append(
                PlanAction(
                    "PRESERVE",
                    area_key,
                    "HUMAN_OWNED",
                    "Observed business source area remains human-owned",
                    "business source bytes unchanged during Adoption",
                )
            )
    for module in module_paths(facts):
        actions.append(
            _create_or_preserve(
                root,
                f"{MODULE_DOCS}/{module}.md",
                "Important indexed module requires a canonical knowledge entry",
                f"create verified-path module entry for {module}",
            )
        )
    known_targets = {action.target for action in actions}
    preserved, preserve_walk = _preserve_human_paths(root, budget=budget)
    for path in preserved:
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
    if preserve_walk.truncated or preserve_walk.unknown:
        facts = list(facts) + [
            DiscoveryFact(
                "human_owned_preservation",
                {
                    "observation": preserve_walk.observation,
                    "paths": list(preserved),
                    "entries_enumerated": preserve_walk.entries_enumerated,
                },
                "UNKNOWN",
                True,
            )
        ]
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
    actions.extend(_consumer_install_preserve_actions(root))
    envelope = [a.target for a in actions if a.action_class in {"CREATE", "MANAGED_UPDATE"}]
    coverage: dict[str, Any] = {}
    baseline["inventory"] = durable_inventory(
        root, exact_observe=envelope, coverage_out=coverage
    )
    baseline["inventory_coverage"] = coverage
    blockers = _activation_blockers(facts, actions)
    body = {
        "schema_version": ADOPTION_PLAN_SCHEMA_VERSION,
        "release_id": release.release_id,
        "pinned_understand": _ref_dict(pinned),
        "intended_lock": intended,
        "target_contract_generation": target_generation,
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
        target_contract_generation=target_generation,
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
    proven_generated = _proven_session_targets(root, old, session)
    for previous in old.actions:
        if previous.target == AGENTS_MD:
            actions.append(_agents_plan_action(root, facts))
            continue
        if previous.target.endswith("/"):
            actions.append(previous)
            continue
        action = previous
        if (
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
                action = PlanAction(
                    "PRESERVE",
                    previous.target,
                    "HUMAN_OWNED",
                    "Existing target lacks current Session generation provenance",
                    "file bytes unchanged",
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
    if observed_testing_surface(facts) and not any(
        action.target == TESTING_MD for action in actions
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
    for area in (source.value if source and source.value else []):
        area_key = source_area_key(area)
        if area_key and not any(action.target == area_key for action in actions):
            actions.append(
                PlanAction(
                    "PRESERVE",
                    area_key,
                    "HUMAN_OWNED",
                    "Replacement Plan preserves observed business source authority",
                    "business source bytes unchanged",
                )
            )
    for module in module_paths(facts):
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
    actions.extend(_consumer_install_preserve_actions(root))
    known = {action.target for action in actions}
    for path, row in durable_inventory(root).items():
        if path.startswith(".scaffold/runtime/") or path in known:
            continue
        if _is_consumer_install_path(path):
            continue
        if not isinstance(row, dict) or row.get("type") != "file":
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
    envelope = [
        action.target
        for action in actions
        if action.action_class in {"CREATE", "MANAGED_UPDATE"}
    ]
    coverage: dict[str, Any] = {}
    baseline["inventory"] = durable_inventory(
        root, exact_observe=envelope, coverage_out=coverage
    )
    baseline["inventory_coverage"] = coverage
    blockers = _activation_blockers(facts, actions)
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
                managed_region=a.get("managed_region"),
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


def persist_session(
    root: Path,
    plan: AdoptionPlan,
    *,
    status: str,
    steps: list[str],
    checkpoints: list[str],
    mutations: list[dict[str, Any]],
    observed_approved: bool,
    authorization_basis: dict[str, Any] | None = None,
) -> Path:
    session_id = make_id("adopt")
    directory = root / ".scaffold" / "runtime" / "adoption-sessions" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    now = iso_now()
    plan_record: dict[str, Any] = {
        "identity": plan.plan_id,
        "digest": plan.digest,
        "observed_approved": observed_approved,
    }
    basis = normalize_authorization_basis(authorization_basis)
    if basis is not None:
        plan_record["authorization_basis"] = basis
    session = {
        "record_type": "adoption_session",
        "schema_version": "1",
        "record_id": session_id,
        "created_at": now,
        "updated_at": now,
        "status": status,
        "baseline": plan.baseline,
        "plan": plan_record,
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


def replace_session_plan(
    directory: Path,
    plan: AdoptionPlan,
    *,
    authorization_basis: dict[str, Any] | None = None,
) -> None:
    existing = read_yaml(directory / "session.yaml")
    provenance = dict(existing.get("generated_provenance") or {})
    host_root = directory.parents[3]
    for action in plan.actions:
        path = host_root / action.target
        if action.ownership == "GENERATED" and path.is_file():
            provenance[action.target] = file_digest(path)
    prior_plan = existing.get("plan") if isinstance(existing.get("plan"), dict) else {}
    prior_basis = prior_plan.get("authorization_basis")
    basis = normalize_authorization_basis(authorization_basis)
    if basis is None and isinstance(prior_basis, dict):
        basis = dict(prior_basis)
    plan_record = {
        "identity": plan.plan_id,
        "digest": plan.digest,
        "observed_approved": True,
    }
    if basis is not None:
        plan_record["authorization_basis"] = basis
    write_yaml_atomic(directory / "plan.yaml", plan_to_dict(plan))
    update_session(
        directory,
        status="OPEN",
        baseline=plan.baseline,
        plan=plan_record,
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
    if action.managed_region:
        data["managed_region"] = action.managed_region
    return data


def _agents_plan_action(root: Path, facts: list[DiscoveryFact]) -> PlanAction:
    state = classify_agents_file(root)
    if state == "absent":
        return PlanAction(
            "CREATE",
            AGENTS_MD,
            "GENERATED",
            "No existing router; create thin Scaffold router",
            "create AGENTS.md",
        )
    text = ""
    if (root / AGENTS_MD).is_file():
        try:
            text = (root / AGENTS_MD).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            text = ""
    if state == GENUINE:
        managed = has_managed_router_region(text)
        return PlanAction(
            "PRESERVE",
            AGENTS_MD,
            "MANAGED" if managed else "HUMAN_OWNED",
            "Existing Agent router already satisfies the Scaffold routing contract",
            "file bytes unchanged",
            "THIN_BRIDGE",
            AGENTS_ROUTER_REGION if managed else None,
        )
    if state == SAFE_INTEGRATE:
        return PlanAction(
            "MANAGED_UPDATE",
            AGENTS_MD,
            "MANAGED",
            "Existing human AGENTS.md remains; propose a bounded Scaffold router region. No whole-file replace.",
            "insert or replace the scaffold:managed:agents-router region only; human text outside the region is unchanged",
            "THIN_BRIDGE",
            AGENTS_ROUTER_REGION,
        )
    return PlanAction(
        "PRESERVE",
        AGENTS_MD,
        "HUMAN_OWNED",
        "Existing AGENTS.md has conflicting markers, an explicit anti-Scaffold instruction, or other unsafe integration evidence. Human must choose how the Layer-1 router is established.",
        "file bytes unchanged",
        "DEFER",
    )


def _activation_blockers(
    facts: list[DiscoveryFact],
    actions: list[PlanAction],
) -> list[str]:
    agents_action = next(
        (action for action in actions if action.target == AGENTS_MD),
        None,
    )
    planned_integration = bool(
        agents_action and agents_action.action_class == "MANAGED_UPDATE"
    )
    blockers = []
    for fact in facts:
        if not fact.critical or fact.confidence not in {"UNKNOWN", "CONFLICTING"}:
            continue
        if fact.name == "agents_scaffold_bridge" and planned_integration:
            continue
        blockers.append(f"{fact.name}:{fact.confidence}")
    return blockers


def _consumer_install_preserve_actions(root: Path) -> list[PlanAction]:
    if not (root / ".scaffold" / "install" / "install.yaml").is_file():
        return []
    actions = [
        PlanAction(
            "PRESERVE",
            ".scaffold/install/",
            "MANAGED",
            "Project-local Scaffold installation is managed product bytes, not Adoption",
            "installation bytes unchanged during Adoption",
        )
    ]
    for name in (
        "scaffold-understand",
        "scaffold-develop",
        "scaffold-test",
        "scaffold-submit",
    ):
        rel = f".cursor/skills/{name}/SKILL.md"
        if (root / rel).is_file():
            actions.append(
                PlanAction(
                    "PRESERVE",
                    rel,
                    "MANAGED",
                    "Cursor discovery adapter is managed installation, not a fifth Skill",
                    "bytes unchanged",
                    "THIN_BRIDGE",
                )
            )
    return actions


def _is_consumer_install_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").strip("/")
    return (
        normalized == ".scaffold/install"
        or normalized.startswith(".scaffold/install/")
        or normalized.startswith(".cursor/skills/scaffold")
    )


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


def _preserve_human_paths(
    root: Path,
    *,
    budget: InventoryBudget | None = None,
) -> tuple[list[str], MetadataWalk]:
    out: list[str] = []
    limits = budget or InventoryBudget()
    session = DiscoverySession.ephemeral(root, budget=limits)
    for rel in ("README.md", "docs/notes.md", "docs/human.md"):
        actual = resolve_existing(root, rel, session=session)
        if actual:
            out.append(actual)
    walked = bounded_metadata_walk(
        root,
        start="docs",
        budget=limits,
        skip_dir_names=EXCLUDED_DIR_NAMES,
        state=session.walk,
        on_directory=session.remember_directory,
        dir_cache=session.directories,
    )
    if not walked.unknown or walked.files or walked.directories:
        for rel in walked.files:
            if rel not in out:
                out.append(rel)
    return out, walked


def _baseline_paths(root: Path) -> list[str]:
    paths = ["README.md", AGENTS_MD, "CLAUDE.md"]
    return [p for p in paths if (root / p).exists()]


def _p6_durable_evidence_area_action() -> PlanAction:
    return PlanAction(
        "CREATE",
        P6_DURABLE_EVIDENCE_AREA,
        "GENERATED",
        (
            "P6 durable Evidence support-artifact root. Bootstrap registers "
            "GENERATED area ownership only and does not create the directory."
        ),
        "register GENERATED area ownership only; no file created at Bootstrap",
    )


def ownership_presentation(plan: AdoptionPlan) -> dict[str, Any]:
    """Human-facing GENERATED ownership in the reviewed Adoption Plan."""
    generated_targets: list[dict[str, str]] = []
    generated_areas: list[dict[str, str]] = []
    for action in plan.actions:
        if action.ownership != "GENERATED":
            continue
        row = {
            "target": action.target,
            "action_class": action.action_class,
            "rationale": action.rationale,
            "expected": action.expected,
        }
        generated_targets.append(row)
        if action.target.endswith("/"):
            generated_areas.append(row)
    return {
        "note": (
            "GENERATED ownership below is part of the human-reviewed Adoption "
            "Plan. It is not injected after Plan approval."
        ),
        "generated_targets": generated_targets,
        "generated_areas": generated_areas,
        "p6_durable_evidence_area": P6_DURABLE_EVIDENCE_AREA,
    }


def preservation_presentation(plan: AdoptionPlan) -> dict[str, Any]:
    """Human-facing summary of important PRESERVE areas. Not a new record."""
    important: list[str] = []
    for action in plan.actions:
        if action.action_class != "PRESERVE":
            continue
        target = action.target
        if _important_preserved_area(target) and target not in important:
            important.append(target)
    return {
        "note": (
            "Important existing HUMAN_OWNED areas remain outside the mutation "
            "envelope. Reference does not transfer ownership."
        ),
        "areas": important,
    }


def _important_preserved_area(target: str) -> bool:
    lowered = target.replace("\\", "/")
    if target in {AGENTS_MD, "CLAUDE.md", "CLAUDE.local.md", "README.md", "CODEX.md"}:
        return True
    if lowered.startswith(".cursor/") or lowered == ".cursor/rules":
        return True
    if lowered.startswith("docs/") or lowered.endswith("architecture.md"):
        return True
    if lowered.endswith("/") and lowered.rstrip("/").split("/")[0] in {
        "src",
        "lib",
        "app",
        "pkg",
    }:
        return True
    return False


def _fact(facts: list[DiscoveryFact], name: str) -> DiscoveryFact | None:
    return next((fact for fact in facts if fact.name == name), None)
