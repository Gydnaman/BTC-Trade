"""Safe catalog of completed campaign trials for the local read-only UI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


_STAGE_ORDER = {"development": 0, "validation": 1, "holdout": 2}
_STRATEGY_ORDER = {"cash_zero": 0, "carry_static": 1, "funding_filter": 2}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid campaign artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"campaign artifact must be an object: {path.name}")
    return value


def _resolve_inside(root: Path, value: str, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} must resolve inside campaign directory") from exc
    if not resolved.is_file():
        raise ValueError(f"{field} does not exist: {resolved.name}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_campaign_catalog(run_dir: str, *, include_facts: bool = True,
                          include_holdout: bool = True) -> dict:
    """Return audited trial metadata, optionally excluding global facts/holdout files."""
    root = Path(run_dir).resolve()
    if not root.is_dir():
        raise ValueError("campaign directory does not exist")
    trials = []
    paths = [*root.glob("trial-*.json")]
    if include_holdout:
        paths.extend(root.glob("holdout-*.json"))
    paths = sorted(paths)
    records = []
    for trial_path in paths:
        trial_path = _resolve_inside(root, str(trial_path), "trial artifact")
        record = _read_json(trial_path)
        if record.get("status") != "succeeded":
            continue
        records.append((trial_path, record))
    if not records:
        return {"campaign_dir": str(root), "trials": [],
                "campaign_feasibility": None}
    campaign_path = _resolve_inside(root, "campaign-feasibility.json",
                                    "campaign-feasibility")
    campaign = _read_json(campaign_path)
    if (campaign.get("schema_version") != "crypto-campaign-feasibility-v1" or
            not isinstance(campaign.get("snapshot_id"), str) or
            not isinstance(campaign.get("candidate_strategy"), str) or
            not isinstance(campaign.get("trial_audits"), list)):
        raise ValueError("campaign-feasibility artifact has an invalid identity")
    campaign_audits = campaign["trial_audits"]
    for trial_path, record in records:
        metrics = record.get("metrics")
        provenance = record.get("provenance")
        if not isinstance(metrics, dict) or not isinstance(provenance, dict):
            raise ValueError(f"{trial_path.name} is missing metrics or provenance")
        required = ("run_id", "stage", "strategy", "created_at", "ledger_path")
        if any(not record.get(key) for key in required):
            raise ValueError(f"{trial_path.name} is missing trial identity fields")
        ledger_path = _resolve_inside(root, record["ledger_path"], "ledger_path")
        audit_path = _resolve_inside(root, f"{trial_path.stem}-margin-audit.json",
                                     "margin audit")
        audit = _read_json(audit_path)
        ledger_hash = _sha256(ledger_path)
        if audit.get("ledger_sha256") != ledger_hash:
            raise ValueError(f"ledger hash does not match margin audit for {trial_path.name}")
        for key, expected in (("run_id", record["run_id"]),
                              ("stage", record["stage"]),
                              ("strategy", record["strategy"]),
                              ("snapshot_id", provenance.get("snapshot_id"))):
            if audit.get(key) != expected:
                raise ValueError(f"margin audit {key} does not match {trial_path.name}")
        if campaign.get("snapshot_id") != provenance.get("snapshot_id"):
            raise ValueError(f"campaign snapshot does not match {trial_path.name}")
        matching_campaign_audits = [item for item in campaign_audits
                                    if isinstance(item, dict) and
                                    item.get("run_id") == record["run_id"]]
        if len(matching_campaign_audits) != 1:
            raise ValueError(f"campaign feasibility is missing a unique audit for {trial_path.name}")
        campaign_audit = matching_campaign_audits[0]
        for key, expected in (("stage", record["stage"]),
                              ("strategy", record["strategy"]),
                              ("snapshot_id", provenance.get("snapshot_id")),
                              ("ledger_sha256", ledger_hash)):
            if campaign_audit.get(key) != expected:
                raise ValueError(f"campaign audit {key} does not match {trial_path.name}")
        trials.append({
            "trial_id": trial_path.stem,
            "run_id": record["run_id"],
            "stage": record["stage"],
            "strategy": record["strategy"],
            "created_at": record["created_at"],
            "start_time": metrics.get("start_time"),
            "end_time": metrics.get("end_time"),
            "total_return": metrics.get("total_return"),
            "cagr": metrics.get("cagr"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe_daily": metrics.get("sharpe_daily"),
            "daily_return_count": metrics.get("daily_return_count"),
            "snapshot_id": provenance.get("snapshot_id"),
            "market": provenance.get("market"),
            "trial_file": trial_path.name,
            "ledger_file": ledger_path.relative_to(root).as_posix(),
            "margin_audit_file": audit_path.name,
            "margin_status": audit.get("status"),
            "margin_breaches": audit.get("breach_observations"),
            "margin_marks": audit.get("mark_observations"),
        })
    facts_path = None
    if include_facts:
        facts_path = _resolve_inside(root, "facts.json", "facts")
        facts = _read_json(facts_path)
        facts_provenance = facts.get("provenance")
        if (facts.get("schema_version") != "crypto-facts-v1" or
                not isinstance(facts_provenance, dict) or
                facts_provenance.get("snapshot_id") != campaign["snapshot_id"]):
            raise ValueError("facts snapshot does not match campaign-feasibility")
    trials.sort(key=lambda row: (
        _STAGE_ORDER.get(row["stage"], 99),
        _STRATEGY_ORDER.get(row["strategy"], 99),
        row["trial_id"],
    ))
    result = {"campaign_dir": str(root), "trials": trials,
              "campaign_file": campaign_path.name,
              "campaign_feasibility": campaign}
    if facts_path is not None:
        result["facts_file"] = facts_path.name
    return result
