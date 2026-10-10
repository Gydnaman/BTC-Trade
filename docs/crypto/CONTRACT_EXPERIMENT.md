# Fixed-block contract experiment

## Status on 2026-10-10

The local-target preflight is implemented and tested. It accepts only HTTP loopback on the default Anvil port, requires a `node_verified` manifest, and compares the observed chain ID, fixed block number, and block hash. The check does not start Anvil or issue RPC requests.

The host has no usable WSL distribution or Anvil binary, and Docker's Linux Engine is not running. Therefore the approve/swap/revert integration test was **not run**. There are no receipts, gas measurements, token-balance deltas, or contract-call results to report. This is an environment block, not a passing test or a skipped integration success.

## Intended experiment once the local fork is available

1. Start Anvil against a read-only archive RPC at the block pinned in the verified manifest. Keep the endpoint local and do not expose the RPC URL in command output or saved artifacts.
2. Use a deterministic fork account with test balances only; never load a user's wallet or private key.
3. Verify the pool and token contracts at the fork block, then test the intended router path with a small exact-input amount.
4. Assert allowance after approval, input and output balances after a successful swap, and a revert when `amountOutMinimum` is intentionally unreachable.
5. Revoke allowance and confirm a subsequent swap cannot proceed. Record receipts and gas from the local fork only.

The code currently contains only a fail-closed fork-target validator. It does not implement the router calls or claim that a local swap proves historical execution quality, MEV resistance, or profitability. Uniswap's pool interface documents the pool `Swap` event and its post-swap state fields; router execution and user allowance are separate behaviors that still need the local integration test.

See [environment setup and current blocker](ONCHAIN_SETUP.md).
