"""Strict configuration parsing for reproducible crypto research runs."""
import json
import math
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path

from crypto.gap_policy import is_supported_known_gaps


_SECTIONS = ("market", "data", "costs", "campaign")
_COST_FIELDS = ("spot_fee_bps", "perp_fee_bps", "slippage_bps")


def validate_config(config: dict) -> dict:
    """Validate a JSON-compatible research config without supplying defaults."""
    if not isinstance(config, dict):
        raise ValueError("configuration root must be an object")
    for section in _SECTIONS:
        if not isinstance(config.get(section), dict):
            raise ValueError(f"{section} must be an object")

    result = {section: dict(config[section]) for section in _SECTIONS}
    market = result["market"]
    for field in ("exchange", "market_type", "spot_symbol", "perp_symbol"):
        if not isinstance(market.get(field), str) or not market[field].strip():
            raise ValueError(f"market.{field} is required")
    if market["market_type"] != "spot_perpetual_carry":
        raise ValueError("market.market_type must be spot_perpetual_carry")
    market["exchange"] = market["exchange"].lower()
    if market["exchange"] != "binance":
        raise ValueError("market.exchange must be binance; other adapters are not implemented")

    data = result["data"]
    if data.get("mode") != "real_snapshot":
        raise ValueError("data.mode must be real_snapshot for research")
    if not isinstance(data.get("root"), str) or not data["root"].strip():
        raise ValueError("data.root is required")
    if data.get("timeframe") != "1h":
        raise ValueError("data.timeframe must be 1h in the initial research version")
    timestamps = {}
    for field in ("start", "end"):
        value = data.get(field)
        if not isinstance(value, str):
            raise ValueError(f"data.{field} must be an ISO-8601 timestamp with a timezone")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"data.{field} must be an ISO-8601 timestamp with a timezone") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"data.{field} must be an ISO-8601 timestamp with a timezone")
        timestamps[field] = parsed.astimezone(timezone.utc)
        data[field] = timestamps[field].isoformat().replace("+00:00", "Z")
    if timestamps["end"] <= timestamps["start"]:
        raise ValueError("data.end must be later than data.start")
    if any(int(value.timestamp() * 1000) % 3_600_000 for value in timestamps.values()):
        raise ValueError("data range boundaries must align to the UTC hour")

    if "known_gaps" in data:
        known_gaps = data["known_gaps"]
        if not isinstance(known_gaps, list):
            raise ValueError("data.known_gaps must be a list")
        normalized_gaps = []
        for index, gap in enumerate(known_gaps):
            prefix = f"data.known_gaps[{index}]"
            if not isinstance(gap, dict):
                raise ValueError(f"{prefix} must be an object")
            table = gap.get("table")
            if table not in {"spot_ohlcv", "perp_ohlcv", "mark_ohlcv"}:
                raise ValueError(f"{prefix}.table must name a price table")
            start_value, end_value = gap.get("start"), gap.get("end")
            try:
                gap_start = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
                gap_end = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError(f"{prefix} start/end must be timezone-aware ISO-8601") from exc
            if (gap_start.tzinfo is None or gap_start.utcoffset() is None or
                    gap_end.tzinfo is None or gap_end.utcoffset() is None):
                raise ValueError(f"{prefix} start/end must be timezone-aware ISO-8601")
            gap_start = gap_start.astimezone(timezone.utc)
            gap_end = gap_end.astimezone(timezone.utc)
            if gap_end <= gap_start:
                raise ValueError(f"{prefix}.end must be later than start")
            if (int(gap_start.timestamp() * 1000) % 3_600_000 or
                    int(gap_end.timestamp() * 1000) % 3_600_000):
                raise ValueError(f"{prefix} boundaries must align to the UTC hour")
            if gap_start < timestamps["start"] or gap_end > timestamps["end"]:
                raise ValueError(f"{prefix} must fall inside the configured data range")
            reason, source_url = gap.get("reason"), gap.get("source_url")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{prefix}.reason is required")
            if not isinstance(source_url, str) or not source_url.startswith("https://"):
                raise ValueError(f"{prefix}.source_url must be an HTTPS source")
            normalized_gaps.append({"table": table,
                                    "start": gap_start.isoformat().replace("+00:00", "Z"),
                                    "end": gap_end.isoformat().replace("+00:00", "Z"),
                                    "reason": reason.strip(),
                                    "source_url": source_url})
        if not is_supported_known_gaps(normalized_gaps):
            raise ValueError(
                "data.known_gaps may contain only the documented Binance spot outage")
        data["known_gaps"] = normalized_gaps

    costs = result["costs"]
    for field in _COST_FIELDS:
        value = costs.get(field)
        if (isinstance(value, bool) or not isinstance(value, Real)
                or not math.isfinite(float(value)) or value < 0):
            raise ValueError(f"costs.{field} must be a finite non-negative number")

    campaign = result["campaign"]
    equity = campaign.get("initial_equity")
    if (isinstance(equity, bool) or not isinstance(equity, Real)
            or not math.isfinite(float(equity)) or equity <= 0):
        raise ValueError("campaign.initial_equity must be a finite positive number")
    attempts = campaign.get("max_attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10:
        raise ValueError("campaign.max_attempts must be an integer between 1 and 10")
    if "cash_return_assumption_annual" in campaign:
        cash_rate = campaign["cash_return_assumption_annual"]
        if (isinstance(cash_rate, bool) or not isinstance(cash_rate, Real) or
                not math.isfinite(float(cash_rate)) or cash_rate <= -1):
            raise ValueError(
                "campaign.cash_return_assumption_annual must be finite and greater than -1")
    return result


def load_config(path: str) -> dict:
    """Load and validate one UTF-8 JSON research configuration."""
    with Path(path).open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    return validate_config(config)
