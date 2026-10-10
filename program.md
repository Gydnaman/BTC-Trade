# Bounded strategy research protocol

This is a project-specific workflow inspired by Auto-Quant's separation of strategy
changes and evaluation infrastructure. It does not require or install FreqTrade.

1. Read `docs/HARNESS.md`. Run `python -B -m harness.validate` first.
2. Write a hypothesis, development dataset source/date range, acceptance criteria
   and a budget of at most 10 trials in an experiment note. Keep final holdout
   data separate and do not provide it to this development runner.
3. During a research campaign modify only strategy code/parameters. Treat data,
   evaluator, fees, tests and the campaign contract as fixed. If an engine defect
   appears, stop research and switch explicitly to engineering mode.
4. Execute one candidate using `python -B -m harness.research`. Inspect the full
   return path and costs as well as headline metrics. Record rejected ideas too.
5. After each run, save the hypothesis and interpretation next to its trial JSON.
   Retain prior results. Never delete trials or create a new directory to evade
   the budget. Do not use destructive git resets; use normal scoped edits.
6. Stop at the budget or on an invalid signal/evaluation contract. Report findings
   and remaining uncertainties. Do not run an unlimited loop or promote a result
   to paper/live trading automatically.

The runner is a local cooperation contract, not a sandbox for malicious strategy
code. It fingerprints the evaluator and data and caps successful stored trials;
the human-readable experiment note must also count rejected/error attempts and
other campaigns. A final independent holdout evaluation is not implemented yet.
