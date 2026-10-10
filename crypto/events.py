"""Validation and deterministic same-time ordering for ledger events."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


_PRIORITY = {"funding": 0, "mark": 2, "spot_fill": 3,
             "perp_fill": 3, "risk": 5}


def _priority(event):
    if event["kind"] != "collateral_transfer":
        return _PRIORITY[event["kind"]]
    if event["payload"].get("withdraw_all") is True:
        return 4
    try:
        amount = Decimal(str(event["payload"].get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        return 1
    if not amount.is_finite():
        return 1
    return 1 if amount >= 0 else 4


def event_time_ms(value) -> int:
    if not isinstance(value, str):
        raise ValueError("event_time must be a timezone-aware ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("event_time must be a timezone-aware ISO-8601 string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event_time must be a timezone-aware ISO-8601 string")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def sort_events(events: list[dict]) -> list[dict]:
    """Sort by UTC time, event priority, explicit sequence, then input order.

    Funding is settled before same-timestamp fills regardless of their supplied
    sequence. Deposits happen before fills; collateral withdrawals happen after
    fills. This prevents new positions from receiving a settlement at entry and
    permits a closing fill to release its remaining collateral.
    """
    prepared = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        kind = event.get("kind")
        if kind not in {*_PRIORITY, "collateral_transfer"}:
            raise ValueError("event kind is not supported")
        sequence = event.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise ValueError("event sequence must be an integer")
        if not isinstance(event.get("payload"), dict):
            raise ValueError("event payload must be an object")
        prepared.append((event_time_ms(event.get("event_time")),
                         _priority(event), sequence, index, event))
    return [row[-1] for row in sorted(prepared, key=lambda item: item[:-1])]
