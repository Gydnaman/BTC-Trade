# Crypto Research V0 Baseline

Run date: 2026-10-10. The target folder is not a Git repository, so no branch or commit baseline exists. Existing project files were read-only during this check; implementation adds a new `crypto/` package.

## Runtime

- Default `python` resolves to CPython 3.14.2. Use the bundled CPython 3.12.14 at `C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` for the crypto environment.
- That bundled interpreter has pip 26.2.1, numpy and pandas, but no `pyarrow`, CCXT, or Streamlit before setup.
- Proposed dependencies are isolated in `requirements-crypto.in`; `requirements-crypto.lock` is generated from a dedicated environment after package resolution.
- The app environment exposes no exchange credentials and makes no account or trading requests.

## Existing regression suite

Command: `python -B -m harness.validate --output <workspace>/baseline-validation-312-escalated.json`

Result: **25 tests passed** on CPython 3.12.14, including the crypto config checks. Before this run, the restricted sandbox blocked Python-created files inside randomized `tempfile.TemporaryDirectory` children even when the parent was within the approved project path. The same suite passed after the offline test command was granted one-time unsandboxed execution; this was a runner filesystem boundary, not an application change.

## V0 crypto config contracts

The standalone crypto CLI reads a UTF-8 JSON config and accepts only an audited market-data manifest. It does not call the legacy `main.py` synthetic-data fallback. Costs must be finite and non-negative, the campaign budget is 1–10, and data range timestamps must include timezones. Synthetic data cannot be selected as research input.

Focused command: `python -B -m unittest discover -s tests -p test_crypto_config.py -v`.
