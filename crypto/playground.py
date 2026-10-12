"""Isolated, development-only runs for the BTC carry strategy workbench."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real
import os
from pathlib import Path
import tempfile
import uuid

from crypto.config import load_config, validate_config
from crypto.research import (
    REGISTERED_STRATEGIES,
    _BASELINE_PARAMETERS,
    _build_strategy_events,
    _execute_trial,
    _evaluator_hash,
    _load_snapshot,
    _split_dates,
    _write_ledger_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "crypto" / "config.btc-carry-v3.json"
_PLAYGROUND_FIELDS = {
    "cash_zero": set(),
    "carry_static": {"allocation_fraction", "collateral_ratio"},
    "funding_filter": {
        "allocation_fraction", "collateral_ratio",
        "positive_funding_threshold",
    },
}
_PARAMETER_BOUNDS = {
    "allocation_fraction": (0.0, 0.5, False),
    "collateral_ratio": (0.1, 2.0, True),
}
_MAX_ESTIMATED_CAPITAL_USAGE = 0.95


def _finite_number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def validate_playground_strategy(strategy: str, parameters: dict | None = None) -> dict:
    """Validate and fill defaults for a registered strategy; never accept user code."""
    if strategy not in REGISTERED_STRATEGIES:
        raise ValueError("strategy must be one of the registered baselines")
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict):
        raise ValueError("strategy parameters must be an object")

    allowed = _PLAYGROUND_FIELDS[strategy]
    unknown = set(parameters) - allowed
    if unknown:
        raise ValueError(f"unregistered strategy parameters: {', '.join(sorted(unknown))}")

    normalized = {}
    if strategy != "cash_zero":
        defaults = _BASELINE_PARAMETERS[strategy]
        for field in ("allocation_fraction", "collateral_ratio"):
            value = _finite_number(parameters.get(field, defaults[field]), field)
            lower, upper, include_lower = _PARAMETER_BOUNDS[field]
            if (value < lower if include_lower else value <= lower) or value > upper:
                left = "[" if include_lower else "("
                raise ValueError(f"{field} must be in {left}{lower}, {upper}]")
            normalized[field] = value

        estimated_usage = normalized["allocation_fraction"] * (
            1 + normalized["collateral_ratio"]
        )
        if estimated_usage > _MAX_ESTIMATED_CAPITAL_USAGE:
            raise ValueError(
                "allocation_fraction and collateral_ratio together must leave "
                "at least 5% of initial equity reserve, assuming spot and "
                "perpetual prices are similar"
            )

    if strategy == "funding_filter":
        threshold = _finite_number(
            parameters.get("positive_funding_threshold", 0.0),
            "positive_funding_threshold",
        )
        if not -0.1 <= threshold <= 0.1:
            raise ValueError(
                "positive_funding_threshold must be between -1000 and 1000 basis points"
            )
        normalized["positive_funding_threshold"] = threshold
    return normalized


def _validate_position_affordability(groups: list[dict], initial_equity: float) -> None:
    """Reject a data-dependent entry whose spot cost plus collateral exceeds equity."""
    for group in groups:
        spot_notional = abs(float(group["spot_quantity"])) * float(
            group["spot_entry_price"]
        )
        committed_capital = spot_notional + float(group["collateral"])
        if committed_capital > float(initial_equity) + 1e-8:
            raise ValueError(
                "representative stress position exceeds initial account equity; "
                "lower allocation_fraction or collateral_ratio"
            )



def _project_config(project_root: Path) -> dict:
    config = load_config(str(DEFAULT_CONFIG))
    data_root = Path(config["data"]["root"])
    if not data_root.is_absolute():
        data_root = project_root / data_root
    config["data"]["root"] = str(data_root.resolve())
    return validate_config(config)


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"playground-{stamp}-{uuid.uuid4().hex[:8]}"


def _write_artifact(project_root: Path, record: dict, ledger: list[dict]) -> dict:
    playground_root = project_root / "results" / "crypto" / "playground"
    playground_root.mkdir(parents=True, exist_ok=True)
    run_id = record["run_id"]
    destination = playground_root / run_id
    if destination.exists():
        raise FileExistsError(f"playground run already exists: {run_id}")

    with tempfile.TemporaryDirectory(prefix=".pending-", dir=playground_root) as temp:
        temp_root = Path(temp)
        _write_ledger_csv(temp_root / "ledger.csv", ledger)
        record["ledger_path"] = "ledger.csv"
        (temp_root / "trial.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temp_root, destination)

    return {
        "directory": str(destination),
        "trial": str(destination / "trial.json"),
        "ledger": str(destination / "ledger.csv"),
    }


def run_playground(
    strategy: str,
    parameters: dict | None = None,
    *,
    project_root: str | Path | None = None,
) -> dict:
    """Run one isolated BTC/USDT backtest on the audited development split only."""
    normalized = validate_playground_strategy(strategy, parameters)
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    config = _project_config(root)
    snapshot = _load_snapshot(config)
    split = _split_dates(config)
    stage_range = split["development"]
    prepared_strategy = _build_strategy_events(
        config, snapshot["tables"], stage_range, strategy, normalized
    )
    _validate_position_affordability(
        prepared_strategy[1], config["campaign"]["initial_equity"]
    )
    result = _execute_trial(
        config, snapshot, split, "development", strategy, normalized,
        prepared_strategy=prepared_strategy,
    )

    run_id = _run_id()
    playground_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    research_digest = _evaluator_hash()
    evaluator_digest = hashlib.sha256(
        f"{research_digest}:{playground_digest}".encode("ascii")
    ).hexdigest()
    record = {
        "schema_version": "crypto-playground-trial-v1",
        "run_id": run_id,
        "status": "development_only",
        "stage": "development",
        "created_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "market": config["market"],
        "strategy": strategy,
        "parameters": normalized,
        "provenance": {
            "snapshot_id": snapshot["manifest"].get("snapshot_id"),
            "manifest_path": snapshot["manifest_path"],
            "table_sha256": snapshot["table_hashes"],
            "research_evaluator_sha256": research_digest,
            "playground_evaluator_sha256": playground_digest,
            "evaluator_sha256": evaluator_digest,
            "stage_range": stage_range,
            "time_split": split["policy"],
        },
        "metrics": result["metrics"],
        "attribution": result["attribution"],
        "assumptions": result["assumptions"],
        "limitations": result["limitations"],
        "risk_scenarios": result["risk_scenarios"],
        "equity_series": result["equity_series"],
    }
    artifact_paths = _write_artifact(root, record, result["ledger"])
    return {**record, "artifact_paths": artifact_paths}
