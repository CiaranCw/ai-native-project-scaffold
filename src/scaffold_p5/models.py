from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CORE_SKILLS = ("understand", "develop", "test", "submit")
UNDERSTAND_MODES = ("bootstrap", "full", "refresh", "compatibility")
ACTION_CLASSES = ("CREATE", "MANAGED_UPDATE", "PRESERVE", "LOCAL_ONLY", "DEFER")
CLIENT_STRATEGIES = ("PRESERVE", "MANAGED_UPDATE", "THIN_BRIDGE", "DEFER")
OWNERSHIP_MODES = ("GENERATED", "MANAGED", "HUMAN_OWNED")
FACT_CLASSES = ("VERIFIED", "INFERRED", "UNKNOWN", "CONFLICTING")
LIFECYCLES = ("NOT_ADOPTED", "ADOPTING", "ACTIVE", "RECOVERY_REQUIRED")
VALIDITY = ("VALID", "INVALID")
COMPAT_RESULTS = ("EXACT", "COMPATIBLE", "MIGRATION_REQUIRED", "INCOMPATIBLE", "UNKNOWN")
OUTCOMES = ("COMPLETED", "BLOCKED", "FAILED", "NEEDS_HUMAN")
SESSION_STATES = ("OPEN", "BLOCKED", "INTERRUPTED")
MIGRATION_STATES = ("PREPARED", "APPLYING", "VALIDATING", "COMPLETED", "RECOVERY_REQUIRED", "ABORTED")

PreflightContext = Literal["PRE_ADOPTION_BOOTSTRAP", "HOST_COMPATIBILITY"]
HostClass = Literal[
    "NOT_ADOPTED",
    "INTERRUPTED_INITIAL_ADOPTION",
    "ESTABLISHED_HOST",
    "ESTABLISHED_HOST_CONSISTENCY",
    "PRIOR_FOOTPRINT",
]


@dataclass(frozen=True)
class PackageRef:
    skill_id: str
    skill_version: str
    package_digest: str
    package_format_version: str = "1"


@dataclass
class LoadedPackage:
    ref: PackageRef
    path: str
    manifest: dict[str, Any]
    skill_md: str
    validity: str
    validity_reasons: list[str] = field(default_factory=list)
    may_substitute_for: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SelectedRelease:
    release_id: str
    core: dict[str, PackageRef]

    def pinned(self, skill_id: str) -> PackageRef:
        return self.core[skill_id]


@dataclass
class DiscoveryFact:
    name: str
    value: Any
    confidence: str
    critical: bool = False


@dataclass
class PlanAction:
    action_class: str
    target: str
    ownership: str
    rationale: str
    expected: str
    client_strategy: str | None = None


@dataclass
class AdoptionPlan:
    plan_id: str
    digest: str
    release_id: str
    pinned_understand: PackageRef
    intended_lock: dict[str, str]
    target_contract_generation: str
    mutation_envelope: list[str]
    actions: list[PlanAction]
    facts: list[DiscoveryFact]
    baseline: dict[str, Any]
    activation_blockers: list[str]


@dataclass
class ApprovalObservation:
    kind: str
    digest: str
    observed_approved: bool


@dataclass
class SkillResult:
    skill_id: str
    skill_version: str
    mode: str
    outcome: str
    baseline: dict[str, Any] | None
    mutations: str
    artifacts: list[str]
    evidence: list[str]
    blockers: list[str]
    next_route: str
    compatibility: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
