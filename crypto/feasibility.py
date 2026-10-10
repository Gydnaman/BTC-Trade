"""Post-run checks for isolated perpetual margin on hourly mark observations."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path


_ZERO = Decimal("0")
_BPS = Decimal("10000")
_AUDIT_VERSION = "isolated-margin-hourly-proxy-v1"


def _number(value, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite and numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite and numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite and numeric")
    return result


def audit_margin_observations(ledger_rows, maintenance_ratio,
                              perp_fee_bps, slippage_bps) -> dict:
    """Check open positions at ledger mark events against a declared proxy.

    Margin equity is isolated collateral plus unrealized perpetual PnL; free
    cash and spot PnL are deliberately excluded. This is an hourly research
    screen, not a Binance liquidation reconstruction.
    """
    maintenance_ratio = _number(maintenance_ratio, "maintenance_ratio")
    perp_fee_bps = _number(perp_fee_bps, "perp_fee_bps")
    slippage_bps = _number(slippage_bps, "slippage_bps")
    if not 0 <= maintenance_ratio < 1:
        raise ValueError("maintenance_ratio must be between 0 and 1")
    if min(perp_fee_bps, slippage_bps) < 0:
        raise ValueError("perpetual fee and slippage must be non-negative")

    observations = []
    current_quantity = _ZERO
    average_entry_price = _ZERO
    for index, row in enumerate(ledger_rows):
        if not isinstance(row, dict):
            raise ValueError(f"ledger row {index} must be an object")
        quantity = _number(row.get("perp_quantity"), "perp_quantity")
        kind = row.get("kind")
        if kind == "perp_fill" and row.get("status") == "applied":
            raw_details = row.get("details", {})
            if isinstance(raw_details, str):
                try:
                    raw_details = json.loads(raw_details)
                except ValueError as exc:
                    raise ValueError("perpetual fill details must be valid JSON") from exc
            if not isinstance(raw_details, dict):
                raise ValueError("perpetual fill details must be an object")
            execution_price = _number(raw_details.get("execution_price"),
                                      "details.execution_price")
            if execution_price <= 0:
                raise ValueError("details.execution_price must be positive")
            delta = quantity - current_quantity
            if current_quantity == 0 or current_quantity * delta > 0:
                total = abs(current_quantity) + abs(delta)
                average_entry_price = (
                    (abs(current_quantity) * average_entry_price +
                     abs(delta) * execution_price) / total if total else _ZERO)
            elif quantity == 0:
                average_entry_price = _ZERO
            elif current_quantity * quantity < 0:
                average_entry_price = execution_price
        elif quantity != current_quantity:
            raise ValueError("perpetual quantity changed outside an applied fill event")
        current_quantity = quantity
        if kind != "mark":
            continue
        if quantity == 0:
            continue
        if row.get("status") != "applied":
            raise ValueError("open-position mark event must be applied")
        stamp = row.get("event_time")
        if not isinstance(stamp, str) or not stamp:
            raise ValueError("open-position mark event_time is required")
        mark = _number(row.get("perp_mark"), "perp_mark")
        collateral = _number(row.get("perp_collateral"), "perp_collateral")
        if mark <= 0:
            raise ValueError("perp_mark must be positive for open positions")
        if average_entry_price <= 0:
            raise ValueError("open perpetual position has no reconstructed entry price")
        notional = abs(quantity * mark)
        unrealized_pnl = quantity * (mark - average_entry_price)
        margin_equity = collateral + unrealized_pnl
        maintenance = notional * maintenance_ratio
        close_cost = notional * (perp_fee_bps + slippage_bps) / _BPS
        headroom = margin_equity - maintenance - close_cost
        observations.append({"time": stamp, "margin_equity": margin_equity,
                             "maintenance": maintenance, "headroom": headroom})

    if not observations:
        return {
            "audit_version": _AUDIT_VERSION,
            "status": "not_applicable_no_open_perpetual",
            "maintenance_ratio": float(maintenance_ratio),
            "perp_fee_bps": float(perp_fee_bps),
            "slippage_bps": float(slippage_bps),
            "mark_observations": 0,
            "breach_observations": 0,
            "first_breach_time": None,
            "minimum_headroom": None,
            "minimum_margin_equity": None,
            "liquidation_simulated": False,
            "limitations": [
                "No open perpetual position was present at hourly mark observations.",
                "This audit does not reconstruct exchange liquidation or intrabar paths.",
            ],
        }

    breaches = [item for item in observations if item["headroom"] < 0]
    minimum_headroom = min(item["headroom"] for item in observations)
    minimum_margin_equity = min(item["margin_equity"] for item in observations)
    return {
        "audit_version": _AUDIT_VERSION,
        "status": ("infeasible_under_declared_margin_proxy" if breaches else
                   "no_breach_observed_under_declared_margin_proxy"),
        "maintenance_ratio": float(maintenance_ratio),
        "perp_fee_bps": float(perp_fee_bps),
        "slippage_bps": float(slippage_bps),
        "mark_observations": len(observations),
        "breach_observations": len(breaches),
        "breach_fraction": float(Decimal(len(breaches)) / len(observations)),
        "first_breach_time": breaches[0]["time"] if breaches else None,
        "first_breach_headroom": float(breaches[0]["headroom"]) if breaches else None,
        "minimum_headroom": float(minimum_headroom),
        "minimum_margin_equity": float(minimum_margin_equity),
        "liquidation_simulated": False,
        "margin_equity_definition": "isolated collateral + current-group unrealized perpetual PnL reconstructed from fill execution prices; excludes free cash, spot PnL, and prior realized PnL",
        "breach_definition": "margin equity below notional × maintenance ratio plus estimated perpetual close fee/slippage",
        "limitations": [
            "Maintenance ratio and close costs are declared stress assumptions, not historical Binance rules.",
            "Only hourly ledger mark observations are checked; intrabar liquidation is not reconstructed.",
            "A breach labels the accounting replay infeasible under this proxy; no forced close is simulated.",
        ],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_campaign(run_dir: str) -> dict:
    """Write per-trial margin audits and an aggregate campaign feasibility note."""
    root = Path(run_dir).resolve()
    trial_paths = sorted([*root.glob("trial-*.json"), *root.glob("holdout-*.json")])
    if not trial_paths:
        raise ValueError("no trial artifacts found for campaign audit")
    audits = []
    snapshot_ids = set()
    for trial_path in trial_paths:
        record = json.loads(trial_path.read_text(encoding="utf-8"))
        if record.get("status") != "succeeded":
            continue
        ledger_value = record.get("ledger_path")
        ledger_path = Path(ledger_value) if ledger_value else root / f"{trial_path.stem}-ledger.csv"
        if not ledger_path.is_absolute():
            ledger_path = root / ledger_path
        ledger_path = ledger_path.resolve()
        assumptions = record.get("assumptions", {})
        risks = record.get("risk_scenarios", [])
        base = next((item for item in risks if item.get("scenario") == "base"), None)
        if not isinstance(base, dict):
            raise ValueError(f"{trial_path.name} is missing its base risk assumptions")
        inputs = base.get("inputs", {})
        with ledger_path.open("r", newline="", encoding="utf-8") as handle:
            ledger_rows = list(csv.DictReader(handle))
        audit = audit_margin_observations(
            ledger_rows,
            inputs.get("maintenance_ratio"),
            assumptions.get("perp_fee_bps"),
            assumptions.get("slippage_bps"),
        )
        snapshot_id = record.get("provenance", {}).get("snapshot_id")
        snapshot_ids.add(snapshot_id)
        enriched = {
            **audit,
            "run_id": record.get("run_id"),
            "stage": record.get("stage"),
            "strategy": record.get("strategy"),
            "snapshot_id": snapshot_id,
            "ledger_file": ledger_path.name,
            "ledger_sha256": _sha256(ledger_path),
            "total_return": record.get("metrics", {}).get("total_return"),
            "evaluator_sha256": record.get("provenance", {}).get("evaluator_sha256"),
        }
        audit_path = root / f"{trial_path.stem}-margin-audit.json"
        audit_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2,
                                         allow_nan=False), encoding="utf-8")
        audits.append(enriched)

    if len(snapshot_ids) > 1:
        raise ValueError("campaign artifacts reference different market snapshots")
    holdouts = [item for item in audits if item["stage"] == "holdout"]
    candidate_strategy = holdouts[-1]["strategy"] if holdouts else None
    candidate_stages = {
        stage: next((item for item in audits
                     if item["strategy"] == candidate_strategy and item["stage"] == stage), None)
        for stage in ("development", "validation", "holdout")
    }
    candidate_breaches = [stage for stage, item in candidate_stages.items()
                          if item and item["breach_observations"] > 0]
    campaign_status = ("candidate_has_margin_breaches" if candidate_breaches else
                       "no_breach_observed_in_candidate_stages")
    campaign = {
        "schema_version": "crypto-campaign-feasibility-v1",
        "snapshot_id": next(iter(snapshot_ids), None),
        "candidate_strategy": candidate_strategy,
        "status": campaign_status,
        "candidate_breach_stages": candidate_breaches,
        "stages": candidate_stages,
        "trial_audits": audits,
        "selection_was_frozen_before_this_post_run_audit": True,
        "limitations": [
            "This post-run audit annotates the frozen campaign; it does not change its selection rule or rerun the sealed holdout.",
            "The declared hourly maintenance proxy is not a historical exchange liquidation model.",
        ],
    }
    output = root / "campaign-feasibility.json"
    output.write_text(json.dumps(campaign, ensure_ascii=False, indent=2,
                                 allow_nan=False), encoding="utf-8")
    return campaign
