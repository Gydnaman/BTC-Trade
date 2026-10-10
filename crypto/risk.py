"""Transparent isolated-margin stress checks and non-atomic fill accounting."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation


_ZERO = Decimal("0")
_BPS = Decimal("10000")


def _decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite and numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite and numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite and numeric")
    return result


def _text(value):
    return "0" if value == 0 else format(value.normalize(), "f")


def _required(state, field):
    if field not in state:
        raise ValueError(f"state.{field} is required")
    return _decimal(state[field], f"state.{field}")


def _position_transition(old_quantity: Decimal, old_average: Decimal,
                        signed_delta: Decimal, price: Decimal):
    """Update a signed average execution price and compute realized PnL."""
    new_quantity = old_quantity + signed_delta
    realized = _ZERO
    if old_quantity != 0 and old_average <= 0:
        raise ValueError("a non-flat execution state needs its average entry price")
    if old_quantity == 0 or old_quantity * signed_delta > 0:
        total = abs(old_quantity) + abs(signed_delta)
        average = ((abs(old_quantity) * old_average + abs(signed_delta) * price) /
                   total) if total else _ZERO
    else:
        closed = min(abs(old_quantity), abs(signed_delta))
        direction = Decimal("1") if old_quantity > 0 else Decimal("-1")
        realized = direction * closed * (price - old_average)
        if new_quantity == 0:
            average = _ZERO
        elif new_quantity * old_quantity > 0:
            average = old_average
        else:
            average = price
    return new_quantity, average, realized


def assess_group(state: dict, scenario: dict) -> dict:
    """Stress one carry group under explicit spot/perpetual marks.

    The model treats perpetual collateral as isolated. Spot gains are reported
    but never credited to perpetual margin. No exchange liquidation price is
    inferred. A liquidation action is a research target, not an order.
    """
    if not isinstance(state, dict) or not isinstance(scenario, dict):
        raise ValueError("state and scenario must be objects")
    group_id = state.get("group_id")
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("state.group_id is required")
    spot_quantity = _required(state, "spot_quantity")
    perp_quantity = _required(state, "perp_quantity")
    spot_entry = _required(state, "spot_entry_price")
    perp_entry = _required(state, "perp_entry_price")
    collateral = _required(state, "collateral")
    spot_price = _decimal(scenario.get("spot_price", state.get("spot_price")),
                          "scenario.spot_price")
    perp_mark = _decimal(scenario.get("perp_mark_price",
                                      state.get("perp_mark_price")),
                         "scenario.perp_mark_price")
    funding_mark = _decimal(scenario.get("funding_mark_price", perp_mark),
                            "scenario.funding_mark_price")
    funding_rate = _decimal(scenario.get("funding_rate", 0), "scenario.funding_rate")
    maintenance_ratio = _decimal(scenario.get("maintenance_ratio"),
                                 "scenario.maintenance_ratio")
    slippage_bps = _decimal(scenario.get("slippage_bps", 0), "scenario.slippage_bps")
    perp_fee_bps = _decimal(scenario.get("perp_fee_bps", 0), "scenario.perp_fee_bps")
    spot_fee_bps = _decimal(scenario.get("spot_fee_bps", 0), "scenario.spot_fee_bps")
    if min(spot_entry, perp_entry, spot_price, perp_mark, funding_mark) <= 0:
        raise ValueError("entry and scenario prices must be positive")
    if not 0 <= maintenance_ratio < 1:
        raise ValueError("maintenance_ratio must be between 0 and 1")
    if min(slippage_bps, perp_fee_bps, spot_fee_bps) < 0 or slippage_bps >= _BPS:
        raise ValueError("fees and slippage must be non-negative; slippage below 10000 bps")

    spot_notional = abs(spot_quantity * spot_price)
    perp_notional = abs(perp_quantity * perp_mark)
    spot_pnl = spot_quantity * (spot_price - spot_entry)
    perp_pnl = perp_quantity * (perp_mark - perp_entry)
    funding_flow = -perp_quantity * funding_mark * funding_rate
    close_cost = (spot_notional * (spot_fee_bps + slippage_bps) +
                  perp_notional * (perp_fee_bps + slippage_bps)) / _BPS
    isolated_collateral = collateral + perp_pnl + funding_flow
    isolated_perp_cost = perp_notional * (perp_fee_bps + slippage_bps) / _BPS
    maintenance = perp_notional * maintenance_ratio
    collateral_shortfall = max(_ZERO, maintenance - isolated_collateral + isolated_perp_cost)
    free_cash = _decimal(state.get("free_cash", 0), "state.free_cash")
    account_equity = (free_cash + spot_quantity * spot_price + collateral +
                      perp_pnl + funding_flow - close_cost)
    net_delta = spot_quantity + perp_quantity
    market_available = scenario.get("spot_market_available", True)
    if not isinstance(market_available, bool):
        raise ValueError("spot_market_available must be boolean")

    actions = []
    reasons = []
    if collateral_shortfall > 0:
        reasons.append("isolated perpetual collateral is below the declared maintenance stress")
    if not market_available and spot_quantity != 0:
        reasons.append("spot leg is unavailable in this data-gap scenario")
    if net_delta != 0:
        reasons.append("the two legs leave residual BTC delta")
    if reasons:
        actions.append({"group_id": group_id, "type": "close_group_simulation",
                        "target_spot_quantity": "0", "target_perp_quantity": "0",
                        "reason": "; ".join(reasons),
                        "live_order_sent": False})

    return {
        "group_id": group_id,
        "gross_exposure": _text(spot_notional + perp_notional),
        "spot_exposure": _text(spot_notional),
        "perp_exposure": _text(perp_notional),
        "net_delta": _text(net_delta),
        "spot_unrealized_pnl": _text(spot_pnl),
        "perp_unrealized_pnl": _text(perp_pnl),
        "funding_cashflow": _text(funding_flow),
        "collateral_after_scenario": _text(isolated_collateral),
        "maintenance_requirement": _text(maintenance),
        "collateral_shortfall": _text(collateral_shortfall),
        "estimated_exit_cost": _text(close_cost),
        "account_equity_after_scenario": _text(account_equity),
        "actions": actions,
        "limitations": [
            "isolated perpetual margin; spot profit is not cross-collateral",
            "maintenance ratio and costs are scenario assumptions, not historical exchange rules",
            "hourly bars cannot identify liquidation or leg execution prices",
        ],
    }


def apply_execution_result(state: dict, result: dict) -> dict:
    """Apply signed fills independently and surface any remaining BTC delta.

    `filled_quantity` is a signed position change: positive adds BTC long
    exposure and negative reduces it or opens a short. The state carries
    average execution prices for open positions; realized perpetual PnL is
    credited to isolated collateral. This diagnostic helper still sends no
    orders and does not replace the event ledger.
    """
    if not isinstance(state, dict) or not isinstance(result, dict):
        raise ValueError("state and execution result must be objects")
    group_id = state.get("group_id")
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("state.group_id is required")
    updated = deepcopy(state)
    spot_qty = _decimal(state.get("spot_quantity", 0), "state.spot_quantity")
    perp_qty = _decimal(state.get("perp_quantity", 0), "state.perp_quantity")
    spot_average = _decimal(state.get("spot_average_price", 0),
                            "state.spot_average_price")
    perp_average = _decimal(state.get("perp_average_price", 0),
                            "state.perp_average_price")
    cash = _decimal(state.get("cash", state.get("free_cash", 0)), "state.cash")
    fees_paid = _decimal(state.get("fees_paid", 0), "state.fees_paid")
    spot_realized = _decimal(state.get("spot_realized_pnl", 0),
                             "state.spot_realized_pnl")
    perp_realized = _decimal(state.get("perp_realized_pnl", 0),
                             "state.perp_realized_pnl")
    collateral = _decimal(state.get("perp_collateral", state.get("collateral", 0)),
                          "state.perp_collateral")
    leg_statuses = {}
    deltas = {}
    for leg in ("spot", "perp"):
        fill = result.get(leg, {})
        if not isinstance(fill, dict):
            raise ValueError(f"result.{leg} must be an object")
        status = fill.get("status", "not_attempted")
        if status not in {"filled", "partial", "rejected", "cancelled",
                          "timeout", "not_attempted"}:
            raise ValueError(f"result.{leg}.status is unsupported")
        delta = _decimal(fill.get("filled_quantity", 0), f"result.{leg}.filled_quantity")
        fee = _decimal(fill.get("fee", 0), f"result.{leg}.fee")
        if fee < 0:
            raise ValueError("execution fees must be non-negative")
        if delta != 0:
            price = _decimal(fill.get("price"), f"result.{leg}.price")
            if price <= 0:
                raise ValueError("a non-zero fill needs a positive price")
            if leg == "spot":
                cash -= delta * price
                spot_qty, spot_average, realized = _position_transition(
                    spot_qty, spot_average, delta, price)
                spot_realized += realized
            else:
                perp_qty, perp_average, realized = _position_transition(
                    perp_qty, perp_average, delta, price)
                perp_realized += realized
                collateral += realized
            cash -= fee
            fees_paid += fee
        elif fee != 0:
            cash -= fee
            fees_paid += fee
        deltas[leg] = delta
        leg_statuses[leg] = status

    updated.update({"spot_quantity": _text(spot_qty), "perp_quantity": _text(perp_qty),
                    "spot_average_price": _text(spot_average),
                    "perp_average_price": _text(perp_average),
                    "spot_realized_pnl": _text(spot_realized),
                    "perp_realized_pnl": _text(perp_realized),
                    "perp_collateral": _text(collateral),
                    "cash": _text(cash), "fees_paid": _text(fees_paid)})
    if "free_cash" in state:
        updated["free_cash"] = _text(cash)
    partial = (any(delta != 0 for delta in deltas.values()) and
               (leg_statuses["spot"] != "filled" or leg_statuses["perp"] != "filled"))
    net_delta = spot_qty + perp_qty
    actions = []
    if partial or net_delta != 0:
        actions.append({"group_id": group_id, "type": "close_group_simulation",
                        "target_spot_quantity": "0", "target_perp_quantity": "0",
                        "reason": "execution left residual BTC delta; reconcile or flatten both legs",
                        "live_order_sent": False})
    spot_price = _decimal(state.get("spot_price", 0), "state.spot_price")
    perp_price = _decimal(state.get("perp_mark_price", 0), "state.perp_mark_price")
    gross_exposure = abs(spot_qty * spot_price) + abs(perp_qty * perp_price)
    return {"state": updated, "net_delta": _text(net_delta),
            "realized_spot_pnl": _text(spot_realized),
            "realized_perp_pnl": _text(perp_realized),
            "gross_exposure": _text(gross_exposure),
            "partial_execution": partial, "leg_statuses": leg_statuses,
            "actions": actions,
            "limitations": ["execution simulation only; no order was sent"]}
