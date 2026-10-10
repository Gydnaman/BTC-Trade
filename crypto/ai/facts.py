"""Build a stage-scoped fact view from audited, non-holdout campaign artifacts."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from crypto.ui.catalog import load_campaign_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TRIAL_ID = re.compile(r"^trial-\d{3}$")
_ALLOWED_STAGES = {"development", "validation"}
_REQUIRED_METRICS = {
    "initial_equity", "final_equity", "total_return", "max_drawdown",
    "daily_return_count", "elapsed_days", "start_time", "end_time",
    "annualization_basis", "max_drawdown_basis",
}
_OPTIONAL_METRICS = {
    "cagr", "annualized_volatility", "sharpe_daily",
    "average_collateral_utilization", "peak_residual_delta",
}
_ATTRIBUTION_FIELDS = {
    "spot_pnl", "perp_pnl", "funding", "spot_fees", "perp_fees", "slippage",
}


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid {label} artifact") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} artifact must be an object")
    return value


def _finite_number(value, label: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite and numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite and numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{label} must be finite and numeric")


def _verify_snapshot(record: dict) -> dict:
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("trial provenance is required")
    manifest_value = provenance.get("manifest_path")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise ValueError("trial manifest path is required")
    try:
        manifest_path = Path(manifest_value).resolve(strict=True)
        trusted_root = (PROJECT_ROOT / "data_cache" / "crypto").resolve(strict=True)
        manifest_path.relative_to(trusted_root)
    except (OSError, ValueError) as exc:
        raise ValueError("manifest path is outside the trusted crypto data cache") from exc
    manifest = _read_object(manifest_path, "snapshot manifest")
    if (manifest.get("schema_version") != "crypto-snapshot-v1" or
            manifest.get("status") != "audited" or
            manifest.get("snapshot_id") != provenance.get("snapshot_id")):
        raise ValueError("manifest identity does not match the trial snapshot")
    expected = provenance.get("table_sha256")
    actual_tables = manifest.get("tables")
    if not isinstance(expected, dict) or not expected or not isinstance(actual_tables, dict):
        raise ValueError("trial or manifest table hashes are missing")
    if set(expected) != set(actual_tables):
        raise ValueError("manifest hash table set does not match the trial")
    for table, digest in expected.items():
        manifest_entry = actual_tables.get(table)
        if not isinstance(manifest_entry, dict) or manifest_entry.get("sha256") != digest:
            raise ValueError(f"manifest hash mismatch for {table}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"invalid manifest hash for {table}")
    return provenance


def load_facts(run_dir: str, trial_id: str) -> dict:
    """Load one audited development/validation trial without opening root facts.json."""
    if not isinstance(trial_id, str) or not _TRIAL_ID.fullmatch(trial_id):
        raise PermissionError("AI tools can read only registered non-holdout trials")
    catalog = load_campaign_catalog(run_dir, include_facts=False, include_holdout=False)
    entry = next((item for item in catalog["trials"]
                  if item["trial_id"] == trial_id), None)
    if entry is None:
        raise KeyError(f"audited trial not found: {trial_id}")
    if entry["stage"] not in _ALLOWED_STAGES:
        raise PermissionError("holdout facts are sealed from the AI layer")

    root = Path(catalog["campaign_dir"])
    record = _read_object(root / entry["trial_file"], "trial")
    if (record.get("schema_version") != "crypto-trial-v1" or
            record.get("status") != "succeeded" or
            record.get("stage") not in _ALLOWED_STAGES or
            record.get("stage") != entry["stage"] or
            record.get("run_id") != entry["run_id"] or
            not isinstance(record.get("strategy"), str) or not record["strategy"]):
        raise ValueError("trial identity or status changed after catalog validation")
    provenance = _verify_snapshot(record)
    metrics = record.get("metrics")
    attribution = record.get("attribution")
    risks = record.get("risk_scenarios")
    limitations = record.get("limitations")
    if not isinstance(metrics, dict) or not isinstance(attribution, dict):
        raise ValueError("trial metrics and attribution are required")
    missing_metrics = _REQUIRED_METRICS - set(metrics)
    if missing_metrics:
        raise ValueError(f"trial metric is required: {sorted(missing_metrics)[0]}")
    for field in _REQUIRED_METRICS | (_OPTIONAL_METRICS & set(metrics)):
        if field not in {"daily_return_count", "start_time", "end_time",
                         "annualization_basis", "max_drawdown_basis"}:
            _finite_number(metrics[field], f"metrics.{field}",
                           nullable=field in _OPTIONAL_METRICS)
    if (isinstance(metrics["daily_return_count"], bool) or
            not isinstance(metrics["daily_return_count"], int) or
            metrics["daily_return_count"] < 1):
        raise ValueError("metrics.daily_return_count must be a positive integer")
    for field in ("start_time", "end_time", "annualization_basis", "max_drawdown_basis"):
        if not isinstance(metrics[field], str) or not metrics[field]:
            raise ValueError(f"metrics.{field} must be a non-empty string")
    if _ATTRIBUTION_FIELDS - set(attribution):
        raise ValueError(f"trial attribution is missing {sorted(_ATTRIBUTION_FIELDS - set(attribution))[0]}")
    for field in _ATTRIBUTION_FIELDS:
        _finite_number(attribution[field], f"attribution.{field}")
    if (not isinstance(risks, list) or any(not isinstance(item, dict) for item in risks) or
            not isinstance(limitations, list) or
            any(not isinstance(item, str) for item in limitations)):
        raise ValueError("trial risks and limitations are required")
    assumptions = record.get("assumptions", {})
    if not isinstance(assumptions, dict):
        raise ValueError("trial assumptions must be an object")

    margin = _read_object(root / entry["margin_audit_file"], "margin audit")
    campaign_path = root / catalog["campaign_file"]
    campaign = catalog["campaign_feasibility"]
    matching = [item for item in campaign.get("trial_audits", [])
                if isinstance(item, dict) and item.get("run_id") == record["run_id"]]
    if len(matching) != 1:
        raise ValueError("campaign audit is missing the selected trial")
    campaign_audit = matching[0]
    evidence = {
        "metrics": {"file": entry["trial_file"], "json_pointer": "/metrics"},
        "attribution": {"file": entry["trial_file"], "json_pointer": "/attribution"},
        "risks": {"file": entry["trial_file"], "json_pointer": "/risk_scenarios"},
        "event_ledger": {"file": entry["ledger_file"], "json_pointer": "/"},
        "margin_audit": {"file": entry["margin_audit_file"], "json_pointer": "/"},
        "campaign_audit": {
            "file": campaign_path.name,
            "json_pointer": f"/trial_audits/{campaign['trial_audits'].index(campaign_audit)}",
        },
    }
    return {
        "schema_version": "crypto-ai-facts-v1",
        "run_id": record["run_id"],
        "trial_id": trial_id,
        "stage": record["stage"],
        "strategy": record["strategy"],
        "provenance": {
            key: provenance[key] for key in (
                "campaign_id", "snapshot_id", "table_sha256",
                "contract_sha256", "evaluator_sha256", "stage_range",
            ) if key in provenance
        },
        "metrics": metrics,
        "attribution": attribution,
        "risks": risks,
        "margin_feasibility": margin,
        "campaign_audit": campaign_audit,
        "assumptions": assumptions,
        "limitations": limitations,
        "evidence": evidence,
    }
