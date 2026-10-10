"""Fail-closed preflight for experiments against a localhost Anvil fork."""
from __future__ import annotations

from urllib.parse import urlsplit

from onchain.events import _hash, _integer
from onchain.manifest import validate_manifest


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def validate_local_fork_target(
    endpoint_url: str,
    manifest: dict,
    *,
    observed_chain_id: int,
    observed_block_number: int,
    observed_block_hash: str,
) -> dict:
    """Check a local-only endpoint and exact fork identity without making calls."""
    parsed = urlsplit(endpoint_url) if isinstance(endpoint_url, str) else None
    if (parsed is None or parsed.scheme != "http" or
            parsed.hostname not in _LOOPBACK or parsed.username is not None or
            parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("fork endpoint must be local HTTP without credentials or query data")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("fork endpoint port is invalid") from exc
    if port != 8545:
        raise ValueError("fork endpoint must use the local Anvil port 8545")
    manifest = validate_manifest(manifest)
    if manifest["identity_status"] != "node_verified":
        raise ValueError("fork requires a node-verified manifest")
    chain_id = _integer(observed_chain_id, "observed_chain_id", minimum=1)
    block_number = _integer(observed_block_number, "observed_block_number", minimum=1)
    block_hash = _hash(observed_block_hash, "observed_block_hash")
    if chain_id != manifest["chain_id"]:
        raise ValueError("local fork chain_id does not match manifest")
    if block_number != manifest["block_number"]:
        raise ValueError("local fork block number does not match manifest")
    if block_hash != manifest["block_hash"]:
        raise ValueError("local fork block_hash does not match manifest")
    return {
        "status": "preflight_ok",
        "endpoint_scope": "localhost-only",
        "chain_id": chain_id,
        "fork_block": block_number,
        "block_hash": block_hash,
        "manifest_identity_status": manifest["identity_status"],
    }
