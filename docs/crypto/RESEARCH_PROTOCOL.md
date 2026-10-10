# Bounded BTC carry research protocol

## Question and data

The experiment asks whether a simple BTC spot/perpetual carry baseline remains
economically interesting after explicit fees, slippage, settled funding, and
isolated-margin stress. It uses the audited Binance BTC/USDT and BTC/USDT
perpetual snapshot in `data_cache/crypto/binance-btcusdt`. The snapshot manifest
and each parquet SHA-256 are checked again before every run. Research is blocked
if the files, manifest, or full-table audit no longer match.

The sole accepted price-data gap is the cited one-hour Binance spot outage on
2023-03-24 13:00–14:00 UTC. That hour stays missing, spot orders are blocked
during it, and the prior close is labeled stale. Funding rows preserve their
settlement mark provenance; same-hour mark-candle open values remain labeled as
proxies.

## Split and registered baselines

The date split is chronological and fixed at 60/20/20 UTC days: development,
validation, then a sealed holdout. No shuffling is used. At least 365 calendar
days and 90 holdout days are required.

Only these strategies can execute:

1. `cash_zero`: hold initial cash as a zero-return comparison.
2. `carry_static`: open one fixed-notional spot-long/perpetual-short group and
   close it at the end of the stage.
3. `funding_filter`: hold that hedge only when the most recently settled rate
   exceeds a declared threshold; enter or exit at the next eligible hourly
   open. The default threshold is zero.

No arbitrary user code, LLM-generated strategy, or holdout tuning is allowed.
The first campaign fixes parameters to the registered defaults: 25% of initial
equity allocated to each carry position, 1.0x isolated collateral, and a zero
funding threshold. Parameter sweeps require a separately reviewed campaign.
Fees and slippage come from the campaign config.

## Candidate selection and sealed evaluation

The preregistered selection rule is highest validation total return after the
configured costs, with lower validation maximum drawdown as the tie-breaker;
remaining ties follow the listed baseline order. All three fixed baselines
must each receive exactly one successful development and one validation run,
using the same snapshot, costs, metric code, and default parameters. Freeze
selects the validation winner automatically; a caller cannot nominate a
different candidate. Once frozen, no more development or validation run is
accepted, and holdout evaluation is consumed exactly once, even when execution
fails. The campaign registry records attempts before execution and uses a
hash chain; moving artifact output directories cannot reset the budget.

The hard limit is ten development/validation attempts. This protocol plans six;
unused attempts remain unused. The holdout is a separate, one-time evaluation
after freezing. Do not change strategy, fees, data range, selection rule, or
evaluation code inside an existing campaign.

## Metrics and report

Daily returns use the last UTC equity observation per day. The first return
compares against initial capital so opening fees can produce day-one drawdown.
In a campaign with explicit start/end boundaries, the start-boundary observation
is the baseline and an observation at midnight closes the UTC day just ended;
the exclusive end boundary does not create an extra day.
Maximum drawdown starts from initial equity; CAGR uses the actual elapsed time;
daily Sharpe and volatility are annualized using 365 days. Undefined values
remain null and carry a stated reason.
Maximum drawdown is based on daily closing samples, while average collateral
utilization is weighted by ledger events rather than elapsed time; both bases
are labeled in the structured metrics.

Each run saves a trial JSON, event-ledger CSV, `facts.json`, and `report.md`.
The trial records snapshot/table hashes, evaluator hash, split range,
parameters, costs, assumptions, risk scenarios, and limitations. A report is a
research artifact, not evidence of live profitability or investment advice.
The evaluator fingerprint includes configuration, data, event ordering, gap
policy, ledger, metrics, risk, and reporting code. Research also requires the
config market and documented gap to match the audited manifest. The MVP accepts
only the declared publication-at-close candle availability and
publication-at-settlement funding availability model; later availability is
rejected rather than moved backward in time. Ledger CSV stores nested event
details as JSON so funding-price provenance survives export.

## Known limitations

- Funding rates are known only after settlement; the filter trades later.
- Some settlement mark prices use the same-hour mark-candle open proxy.
- Hourly bars cannot establish intrabar execution, depth, or liquidation.
- Maintenance ratio and fee stresses are declared assumptions, not historical
  exchange settings.
- Risk stress account equity includes uncommitted cash alongside the stressed
  position group's marks, isolated collateral, funding and estimated exit costs.
- Freqtrade's independent spot comparison remains pending until Docker Engine
  is available; it does not validate the combined carry ledger.
