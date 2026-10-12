# BTC Strategy Playground Implementation Plan

> Required sub-skill: use executing-plans or subagent-driven-development to execute the checked tasks. Steps use checkbox syntax.

**Goal:** Add a safe, form-based BTC/USDT Carry development backtest to the Streamlit workbench and rewrite README as a beginner's complete project guide.

**Architecture:** Add a standalone exploratory runner that reuses the audited snapshot and existing event-ledger evaluator but writes only beneath results/crypto/playground/ and hard-codes the development split. Add a Streamlit form tab that can work without frozen local artifacts. Rewrite README around the actual two-layer project and a first-run learning path.

**Tech Stack:** Python 3.12, Streamlit, pandas, existing crypto event ledger/research evaluator, unittest.

**Spec:** docs/superpowers/specs/2026-10-12-btc-strategy-playground-design.md

## Global Constraints
- No arbitrary Python, natural-language parsing, account credentials, exchange orders, or API-key requirement.
- Only cash_zero, carry_static, and funding_filter are supported initially.
- Only audited local Binance BTC/USDT snapshots are accepted; never fall back to synthetic market data.
- Interactive runs use the chronological development split only; never touch validation, holdout, or formal campaign registry.
- Preserve the original campaign's frozen semantics and evaluator output contract.
- Label interactive evidence development_only; do not describe it as live-ready or predictive.
- Follow AGENTS.md: add regression coverage and run python -B -m harness.validate.

### Task 1: Strategy playground domain contract
Files:
- Create crypto/playground.py
- Create tests/test_crypto_playground.py
- Test tests/test_crypto_research.py

Interfaces:
- validate_playground_strategy(strategy: str, parameters: dict | None) -> dict
- run_playground(strategy: str, parameters: dict | None = None, *, project_root: str | Path | None = None) -> dict
- Result includes run ID, strategy, normalized parameters, development range, provenance, assumptions, limitations, metrics, attribution, equity series, and artifact paths.

- [x] Write tests for registry, defaults, parameter bounds, unknown fields, and rejected strategies.
- [x] Run focused tests and confirm the intended failure because the playground API is absent.
- [x] Implement strict validation without changing the formal campaign parameter contract.
- [x] Test a controlled audited fixture; prove only split development is used and formal campaign artifacts are untouched.
- [x] Implement isolated artifact writing under results/crypto/playground/<run-id>/.
- [x] Run focused tests and existing crypto research tests.

### Task 2: Streamlit strategy experiment tab
Files:
- Create crypto/ui/playground_tab.py
- Modify crypto/ui/app.py
- Modify tests/test_crypto_ui_app.py
- Create or modify tests/test_crypto_ui_playground.py

- [x] Add failing UI tests for explicit submit, development-only warning, and missing-snapshot feedback.
- [x] Implement strategy selector and applicable numeric parameters.
- [x] Show rule interpretation, period, snapshot identity, metrics, equity curve, and assumptions.
- [x] Keep the form available without frozen campaign artifacts; preserve existing read-only tabs when their artifacts exist.
- [x] Run focused UI tests.

### Task 3: Beginner-first README
Files:
- Modify README.md

- [x] Verify claims and commands against AGENTS.md, docs/HARNESS.md, docs/crypto/RESEARCH_PROTOCOL.md, DATA.md, LEDGER.md, and WORKBENCH.md.
- [x] Rewrite in plain Chinese: project scope, actual vs planned features, system map, finance/crypto glossary, first-time setup, data collection, first experiment, result reading, directory guide, limitations, and learning links.
- [x] Verify every command, link, and claim.

### Task 4: Full verification
Files:
- Review all changed files.

- [x] Run focused test suites.
- [x] Run python -B -m harness.validate from the repository root.
- [x] Inspect diff, check generated/secret files and verify holdout/campaign isolation.
- [x] Report changes, test evidence, and remaining limitations; do not push without a new request.
