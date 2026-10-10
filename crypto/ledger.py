"""Decimal double-entry-style cash, positions, costs and funding replay."""
from decimal import Decimal, InvalidOperation

from crypto.events import event_time_ms, sort_events
from crypto.gap_policy import SUPPORTED_KNOWN_GAP, is_supported_known_gaps


_ZERO = Decimal("0")
_BPS = Decimal("10000")
_TOLERANCE = Decimal("0.00000001")


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


def _text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def funding_cashflow(quantity: Decimal, mark: Decimal,
                     rate: Decimal) -> Decimal:
    """Return the quote-currency funding cashflow for signed perp quantity."""
    quantity = _decimal(quantity, "quantity")
    mark = _decimal(mark, "mark")
    rate = _decimal(rate, "rate")
    if mark <= 0:
        raise ValueError("mark must be positive")
    return -quantity * mark * rate


def _new_group() -> dict:
    return {"spot_quantity": _ZERO, "spot_avg_reference": _ZERO,
            "spot_avg_execution": _ZERO, "perp_quantity": _ZERO,
            "perp_avg_reference": _ZERO, "perp_avg_execution": _ZERO,
            "collateral": _ZERO}


def _position_transition(old_quantity: Decimal, old_reference: Decimal,
                         old_execution: Decimal, signed_delta: Decimal,
                         reference_price: Decimal, execution_price: Decimal):
    """Update a signed average-cost position and return realized PnL bases."""
    new_quantity = old_quantity + signed_delta
    realized_reference = realized_execution = _ZERO
    if old_quantity == 0 or old_quantity * signed_delta > 0:
        total = abs(old_quantity) + abs(signed_delta)
        average_reference = ((abs(old_quantity) * old_reference +
                              abs(signed_delta) * reference_price) / total)
        average_execution = ((abs(old_quantity) * old_execution +
                              abs(signed_delta) * execution_price) / total)
    else:
        closed = min(abs(old_quantity), abs(signed_delta))
        direction = Decimal("1") if old_quantity > 0 else Decimal("-1")
        realized_reference = direction * closed * (reference_price - old_reference)
        realized_execution = direction * closed * (execution_price - old_execution)
        if new_quantity == 0:
            average_reference = average_execution = _ZERO
        elif new_quantity * old_quantity > 0:
            average_reference, average_execution = old_reference, old_execution
        else:
            average_reference, average_execution = reference_price, execution_price
    return (new_quantity, average_reference, average_execution,
            realized_reference, realized_execution)


