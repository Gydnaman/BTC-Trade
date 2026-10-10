"""Validate fixed EVM experiment identity against observed node metadata."""
from __future__ import annotations

from onchain.manifest import _address, build_manifest, validate_manifest


def validate_experiment(config: dict, chain_metadata: dict) -> dict:
    """Create a manifest only when chain, pool and historical block are verified."""
    if not isinstance(config, dict) or not isinstance(chain_metadata, dict):
        raise ValueError("config and chain_metadata must be objects")
    if "historical_block_available" not in chain_metadata:
        raise RuntimeError("historical block availability is not verified")
    if chain_metadata["historical_block_available"] is not True:
        raise RuntimeError("configured RPC cannot serve the historical block")

    expected = {
        "chain_id": config.get("chain_id"),
        "pool_address": config.get("pool_address"),
        "block_number": config.get("block_number"),
        "block_hash": config.get("block_hash"),
        "fee_tier": config.get("fee_tier"),
    }
    observed = {
        "chain_id": chain_metadata.get("chain_id"),
        "pool_address": chain_metadata.get("pool_address"),
        "block_number": chain_metadata.get("block_number"),
        "block_hash": chain_metadata.get("block_hash"),
        "fee_tier": chain_metadata.get("fee"),
    }
    for field in ("chain_id", "pool_address", "block_number", "block_hash", "fee_tier"):
        left, right = expected[field], observed[field]
        if field in {"pool_address", "block_hash"}:
            if not isinstance(left, str) or not isinstance(right, str):
                raise ValueError(f"{field} is missing from configured/observed identity")
            left, right = left.lower(), right.lower()
        if left != right:
            raise ValueError(f"{field} does not match observed chain metadata")

    tokens = config.get("token_addresses")
    decimals = config.get("decimals")
    if (not isinstance(tokens, list) or len(tokens) != 2 or
            not isinstance(decimals, list) or len(decimals) != 2):
        raise ValueError("token_addresses and decimals must each have two entries")
    for index, (configured_token, configured_decimals) in enumerate(zip(tokens, decimals)):
        field = f"token{index}"
        observed_token = chain_metadata.get(field)
        if _address(configured_token, field) != _address(observed_token, field):
            raise ValueError(f"{field} does not match pool metadata")
        observed_decimals = chain_metadata.get(f"decimals{index}")
        if configured_decimals != observed_decimals:
            raise ValueError(f"decimals{index} does not match token metadata")
    manifest = build_manifest(config)
    manifest["identity_status"] = "node_verified"
    return validate_manifest(manifest)
