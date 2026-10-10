# Crypto Research Workbench

The local Streamlit page visualizes the already-frozen BTC carry campaign. It is
read-only: selecting a trial or date range does not run research, alter a ledger,
or consume the one-time holdout again.

## Install and start

From the project root in PowerShell:

```powershell
uv pip install --python .venv/Scripts/python.exe --requirement requirements-crypto-ui.lock --require-hashes
.\.venv\Scripts\python.exe -m streamlit run crypto/ui/app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Streamlit is pinned in the UI-specific lock file;
the crypto research lock remains separate.

## Final integrated view

The first row summarizes the consumed holdout, the saved AI report status, and
the on-chain evidence status. The page has three tabs: **策略回测**, **AI 研究
报告**, and **链上验证**. The existing trial selector and UTC chart date control
remain read-only.

- **AI 研究报告** displays the fixed `trial-005` development report and its
  metadata. The current provider is `unconfigured`, so the report is a
  deterministic facts-only fallback. It does not contact an LLM and excludes
  the consumed holdout.
- **链上验证** displays the event-processing example and the recorded
  environment checks from `ONCHAIN_SETUP.md`. The sample is explicitly labeled
  `synthetic_fixture` / “不是链上证据”; it does not assert a real pool or RPC
  verification. The tab provides the synthetic JSON and Markdown downloads.
- The application reads saved project-local evidence only. It does not connect
  to an exchange, an RPC endpoint, an LLM provider, or a trading account.

## What the page shows

- The selector switches among the seven completed baseline/stage runs.
- The UTC date control filters the equity and funding charts only. Summary
  metrics and attribution remain the exact full-trial values from the artifact.
- The page shows ledger-based funding cash flows, P&L attribution, the frozen
  campaign's stage comparison, margin audit and registered risk scenarios.
- Download controls return the selected trial JSON, the frozen `facts.json`
  snapshot, its event ledger, and the campaign-wide feasibility audit.
- The AI and on-chain tabs provide their saved report and demonstration
  artifacts separately, with their current evidence status shown beside them.

Each ledger is checked against the SHA-256 recorded in both its standalone
margin audit and campaign feasibility file. Trial identity and market snapshot
must also match; the facts snapshot is checked against the campaign snapshot.
Artifact paths resolving outside the campaign directory are rejected.

## Read the result carefully

The selected `carry_static` holdout returned about 0.39% over 275 daily samples.
Its annualized Sharpe is unstable for a sample shorter than one year. The frozen
candidate also has development observations below the declared isolated-margin
proxy, so the positive development accounting replay is not executable under
that assumption. The margin screen checks hourly observations only; it is not a
historical Binance liquidation model. This workbench is a research artifact,
not a live trading terminal or evidence of future returns.
