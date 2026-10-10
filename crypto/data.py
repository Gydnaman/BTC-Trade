"""Crypto market-data normalization, coverage audit, and public ingestion."""
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from crypto.manifest import build_manifest
from crypto.gap_policy import is_supported_known_gaps


_PRICE_TABLES = ("spot_ohlcv", "perp_ohlcv", "mark_ohlcv")
_TABLE_NAMES = (*_PRICE_TABLES, "funding")


def _safe_part(value: str) -> str:
    part = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    if not part or part in {".", ".."}:
        raise ValueError("instrument key fields must contain letters or digits")
    return part


def instrument_key(instrument: dict) -> str:
    """Build a stable path-safe key that separates market types."""
    fields = ("exchange", "market_type", "base", "quote", "settlement", "timeframe")
    missing = [field for field in fields if field not in instrument]
    if missing:
        raise ValueError(f"missing instrument fields: {', '.join(missing)}")
    values = [instrument[field] if instrument[field] not in (None, "") else "na"
              for field in fields]
    return "-".join(_safe_part(value) for value in values)


def _timestamp_ms(value, unit: str) -> int:
    if isinstance(value, bool):
        raise ValueError("timestamp must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("timestamp must be an integer") from exc
    if str(value).strip() not in {str(number), f"{number}.0"}:
        raise ValueError("timestamp must be an integer")
    if unit == "ms":
        return number
    if unit == "us":
        if number % 1000:
            raise ValueError("microsecond timestamp must align to a millisecond")
        return number // 1000
    raise ValueError("timestamp_unit must be explicitly ms or us")


def _iso_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _number(value, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _first_value(row: dict, *keys):
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    info = row.get("info")
    if isinstance(info, dict):
        for key in keys:
            if info.get(key) is not None:
                return info[key]
    return None


def normalize_records(records: list, schema: dict) -> list[dict]:
    """Normalize explicitly-unit-tagged CCXT OHLCV or funding records."""
    kind = schema.get("kind")
    unit = schema.get("timestamp_unit")
    if unit not in {"ms", "us"}:
        raise ValueError("timestamp_unit must be explicitly ms or us")
    start_ms, end_ms = int(schema["start_ms"]), int(schema["end_ms"])
    if end_ms <= start_ms:
        raise ValueError("end_ms must be later than start_ms")
    normalized = []

    if kind == "ohlcv":
        interval = int(schema.get("timeframe_ms", 0))
        as_of_ms = int(schema["as_of_ms"])
        if interval <= 0:
            raise ValueError("timeframe_ms must be positive")
        for raw in records:
            if isinstance(raw, dict):
                timestamp = raw.get("timestamp", raw.get("open_time"))
                values = [raw.get(key) for key in ("open", "high", "low", "close", "volume")]
            else:
                if len(raw) < 6:
                    raise ValueError("OHLCV record must have at least six fields")
                timestamp, *values = raw[:6]
            open_ms = _timestamp_ms(timestamp, unit)
            close_ms = open_ms + interval
            if open_ms < start_ms or open_ms >= end_ms or close_ms > as_of_ms:
                continue
            open_price, high, low, close, volume = [
                _number(value, field) for value, field in zip(
                    values, ("open", "high", "low", "close", "volume"))]
            if min(open_price, high, low, close) <= 0 or volume < 0:
                raise ValueError("OHLC prices must be positive and volume non-negative")
            if high < max(open_price, close, low) or low > min(open_price, close, high):
                raise ValueError("OHLC high/low relationship is invalid")
            normalized.append({
                "open_time": _iso_ms(open_ms),
                "close_time": _iso_ms(close_ms),
                "available_time": _iso_ms(close_ms),
                "open": open_price, "high": high, "low": low,
                "close": close, "volume": volume,
            })
        return sorted(normalized, key=lambda row: row["open_time"])

    if kind == "funding":
        for raw in records:
            if not isinstance(raw, dict):
                raise ValueError("funding record must be an object")
            timestamp = _first_value(raw, "fundingTimestamp", "timestamp", "settlementTime")
            rate = _first_value(raw, "fundingRate", "rate")
            mark = _first_value(raw, "markPrice", "mark_price")
            if timestamp is None or rate is None:
                raise ValueError("funding record needs timestamp and rate")
            settlement_ms = _timestamp_ms(timestamp, unit)
            if settlement_ms < start_ms or settlement_ms >= end_ms:
                continue
            rate_value = _number(rate, "funding rate")
            mark_value = (None if mark is None or
                          isinstance(mark, str) and not mark.strip()
                          else _number(mark, "mark price"))
            if mark_value is not None and mark_value <= 0:
                raise ValueError("mark price must be positive")
            settlement = _iso_ms(settlement_ms)
            normalized.append({"settlement_time": settlement,
                               "available_time": settlement,
                               "rate": rate_value, "mark_price": mark_value,
                               "mark_price_source": "funding_endpoint" if
                               mark_value is not None else "missing",
                               "mark_price_is_proxy": False,
                               "mark_price_source_time": None})
        return sorted(normalized, key=lambda row: row["settlement_time"])

    raise ValueError("kind must be ohlcv or funding")


def _parse_iso_ms(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("manifest times must be ISO-8601 strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("manifest times must be timezone-aware")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def time_range_ms(data_config: dict) -> tuple[int, int]:
    """Read the configured half-open data range and convert it to UTC ms."""
    start_ms = _parse_iso_ms(data_config["start"])
    end_ms = _parse_iso_ms(data_config["end"])
    if end_ms <= start_ms:
        raise ValueError("data end must be later than data start")
    return start_ms, end_ms


def resolve_funding_mark_prices(events: list[dict], mark_ohlcv: list[dict],
                                timeframe_ms: int) -> list[dict]:
    """Resolve empty exchange settlement marks from the same candle's open.

    Binance's public funding-history endpoint returns blank markPrice values for
    historical events. A same-hour mark-candle open is a transparent proxy, not
    an exact settlement price; unresolved events remain null for the audit to
    reject rather than borrowing a nearby price.
    """
    if timeframe_ms <= 0:
        raise ValueError("timeframe_ms must be positive")
    bars_by_open = {}
    for row in mark_ohlcv:
        open_ms = _parse_iso_ms(row["open_time"])
        if open_ms in bars_by_open:
            raise ValueError("mark candles contain duplicate open times")
        bars_by_open[open_ms] = row

    resolved = []
    for event in events:
        row = dict(event)
        source = row.get("mark_price_source")
        if source == "funding_endpoint":
            row.setdefault("mark_price_is_proxy", False)
            row.setdefault("mark_price_source_time", None)
        elif source == "missing":
            settlement_ms = _parse_iso_ms(row["settlement_time"])
            candle_open_ms = settlement_ms - settlement_ms % timeframe_ms
            candle = bars_by_open.get(candle_open_ms)
            if candle is not None:
                proxy = _number(candle.get("open"), "mark candle open")
                if proxy <= 0:
                    raise ValueError("mark candle open must be positive")
                row.update({"mark_price": proxy,
                            "mark_price_source": "mark_ohlcv.open_proxy",
                            "mark_price_is_proxy": True,
                            "mark_price_source_time": _iso_ms(candle_open_ms)})
        else:
            raise ValueError("funding mark source must be funding_endpoint or missing")
        resolved.append(row)
    return resolved


def audit_dataset(tables: dict, manifest: dict) -> dict:
    """Audit candle completeness/alignment and discrete funding event integrity."""
    errors, gaps, coverage = [], {}, {}
    try:
        start_ms = _parse_iso_ms(manifest["start"])
        end_ms = _parse_iso_ms(manifest["end"])
        interval = int(manifest["timeframe_ms"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"status": "failed", "errors": [f"invalid manifest: {exc}"],
                "coverage": {}, "gaps": {}}
    if interval <= 0 or end_ms <= start_ms:
        return {"status": "failed", "errors": ["invalid manifest range or timeframe"],
                "coverage": {}, "gaps": {}}
    if (end_ms - start_ms) % interval:
        errors.append("manifest range must align to candle boundaries")
    expected = set(range(start_ms, end_ms, interval))
    known_gap_rows = []
    normalized_gap_declarations = []
    known_gap_inputs = manifest.get("known_gaps", [])
    if not isinstance(known_gap_inputs, list):
        errors.append("known_gaps must be a list")
        known_gap_inputs = []
    for index, gap in enumerate(known_gap_inputs):
        try:
            if not isinstance(gap, dict):
                raise ValueError("must be an object")
            table = gap["table"]
            gap_start = _parse_iso_ms(gap["start"])
            gap_end = _parse_iso_ms(gap["end"])
            reason, source_url = gap["reason"], gap["source_url"]
            if table not in _PRICE_TABLES:
                raise ValueError("table must name a price table")
            if (gap_end <= gap_start or gap_start < start_ms or gap_end > end_ms or
                    gap_start % interval or gap_end % interval):
                raise ValueError("range must be positive, hourly aligned, and inside the manifest")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("reason is required")
            if not isinstance(source_url, str) or not source_url.startswith("https://"):
                raise ValueError("source_url must be HTTPS")
            known_gap_rows.append({"table": table, "start_ms": gap_start,
                                   "end_ms": gap_end, "reason": reason,
                                   "source_url": source_url, "index": index})
            normalized_gap_declarations.append({
                "table": table, "start": _iso_ms(gap_start),
                "end": _iso_ms(gap_end), "reason": reason,
                "source_url": source_url,
            })
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            errors.append(f"invalid known gap {index}: {exc}")

    if not is_supported_known_gaps(normalized_gap_declarations):
        errors.append("known_gaps may contain only the documented Binance spot outage")
        # An invalid declaration must never authorize missing candles, even
        # though the audit is already destined to fail for the bad policy.
        known_gap_rows = []

    def permitted_gap(table, stamp):
        return any(gap["table"] == table and gap["start_ms"] <= stamp < gap["end_ms"]
                   for gap in known_gap_rows)

    price_sets = {}
    funding_proxy_count = 0
    reported_known_gaps = []
    mark_open_prices = {}
    for row in tables.get("mark_ohlcv", []) if isinstance(
            tables.get("mark_ohlcv"), list) else []:
        try:
            mark_open_prices[_parse_iso_ms(row["open_time"])] = _number(
                row["open"], "mark candle open")
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

    for name in _TABLE_NAMES:
        rows = tables.get(name)
        if not isinstance(rows, list) or not rows:
            errors.append(f"{name} is empty or missing")
            gaps[name] = {"count": len(expected) if name in _PRICE_TABLES else 0,
                          "samples": []}
            continue
        field = "open_time" if name in _PRICE_TABLES else "settlement_time"
        stamps = []
        for row in rows:
            try:
                stamp = _parse_iso_ms(row[field])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                errors.append(f"{name} has invalid {field}: {exc}")
                continue
            stamps.append(stamp)
            if name in _PRICE_TABLES:
                try:
                    close_ms = _parse_iso_ms(row["close_time"])
                    available_ms = _parse_iso_ms(row["available_time"])
                    prices = [_number(row[key], key) for key in
                              ("open", "high", "low", "close", "volume")]
                    o, h, l, c, v = prices
                    if close_ms != stamp + interval or available_ms < close_ms:
                        errors.append(f"{name} has inconsistent close/availability time at {row[field]}")
                    if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c, l) or l > min(o, c, h):
                        errors.append(f"{name} has invalid OHLCV values at {row[field]}")
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    errors.append(f"{name} has invalid candle fields: {exc}")
            else:
                try:
                    rate = _number(row["rate"], "funding rate")
                    mark = _number(row["mark_price"], "mark price")
                    available_ms = _parse_iso_ms(row["available_time"])
                    if mark <= 0 or available_ms < stamp:
                        errors.append(f"funding event has invalid mark/availability at {row[field]}")
                    source = row["mark_price_source"]
                    is_proxy = row["mark_price_is_proxy"]
                    if source == "funding_endpoint" and is_proxy is False:
                        if row.get("mark_price_source_time") is not None:
                            errors.append(f"endpoint funding mark has unexpected source time at {row[field]}")
                    elif source == "mark_ohlcv.open_proxy" and is_proxy is True:
                        funding_proxy_count += 1
                        source_ms = _parse_iso_ms(row["mark_price_source_time"])
                        expected_source_ms = stamp - stamp % interval
                        if source_ms != expected_source_ms:
                            errors.append(f"funding mark proxy is not from the same candle at {row[field]}")
                        source_price = mark_open_prices.get(source_ms)
                        if source_price is None or not math.isclose(
                                mark, source_price, rel_tol=0.0, abs_tol=0.0):
                            errors.append(f"funding mark proxy does not match mark_ohlcv open at {row[field]}")
                    else:
                        errors.append(f"funding event has invalid mark-price provenance at {row[field]}")
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    errors.append(f"funding has invalid event fields: {exc}")
        if stamps != sorted(stamps):
            errors.append(f"{name} timestamps are not ordered")
        duplicate_stamps = {stamp for stamp, count in Counter(stamps).items()
                            if count > 1}
        if duplicate_stamps:
            errors.append(f"{name} has {len(duplicate_stamps)} duplicate timestamps")
        if name in _PRICE_TABLES:
            actual = set(stamps)
            price_sets[name] = actual
            missing = sorted(expected - actual)
            outside = actual - expected
            unapproved = [stamp for stamp in missing if not permitted_gap(name, stamp)]
            if unapproved:
                gaps[name] = {"count": len(unapproved),
                              "samples": [_iso_ms(value) for value in unapproved[:100]]}
                errors.append(f"{name} is missing {len(unapproved)} undocumented expected candles")
            if outside:
                errors.append(f"{name} contains {len(outside)} candles outside configured range")
            for declared in (gap for gap in known_gap_rows if gap["table"] == name):
                declared_hours = set(range(declared["start_ms"], declared["end_ms"], interval))
                declared_missing = declared_hours & set(missing)
                present_in_outage = declared_hours & actual
                if present_in_outage:
                    errors.append(f"{name} has source candles inside declared known gap at "
                                  f"{_iso_ms(min(present_in_outage))}")
                if not declared_missing:
                    errors.append(f"known gap {declared['index']} does not match a missing {name} candle")
                elif not present_in_outage:
                    reported_known_gaps.append({
                        "table": name,
                        "start": _iso_ms(declared["start_ms"]),
                        "end": _iso_ms(declared["end_ms"]),
                        "reason": declared["reason"],
                        "source_url": declared["source_url"],
                        "missing_candles": len(declared_missing),
                    })
            coverage[name] = {"first": _iso_ms(min(actual)) if actual else None,
                              "last": _iso_ms(max(actual)) if actual else None,
                              "rows": len(rows),
                              "missing_expected_candles": len(missing)}
        else:
            outside = {stamp for stamp in stamps if stamp < start_ms or stamp >= end_ms}
            if outside:
                errors.append(f"funding contains {len(outside)} events outside configured range")
            unique_sorted = sorted(set(stamps))
            long_gaps = [unique_sorted[index]
                         for index in range(1, len(unique_sorted))
                         if unique_sorted[index] - unique_sorted[index - 1] > 24 * 3_600_000]
            if long_gaps:
                gaps[name] = {"count": len(long_gaps),
                              "samples": [_iso_ms(value) for value in long_gaps[:100]]}
                errors.append(f"funding has {len(long_gaps)} settlement gaps longer than 24 hours; verify source coverage and cadence")
            coverage[name] = {"first": _iso_ms(min(stamps)) if stamps else None,
                              "last": _iso_ms(max(stamps)) if stamps else None,
                              "rows": len(rows)}

    if len(price_sets) == len(_PRICE_TABLES):
        reference = price_sets[_PRICE_TABLES[0]]
        for name in _PRICE_TABLES[1:]:
            for stamp in reference.symmetric_difference(price_sets[name]):
                absent_table = name if stamp in reference else _PRICE_TABLES[0]
                if not permitted_gap(absent_table, stamp):
                    errors.append(f"{name} candle timestamps do not align with spot_ohlcv")
                    break
        common = set.intersection(*(price_sets[name] for name in _PRICE_TABLES))
        coverage["common_price_range"] = {
            "first": _iso_ms(min(common)) if common else None,
            "last": _iso_ms(max(common)) if common else None,
            "candles": len(common),
        }
    else:
        coverage["common_price_range"] = {"first": None, "last": None, "candles": 0}

    return {"status": "audited" if not errors else "failed",
            "errors": errors, "coverage": coverage, "gaps": gaps,
            "known_gaps": reported_known_gaps,
            "funding_mark_price_proxy_count": funding_proxy_count}


def fetch_pages(fetch_page, start_ms: int, end_ms: int, *,
                timeframe_ms: int | None = None, limit: int = 1000,
                max_pages: int = 10000) -> list:
    """Page a CCXT-style endpoint by its explicit millisecond timestamp."""
    if end_ms <= start_ms or limit <= 0 or max_pages <= 0:
        raise ValueError("invalid pagination range, limit, or page budget")
    result, cursor = [], start_ms
    for _ in range(max_pages):
        if cursor >= end_ms:
            return result
        page = fetch_page(cursor, limit)
        if not page:
            return result
        dated = []
        for row in page:
            timestamp = row[0] if not isinstance(row, dict) else row.get(
                "timestamp", row.get("fundingTimestamp", row.get("settlementTime")))
            if timestamp is None:
                raise ValueError("pagination record is missing timestamp")
            dated.append((int(timestamp), row))
        if max(stamp for stamp, _ in dated) < cursor:
            raise RuntimeError("pagination endpoint did not advance past the requested cursor")
        accepted = [(stamp, row) for stamp, row in dated if cursor <= stamp < end_ms]
        result.extend(row for _, row in accepted)
        newest = max(stamp for stamp, _ in dated)
        next_cursor = newest + (timeframe_ms if timeframe_ms is not None else 1)
        if timeframe_ms is not None and timeframe_ms <= 0:
            raise ValueError("timeframe_ms must be positive")
        if next_cursor <= cursor:
            raise RuntimeError("pagination cursor did not advance")
        cursor = next_cursor
    raise RuntimeError("pagination exceeded its page budget")


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8")


def _collect_ohlcv(exchange, symbol: str, start_ms: int, end_ms: int,
                   *, price: str | None = None) -> list:
    params = {"price": price} if price else {}

    def fetch_page(since, limit):
        return exchange.fetch_ohlcv(symbol, "1h", since, limit,
                                    params=params.copy())

    raw = fetch_pages(fetch_page, start_ms, end_ms, timeframe_ms=3_600_000)
    return raw


def collect_snapshot(config: dict) -> dict:
    """Download a public spot/perp/mark/funding snapshot and audit it."""
    import ccxt
    import pandas as pd

    from crypto.config import validate_config

    config = validate_config(config)
    start_ms, end_ms = time_range_ms(config["data"])
    as_of_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    spot_exchange = ccxt.binance({"enableRateLimit": True})
    perp_exchange = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        spot_exchange.load_markets()
        perp_exchange.load_markets()
        markets_retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        spot_symbol, perp_symbol = (config["market"]["spot_symbol"],
                                    config["market"]["perp_symbol"])
        if spot_symbol not in spot_exchange.markets or perp_symbol not in perp_exchange.markets:
            raise ValueError("configured spot or perpetual market is not listed by Binance")
        spot_meta = spot_exchange.market(spot_symbol)
        perp_meta = perp_exchange.market(perp_symbol)
        start_date, end_date = _iso_ms(start_ms), _iso_ms(end_ms)
        raw = {
            "spot_ohlcv": _collect_ohlcv(spot_exchange, spot_symbol, start_ms, end_ms),
            "perp_ohlcv": _collect_ohlcv(perp_exchange, perp_symbol, start_ms, end_ms),
            "mark_ohlcv": _collect_ohlcv(perp_exchange, perp_symbol, start_ms, end_ms,
                                          price="mark"),
        }

        def fetch_funding(since, limit):
            return perp_exchange.fetch_funding_rate_history(perp_symbol, since, limit)

        raw["funding"] = fetch_pages(fetch_funding, start_ms, end_ms, limit=1000)
        interval_ms = 3_600_000
        schemas = {
            name: {"kind": "ohlcv", "timestamp_unit": "ms",
                   "timeframe_ms": interval_ms, "start_ms": start_ms,
                   "end_ms": end_ms, "as_of_ms": as_of_ms}
            for name in _PRICE_TABLES
        }
        schemas["funding"] = {"kind": "funding", "timestamp_unit": "ms",
                              "start_ms": start_ms, "end_ms": end_ms}
        tables = {name: normalize_records(raw[name], schemas[name]) for name in _TABLE_NAMES}
        tables["funding"] = resolve_funding_mark_prices(
            tables["funding"], tables["mark_ohlcv"], interval_ms)
        audit = audit_dataset(tables, {"start": start_date, "end": end_date,
                                       "timeframe_ms": interval_ms,
                                       "known_gaps": config["data"].get("known_gaps", [])})

        data_root = Path(config["data"]["root"])
        data_root.mkdir(parents=True, exist_ok=True)
        instruments = {
            "spot_ohlcv": {"exchange": "binance", "market_type": "spot",
                           "base": spot_meta.get("base"), "quote": spot_meta.get("quote"),
                           "settlement": "", "timeframe": "1h"},
            "perp_ohlcv": {"exchange": "binance", "market_type": "linear_perpetual",
                           "base": perp_meta.get("base"), "quote": perp_meta.get("quote"),
                           "settlement": perp_meta.get("settle"), "timeframe": "1h"},
            "mark_ohlcv": {"exchange": "binance", "market_type": "linear_perpetual-mark",
                           "base": perp_meta.get("base"), "quote": perp_meta.get("quote"),
                           "settlement": perp_meta.get("settle"), "timeframe": "1h"},
        }
        table_files = {}
        source_files = {}
        for name in _PRICE_TABLES:
            stem = instrument_key(instruments[name])
            table_path = data_root / f"{stem}.parquet"
            source_path = data_root / f"{stem}.source.json"
            pd.DataFrame(tables[name]).to_parquet(table_path, index=False)
            _write_json(source_path, raw[name])
            table_files[name] = str(table_path)
            source_files[f"{name}_source_records"] = str(source_path)
        funding_path = data_root / "binance-usdm-btcusdt-funding.parquet"
        funding_source = data_root / "binance-usdm-btcusdt-funding.source.json"
        pd.DataFrame(tables["funding"]).to_parquet(funding_path, index=False)
        _write_json(funding_source, raw["funding"])
        table_files["funding"] = str(funding_path)
        source_files["funding_source_records"] = str(funding_source)

        market_metadata = {
            "markets_retrieved_at": markets_retrieved_at,
            "spot": {key: spot_meta.get(key) for key in ("symbol", "precision", "limits", "active")},
            "perpetual": {key: perp_meta.get(key) for key in ("symbol", "precision", "limits", "active")},
            "warning": "These are current market rules captured at retrieval time, not historical precision or leverage tiers.",
        }
        manifest = build_manifest(config, tables, table_files, audit,
                                  market_metadata, source_files=source_files)
        manifest_path = data_root / "manifest.json"
        _write_json(manifest_path, manifest)
        return {"manifest": manifest, "manifest_path": str(manifest_path),
                "table_paths": table_files, "source_paths": source_files}
    finally:
        spot_exchange.close()
        perp_exchange.close()