def replay_events(events: list[dict], config: dict) -> dict:
    """Replay fills, collateral, marks and settlement events into a cash ledger.

    Settlement events are ordered before fills at the same UTC millisecond.
    This preserves the rule that a position opened at settlement cannot receive
    that event's funding. `price` on a fill is the reference market price;
    configured slippage produces the executed price used in cash flows.
    """
    initial_equity = _decimal(config["campaign"]["initial_equity"], "initial_equity")
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    costs = config["costs"]
    spot_fee_bps = _decimal(costs["spot_fee_bps"], "spot_fee_bps")
    perp_fee_bps = _decimal(costs["perp_fee_bps"], "perp_fee_bps")
    slippage_bps = _decimal(costs["slippage_bps"], "slippage_bps")
    if min(spot_fee_bps, perp_fee_bps, slippage_bps) < 0 or slippage_bps >= _BPS:
        raise ValueError("fees must be non-negative and slippage must be below 10000 bps")

    free_cash = initial_equity
    groups: dict[str, dict] = {}
    spot_mark = perp_mark = _ZERO
    spot_market_available, spot_mark_is_stale = True, False
    realized_spot = realized_perp = funding_total = _ZERO
    spot_fees = perp_fees = slippage_total = _ZERO
    ledger, risk_events = [], []

    def get_group(group_id):
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("position event needs a non-empty group_id")
        if group_id not in groups:
            groups[group_id] = _new_group()
        return groups[group_id]

    def current_spot_pnl():
        return realized_spot + sum(
            (group["spot_quantity"] * (spot_mark - group["spot_avg_reference"])
             for group in groups.values()), _ZERO)

    def current_perp_pnl():
        return realized_perp + sum(
            (group["perp_quantity"] * (perp_mark - group["perp_avg_reference"])
             for group in groups.values()), _ZERO)

    def current_equity():
        spot_value = sum((group["spot_quantity"] * spot_mark
                          for group in groups.values()), _ZERO)
        perp_unrealized = sum(
            (group["perp_quantity"] * (perp_mark - group["perp_avg_execution"])
             for group in groups.values()), _ZERO)
        collateral = sum((group["collateral"] for group in groups.values()), _ZERO)
        return free_cash + spot_value + collateral + perp_unrealized

    def attributed_equity():
        return (initial_equity + current_spot_pnl() + current_perp_pnl() +
                funding_total - spot_fees - perp_fees - slippage_total)

    known_gaps = config.get("data", {}).get("known_gaps", [])
    if not is_supported_known_gaps(known_gaps):
        raise ValueError("ledger accepts only the documented Binance spot outage")
    # The confirmed no-trade interval is a market fact, not an optional config
    # switch. A replay cannot make that hour tradable by omitting its annotation.
    outage_ranges = [(event_time_ms(SUPPORTED_KNOWN_GAP["start"]),
                      event_time_ms(SUPPORTED_KNOWN_GAP["end"]))]

    for event in sort_events(events):
        kind, payload = event["kind"], event["payload"]
        status, details = "applied", {}
        event_ms = event_time_ms(event["event_time"])
        if kind == "spot_fill" and (not spot_market_available or any(
                start <= event_ms < end for start, end in outage_ranges)):
            status = "rejected_market_outage"
            details["rejection_reason"] = "spot market is unavailable during a documented outage"
        elif kind in {"spot_fill", "perp_fill"}:
            group = get_group(payload.get("group_id"))
            side = payload.get("side")
            quantity = _decimal(payload.get("quantity"), "fill.quantity")
            reference_price = _decimal(payload.get("reference_price",
                                                   payload.get("price")),
                                       "fill.reference_price")
            if side not in {"buy", "sell"} or quantity <= 0 or reference_price <= 0:
                raise ValueError("fill needs buy/sell side and positive quantity/reference price")
            sign = Decimal("1") if side == "buy" else Decimal("-1")
            execution_price = reference_price * (
                Decimal("1") + sign * slippage_bps / _BPS)
            fee_rate = (spot_fee_bps if kind == "spot_fill" else perp_fee_bps) / _BPS
            fee = quantity * execution_price * fee_rate
            cash_after_fee = free_cash - fee
            if kind == "perp_fill" and cash_after_fee < 0:
                status, details["rejection_reason"] = "rejected_insufficient_free_cash", "fee exceeds free cash"
            elif kind == "spot_fill":
                delta = sign * quantity
                if side == "buy":
                    if cash_after_fee < quantity * execution_price:
                        status, details["rejection_reason"] = "rejected_insufficient_free_cash", "cash does not cover spot purchase"
                    else:
                        (group["spot_quantity"], group["spot_avg_reference"],
                         group["spot_avg_execution"], realized, _) = _position_transition(
                            group["spot_quantity"], group["spot_avg_reference"],
                            group["spot_avg_execution"], delta,
                            reference_price, execution_price)
                        free_cash = cash_after_fee - quantity * execution_price
                        realized_spot += realized
                        spot_fees += fee
                        spot_mark = _decimal(payload.get("mark_price", reference_price),
                                             "fill.mark_price")
                        if spot_mark <= 0:
                            raise ValueError("spot fill mark price must be positive")
                        spot_market_available, spot_mark_is_stale = True, False
                        slippage_total += max(_ZERO, sign * quantity *
                                              (execution_price - reference_price))
                elif quantity > group["spot_quantity"]:
                    status, details["rejection_reason"] = "rejected_insufficient_spot", "sell exceeds available spot position"
                elif free_cash + quantity * execution_price - fee < 0:
                    status, details["rejection_reason"] = "rejected_insufficient_free_cash", "sale proceeds do not cover fee"
                else:
                    (group["spot_quantity"], group["spot_avg_reference"],
                     group["spot_avg_execution"], realized, _) = _position_transition(
                        group["spot_quantity"], group["spot_avg_reference"],
                        group["spot_avg_execution"], delta,
                        reference_price, execution_price)
                    free_cash = cash_after_fee + quantity * execution_price
                    realized_spot += realized
                    spot_fees += fee
                    spot_mark = _decimal(payload.get("mark_price", reference_price),
                                         "fill.mark_price")
                    if spot_mark <= 0:
                        raise ValueError("spot fill mark price must be positive")
                    spot_market_available, spot_mark_is_stale = True, False
                    slippage_total += max(_ZERO, sign * quantity *
                                          (execution_price - reference_price))
            else:
                delta = sign * quantity
                (group["perp_quantity"], group["perp_avg_reference"],
                 group["perp_avg_execution"], realized_ref, realized_exec) = _position_transition(
                    group["perp_quantity"], group["perp_avg_reference"],
                    group["perp_avg_execution"], delta,
                    reference_price, execution_price)
                free_cash = cash_after_fee
                group["collateral"] += realized_exec
                realized_perp += realized_ref
                perp_fees += fee
                perp_mark = _decimal(payload.get("mark_price", reference_price),
                                     "fill.mark_price")
                if perp_mark <= 0:
                    raise ValueError("perpetual fill mark price must be positive")
                slippage_total += max(_ZERO, sign * quantity *
                                      (execution_price - reference_price))
                details.update({"reference_price": _text(reference_price),
                                "execution_price": _text(execution_price),
                                "fee": _text(fee)})

        elif kind == "collateral_transfer":
            group = get_group(payload.get("group_id"))
            amount = _decimal(payload.get("amount"), "collateral.amount")
            withdraw_all = payload.get("withdraw_all", False)
            if not isinstance(withdraw_all, bool):
                raise ValueError("collateral.withdraw_all must be boolean")
            if withdraw_all and amount != 0:
                raise ValueError("withdraw-all collateral transfer must use amount zero")
            if withdraw_all and (group["spot_quantity"] != 0 or
                                 group["perp_quantity"] != 0):
                status = "rejected_position_open"
                details["rejection_reason"] = "group positions must be flat before withdrawing collateral"
                amount = _ZERO
            elif withdraw_all:
                amount = -max(group["collateral"], _ZERO)
                free_cash -= amount
                group["collateral"] += amount
                details.update({"amount": _text(amount), "withdraw_all": True})
            elif amount > 0 and amount > free_cash:
                status, details["rejection_reason"] = "rejected_insufficient_free_cash", "collateral deposit exceeds free cash"
            elif amount < 0 and -amount > group["collateral"]:
                status, details["rejection_reason"] = "rejected_insufficient_collateral", "withdrawal exceeds group collateral"
            else:
                free_cash -= amount
                group["collateral"] += amount
                details["amount"] = _text(amount)

        elif kind == "funding":
            rate = _decimal(payload.get("rate"), "funding.rate")
            mark = _decimal(payload.get("mark_price"), "funding.mark_price")
            if mark <= 0:
                raise ValueError("funding mark price must be positive")
            source = payload.get("mark_price_source")
            is_proxy = payload.get("mark_price_is_proxy")
            source_time = payload.get("mark_price_source_time")
            if source == "funding_endpoint":
                if is_proxy is not False or source_time is not None:
                    raise ValueError("endpoint funding mark has invalid mark-price provenance")
            elif source == "mark_ohlcv.open_proxy":
                if is_proxy is not True or not isinstance(source_time, str):
                    raise ValueError("funding proxy needs complete mark-price provenance")
                source_ms = event_time_ms(source_time)
                if (source_ms % 3_600_000 or
                        source_ms != event_ms - event_ms % 3_600_000):
                    raise ValueError("funding proxy source must be from the same UTC hour")
            else:
                raise ValueError("funding event needs complete mark-price provenance")
            perp_mark = mark
            cashflow = _ZERO
            for group in groups.values():
                flow = funding_cashflow(group["perp_quantity"], mark, rate)
                group["collateral"] += flow
                cashflow += flow
            funding_total += cashflow
            details.update({"rate": _text(rate), "mark_price": _text(mark),
                            "cashflow": _text(cashflow),
                            "mark_price_source": source,
                            "mark_price_is_proxy": is_proxy,
                            "mark_price_source_time": source_time})

        elif kind == "mark":
            if "spot_price" in payload:
                spot_mark = _decimal(payload["spot_price"], "mark.spot_price")
                if spot_mark <= 0:
                    raise ValueError("spot mark price must be positive")
            if "spot_mark_is_stale" in payload:
                if not isinstance(payload["spot_mark_is_stale"], bool):
                    raise ValueError("spot_mark_is_stale must be boolean")
                spot_mark_is_stale = payload["spot_mark_is_stale"]
            if "spot_market_available" in payload:
                if not isinstance(payload["spot_market_available"], bool):
                    raise ValueError("spot_market_available must be boolean")
                spot_market_available = payload["spot_market_available"]
            if "perp_mark_price" in payload:
                perp_mark = _decimal(payload["perp_mark_price"], "mark.perp_mark_price")
                if perp_mark <= 0:
                    raise ValueError("perpetual mark price must be positive")
            details.update({"spot_mark": _text(spot_mark),
                            "perp_mark": _text(perp_mark),
                            "spot_market_available": spot_market_available,
                            "spot_mark_is_stale": spot_mark_is_stale})

        elif kind == "risk":
            risk_events.append({"event_time": event["event_time"], **payload})
            details = dict(payload)

        equity_value = current_equity()
        attributed_value = attributed_equity()
        if abs(equity_value - attributed_value) > _TOLERANCE:
            raise ArithmeticError(
                f"ledger equity attribution does not reconcile at {event['event_time']}: "
                f"{_text(equity_value)} != {_text(attributed_value)}")
        row = {"event_time": event["event_time"], "kind": kind,
               "sequence": event["sequence"], "status": status,
               "free_cash": _text(free_cash),
               "spot_quantity": _text(sum((g["spot_quantity"] for g in groups.values()), _ZERO)),
               "spot_market_value": _text(sum((g["spot_quantity"] * spot_mark
                                                for g in groups.values()), _ZERO)),
               "perp_quantity": _text(sum((g["perp_quantity"] for g in groups.values()), _ZERO)),
               "perp_collateral": _text(sum((g["collateral"] for g in groups.values()), _ZERO)),
               "spot_mark": _text(spot_mark), "perp_mark": _text(perp_mark),
               "spot_market_available": spot_market_available,
               "spot_mark_is_stale": spot_mark_is_stale,
               "spot_pnl": _text(current_spot_pnl()),
               "perp_pnl": _text(current_perp_pnl()),
               "funding": _text(funding_total), "spot_fees": _text(spot_fees),
               "perp_fees": _text(perp_fees), "slippage": _text(slippage_total),
               "equity": _text(equity_value),
               "attributed_equity": _text(attributed_value),
               "details": details}
        ledger.append(row)

    attribution = {"spot_pnl": _text(current_spot_pnl()),
                   "perp_pnl": _text(current_perp_pnl()),
                   "funding": _text(funding_total),
                   "spot_fees": _text(spot_fees), "perp_fees": _text(perp_fees),
                   "slippage": _text(slippage_total)}
    positions = [{"group_id": group_id,
                  "spot_quantity": _text(group["spot_quantity"]),
                  "spot_avg_reference": _text(group["spot_avg_reference"]),
                  "spot_avg_execution": _text(group["spot_avg_execution"]),
                  "perp_quantity": _text(group["perp_quantity"]),
                  "perp_avg_reference": _text(group["perp_avg_reference"]),
                  "perp_avg_execution": _text(group["perp_avg_execution"]),
                  "collateral": _text(group["collateral"])}
                 for group_id, group in sorted(groups.items())]
    return {"ledger": ledger, "positions": positions, "risk_events": risk_events,
            "attribution": attribution, "initial_equity": _text(initial_equity),
            "final_equity": _text(current_equity()),
            "free_cash": _text(free_cash), "spot_mark": _text(spot_mark),
            "perp_mark": _text(perp_mark),
            "total_collateral": _text(sum((g["collateral"] for g in groups.values()), _ZERO))}
