# Risk and execution stress model

This is an auditable research stress model, not an exchange liquidation
calculator or an order router. It uses explicit scenarios because the hourly
history does not contain order-book depth, intrabar paths, or historical
maintenance tiers.

## Isolated perpetual collateral

For a position group, the model marks spot and perpetual legs separately:

- Spot PnL: `spot_quantity × (spot_scenario_price − spot_entry_price)`.
- Perpetual PnL: `perp_quantity × (perp_mark − perp_entry_price)`.
- Funding cash flow: `−perp_quantity × funding_mark × funding_rate`.
- Perpetual collateral after the scenario: initial isolated collateral plus
  perpetual PnL and funding. Spot profit never tops up isolated collateral.
- Account equity after the scenario includes free cash outside the stressed
  group, the spot leg, isolated collateral, perpetual PnL and funding, minus
  estimated exit costs. The registered strategies stress one group at a time;
  the cash-only baseline carries its full initial equity as free cash.
- Stress shortfall: `max(0, maintenance_requirement − collateral_after_scenario
  + estimated_perpetual_close_cost)`.

Positive funding means longs pay shorts. A short perpetual therefore receives
positive funding and pays when the rate is negative. Fees and slippage are
declared in basis points. They are stress assumptions, not a reconstruction of
historical fills.

## Partial execution

Spot and perpetual fills are applied independently. The output records each
leg's status, remaining signed quantities, net BTC delta, gross exposure,
updated cash and fees. If a fill leaves residual delta, the model emits a
`close_group_simulation` target for review. It sends no live order and does not
assume that the other leg can be rolled back atomically.

After both legs are flat, the research ledger can sweep the group's positive
remaining collateral back to free cash. A sweep is rejected while either leg
is open. Closed spot or perpetual fills update average execution basis and
realize PnL; perpetual PnL stays in the isolated collateral balance.

## Scenarios

The research run reports a base case, a 20% price gap, adverse basis expansion,
negative funding, spot unavailability, slippage at 1/5/15 bps, and a spot fill
whose perpetual hedge times out. Every scenario records its input values,
result, and model limitations. The maintenance ratio is explicitly stated as a
stress input; the result must not be presented as an actual liquidation price.

## Limits

- Spot and perpetual positions use isolated collateral; cross-margin and
  portfolio offsets are not modeled.
- Candle data cannot reveal the intrabar order of price moves or realistic
  execution during a gap.
- Historical exchange maintenance brackets and liquidation fees are unavailable
  in this snapshot.
- Partial-fill actions are simulated targets, not an operational recovery
  guarantee.
