"""Small read-only allowlist for the AI layer; never exposes filesystem access."""
from __future__ import annotations

from copy import deepcopy
import re

from crypto.ai.facts import load_facts


_ARGUMENTS = {
    "get_summary": {"trial_id"},
    "get_attribution": {"trial_id"},
    "get_risks": {"trial_id"},
    "get_evidence": {"trial_id", "evidence_id"},
}
_EVIDENCE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CALL_LOG: list[dict] = []


def _log(name, arguments, outcome):
    tool = name if isinstance(name, str) and name in _ARGUMENTS else "<blocked>"
    trial_id = arguments.get("trial_id") if isinstance(arguments, dict) else None
    safe_trial_id = trial_id if isinstance(trial_id, str) and re.fullmatch(
        r"trial-\d{3}", trial_id) else None
    _CALL_LOG.append({"tool": tool, "trial_id": safe_trial_id, "outcome": outcome})


def clear_tool_call_log() -> None:
    """Reset in-memory diagnostic records; never logs arguments or credentials."""
    _CALL_LOG.clear()


def get_tool_call_log() -> list[dict]:
    """Return a copy of the safe in-memory tool diagnostic records."""
    return deepcopy(_CALL_LOG)


def call_tool(name: str, arguments: dict, run_dir: str) -> dict:
    """Invoke one read-only fact lookup for a registered development/validation trial."""
    if not isinstance(name, str) or name not in _ARGUMENTS:
        _log(name, arguments, "denied")
        raise PermissionError("tool is not on the read-only allowlist")
    if not isinstance(arguments, dict) or set(arguments) != _ARGUMENTS[name]:
        _log(name, arguments, "denied")
        raise PermissionError("tool arguments do not match the allowlisted schema")
    trial_id = arguments.get("trial_id")
    if not isinstance(trial_id, str) or not re.fullmatch(r"trial-\d{3}", trial_id):
        _log(name, arguments, "denied")
        raise PermissionError("trial_id must be a registered non-holdout trial")
    try:
        facts = load_facts(run_dir, trial_id)
        if name == "get_summary":
            result = {
                "run_id": facts["run_id"], "stage": facts["stage"],
                "strategy": facts["strategy"], "provenance": facts["provenance"],
                "metrics": facts["metrics"], "limitations": facts["limitations"],
                "evidence_ids": ["metrics"],
            }
        elif name == "get_attribution":
            result = {"attribution": facts["attribution"],
                      "evidence_ids": ["attribution"]}
        elif name == "get_risks":
            result = {
                "risks": facts["risks"],
                "margin_feasibility": facts["margin_feasibility"],
                "limitations": facts["limitations"],
                "evidence_ids": ["risks", "margin_audit"],
            }
        else:
            evidence_id = arguments.get("evidence_id")
            if not isinstance(evidence_id, str) or not _EVIDENCE_ID.fullmatch(evidence_id):
                raise PermissionError("evidence_id must be a registered identifier")
            evidence = facts["evidence"].get(evidence_id)
            if evidence is None:
                raise KeyError("evidence id not found")
            value_key = {
                "metrics": "metrics", "attribution": "attribution",
                "risks": "risks", "margin_audit": "margin_feasibility",
                "campaign_audit": "campaign_audit",
            }.get(evidence_id)
            result = {
                "evidence_id": evidence_id,
                "source": evidence,
                "value": facts.get(value_key) if value_key else None,
            }
        _log(name, arguments, "allowed")
        return deepcopy(result)
    except (KeyError, PermissionError, ValueError, OSError):
        _log(name, arguments, "denied")
        raise
