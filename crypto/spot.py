"""Small, deterministic long-only spot cash ledger for cross-checking signals."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from crypto.gap_policy import SUPPORTED_KNOWN_GAP, is_supported_known_gaps

_ZERO = Decimal("0")
_BPS = Decimal("10000")


def _decimal(value, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite and numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite and numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite and numeric")
    return number


def _time_ms(value, field: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 string")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _text(value: Decimal) -> str:
    return format(value, "f")


def run_spot(bars: list[dict], orders: list[dict], config: dict) -> dict:
    """Replay spot orders at their exact eligible candle open.

    Order time means the next intended candle open after a signal is available.
    Orders do not drift to a later candle when that open is missing or the market
    is in the confirmed Binance outage. All ledger values use Decimal and are returned as
    strings so that they remain JSON-safe without binary-float roundoff.
    """
    initial = _decimal(config["campaign"]["initial_equity"], "initial_equity")
    fee_bps = _decimal(config["costs"]["spot_fee_bps"], "spot_fee_bps")
    slip_bps = _decimal(config["costs"].get("slippage_bps", 0), "slippage_bps")
    if initial <= 0 or fee_bps < 0 or not 0 <= slip_bps < _BPS:
        raise ValueError("invalid initial equity, fee, or slippage assumptions")

    normalized_bars = []
    seen = set()
    for bar in bars:
        open_ms = _time_ms(bar["open_time"], "bar.open_time")
        close_ms = _time_ms(bar["close_time"], "bar.close_time")
        available_ms = _time_ms(bar["available_time"], "bar.available_time")
        if open_ms in seen:
            raise ValueError("spot bars contain duplicate open times")
        if close_ms <= open_ms or available_ms < close_ms:
            raise ValueError("spot bar close or availability time is invalid")
        price_open = _decimal(bar["open"], "bar.open")
        price_close = _decimal(bar["close"], "bar.close")
        if price_open <= 0 or price_close <= 0:
            raise ValueError("spot bar prices must be positive")
        normalized_bars.append((open_ms, close_ms, price_open, price_close))
        seen.add(open_ms)
    normalized_bars.sort(key=lambda item: item[0])
    bars_by_open = {row[0]: row for row in normalized_bars}

    declared_gaps = config.get("data", {}).get("known_gaps", [])
    if not is_supported_known_gaps(declared_gaps):
        raise ValueError("spot ledger accepts only the documented Binance spot outage")
    known_gaps = [(_time_ms(SUPPORTED_KNOWN_GAP["start"], "known_gap.start"),
                   _time_ms(SUPPORTED_KNOWN_GAP["end"], "known_gap.end"))]

    normalized_orders = []
    for index, order in enumerate(orders):
        order_ms = _time_ms(order.get("time"), "order.time")
        side = order.get("side")
        amount = _decimal(order.get("quantity"), "order.quantity")
        if side not in {"buy", "sell"} or amount <= 0:
            raise ValueError("order side must be buy/sell and quantity must be positive")
        normalized_orders.append((order_ms, index, side, amount))
    normalized_orders.sort(key=lambda row: (row[0], row[1]))

    cash, quantity = initial, _ZERO
    fees, slippage = _ZERO, _ZERO
    order_results, trades, equity = [], [], []
    order_index = 0

    def process_order(order_ms, side, amount, candle_row):
        nonlocal cash, quantity, fees, slippage
        status, reason = "rejected_no_market_bar", "no candle opens at the requested time"
        fill = None
        if any(start <= order_ms < end for start, end in known_gaps):
            status, reason = "rejected_market_outage", "spot market is unavailable"
        elif candle_row is not None and candle_row[0] == order_ms:
            open_price = candle_row[2]
            direction = Decimal("1") if side == "buy" else Decimal("-1")
            fill_price = open_price * (Decimal("1") + direction * slip_bps / _BPS)
            notional = fill_price * amount
            fee = notional * fee_bps / _BPS
            if side == "buy":
                if notional + fee > cash:
                    status, reason = "rejected_insufficient_cash", "cash does not cover notional and fee"
                else:
                    cash -= notional + fee
                    quantity += amount
                    status, reason = "filled", ""
            elif amount > quantity:
                status, reason = "rejected_insufficient_position", "sell exceeds available spot quantity"
            else:
                cash += notional - fee
                quantity -= amount
                status, reason = "filled", ""

            if status == "filled":
                fees += fee
                slippage += abs(fill_price - open_price) * amount
                fill = {"time": _iso_ms(order_ms), "side": side,
                        "quantity": _text(amount), "price": _text(fill_price),
                        "fee": _text(fee), "cash_after": _text(cash),
                        "quantity_after": _text(quantity)}
                trades.append(fill)

        order_results.append({"time": _iso_ms(order_ms), "side": side,
                              "quantity": _text(amount), "status": status,
                              "reason": reason, "fill": fill})

    for candle_row in normalized_bars:
        open_ms, close_ms, _, close_price = candle_row
        while (order_index < len(normalized_orders) and
               normalized_orders[order_index][0] <= open_ms):
            order_ms, _, side, amount = normalized_orders[order_index]
            process_order(order_ms, side, amount, bars_by_open.get(order_ms))
            order_index += 1
        equity.append({"time": _iso_ms(close_ms), "available_time": _iso_ms(close_ms),
                       "cash": _text(cash), "quantity": _text(quantity),
                       "mark_price": _text(close_price),
                       "equity": _text(cash + quantity * close_price)})
    while order_index < len(normalized_orders):
        order_ms, _, side, amount = normalized_orders[order_index]
        process_order(order_ms, side, amount, bars_by_open.get(order_ms))
        order_index += 1
    last_mark = normalized_bars[-1][3] if normalized_bars else _ZERO
    final_equity = cash + quantity * last_mark
    return {"trades": trades, "orders": order_results, "equity": equity,
            "costs": {"fees": _text(fees), "slippage": _text(slippage)},
            "initial_equity": _text(initial), "final_cash": _text(cash),
            "final_quantity": _text(quantity), "final_mark_price": _text(last_mark),
            "final_equity": _text(final_equity), "open_position": quantity != 0}
