"""Normalize, audit and summarize bounded EVM pool Swap logs."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re

from onchain.manifest import validate_manifest


_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{field} must be a 32-byte hash")
    return value.lower()


def _decimal_text(value: Decimal) -> str:
    if not value:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("retrieved_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("retrieved_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_identity(row: dict) -> tuple[int, str, int, str]:
    # A re-included transaction may emit the same log index in a different block.
    required = {
        "chain_id", "transaction_hash", "log_index", "block_hash", "pool_address",
        "block_number", "transaction_index", "amount0", "amount1", "sqrt_price_x96",
        "liquidity", "tick",
    }
    if not required.issubset(row):
        raise ValueError("row event identity or decoded Swap fields are incomplete")
    return (
        _integer(row["chain_id"], "chain_id", minimum=1),
        _hash(row["transaction_hash"], "transaction_hash"),
        _integer(row["log_index"], "log_index", minimum=0),
        _hash(row["block_hash"], "block_hash"),
    )


def _same_log(left: dict, right: dict) -> bool:
    fields = (
        "chain_id", "pool_address", "block_number", "block_hash",
        "transaction_hash", "transaction_index", "log_index", "amount0",
        "amount1", "sqrt_price_x96", "liquidity", "tick",
    )
    return all(left[field] == right[field] for field in fields)


def normalize_logs(logs: list[dict], manifest: dict) -> list[dict]:
    """Normalize already ABI-decoded Swap events; identical tx/logs deduplicate."""
    manifest = validate_manifest(manifest)
    if not isinstance(logs, list):
        raise ValueError("logs must be a list")
    rows: dict[tuple[int, str, int], dict] = {}
    for raw in logs:
        if not isinstance(raw, dict) or raw.get("event") != "Swap":
            raise ValueError("each log must be a decoded Swap event")
        chain_id = _integer(raw.get("chain_id"), "chain_id", minimum=1)
        if chain_id != manifest["chain_id"]:
            raise ValueError("log chain_id does not match manifest")
        pool = raw.get("pool_address")
        if not isinstance(pool, str) or pool.lower() != manifest["pool_address"]:
            raise ValueError("log pool_address does not match manifest")
        block_number = _integer(raw.get("block_number"), "block_number", minimum=1)
        transaction_index = _integer(raw.get("transaction_index"), "transaction_index", minimum=0)
        log_index = _integer(raw.get("log_index"), "log_index", minimum=0)
        transaction_hash = _hash(raw.get("transaction_hash"), "transaction_hash")
        amount0 = _integer(raw.get("amount0"), "amount0")
        amount1 = _integer(raw.get("amount1"), "amount1")
        sqrt_price_x96 = _integer(raw.get("sqrt_price_x96"), "sqrt_price_x96", minimum=1)
        liquidity = _integer(raw.get("liquidity"), "liquidity", minimum=0)
        tick = _integer(raw.get("tick"), "tick")
        if not -(2**255) <= amount0 < 2**255 or not -(2**255) <= amount1 < 2**255:
            raise ValueError("Swap amount exceeds int256 range")
        if sqrt_price_x96 >= 2**160:
            raise ValueError("sqrt_price_x96 exceeds uint160 range")
        if liquidity >= 2**128:
            raise ValueError("liquidity exceeds uint128 range")
        if not -(2**23) <= tick < 2**23:
            raise ValueError("tick exceeds int24 range")
        row = {
            "chain_id": chain_id,
            "block_number": block_number,
            "block_hash": _hash(raw.get("block_hash"), "block_hash"),
            "transaction_hash": transaction_hash,
            "transaction_index": transaction_index,
            "log_index": log_index,
            "pool_address": manifest["pool_address"],
            "amount0": amount0,
            "amount1": amount1,
            "sqrt_price_x96": sqrt_price_x96,
            "liquidity": liquidity,
            "tick": tick,
            "retrieved_at": _timestamp(raw.get("retrieved_at")),
            "duplicate_copies": 0,
        }
        with localcontext() as context:
            context.prec = 120
            row["amount0_units"] = _decimal_text(
                Decimal(row["amount0"]).scaleb(-manifest["decimals"][0]))
            row["amount1_units"] = _decimal_text(
                Decimal(row["amount1"]).scaleb(-manifest["decimals"][1]))
        key = _event_identity(row)
        existing = rows.get(key)
        if existing is not None:
            if not _same_log(existing, row):
                raise ValueError("conflicting duplicate transaction/log identity")
            existing["duplicate_copies"] += 1
            if row["retrieved_at"] < existing["retrieved_at"]:
                existing["retrieved_at"] = row["retrieved_at"]
            continue
        rows[key] = row
    return sorted(rows.values(), key=lambda row: (
        row["block_number"], row["transaction_index"], row["log_index"],
    ))


def _validated_range(
    block_range: tuple[int, int], *, maximum_blocks: int = 10_000,
) -> tuple[int, int]:
    if not isinstance(block_range, (tuple, list)) or len(block_range) != 2:
        raise ValueError("block_range must contain inclusive start and end blocks")
    start = _integer(block_range[0], "range start", minimum=1)
    end = _integer(block_range[1], "range end", minimum=start)
    if end - start + 1 > maximum_blocks:
        raise ValueError("requested event range exceeds manifest limit")
    return start, end


def bounded_block_ranges(start: int, end: int, manifest: dict) -> list[tuple[int, int]]:
    """Split an inclusive eth_getLogs range under both manifest bounds."""
    manifest = validate_manifest(manifest)
    start, end = _validated_range((start, end), maximum_blocks=manifest["max_event_blocks"])
    size = manifest["max_batch_blocks"]
    return [
        (batch_start, min(batch_start + size - 1, end))
        for batch_start in range(start, end + 1, size)
    ]


def audit_logs(
    rows: list[dict],
    canonical_blocks: dict[int, str],
    *,
    block_range: tuple[int, int] | None = None,
) -> dict:
    """Deduplicate, identify uncovered heights and discard logs orphaned by reorgs."""
    if not isinstance(rows, list) or not isinstance(canonical_blocks, dict):
        raise ValueError("rows and canonical_blocks must be list and mapping")
    normalized_hashes = {}
    for height, block_hash in canonical_blocks.items():
        height = _integer(height, "canonical block number", minimum=1)
        normalized_hashes[height] = _hash(block_hash, f"canonical hash at {height}")
    if block_range is None:
        if not normalized_hashes:
            raise ValueError("block_range is required when no canonical block hashes were supplied")
        block_range = (min(normalized_hashes), max(normalized_hashes))
    start, end = _validated_range(block_range)
    missing = [height for height in range(start, end + 1) if height not in normalized_hashes]
    unique: dict[tuple[int, str, int], dict] = {}
    duplicate_count = 0
    reorged = []
    canonical_rows = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("audited rows must be objects")
        key = _event_identity(row)
        existing = unique.get(key)
        if existing is not None:
            if not _same_log(existing, row):
                raise ValueError("conflicting duplicate transaction/log identity")
            duplicate_count += 1
            continue
        unique[key] = row
        duplicate_count += _integer(row.get("duplicate_copies", 0), "duplicate_copies", minimum=0)
        height = _integer(row.get("block_number"), "block_number", minimum=1)
        if not start <= height <= end:
            raise ValueError("log block is outside the audited query range")
        canonical_hash = normalized_hashes.get(height)
        if canonical_hash is None:
            continue
        row_hash = _hash(row.get("block_hash"), "row.block_hash")
        if row_hash != canonical_hash:
            reorged.append({
                "transaction_hash": row["transaction_hash"],
                "log_index": row["log_index"],
                "block_number": height,
                "orphaned_block_hash": row_hash,
                "canonical_block_hash": canonical_hash,
            })
            continue
        if start <= height <= end:
            canonical_rows.append(row)
    canonical_rows.sort(key=lambda row: (
        row["block_number"], row["transaction_index"], row["log_index"],
    ))
    status = "incomplete" if missing else ("reorg_detected" if reorged else "ok")
    return {
        "status": status,
        "block_range": [start, end],
        "canonical_block_count": len(normalized_hashes),
        "missing_blocks": missing,
        "duplicate_count": duplicate_count,
        "reorged_rows_count": len(reorged),
        "reorged_rows": reorged,
        "canonical_rows": canonical_rows,
    }


def summarize_pool(audit: dict, manifest: dict, *, source_status: str) -> dict:
    """Summarize only complete, audited canonical Swap rows."""
    manifest = validate_manifest(manifest)
    if source_status not in {"synthetic_fixture", "rpc_verified"}:
        raise ValueError("source_status must be synthetic_fixture or rpc_verified")
    if source_status == "rpc_verified" and manifest["identity_status"] != "node_verified":
        raise ValueError("rpc_verified source requires a node-verified manifest")
    if not isinstance(audit, dict) or audit.get("status") not in {"ok", "reorg_detected"}:
        raise ValueError("cannot summarize incomplete block coverage")
    if audit.get("missing_blocks") != [] or not isinstance(audit.get("canonical_rows"), list):
        raise ValueError("cannot summarize incomplete block coverage")
    token0_volume = Decimal(0)
    token1_volume = Decimal(0)
    token0_net = Decimal(0)
    token1_net = Decimal(0)
    prices = []
    liquidity = []
    with localcontext() as context:
        context.prec = 120
        for row in audit["canonical_rows"]:
            if (row.get("chain_id") != manifest["chain_id"] or
                    row.get("pool_address") != manifest["pool_address"]):
                raise ValueError("audited row identity does not match manifest")
            raw0 = _integer(row.get("amount0"), "amount0")
            raw1 = _integer(row.get("amount1"), "amount1")
            amount0 = Decimal(raw0).scaleb(-manifest["decimals"][0])
            amount1 = Decimal(raw1).scaleb(-manifest["decimals"][1])
            token0_volume += abs(amount0)
            token1_volume += abs(amount1)
            token0_net += amount0
            token1_net += amount1
            sqrt_price_x96 = _integer(row.get("sqrt_price_x96"), "sqrt_price_x96", minimum=1)
            price = ((Decimal(sqrt_price_x96) ** 2) / Decimal(2**192)
                     * (Decimal(10) ** (manifest["decimals"][0] - manifest["decimals"][1])))
            prices.append({
                "block_number": row["block_number"],
                "transaction_hash": row["transaction_hash"],
                "token1_per_token0": _decimal_text(price),
                "tick": row["tick"],
            })
            liquidity.append({
                "block_number": row["block_number"],
                "transaction_hash": row["transaction_hash"],
                "liquidity_raw": row["liquidity"],
            })
    limitations = [
        "Swap deltas are pool-side token balance changes, not trader profit.",
        "A Swap-event price is an observation, not an executable quote.",
        "Gross flow sums absolute pool-side deltas and is not unique trader volume.",
        "Block finality depends on the declared confirmation depth and node canonical hashes.",
    ]
    if source_status == "synthetic_fixture":
        limitations.append("Synthetic engineering fixture only; it is not on-chain evidence.")
    return {
        "status": audit["status"],
        "identity_status": manifest["identity_status"],
        "source_status": source_status,
        "block_range": audit["block_range"],
        "canonical_block_count": audit["canonical_block_count"],
        "swap_count": len(audit["canonical_rows"]),
        "duplicate_count": audit.get("duplicate_count", 0),
        "reorged_rows_count": audit.get("reorged_rows_count", 0),
        "gross_token0_volume": _decimal_text(token0_volume),
        "gross_token1_volume": _decimal_text(token1_volume),
        "net_token0_delta": _decimal_text(token0_net),
        "net_token1_delta": _decimal_text(token1_net),
        "price_observations": prices,
        "liquidity_observations": liquidity,
        "limitations": limitations,
    }
