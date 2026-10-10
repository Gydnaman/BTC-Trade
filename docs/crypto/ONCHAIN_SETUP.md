# On-chain experiment setup

## Status on 2026-10-10

The manifest validator and fixed-identity checks are implemented and covered by local tests. A real pool/block manifest has **not** been created: this Windows host cannot currently run the required chain checks.

Observed on this host:

- `wsl.exe -l -q` fails with `E_ACCESSDENIED`; no usable WSL distribution was returned.
- `anvil` and `forge` are not installed.
- Docker CLI exists, but `docker info` cannot connect to the Linux Engine named pipe.
- The project Python environment has neither `web3` nor `eth_defi` installed.
- No RPC-related environment variable names are configured. No secret values were read or printed.

The candidate scope is Ethereum mainnet (chain ID `1`) and a Uniswap V3 pool. Uniswap's deployment record lists the canonical V3 factory and ties the core/periphery deployments to version `1.0.0`; its pool event interface defines the `Swap` deltas and post-swap price/liquidity fields used by this experiment. These sources establish the protocol reference only. The pool address, token order/decimals, fee tier, deployed code identity, and fixed block/hash still require an RPC read before any real manifest can be accepted.

Until a node is available, test addresses and hashes are synthetic fixtures. They are not a deployment selection and must not be used for analysis or a fork test.

## Resume checklist

1. Start or install a usable WSL distribution and Foundry (`anvil`, `forge`), or start Docker Desktop's Linux Engine and use a pinned Foundry image.
2. Configure a read-only archive RPC URL outside the repository (for example, process environment variable `ONCHAIN_ARCHIVE_RPC_URL`). Do not put it in a manifest, report, prompt, or log.
3. Query `eth_chainId`; select a candidate pool from the official factory; verify `token0`, `token1`, each token's `decimals`, and `fee`; query the chosen historical block and record its returned hash.
4. Resolve the deployed contract's verified source/package to an immutable commit. A package tag alone is not a commit hash.
5. Pass only the public config and observed metadata to `validate_experiment`; if historical state is unavailable or any identity differs, stop and retain the failure status.
6. Pin the validated block for bounded event retrieval and the local Anvil fork. Never send a transaction to a public endpoint.

The current validator has no RPC adapter and does not infer a pool from a symbol or hard-code a moving `latest` block. The event normalizer accepts **already ABI-decoded** `Swap` mappings; it is not an `eth_getLogs` client or raw ABI decoder. `bounded_block_ranges` only creates inclusive request ranges. No live logs were downloaded or compared with transaction receipts. The generated [synthetic demo](../../results/crypto/onchain/synthetic-event-demo.md) is derived from the explicitly synthetic fixture and is not chain evidence. A future RPC adapter must persist only the sanitized manifest returned by the validator.

## References

- [Uniswap V3 deployment addresses and package versions](https://github.com/Uniswap/v3-periphery/blob/main/deploys.md)
- [Uniswap V3 pool event interface](https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolEvents.sol)
