"""Build sanitized, reproducible manifests for on-chain experiments."""
from __future__ import annotations

import re


_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")


def _address(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        raise ValueError(f"{field} must be a 20-byte EVM address")
    return value.lower()


def validate_manifest(manifest: dict) -> dict:
    """Validate the public identity fields and reject any secret-bearing URL."""
    required = {
        "schema_version", "identity_status", "chain_id", "pool_address", "token_addresses",
        "decimals", "fee_tier", "block_number", "block_hash",
        "deployment_source", "package_commit", "confirmation_depth",
        "max_event_blocks", "max_batch_blocks",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("manifest fields do not match onchain-manifest-v1")
    if manifest["schema_version"] != "onchain-manifest-v1":
        raise ValueError("manifest schema version is invalid")
    if manifest["identity_status"] not in {"unverified", "node_verified"}:
        raise ValueError("manifest identity_status is invalid")
    for field in ("chain_id", "block_number", "confirmation_depth",
                  "max_event_blocks", "max_batch_blocks"):
        value = manifest[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"manifest.{field} must be a non-negative integer")
    if manifest["chain_id"] < 1 or manifest["block_number"] < 1:
        raise ValueError("manifest chain_id and block_number must be positive")
    if not 1 <= manifest["max_event_blocks"] <= 10_000:
        raise ValueError("manifest.max_event_blocks must be between 1 and 10000")
    if not 1 <= manifest["max_batch_blocks"] <= 1_000:
        raise ValueError("manifest.max_batch_blocks must be between 1 and 1000")
    if manifest["confirmation_depth"] < 1:
        raise ValueError("manifest.confirmation_depth must be positive")
    _address(manifest["pool_address"], "manifest.pool_address")
    tokens = manifest["token_addresses"]
    decimals = manifest["decimals"]
    if not isinstance(tokens, list) or len(tokens) != 2:
        raise ValueError("manifest.token_addresses must contain token0 and token1")
    if not isinstance(decimals, list) or len(decimals) != 2:
        raise ValueError("manifest.decimals must contain token0 and token1 decimals")
    normalized_tokens = [_address(token, "manifest.token_address") for token in tokens]
    if normalized_tokens[0] == normalized_tokens[1]:
        raise ValueError("manifest token addresses must be distinct")
    if normalized_tokens[0] > normalized_tokens[1]:
        raise ValueError("manifest token0/token1 order must follow ascending address order")
    for value in decimals:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 36:
            raise ValueError("token decimals must be integers between 0 and 36")
    if (isinstance(manifest["fee_tier"], bool) or
            not isinstance(manifest["fee_tier"], int) or
            not 0 < manifest["fee_tier"] <= 1_000_000):
        raise ValueError("manifest fee_tier is invalid")
    if not isinstance(manifest["block_hash"], str) or not _HASH.fullmatch(manifest["block_hash"]):
        raise ValueError("manifest.block_hash must be a 32-byte hash")
    if not isinstance(manifest["deployment_source"], str) or not manifest["deployment_source"].startswith("https://"):
        raise ValueError("manifest.deployment_source must be an HTTPS source")
    if not isinstance(manifest["package_commit"], str) or not _COMMIT.fullmatch(manifest["package_commit"]):
        raise ValueError("manifest.package_commit must be a 40-character commit hash")
    return {
        **manifest,
        "pool_address": _address(manifest["pool_address"], "manifest.pool_address"),
        "token_addresses": normalized_tokens,
        "block_hash": manifest["block_hash"].lower(),
        "package_commit": manifest["package_commit"].lower(),
    }


def build_manifest(config: dict) -> dict:
    """Select only reviewed public config fields; RPC endpoints never persist."""
    if not isinstance(config, dict):
        raise ValueError("experiment config must be an object")
    value = {
        "schema_version": "onchain-manifest-v1",
        "identity_status": "unverified",
        "chain_id": config.get("chain_id"),
        "pool_address": config.get("pool_address"),
        "token_addresses": config.get("token_addresses"),
        "decimals": config.get("decimals"),
        "fee_tier": config.get("fee_tier"),
        "block_number": config.get("block_number"),
        "block_hash": config.get("block_hash"),
        "deployment_source": config.get("deployment_source"),
        "package_commit": config.get("package_commit"),
        "confirmation_depth": config.get("confirmation_depth", 64),
        "max_event_blocks": config.get("max_event_blocks", 10_000),
        "max_batch_blocks": config.get("max_batch_blocks", 1_000),
    }
    return validate_manifest(value)
