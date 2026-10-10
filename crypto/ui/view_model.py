"""Validated, read-only dashboard data derived from frozen trial artifacts."""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import statistics

from crypto.ui.catalog import load_campaign_catalog


_TRIAL_ID = re.compile(r"^(?:trial|holdout)-\d{3,}$")
_SUMMARY_FIELDS = (
    "initial_equity", "final_equity", "total_return", "cagr", "max_drawdown",
    "annualized_volatility", "sharpe_daily", "daily_return_count",
    "elapsed_days", "start_time", "end_time", "annualization_basis",
    "max_drawdown_basis", "average_collateral_utilization", "peak_residual_delta",
)
_REQUIRED_METRICS = set(_SUMMARY_FIELDS)
_OPTIONAL_METRICS = {"cagr", "max_drawdown", "annualized_volatility", "sharpe_daily",
                     "average_collateral_utilization", "peak_residual_delta"}


def _decimal(value, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite and numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite and numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite and numeric")
    return result


def _chart_number(value, field: str) -> float:
    result = float(_decimal(value, field))
    if not math.isfinite(result):
        raise ValueError(f"{field} must remain finite for chart display")
    return result


def _utc(value, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _day_filter(value: str | None, default: date, field: str) -> date:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD")
    return parsed


def _utc_close_day(timestamp: datetime) -> date:
    """Map a UTC mark or settlement timestamp to the date it closes."""
    day = timestamp.date()
    return day - timedelta(days=1) if timestamp.time() == time.min else day


def _window_metrics(metrics: dict, equity_points: list[dict],
                    start_day: date, end_day: date,
                    coverage_start_time: datetime) -> tuple[dict, list[str]]:
    """Calculate return statistics for an inclusive UTC date window.

    Daily closes follow crypto.metrics: a mark at UTC midnight closes the day
    that just ended. The opening balance is the last mark at or before the
    selected start boundary; the first campaign day uses registered capital.
    """
    start_boundary = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    if start_day == coverage_start_time.date():
        opening_equity = _chart_number(metrics["initial_equity"],
                                       "metrics.initial_equity")
        opening_time = coverage_start_time
    else:
        prior = [point for point in equity_points
                 if point["timestamp"] <= start_boundary]
        if not prior:
            raise ValueError("selected window has no opening equity observation")
        opening_equity = prior[-1]["equity"]
        opening_time = prior[-1]["timestamp"]

    daily_closes: dict[date, dict] = {}
    for point in equity_points:
        stamp = point["timestamp"]
        if stamp <= coverage_start_time:
            continue
        close_day = _utc_close_day(stamp)
        if start_day <= close_day <= end_day:
            daily_closes[close_day] = point
    selected = [daily_closes[day] for day in sorted(daily_closes)]
    if not selected:
        raise ValueError("selected date range contains no equity observations")
    final_equity = selected[-1]["equity"]
    if opening_equity <= 0:
        raise ValueError("window opening equity must be positive")

    daily_returns = []
    previous_equity = opening_equity
    for point in selected:
        if previous_equity > 0:
            daily_returns.append(point["equity"] / previous_equity - 1.0)
        previous_equity = point["equity"]

    elapsed_seconds = (selected[-1]["timestamp"] - opening_time).total_seconds()
    elapsed_days = elapsed_seconds / 86_400.0
    total_return = final_equity / opening_equity - 1.0
    cagr = None
    if elapsed_seconds > 0 and final_equity >= 0:
        cagr = (final_equity / opening_equity) ** (365.25 * 86_400.0 /
                                                   elapsed_seconds) - 1.0

    drawdown = 0.0
    peak = opening_equity
    for point in selected:
        peak = max(peak, point["equity"])
        if peak > 0:
            drawdown = min(drawdown, point["equity"] / peak - 1.0)

    annualized_volatility = sharpe = None
    limitations = []
    if len(daily_returns) >= 2:
        sample_std = statistics.stdev(daily_returns)
        annualized_volatility = sample_std * math.sqrt(365.0)
        if sample_std > 0:
            annual_rf = _chart_number(metrics.get("risk_free_rate_annual", 0),
                                      "metrics.risk_free_rate_annual")
            daily_rf = ((1.0 + annual_rf) ** (1.0 / 365.0) - 1.0
                        if annual_rf > -1.0 else 0.0)
            excess = [value - daily_rf for value in daily_returns]
            sharpe = statistics.mean(excess) / sample_std * math.sqrt(365.0)
        else:
            limitations.append("所选区间日收益波动为零，Sharpe 未定义。")

    if elapsed_seconds <= 0:
        limitations.append("所选区间没有正的经过时间，CAGR 未定义。")
    if elapsed_seconds < 365 * 86_400:
        limitations.append("所选区间不足一年，CAGR、年化波动和 Sharpe 不稳定。")
    if len(daily_returns) < 2:
        limitations.append("日收益样本不足，年化波动和 Sharpe 未计算。")

    selected_summary = dict(metrics)
    selected_summary.update({
        "initial_equity": opening_equity,
        "final_equity": final_equity,
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": drawdown,
        "annualized_volatility": annualized_volatility,
        "sharpe_daily": sharpe,
        "daily_return_count": len(daily_returns),
        "elapsed_days": elapsed_days,
        "start_time": opening_time.isoformat().replace("+00:00", "Z"),
        "end_time": selected[-1]["timestamp"].isoformat().replace("+00:00", "Z"),
    })
    return selected_summary, limitations


def build_dashboard_model(run_dir: str, trial_id: str,
                          start: str | None = None,
                          end: str | None = None) -> dict:
    """Build chart-ready data without changing or recalculating trial metrics."""
    if not isinstance(trial_id, str) or not _TRIAL_ID.fullmatch(trial_id):
        raise ValueError("trial_id must identify a campaign trial")
    catalog = load_campaign_catalog(run_dir)
    entry = next((row for row in catalog["trials"]
                  if row["trial_id"] == trial_id), None)
    if entry is None:
        raise ValueError(f"successful audited trial not found: {trial_id}")
    root = Path(catalog["campaign_dir"])
    record = json.loads((root / entry["trial_file"]).read_text(encoding="utf-8"))
    metrics = record.get("metrics")
    equity = record.get("equity_series")
    if not isinstance(metrics, dict) or not isinstance(equity, list) or not equity:
        raise ValueError("trial is missing metrics or equity_series")
    missing_metrics = _REQUIRED_METRICS - set(metrics)
    if missing_metrics:
        name = sorted(missing_metrics)[0]
        raise ValueError(f"metrics.{name} is required")
    for key in _SUMMARY_FIELDS:
        value = metrics[key]
        if value is None and key in _OPTIONAL_METRICS:
            continue
        _decimal(value, f"metrics.{key}") if key not in {
            "daily_return_count", "start_time", "end_time",
            "annualization_basis", "max_drawdown_basis",
        } else None
    if (isinstance(metrics["daily_return_count"], bool) or
            not isinstance(metrics["daily_return_count"], int) or
            metrics["daily_return_count"] < 1):
        raise ValueError("metrics.daily_return_count must be a positive integer")
    for key in ("annualization_basis", "max_drawdown_basis"):
        if not isinstance(metrics[key], str) or not metrics[key]:
            raise ValueError(f"metrics.{key} must be a non-empty description")
    metric_limitations = metrics.get("limitations", [])
    if not isinstance(metric_limitations, list) or any(
            not isinstance(item, str) for item in metric_limitations):
        raise ValueError("metrics.limitations must be a list of descriptions")
    if not metrics.get("start_time") or not metrics.get("end_time"):
        raise ValueError("trial metrics are missing coverage timestamps")
    coverage_start_time = _utc(metrics["start_time"], "metrics.start_time")
    coverage_end_time = _utc(metrics["end_time"], "metrics.end_time")
    coverage_start = coverage_start_time.date()
    coverage_end = coverage_end_time.date()
    coverage_end = _utc_close_day(coverage_end_time)
    if coverage_end < coverage_start:
        raise ValueError("trial metrics have reversed coverage")
    start_day = _day_filter(start, coverage_start, "start")
    end_day = _day_filter(end, coverage_end, "end")
    if start_day > end_day:
        raise ValueError("start date must not be after end date")
    if start_day < coverage_start or end_day > coverage_end:
        raise ValueError("selected dates are outside audited coverage")

    equity_rows = []
    equity_points = []
    start_boundary = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_boundary = datetime.combine(end_day + timedelta(days=1), time.min,
                                    tzinfo=timezone.utc)
    previous_timestamp = None
    for index, point in enumerate(equity):
        if not isinstance(point, dict) or "time" not in point or "equity" not in point:
            raise ValueError(f"equity_series[{index}] is missing time or equity")
        timestamp = _utc(point["time"], f"equity_series[{index}].time")
        if timestamp < coverage_start_time or timestamp > coverage_end_time:
            raise ValueError(f"equity_series[{index}].time is outside audited coverage")
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValueError("equity_series timestamps must be ordered")
        previous_timestamp = timestamp
        amount = _chart_number(point["equity"], f"equity_series[{index}].equity")
        equity_points.append({"timestamp": timestamp, "equity": amount})
    window_points = [point for point in equity_points
                     if start_boundary <= point["timestamp"] <= end_boundary]
    if not any(point["timestamp"] == start_boundary for point in window_points):
        opening_points = [point for point in equity_points
                          if point["timestamp"] < start_boundary]
        if opening_points:
            window_points.insert(0, opening_points[-1])
    equity_rows = [{
        "time": point["timestamp"].isoformat().replace("+00:00", "Z"),
        "equity": point["equity"],
    } for point in window_points]
    if not equity_rows:
        raise ValueError("selected date range contains no equity observations")

    selected_summary, selected_metric_limitations = _window_metrics(
        metrics, equity_points, start_day, end_day, coverage_start_time)
    funding_by_day: dict[date, Decimal] = {}
    attribution_fields = ("spot_pnl", "perp_pnl", "funding", "spot_fees",
                          "perp_fees", "slippage")
    zero_attribution = {name: Decimal(0) for name in attribution_fields}
    opening_attribution = dict(zero_attribution)
    ending_attribution = dict(zero_attribution)
    selected_ledger_rows = []
    ledger_path = root / entry["ledger_file"]
    with ledger_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"event_time", "kind", "status", "details",
                    *attribution_fields, "equity", "perp_collateral",
                    "spot_quantity", "perp_quantity"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("ledger is missing window metrics or attribution fields")
        previous_ledger_time = None
        for index, row in enumerate(reader):
            timestamp = _utc(row.get("event_time"), f"ledger row {index}.event_time")
            if previous_ledger_time is not None and timestamp < previous_ledger_time:
                raise ValueError("ledger event timestamps must be ordered")
            previous_ledger_time = timestamp
            if row.get("status") != "applied":
                continue
            cumulative = {
                name: _decimal(row.get(name), f"ledger row {index}.{name}")
                for name in attribution_fields
            }
            ledger_day = _utc_close_day(timestamp)
            if ledger_day < start_day:
                opening_attribution = cumulative
            if ledger_day <= end_day:
                ending_attribution = cumulative
            if start_day <= ledger_day <= end_day:
                selected_ledger_rows.append(row)
                if row.get("kind") == "funding":
                    try:
                        details = json.loads(row.get("details") or "")
                    except ValueError as exc:
                        raise ValueError(
                            f"ledger row {index} has invalid funding details") from exc
                    if not isinstance(details, dict) or "cashflow" not in details:
                        raise ValueError(
                            f"ledger row {index} is missing funding cashflow")
                    funding_by_day[ledger_day] = (
                        funding_by_day.get(ledger_day, Decimal(0)) +
                        _decimal(details["cashflow"], f"ledger row {index}.cashflow"))

    for name in attribution_fields:
        selected_summary[name] = float(ending_attribution[name] -
                                       opening_attribution[name])
    utilization = []
    residual_delta = []
    for index, row in enumerate(selected_ledger_rows):
        equity_value = _decimal(row.get("equity"), f"ledger row {index}.equity")
        if equity_value > 0:
            utilization.append(float(
                _decimal(row.get("perp_collateral"),
                         f"ledger row {index}.perp_collateral") / equity_value))
        residual_delta.append(abs(float(
            _decimal(row.get("spot_quantity"),
                     f"ledger row {index}.spot_quantity") +
            _decimal(row.get("perp_quantity"),
                     f"ledger row {index}.perp_quantity"))))
    selected_summary["average_collateral_utilization"] = (
        statistics.mean(utilization) if utilization else None)
    selected_summary["peak_residual_delta"] = (
        max(residual_delta) if residual_delta else None)

    attribution = record.get("attribution")
    if not isinstance(attribution, dict):
        raise ValueError("trial is missing attribution")
    attribution_rows = []
    for label in attribution_fields:
        if label not in attribution:
            raise ValueError(f"attribution.{label} is required")
        _decimal(attribution[label], f"attribution.{label}")
        attribution_rows.append({"component": label,
                                 "amount": float(ending_attribution[label] -
                                                 opening_attribution[label])})
    scenarios = record.get("risk_scenarios", [])
    if scenarios is None:
        scenarios = []
    if not isinstance(scenarios, list) or any(not isinstance(item, dict) for item in scenarios):
        raise ValueError("risk_scenarios must be a list of objects")
    audit = json.loads((root / entry["margin_audit_file"]).read_text(encoding="utf-8"))
    campaign = catalog["campaign_feasibility"]
    summary = {key: metrics[key] for key in _SUMMARY_FIELDS if key in metrics}
    return {
        "trial_id": trial_id,
        "run_id": record["run_id"],
        "stage": record["stage"],
        "strategy": record["strategy"],
        "selected_range": {"start": start_day.isoformat(), "end": end_day.isoformat()},
        "coverage": {"start": coverage_start.isoformat(), "end": coverage_end.isoformat()},
        "summary": summary,
        "selected_summary": selected_summary,
        "equity_series": equity_rows,
        "funding_series": [{"date": day.isoformat(), "cashflow": float(amount)}
                            for day, amount in sorted(funding_by_day.items())],
        "attribution_rows": attribution_rows,
        "risk_scenarios": scenarios,
        "assumptions": record.get("assumptions", {}),
        "provenance": record.get("provenance", {}),
        "margin_audit": audit,
        "campaign_feasibility": campaign,
        "metric_limitations": metric_limitations,
        "selected_metric_limitations": selected_metric_limitations,
        "limitations": record.get("limitations", []),
        "source_files": {"trial": entry["trial_file"],
                         "ledger": entry["ledger_file"],
                         "margin_audit": entry["margin_audit_file"]},
    }
