"""Content hashes and provenance for collected crypto market data."""
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(config: dict, tables: dict, table_files: dict,
                   audit: dict, market_metadata: dict,
                   retrieved_at: str | None = None,
                   source_files: dict | None = None) -> dict:
    """Create a reproducible, JSON-compatible snapshot manifest."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z")
    table_meta = {}
    for name, path in sorted(table_files.items()):
        rows = tables.get(name, [])
        timestamps = []
        time_field = "settlement_time" if name == "funding" else "open_time"
        for row in rows:
            if row.get(time_field) is not None:
                timestamps.append(row[time_field])
        table_meta[name] = {
            "path": Path(path).name,
            "sha256": sha256_file(str(path)),
            "row_count": len(rows),
            "first_time": min(timestamps) if timestamps else None,
            "last_time": max(timestamps) if timestamps else None,
        }
    source_meta = {
        name: {"path": Path(path).name, "sha256": sha256_file(str(path))}
        for name, path in sorted((source_files or {}).items())
    }
    try:
        ccxt_version = version("ccxt")
    except PackageNotFoundError:
        ccxt_version = "unavailable"
    fingerprint = json.dumps({"config": config, "tables": table_meta,
                              "source_records": source_meta},
                             sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
    snapshot_id = hashlib.sha256(fingerprint).hexdigest()[:20]
    return {
        "schema_version": "crypto-snapshot-v1",
        "snapshot_id": snapshot_id,
        "status": "audited" if audit.get("status") == "audited" else "failed",
        "source": "Binance public market-data API via CCXT",
        "retrieved_at": retrieved_at,
        "config": config,
        "known_gaps": audit.get("known_gaps", []),
        "tables": table_meta,
        "source_records": source_meta,
        "audit": audit,
        "market_rules": market_metadata,
        "market_rules_are_current_snapshot": True,
        "availability_model": {
            "ohlcv": "Assumed available at candle close; historical publication time is not archived.",
            "funding": "Settled rate is available only after settlement; strategy entry is delayed to a later full-hour open.",
        },
        "funding_mark_pricing": {
            "endpoint_mark_price_rows": sum(
                row.get("mark_price_source") == "funding_endpoint"
                for row in tables.get("funding", [])),
            "mark_ohlcv_open_proxy_rows": audit.get(
                "funding_mark_price_proxy_count", 0),
            "proxy_rule": "When Binance funding history has blank markPrice, use the open of the mark-price candle whose UTC hour contains the settlement timestamp.",
            "proxy_is_exact_settlement_price": False,
        },
        "software": {"ccxt": ccxt_version},
    }
