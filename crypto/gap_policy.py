"""Narrow exception policy for the one source-verified data outage."""
from datetime import datetime, timezone


SUPPORTED_KNOWN_GAP = {
    "table": "spot_ohlcv",
    "start": "2023-03-24T13:00:00Z",
    "end": "2023-03-24T14:00:00Z",
    "reason": "Binance spot trading system maintenance; trading resumed at 14:00 UTC",
    "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a",
}


def is_supported_known_gaps(gaps: list[dict]) -> bool:
    """Allow no exception or exactly the one documented Binance spot outage."""
    if gaps == []:
        return True
    if not isinstance(gaps, list) or len(gaps) != 1 or not isinstance(gaps[0], dict):
        return False
    gap = gaps[0]
    if set(gap) != set(SUPPORTED_KNOWN_GAP):
        return False
    for field in ("table", "reason", "source_url"):
        if gap.get(field) != SUPPORTED_KNOWN_GAP[field]:
            return False
    try:
        actual_start = _utc_ms(gap["start"])
        actual_end = _utc_ms(gap["end"])
        expected_start = _utc_ms(SUPPORTED_KNOWN_GAP["start"])
        expected_end = _utc_ms(SUPPORTED_KNOWN_GAP["end"])
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return actual_start == expected_start and actual_end == expected_end


def _utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)
