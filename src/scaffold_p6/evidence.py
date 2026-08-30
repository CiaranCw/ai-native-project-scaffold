"""Evidence items, Evidence References, and the Evidence Compiler."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scaffold_p5.io_util import sha256_text

from scaffold_p6.models import (
    EVIDENCE_KINDS,
    EVIDENCE_SCHEMA_VERSION,
    INLINE_LOG_LIMIT,
    SCENARIO_RESULTS,
    CandidateIdentity,
    ExecutionObservation,
)


SUPPLIED_PROVENANCE = frozenset({"EXTERNAL_RESULT", "HUMAN_OBSERVATION", "CI_RESULT"})
LOCAL_PERMITTED = frozenset({"LOCAL_EXECUTION", ""})


def compile_local_evidence(
    *,
    run_id: str,
    profile_id: str,
    candidate: CandidateIdentity,
    observation: ExecutionObservation,
    result: str,
    required_kinds: list[str],
    artifacts: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    items: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    now = _now()
    stdout_item, stdout_ref = _log_item(
        run_id=run_id,
        profile_id=profile_id,
        candidate=candidate,
        stream="stdout",
        text=observation.stdout,
        observed_at=observation.ended_at or now,
        artifacts=artifacts,
    )
    stderr_item, stderr_ref = _log_item(
        run_id=run_id,
        profile_id=profile_id,
        candidate=candidate,
        stream="stderr",
        text=observation.stderr,
        observed_at=observation.ended_at or now,
        artifacts=artifacts,
    )
    command_item = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": f"{run_id}-{profile_id}-command",
        "kind": "command_result",
        "provenance": "LOCAL_EXECUTION",
        "mechanism": "local_target_adapter",
        "profile_id": profile_id,
        "candidate_digest": candidate.digest,
        "observed_at": observation.ended_at or now,
        "summary": f"exit={observation.exit_code} termination={observation.termination}",
        "result": result,
        "command": list(observation.command),
        "working_directory": observation.working_directory,
        "exit_code": observation.exit_code,
        "duration_ms": observation.duration_ms,
        "termination": observation.termination,
        "adapter": observation.adapter_id,
        "stdout_ref": stdout_ref["ref_id"] if stdout_ref else None,
        "stderr_ref": stderr_ref["ref_id"] if stderr_ref else None,
        "locator": f"test-runs/{run_id}/evidence/{profile_id}-command.yaml",
        "usable": True,
    }
    usable, _reason = evidence_item_usable(command_item)
    command_item["usable"] = usable
    items.append(command_item)
    if stdout_item:
        items.append(stdout_item)
    if stderr_item:
        items.append(stderr_item)
    if stdout_ref:
        refs.append(stdout_ref)
    if stderr_ref:
        refs.append(stderr_ref)
    present = {item["kind"] for item in items if item.get("usable") is True}
    complete = _kinds_satisfied(required_kinds, present)
    return items, refs, complete


def compile_supplied_bundle(
    *,
    run_id: str,
    profile_id: str,
    candidate: CandidateIdentity,
    supplied_items: list[dict[str, Any]],
    required_kinds: list[str],
    declared_provenance: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, list[str], str]:
    items: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    blockers: list[str] = []
    claimed_results: list[str] = []
    for index, supplied in enumerate(supplied_items):
        compiled, item_refs, item_blockers, claimed = _compile_one_supplied(
            run_id=run_id,
            profile_id=profile_id,
            candidate=candidate,
            supplied=supplied,
            declared_provenance=declared_provenance,
            index=index,
        )
        blockers.extend(item_blockers)
        if compiled:
            items.append(compiled)
            if claimed:
                claimed_results.append(claimed)
        refs.extend(item_refs)
    unique_claims = list(dict.fromkeys(claimed_results))
    if len(unique_claims) > 1:
        blockers.append("conflicting supplied verification results for one profile")
        for item in items:
            item["usable"] = False
        return items, refs, False, blockers, "BLOCKED"
    usable_kinds = {item["kind"] for item in items if item.get("usable") is True}
    complete = _kinds_satisfied(required_kinds, usable_kinds)
    if unique_claims:
        result = unique_claims[0]
    else:
        result = "BLOCKED"
    if blockers and result != "FAIL":
        result = "BLOCKED"
        complete = False
    return items, refs, complete, blockers, result


def compile_supplied_evidence(
    *,
    run_id: str,
    profile_id: str,
    candidate: CandidateIdentity,
    supplied: dict[str, Any],
    required_kinds: list[str],
    declared_provenance: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, list[str]]:
    items, refs, complete, blockers, _result = compile_supplied_bundle(
        run_id=run_id,
        profile_id=profile_id,
        candidate=candidate,
        supplied_items=[supplied],
        required_kinds=required_kinds,
        declared_provenance=declared_provenance,
    )
    return items, refs, complete, blockers


def evidence_item_usable(item: dict[str, Any]) -> tuple[bool, str]:
    kind = item.get("kind")
    if kind not in EVIDENCE_KINDS:
        return False, "unsupported evidence kind"
    if kind == "command_result":
        has_command = isinstance(item.get("command"), list) and bool(item.get("command"))
        has_result = item.get("result") in SCENARIO_RESULTS or item.get("exit_code") is not None
        if has_command and has_result:
            return True, ""
        return False, "command_result lacks command/result execution data"
    if kind == "structured_assertion":
        payload = item.get("assertion")
        if payload is None:
            payload = item.get("content")
        if isinstance(payload, (dict, list)) and payload:
            return True, ""
        summary = item.get("summary")
        if isinstance(summary, str) and summary.strip():
            return True, ""
        return False, "structured_assertion lacks a payload or summary"
    if kind == "log_text":
        if (isinstance(item.get("inline"), str) and item.get("inline")) or item.get("locator"):
            return True, ""
        return False, "log_text lacks inline content or a locator"
    if kind == "structured_state":
        if item.get("state") or item.get("content") or item.get("locator"):
            return True, ""
        return False, "structured_state lacks state content or a locator"
    if kind == "event_trace":
        if item.get("trace") or item.get("locator") or item.get("content"):
            return True, ""
        return False, "event_trace lacks a trace locator or content"
    if kind == "file_artifact":
        if item.get("locator"):
            return True, ""
        return False, "file_artifact lacks a locator/reference"
    if kind == "visual_checkpoint":
        if item.get("locator") or item.get("artifact") or item.get("content"):
            return True, ""
        return False, "visual_checkpoint lacks a locator or visual artifact reference"
    if kind == "human_observation":
        text = str(item.get("summary") or item.get("observation") or "").strip()
        if text:
            return True, ""
        return False, "human_observation lacks observation content"
    if kind == "external_ci":
        if item.get("locator") or item.get("run_url") or item.get("ci_id") or (
            isinstance(item.get("summary"), str) and item.get("summary", "").strip()
        ):
            return True, ""
        return False, "external_ci lacks result identity/reference metadata"
    return False, "unsupported evidence kind"


def evidence_kinds_complete(required_kinds: list[str], actual_kinds: set[str]) -> bool:
    return _kinds_satisfied(required_kinds, actual_kinds)


def observation_dict(observation: ExecutionObservation) -> dict[str, Any]:
    return {
        "adapter": observation.adapter_id,
        "command": list(observation.command),
        "working_directory": observation.working_directory,
        "started_at": observation.started_at,
        "ended_at": observation.ended_at,
        "duration_ms": observation.duration_ms,
        "exit_code": observation.exit_code,
        "termination": observation.termination,
        "error": observation.error,
        "stdout_chars": len(observation.stdout),
        "stderr_chars": len(observation.stderr),
    }


def scenario_from_observation(
    profile: dict[str, Any],
    observation: ExecutionObservation,
) -> str:
    if observation.termination in {"timeout", "error"}:
        return "BLOCKED"
    expected = 0
    success = profile.get("success")
    if isinstance(success, dict) and success.get("exit_code") is not None:
        expected = int(success["exit_code"])
    if observation.exit_code == expected:
        return "PASS"
    return "FAIL"


def local_execution_permitted(declared_provenance: str) -> bool:
    return (declared_provenance or "LOCAL_EXECUTION") in LOCAL_PERMITTED or (
        declared_provenance == "LOCAL_EXECUTION"
    )


def _compile_one_supplied(
    *,
    run_id: str,
    profile_id: str,
    candidate: CandidateIdentity,
    supplied: dict[str, Any],
    declared_provenance: str,
    index: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str], str]:
    provenance = supplied.get("provenance")
    kind = supplied.get("kind")
    required = declared_provenance or "LOCAL_EXECUTION"
    if provenance == "LOCAL_EXECUTION":
        return None, [], ["supplied evidence cannot claim LOCAL_EXECUTION"], ""
    if provenance not in SUPPLIED_PROVENANCE:
        return None, [], [f"unsupported supplied provenance: {provenance!r}"], ""
    if required == "LOCAL_EXECUTION":
        return None, [], [
            f"profile requires LOCAL_EXECUTION; {provenance} cannot satisfy it"
        ], ""
    if required != provenance:
        return None, [], [
            f"profile requires {required}; {provenance} cannot satisfy it"
        ], ""
    if kind is None:
        kind = _default_kind(str(provenance))
    if kind not in EVIDENCE_KINDS:
        return None, [], [f"unsupported evidence kind: {kind!r}"], ""

    supplied_candidate = supplied.get("candidate_digest")
    binding_mechanism = "explicit_candidate_digest"
    bound = candidate.digest
    if isinstance(supplied_candidate, str) and supplied_candidate:
        if supplied_candidate != candidate.digest:
            return (
                None,
                [],
                [f"{provenance} candidate identity does not match the current candidate"],
                "",
            )
        bound = supplied_candidate
    elif provenance == "HUMAN_OBSERVATION":
        binding_mechanism = "synchronous_invocation"
        bound = candidate.digest
    else:
        return (
            None,
            [],
            [f"{provenance} requires an explicit candidate_digest for the current candidate"],
            "",
        )

    item = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": f"{run_id}-{profile_id}-supplied-{index}",
        "kind": kind,
        "provenance": provenance,
        "mechanism": str(supplied.get("mechanism") or provenance.lower()),
        "profile_id": profile_id,
        "candidate_digest": bound,
        "binding_mechanism": binding_mechanism,
        "observed_at": str(supplied.get("observed_at") or _now()),
        "summary": str(supplied.get("summary") or ""),
        "observation": supplied.get("observation"),
        "assertion": supplied.get("assertion"),
        "content": supplied.get("content"),
        "state": supplied.get("state"),
        "trace": supplied.get("trace"),
        "artifact": supplied.get("artifact"),
        "run_url": supplied.get("run_url"),
        "ci_id": supplied.get("ci_id"),
        "result": supplied.get("result"),
        "locator": str(supplied.get("locator") or ""),
        "local_verified": False,
        "usable": True,
    }
    usable, reason = evidence_item_usable(item)
    item["usable"] = usable
    blockers = [] if usable else [reason]
    refs: list[dict[str, Any]] = []
    locator = supplied.get("locator")
    digest = supplied.get("digest")
    if locator:
        refs.append(
            {
                "ref_id": f"{run_id}-{profile_id}-ext-{index}",
                "kind": kind,
                "locator": locator,
                "digest": digest,
                "resolvable": False,
                "report_id": run_id,
                "candidate_digest": bound,
            }
        )
    claimed = ""
    raw = supplied.get("result")
    if raw in SCENARIO_RESULTS:
        claimed = str(raw)
    return item, refs, blockers, claimed


def _kinds_satisfied(required_kinds: list[str], actual: set[str]) -> bool:
    return set(required_kinds) <= actual


def _log_item(
    *,
    run_id: str,
    profile_id: str,
    candidate: CandidateIdentity,
    stream: str,
    text: str,
    observed_at: str,
    artifacts: dict[str, str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if text == "":
        empty = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "evidence_id": f"{run_id}-{profile_id}-{stream}",
            "kind": "log_text",
            "provenance": "LOCAL_EXECUTION",
            "mechanism": "local_target_adapter",
            "profile_id": profile_id,
            "candidate_digest": candidate.digest,
            "observed_at": observed_at,
            "summary": f"{stream} empty",
            "stream": stream,
            "inline": "",
            "locator": "",
            "usable": False,
        }
        return empty, None
    digest = sha256_text(text)
    name = f"{profile_id}-{stream}.txt"
    artifacts[name] = text
    locator = f"test-runs/{run_id}/evidence/{name}"
    inline = text if len(text) <= INLINE_LOG_LIMIT else (
        text[:512] + "\n...[truncated]...\n" + text[-256:]
    )
    item = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": f"{run_id}-{profile_id}-{stream}",
        "kind": "log_text",
        "provenance": "LOCAL_EXECUTION",
        "mechanism": "local_target_adapter",
        "profile_id": profile_id,
        "candidate_digest": candidate.digest,
        "observed_at": observed_at,
        "summary": f"{stream} {len(text)} chars digest={digest[:12]}",
        "stream": stream,
        "inline": inline,
        "truncated": len(text) > INLINE_LOG_LIMIT,
        "locator": locator,
        "usable": True,
    }
    ref = {
        "ref_id": f"{run_id}-{profile_id}-{stream}",
        "kind": "log_text",
        "locator": locator,
        "digest": digest,
        "size": len(text),
        "resolvable": True,
        "report_id": run_id,
        "candidate_digest": candidate.digest,
    }
    return item, ref


def _default_kind(provenance: str) -> str:
    if provenance == "HUMAN_OBSERVATION":
        return "human_observation"
    if provenance == "CI_RESULT":
        return "external_ci"
    return "structured_assertion"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def preserve_verification_truth(raw_result: str) -> str:
    """Compiler must not rewrite PASS/FAIL truth."""
    if raw_result in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
        return raw_result
    return "BLOCKED"
