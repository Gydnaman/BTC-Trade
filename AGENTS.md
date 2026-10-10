# QuantTrading engineering workflow

User instructions take precedence over these project defaults and skills.

## Skills

Use the installed `backtesting-frameworks` skill when changing data, strategies,
backtesting or research validation. For bug fixes use `systematic-debugging`,
`test-driven-development`, and `verification-before-completion` (from Superpowers).
Resolve skills through the current agent's catalog. If unavailable, follow the
workflow below and disclose the missing skill instead of silently claiming use.

## Engineering loop

1. Reproduce the defect with a small, hand-calculable fixture.
2. Add a regression test and observe the original behavior fail.
3. Fix the cause with a scoped change.
4. Run `python -B -m harness.validate` from the project root.
5. Report evidence, affected contracts, and remaining limitations.

Never accept higher backtest returns as proof of correctness. No network or broker
credentials are needed for engineering tests. Do not silently substitute synthetic
data in research results. Monetary accounting, timestamps, fees, and weight
constraints must have explicit semantics.

## Research loop

Read `program.md` and `docs/HARNESS.md` before running research. Engineering work
may change the evaluator with regression evidence. Strategy research must keep
the evaluator, tests, data and fee contract fixed. Do not mix these two modes.
The initial research runner produces development-only evidence, not validation
or production-readiness verdicts. Full execution semantics and integrated risk
controls remain separate milestones listed in `docs/HARNESS.md`.
