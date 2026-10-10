"""Daily-return metrics with explicit UTC and sample-size limitations."""
from datetime import datetime, timedelta, timezone
import math
import statistics


_SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


def _time(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware ISO-8601")
    return parsed.astimezone(timezone.utc)


def _finite(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite and numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite and numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite and numeric")
    return result


def evaluate_metrics(equity: list[dict], initial_equity: float,
                     risk_free_rate: float = 0.0,
                     start_time: str | None = None,
                     ledger: list[dict] | None = None) -> dict:
    """Summarize an equity path using UTC daily observations.

    The first day return is measured from initial equity, so entry fees can
    create a drawdown on day one. CAGR uses elapsed seconds rather than assuming
    an exact number of years. Risk-free rate is a declared annual scenario.
    """
    initial = _finite(initial_equity, "initial_equity")
    annual_rf = _finite(risk_free_rate, "risk_free_rate")
    if initial <= 0:
        raise ValueError("initial_equity must be positive")
    if not isinstance(equity, list) or not equity:
        raise ValueError("equity series must contain at least one observation")

    observations = []
    previous = None
    for row in equity:
        if not isinstance(row, dict) or "time" not in row or "equity" not in row:
            raise ValueError("equity rows require time and equity")
        stamp = _time(row["time"], "equity.time")
        value = _finite(row["equity"], "equity.value")
        if value <= 0:
            raise ValueError("equity values must be positive for return metrics")
        if previous is not None and stamp <= previous:
            raise ValueError("equity timestamps must be strictly increasing")
        observations.append((stamp, value))
        previous = stamp

    start = _time(start_time, "start_time") if start_time else observations[0][0]
    daily = {}
    for stamp, value in observations:
        if start_time and stamp <= start:
            continue
        # A mark at exactly midnight closes the UTC day that just ended.
        day = stamp.date()
        if stamp.time() == datetime.min.time():
            day -= timedelta(days=1)
        daily[day] = (stamp, value)
    daily_rows = list(daily.values())
    daily_returns = []
    previous_value = initial
    for _, value in daily_rows:
        daily_returns.append(value / previous_value - 1.0)
        previous_value = value

    limitations = []
    sample_std = statistics.stdev(daily_returns) if len(daily_returns) > 1 else None
    if sample_std is None:
        annualized_volatility = sharpe = None
        limitations.append("fewer than two daily returns; volatility and Sharpe are undefined")
    elif sample_std == 0:
        annualized_volatility = 0.0
        sharpe = None
        limitations.append("zero variance in daily returns; Sharpe is undefined")
    else:
        annualized_volatility = sample_std * math.sqrt(365.0)
        daily_rf = (1.0 + annual_rf) ** (1.0 / 365.0) - 1.0
        excess = [value - daily_rf for value in daily_returns]
        sharpe = statistics.mean(excess) / sample_std * math.sqrt(365.0)

    end = observations[-1][0]
    elapsed_seconds = (end - start).total_seconds()
    elapsed_days = elapsed_seconds / 86400.0
    final_value = observations[-1][1]
    if elapsed_seconds <= 0:
        cagr = None
        limitations.append("non-positive elapsed time; CAGR is undefined")
    else:
        cagr = (final_value / initial) ** (_SECONDS_PER_YEAR / elapsed_seconds) - 1.0
    if elapsed_seconds < 365 * 86400:
        limitations.append("less than one year of observations; annualized metrics are unstable")

    peak = initial
    max_drawdown = 0.0
    for _, value in daily_rows:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1.0)

    result = {
        "initial_equity": initial,
        "final_equity": final_value,
        "total_return": final_value / initial - 1.0,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "annualized_volatility": annualized_volatility,
        "sharpe_daily": sharpe,
        "daily_return_count": len(daily_returns),
        "elapsed_days": elapsed_days,
        "start_time": start.isoformat().replace("+00:00", "Z"),
        "end_time": end.isoformat().replace("+00:00", "Z"),
        "risk_free_rate_annual": annual_rf,
        "annualization_basis": "365-day UTC daily returns",
        "max_drawdown_basis": "UTC daily close samples including initial equity",
        "limitations": limitations,
    }
    if ledger:
        utilization, residual = [], []
        for row in ledger:
            try:
                equity_value = _finite(row["equity"], "ledger.equity")
                if equity_value > 0:
                    utilization.append(_finite(row.get("perp_collateral", 0),
                                                "ledger.perp_collateral") / equity_value)
                residual.append(abs(_finite(row.get("spot_quantity", 0),
                                            "ledger.spot_quantity") +
                                    _finite(row.get("perp_quantity", 0),
                                            "ledger.perp_quantity")))
            except (KeyError, TypeError, ValueError):
                continue
        result["average_collateral_utilization"] = (
            statistics.mean(utilization) if utilization else None)
        result["collateral_utilization_basis"] = "event-weighted ledger observations"
        result["peak_residual_delta"] = max(residual) if residual else None
    return result
