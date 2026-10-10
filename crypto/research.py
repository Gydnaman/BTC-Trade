"""Bounded BTC carry experiments with an immutable, one-use holdout."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from bisect import bisect_right
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re

import pandas as pd

from crypto.config import validate_config
from crypto.data import audit_dataset
from crypto.gap_policy import SUPPORTED_KNOWN_GAP
from crypto.ledger import replay_events
from crypto.manifest import sha256_file
from crypto.metrics import evaluate_metrics
from crypto.report import build_report
from crypto.risk import apply_execution_result, assess_group


REGISTERED_STRATEGIES = {
    "cash_zero": "Hold initial cash with zero return.",
    "carry_static": "Open one fixed-notional spot/perpetual hedge and hold it.",
    "funding_filter": "Hold the hedge only when the most recently settled funding rate exceeds a threshold.",
}
_VALID_STAGES = {"development", "validation", "holdout"}
_HOUR_MS = 3_600_000
_INITIAL_COLLATERAL_RATIO = 1.0
_DEFAULT_ALLOCATION_FRACTION = 0.25
_SELECTION_POLICY = "highest_validation_total_return_then_lowest_drawdown"
_BASELINE_PARAMETERS = {
    "cash_zero": {},
    "carry_static": {"allocation_fraction": _DEFAULT_ALLOCATION_FRACTION,
                     "collateral_ratio": _INITIAL_COLLATERAL_RATIO},
    "funding_filter": {"allocation_fraction": _DEFAULT_ALLOCATION_FRACTION,
                       "collateral_ratio": _INITIAL_COLLATERAL_RATIO,
                       "positive_funding_threshold": 0.0},
}


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _time(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


def _clean_records(frame):
    records = []
    for source in frame.to_dict(orient="records"):
        row = {}
        for key, value in source.items():
            if pd.isna(value):
                row[key] = None
            elif isinstance(value, (datetime, pd.Timestamp)):
                row[key] = _iso(value.to_pydatetime() if isinstance(value, pd.Timestamp)
                                else value)
            else:
                row[key] = value.item() if hasattr(value, "item") else value
        records.append(row)
    return records


def _load_snapshot(config: dict) -> dict:
    """Read and re-audit every table after verifying manifest SHA-256 values."""
    root = Path(config["data"]["root"]).resolve()
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("audited market-data manifest is unavailable or invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "audited":
        raise ValueError("research requires a manifest with audited status")
    saved_config = manifest.get("config")
    if not isinstance(saved_config, dict):
        raise ValueError("snapshot manifest is missing its source configuration")
    try:
        saved_config = validate_config(saved_config)
    except ValueError as exc:
        raise ValueError(f"snapshot source configuration is invalid: {exc}") from exc
    for field in ("start", "end", "timeframe"):
        if saved_config["data"].get(field) != config["data"].get(field):
            raise ValueError("research config range must match the audited snapshot")
    if saved_config["market"] != config["market"]:
        raise ValueError("research market does not match the audited snapshot")
    if saved_config["data"].get("known_gaps", []) != config["data"].get(
            "known_gaps", []):
        raise ValueError("research gap policy must match the audited snapshot")

    tables, table_hashes = {}, {}
    table_meta = manifest.get("tables", {})
    for name in ("spot_ohlcv", "perp_ohlcv", "mark_ohlcv", "funding"):
        meta = table_meta.get(name)
        if not isinstance(meta, dict) or not isinstance(meta.get("path"), str):
            raise ValueError(f"snapshot is missing {name} metadata")
        if Path(meta["path"]).name != meta["path"]:
            raise ValueError(f"snapshot {name} path must be a local file name")
        path = (root / meta["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"snapshot {name} path escapes its data root") from exc
        if not path.is_file():
            raise ValueError(f"snapshot table {name} is missing")
        actual_hash = sha256_file(str(path))
        if actual_hash != meta.get("sha256"):
            raise ValueError(f"snapshot table {name} SHA-256 does not match manifest")
        try:
            tables[name] = _clean_records(pd.read_parquet(path))
        except Exception as exc:
            raise ValueError(f"snapshot table {name} could not be read") from exc
        table_hashes[name] = actual_hash

    source_config = saved_config["data"]
    audit_manifest = {"start": source_config["start"], "end": source_config["end"],
                      "timeframe_ms": _HOUR_MS,
                      "known_gaps": source_config.get("known_gaps", [])}
    audit = audit_dataset(tables, audit_manifest)
    if audit.get("status") != "audited":
        raise ValueError("snapshot tables failed research-time audit: " +
                         "; ".join(audit.get("errors", [])))
    _assert_research_availability(tables)
    return {"manifest": manifest, "manifest_path": str(manifest_path.resolve()),
            "tables": tables, "table_hashes": table_hashes, "audit": audit}


def _assert_research_availability(tables: dict) -> None:
    """Fail closed unless observed times match the declared MVP availability model."""
    for name in ("spot_ohlcv", "perp_ohlcv", "mark_ohlcv"):
        for row in tables.get(name, []):
            if _time(row["available_time"], f"{name}.available_time") != _time(
                    row["close_time"], f"{name}.close_time"):
                raise ValueError(
                    f"{name} research requires publication-at-close availability")
    for row in tables.get("funding", []):
        if _time(row["available_time"], "funding.available_time") != _time(
                row["settlement_time"], "funding.settlement_time"):
            raise ValueError(
                "funding research requires publication-at-settlement availability")


def _split_dates(config: dict) -> dict:
    start = _time(config["data"]["start"], "data.start")
    end = _time(config["data"]["end"], "data.end")
    if start.time() != datetime.min.time() or end.time() != datetime.min.time():
        raise ValueError("research split requires UTC-midnight date boundaries")
    total_days = (end.date() - start.date()).days
    dev_days = int(total_days * 0.6)
    validation_days = int(total_days * 0.2)
    dev_end = start + timedelta(days=dev_days)
    validation_end = dev_end + timedelta(days=validation_days)
    holdout_days = (end - validation_end).days
    if total_days < 365 or holdout_days < 90:
        raise ValueError("data range must cover at least 365 days and holdout at least 90 days")
    return {
        "policy": "chronological 60/20/20 UTC dates; no shuffle",
        "development": {"start": _iso(start), "end": _iso(dev_end)},
        "validation": {"start": _iso(dev_end), "end": _iso(validation_end)},
        "holdout": {"start": _iso(validation_end), "end": _iso(end)},
        "development_days": dev_days, "validation_days": validation_days,
        "holdout_days": holdout_days,
    }


def _evaluator_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    names = ("crypto/config.py", "crypto/data.py", "crypto/events.py",
             "crypto/gap_policy.py", "crypto/ledger.py", "crypto/manifest.py",
             "crypto/metrics.py", "crypto/research.py", "crypto/report.py",
             "crypto/risk.py")
    content = bytearray()
    for name in names:
        path = root / name
        content.extend(name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return _sha256(bytes(content))


def _contract(config: dict, snapshot: dict, split: dict) -> dict:
    campaign = config["campaign"]
    snapshot_market = snapshot.get("manifest", {}).get("config", {}).get("market")
    if snapshot_market != config["market"]:
        raise ValueError("research market does not match the audited snapshot")
    selection_policy = campaign.get("selection_policy", _SELECTION_POLICY)
    if selection_policy != _SELECTION_POLICY:
        raise ValueError("selection_policy must use the preregistered campaign rule")
    table_hashes = snapshot.get("table_hashes")
    if not isinstance(table_hashes, dict):
        table_hashes = {
            name: meta.get("sha256")
            for name, meta in snapshot.get("manifest", {}).get("tables", {}).items()
            if isinstance(meta, dict) and isinstance(meta.get("sha256"), str)
        }
    required_tables = {"spot_ohlcv", "perp_ohlcv", "mark_ohlcv", "funding"}
    if not required_tables.issubset(table_hashes):
        raise ValueError("snapshot contract requires SHA-256 hashes for all market tables")
    value = {
        "schema_version": "crypto-campaign-contract-v1",
        "campaign_id": campaign.get("campaign_id", "btc-carry-main"),
        "snapshot_id": snapshot["manifest"].get("snapshot_id"),
        "table_sha256": table_hashes,
        "data_range": {"start": config["data"]["start"],
                       "end": config["data"]["end"]},
        "market": config["market"],
        "costs": config["costs"],
        "initial_equity": campaign["initial_equity"],
        "cash_return_assumption_annual": campaign.get(
            "cash_return_assumption_annual", 0),
        "selection_policy": selection_policy,
        "known_gaps": config["data"].get("known_gaps", []),
        "max_attempts": campaign["max_attempts"],
        "split": split,
        "evaluator_sha256": _evaluator_hash(),
        "python": platform.python_version(),
    }
    value["contract_sha256"] = _sha256(_canonical_bytes(value))
    return value


def _campaign_paths(config: dict) -> tuple[Path, str]:
    campaign = config.get("campaign", {})
    campaign_id = campaign.get("campaign_id", "btc-carry-main")
    if not isinstance(campaign_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", campaign_id):
        raise ValueError("campaign_id must be a 2–64 character path-safe identifier")
    registry_root = Path(campaign.get("registry_root", "results/crypto/campaign-registry"))
    if not registry_root.is_absolute():
        registry_root = Path.cwd() / registry_root
    return registry_root.resolve() / campaign_id, campaign_id


def _read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result, previous_hash = [], "0" * 64
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
            event_hash = event.pop("event_sha256")
            stored_previous = event.pop("previous_sha256")
        except (ValueError, KeyError) as exc:
            raise ValueError(f"campaign registry is corrupt at line {line_number}") from exc
        if stored_previous != previous_hash:
            raise ValueError(f"campaign registry hash chain is broken at line {line_number}")
        expected = _sha256(previous_hash.encode("ascii") + b"\n" + _canonical_bytes(event))
        if event_hash != expected:
            raise ValueError(f"campaign registry hash is invalid at line {line_number}")
        result.append(event)
        previous_hash = event_hash
    return result


def _append_event(path: Path, event: dict) -> dict:
    events = _read_events(path)
    previous_hash = "0" * 64
    if path.exists() and path.stat().st_size:
        last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        previous_hash = last["event_sha256"]
    payload = dict(event)
    payload["previous_sha256"] = previous_hash
    payload["event_sha256"] = _sha256(previous_hash.encode("ascii") + b"\n" +
                                      _canonical_bytes(event))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return payload


def _locked(registry_dir: Path):
    registry_dir.mkdir(parents=True, exist_ok=True)
    lock = registry_dir / ".running"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("campaign is busy; inspect the registry lock after interruption") from exc
    handle.write(f"pid={os.getpid()}\n")
    handle.close()
    return lock


def _validate_strategy(strategy: str, parameters: dict) -> dict:
    if strategy not in REGISTERED_STRATEGIES:
        raise ValueError("strategy must be a registered baseline")
    if not isinstance(parameters, dict):
        raise ValueError("strategy parameters must be an object")
    allowed = {"cash_zero": set(),
               "carry_static": {"allocation_fraction", "collateral_ratio"},
               "funding_filter": {"allocation_fraction", "collateral_ratio",
                                  "positive_funding_threshold"}}[strategy]
    unknown = set(parameters) - allowed
    if unknown:
        raise ValueError(f"unregistered strategy parameters: {', '.join(sorted(unknown))}")
    normalized = dict(parameters)
    if strategy != "cash_zero":
        allocation = float(normalized.get("allocation_fraction", _DEFAULT_ALLOCATION_FRACTION))
        collateral = float(normalized.get("collateral_ratio", _INITIAL_COLLATERAL_RATIO))
        if not math.isfinite(allocation) or not 0 < allocation <= 0.5:
            raise ValueError("allocation_fraction must be in (0, 0.5]")
        if not math.isfinite(collateral) or not 0.1 <= collateral <= 2.0:
            raise ValueError("collateral_ratio must be between 0.1 and 2.0")
        normalized["allocation_fraction"] = allocation
        normalized["collateral_ratio"] = collateral
    if strategy == "funding_filter":
        threshold = float(normalized.get("positive_funding_threshold", 0.0))
        if not math.isfinite(threshold):
            raise ValueError("positive_funding_threshold must be finite")
        normalized["positive_funding_threshold"] = threshold
    if normalized != _BASELINE_PARAMETERS[strategy]:
        raise ValueError("initial campaign permits only the preregistered baseline parameters")
    return normalized


def _as_rows(table):
    if isinstance(table, list):
        return table
    if hasattr(table, "to_dict"):
        return _clean_records(table)
    raise ValueError("snapshot tables must be lists of records")


def _bar_map(rows, key):
    result = {}
    for row in rows:
        stamp = _time(row[key], key)
        result[int(stamp.timestamp() * 1000)] = row
    return result


def _build_strategy_events(config: dict, tables: dict, stage_range: dict,
                           strategy: str, parameters: dict) -> tuple[list[dict], list[dict]]:
    start_ms = int(_time(stage_range["start"], "stage.start").timestamp() * 1000)
    end_ms = int(_time(stage_range["end"], "stage.end").timestamp() * 1000)
    spot_bars = _as_rows(tables["spot_ohlcv"])
    perp_bars = _as_rows(tables["perp_ohlcv"])
    mark_bars = _as_rows(tables["mark_ohlcv"])
    funding_rows = _as_rows(tables["funding"])
    spot = _bar_map(spot_bars, "open_time")
    perp = _bar_map(perp_bars, "open_time")
    mark = _bar_map(mark_bars, "open_time")
    spot_closes = _bar_map(spot_bars, "close_time")
    perp_closes = _bar_map(perp_bars, "close_time")
    mark_closes = _bar_map(mark_bars, "close_time")
    gap_start = int(_time(SUPPORTED_KNOWN_GAP["start"], "gap.start").timestamp() * 1000)
    gap_end = int(_time(SUPPORTED_KNOWN_GAP["end"], "gap.end").timestamp() * 1000)
    eligible = sorted(stamp for stamp in set(spot) & set(perp) & set(mark)
                      if start_ms <= stamp < end_ms and not gap_start <= stamp < gap_end)
    if strategy != "cash_zero" and len(eligible) < 2:
        raise ValueError("stage needs at least two common tradable spot/perpetual candles")

    events, sequence = [], 0

    def add(kind, stamp_ms, payload):
        nonlocal sequence
        events.append({"kind": kind, "event_time": _iso(datetime.fromtimestamp(
            stamp_ms / 1000, timezone.utc)), "sequence": sequence, "payload": payload})
        sequence += 1

    # Hourly close marks are available only when each candle has closed.
    close_times = sorted((set(spot_closes) | set(perp_closes) | set(mark_closes))
                         & set(range(start_ms, end_ms + 1, _HOUR_MS)))
    last_spot_close = None
    last_perp_mark = None
    for stamp in close_times:
        spot_row = spot_closes.get(stamp)
        perp_row = perp_closes.get(stamp)
        mark_row = mark_closes.get(stamp)
        if spot_row is not None:
            last_spot_close = float(spot_row["close"])
        if mark_row is not None:
            last_perp_mark = float(mark_row["close"])
        elif perp_row is not None:
            last_perp_mark = float(perp_row["close"])
        if last_spot_close is None or last_perp_mark is None:
            continue
        unavailable = gap_start <= stamp < gap_end
        add("mark", stamp, {"spot_price": last_spot_close,
                            "perp_mark_price": last_perp_mark,
                            "spot_market_available": not unavailable,
                            "spot_mark_is_stale": unavailable})

    # Revalue at the first observed spot price after the outage before any fill.
    resume = spot.get(gap_end)
    if resume is not None and start_ms <= gap_end < end_ms:
        resume_mark = mark.get(gap_end)
        resume_perp = perp.get(gap_end)
        add("mark", gap_end, {
            "spot_price": float(resume["open"]),
            "perp_mark_price": float((resume_mark or resume_perp)["open"]),
            "spot_market_available": True,
            "spot_mark_is_stale": False,
        })

    for row in funding_rows:
        stamp = int(_time(row["settlement_time"], "funding.settlement_time").timestamp() * 1000)
        if start_ms <= stamp < end_ms:
            add("funding", stamp, {
                "rate": row["rate"], "mark_price": row["mark_price"],
                "mark_price_source": row["mark_price_source"],
                "mark_price_is_proxy": row["mark_price_is_proxy"],
                "mark_price_source_time": row["mark_price_source_time"],
            })

    allocation = float(parameters.get("allocation_fraction", _DEFAULT_ALLOCATION_FRACTION))
    collateral_ratio = float(parameters.get("collateral_ratio", _INITIAL_COLLATERAL_RATIO))
    initial_equity = float(config["campaign"]["initial_equity"])
    groups = {}

    def open_group(stamp, group_id):
        spot_row, perp_row = spot.get(stamp), perp.get(stamp)
        mark_row = mark.get(stamp) or perp_row
        if spot_row is None or perp_row is None or mark_row is None:
            return False
        spot_price, perp_price = float(spot_row["open"]), float(perp_row["open"])
        quantity = initial_equity * allocation / spot_price
        collateral = abs(quantity * perp_price) * collateral_ratio
        add("collateral_transfer", stamp, {"group_id": group_id,
                                            "amount": f"{collateral:.16g}"})
        add("spot_fill", stamp, {"group_id": group_id, "side": "buy",
                                  "quantity": f"{quantity:.16g}",
                                  "reference_price": f"{spot_price:.16g}",
                                  "mark_price": f"{spot_price:.16g}"})
        add("perp_fill", stamp, {"group_id": group_id, "side": "sell",
                                 "quantity": f"{quantity:.16g}",
                                 "reference_price": f"{perp_price:.16g}",
                                 "mark_price": f"{float(mark_row['open']):.16g}"})
        groups[group_id] = {"group_id": group_id,
                            "spot_quantity": quantity,
                            "perp_quantity": -quantity,
                            "spot_entry_price": spot_price,
                            "perp_entry_price": perp_price,
                            "spot_price": spot_price,
                            "perp_mark_price": float(mark_row["open"]),
                            "collateral": collateral}
        return True

    def close_group(stamp, group_id):
        entry = groups.get(group_id)
        spot_row, perp_row = spot.get(stamp), perp.get(stamp)
        mark_row = mark.get(stamp) or perp_row
        if entry is None or spot_row is None or perp_row is None or mark_row is None:
            return False
        add("spot_fill", stamp, {"group_id": group_id, "side": "sell",
                                  "quantity": f"{entry['spot_quantity']:.16g}",
                                  "reference_price": f"{float(spot_row['open']):.16g}",
                                  "mark_price": f"{float(spot_row['open']):.16g}"})
        add("perp_fill", stamp, {"group_id": group_id, "side": "buy",
                                 "quantity": f"{entry['spot_quantity']:.16g}",
                                 "reference_price": f"{float(perp_row['open']):.16g}",
                                 "mark_price": f"{float(mark_row['open']):.16g}"})
        add("collateral_transfer", stamp, {"group_id": group_id, "amount": "0",
                                            "withdraw_all": True})
        return True

    if strategy == "carry_static":
        group_id = "carry-static-1"
        open_group(eligible[0], group_id)
        close_group(eligible[-1], group_id)
    elif strategy == "funding_filter":
        threshold = float(parameters.get("positive_funding_threshold", 0.0))
        active_group = None
        group_counter = 0
        trade_times = eligible[:-1]  # reserve the last eligible open for liquidation
        for row in sorted(funding_rows,
                          key=lambda item: item["available_time"]):
            settlement = int(_time(row["available_time"],
                                   "funding.available_time").timestamp() * 1000)
            if not start_ms <= settlement < end_ms:
                continue
            desired = float(row["rate"]) > threshold
            if desired == (active_group is not None):
                continue
            index = bisect_right(trade_times, settlement)
            if index >= len(trade_times):
                continue
            action_time = trade_times[index]
            if desired:
                group_counter += 1
                active_group = f"funding-filter-{group_counter:04d}"
                if not open_group(action_time, active_group):
                    active_group = None
            else:
                close_group(action_time, active_group)
                active_group = None
        if active_group is not None:
            close_group(eligible[-1], active_group)

    return events, list(groups.values())


def _risk_scenarios(groups: list[dict], costs: dict,
                    initial_equity: float) -> list[dict]:
    if groups:
        representative = dict(groups[0])
        # The scenarios stress one representative active group while keeping
        # the rest of the account in free cash. These registered strategies
        # never hold multiple groups at once.
        committed_capital = (abs(float(representative["spot_quantity"])) *
                             float(representative["spot_entry_price"]) +
                             float(representative["collateral"]))
        representative["free_cash"] = initial_equity - committed_capital
        if representative["free_cash"] < -1e-8:
            raise ValueError("representative stress position exceeds initial account equity")
    else:
        representative = {"group_id": "no-position", "spot_quantity": "0",
                          "perp_quantity": "0", "spot_entry_price": "1",
                          "perp_entry_price": "1", "spot_price": "1",
                          "perp_mark_price": "1", "collateral": "0",
                          "free_cash": initial_equity}
    base_spot = float(representative["spot_entry_price"])
    base_perp = float(representative["perp_entry_price"])
    base = {"spot_price": base_spot, "perp_mark_price": base_perp,
            "maintenance_ratio": 0.05,
            "perp_fee_bps": costs["perp_fee_bps"],
            "spot_fee_bps": costs["spot_fee_bps"],
            "slippage_bps": costs["slippage_bps"]}
    cases = [
        ("base", dict(base)),
        ("price_gap_up_20pct", {**base, "spot_price": base_spot * 1.2,
                                 "perp_mark_price": base_perp * 1.2}),
        ("basis_expansion_against_short", {**base, "spot_price": base_spot * 1.05,
                                            "perp_mark_price": base_perp * 1.2}),
        ("negative_funding", {**base, "funding_rate": -0.001,
                              "funding_mark_price": base_perp}),
        ("spot_data_outage", {**base, "spot_market_available": False}),
        *[(f"slippage_{bps}bps", {**base, "slippage_bps": bps})
          for bps in (1, 5, 15)],
    ]
    scenarios = []
    for name, inputs in cases:
        assessed = assess_group(representative, inputs)
        scenarios.append({"scenario": name, "inputs": inputs, **assessed})
    one_leg = apply_execution_result(
        {"group_id": "single-leg-stress", "spot_quantity": "0",
         "perp_quantity": "0", "cash": "1000", "fees_paid": "0",
         "spot_price": str(base_spot), "perp_mark_price": str(base_perp)},
        {"spot": {"filled_quantity": str(abs(float(representative["spot_quantity"]))),
                   "price": str(base_spot), "fee": "0", "status": "filled"},
         "perp": {"filled_quantity": "0", "fee": "0", "status": "timeout"}})
    scenarios.append({"scenario": "perpetual_entry_timeout_after_spot_fill",
                      "inputs": {"spot_fill": "full", "perp_fill": "zero"},
                      "result": one_leg})
    return scenarios


def _execute_trial(config: dict, snapshot: dict, split: dict, stage: str,
                   strategy: str, parameters: dict) -> dict:
    tables = snapshot["tables"]
    events, groups = _build_strategy_events(config, tables, split[stage],
                                            strategy, parameters)
    cfg = deepcopy(config)
    cfg["data"]["known_gaps"] = config["data"].get("known_gaps", [])
    first = replay_events(events, cfg)
    _assert_strategy_events_applied(first["ledger"])
    # Release positive isolated collateral after all positions have closed.
    withdrawals = []
    final_time = events[-1]["event_time"] if events else split[stage]["end"]
    for position in first["positions"]:
        amount = float(position["collateral"])
        if (amount > 0 and float(position["spot_quantity"]) == 0 and
                float(position["perp_quantity"]) == 0):
            withdrawals.append({"kind": "collateral_transfer", "event_time": final_time,
                                "sequence": len(events) + len(withdrawals),
                                "payload": {"group_id": position["group_id"],
                                            "amount": f"{-amount:.16g}"}})
    replay = replay_events(events + withdrawals, cfg)
    _assert_strategy_events_applied(replay["ledger"])
    positions_by_id = {row["group_id"]: row for row in replay["positions"]}
    unclosed = [group["group_id"] for group in groups
                if group["group_id"] not in positions_by_id or
                float(positions_by_id[group["group_id"]]["spot_quantity"]) != 0 or
                float(positions_by_id[group["group_id"]]["perp_quantity"]) != 0]
    if unclosed:
        raise ValueError("strategy left unclosed position groups: " + ", ".join(unclosed))
    equity_series = []
    for row in replay["ledger"]:
        point = {"time": row["event_time"], "equity": row["equity"]}
        if equity_series and equity_series[-1]["time"] == point["time"]:
            equity_series[-1] = point
        else:
            equity_series.append(point)
    metrics = evaluate_metrics(
        equity_series, config["campaign"]["initial_equity"],
        risk_free_rate=config["campaign"].get("cash_return_assumption_annual", 0),
        start_time=split[stage]["start"], ledger=replay["ledger"])
    risk_scenarios = _risk_scenarios(
        groups, config["costs"], config["campaign"]["initial_equity"])
    limitations = [
        "Binance funding is observed only after settlement; the filter enters at the next eligible hourly open.",
        "Funding mark proxy candles use same-hour mark open where exact settlement mark is unavailable.",
        "Collateral stress uses an explicit 5% maintenance-ratio scenario, not historical Binance tiers or liquidation prices.",
        "Hourly OHLCV cannot model order-book depth, simultaneous fills or intrabar liquidation.",
        "Spot outage hour is kept missing; spot fills are blocked and its prior close is shown as stale.",
    ]
    return {"metrics": metrics, "equity_series": equity_series,
            "ledger": replay["ledger"], "positions": replay["positions"],
            "attribution": replay["attribution"],
            "initial_equity": replay["initial_equity"],
            "final_equity": replay["final_equity"],
            "risk_scenarios": risk_scenarios, "limitations": limitations,
            "assumptions": {"allocation_fraction": parameters.get(
                "allocation_fraction", _DEFAULT_ALLOCATION_FRACTION),
                "collateral_ratio": parameters.get("collateral_ratio",
                                                  _INITIAL_COLLATERAL_RATIO),
                "spot_fee_bps": config["costs"]["spot_fee_bps"],
                "perp_fee_bps": config["costs"]["perp_fee_bps"],
                "slippage_bps": config["costs"]["slippage_bps"],
             "cash_return_assumption_annual": config["campaign"].get(
                 "cash_return_assumption_annual", 0)}}


def _assert_strategy_events_applied(ledger: list[dict]) -> None:
    rejected = [row for row in ledger
                if row["kind"] in {"spot_fill", "perp_fill", "collateral_transfer"}
                and row["status"] != "applied"]
    if rejected:
        first = rejected[0]
        reason = first.get("details", {}).get("rejection_reason", first["status"])
        raise ValueError(f"strategy event was rejected at {first['event_time']}: {reason}")


def _write_ledger_csv(path: Path, ledger: list[dict]):
    fields = ["event_time", "kind", "sequence", "status", "free_cash",
              "spot_quantity", "spot_market_value", "perp_quantity",
              "perp_collateral", "spot_mark", "perp_mark", "spot_market_available",
              "spot_mark_is_stale", "spot_pnl", "perp_pnl", "funding",
              "spot_fees", "perp_fees", "slippage", "equity", "attributed_equity",
              "details"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        rows = []
        for row in ledger:
            copied = dict(row)
            copied["details"] = json.dumps(row.get("details", {}), ensure_ascii=False,
                                           sort_keys=True, allow_nan=False)
            rows.append(copied)
        writer.writerows(rows)


def run_trial(config: dict, campaign_dir: str) -> dict:
    """Run one registered baseline on development or validation data only.

    Attempt start is durably appended before validation or execution; rejected
    and failed work consumes a slot. A stable campaign registry root means a
    different artifact folder cannot reset its budget.
    """
    if not isinstance(config, dict) or not isinstance(config.get("campaign"), dict):
        raise ValueError("campaign configuration is required")
    registry_dir, campaign_id = _campaign_paths(config)
    registry = registry_dir / "events.jsonl"
    lock = _locked(registry_dir)
    try:
        history = _read_events(registry)
        attempt = sum(item.get("event") == "attempt_started" for item in history) + 1
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z")
        _append_event(registry, {"event": "attempt_started", "campaign_id": campaign_id,
                                 "attempt": attempt, "created_at": created_at})
        config = validate_config(config)
        campaign = config["campaign"]
        stage = campaign.get("stage", "development")
        strategy = campaign.get("strategy", "cash_zero")
        parameters = campaign.get("parameters", {})
        status = "failed"
        try:
            if attempt > campaign["max_attempts"]:
                raise ValueError("campaign trial budget exhausted")
            if _freeze_from_history(history):
                raise ValueError("campaign is already frozen; no more trials are allowed")
            if stage == "holdout":
                raise ValueError("cannot run holdout through run_trial; freeze then evaluate once")
            if stage not in {"development", "validation"}:
                raise ValueError("stage must be development or validation")
            normalized_parameters = _validate_strategy(strategy, parameters)
            snapshot = _load_snapshot(config)
            split = _split_dates(config)
            contract = _contract(config, snapshot, split)
            contract_path = registry_dir / "contract.json"
            if contract_path.exists():
                saved = json.loads(contract_path.read_text(encoding="utf-8"))
                if saved != contract:
                    raise ValueError("campaign contract changed; use a new reviewed campaign")
            else:
                contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2,
                                                    allow_nan=False), encoding="utf-8")
                (registry_dir / "split.json").write_text(
                    json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")
            duplicate = any(item.get("event") == "attempt_finished" and
                            item.get("status") == "succeeded" and
                            item.get("stage") == stage and
                            item.get("strategy") == strategy and
                            item.get("parameters") == normalized_parameters
                            for item in history)
            if duplicate:
                raise ValueError("registered baseline already has a successful trial for this stage")
            result = _execute_trial(config, snapshot, split, stage, strategy,
                                    normalized_parameters)
            output = Path(campaign_dir).resolve()
            output.mkdir(parents=True, exist_ok=True)
            ledger_path = output / f"trial-{attempt:03d}-ledger.csv"
            trial_path = output / f"trial-{attempt:03d}.json"
            _write_ledger_csv(ledger_path, result["ledger"])
            record = {
                "schema_version": "crypto-trial-v1", "run_id": f"{campaign_id}-{attempt:03d}",
                "attempt": attempt, "status": "succeeded", "stage": stage,
                "strategy": strategy, "parameters": normalized_parameters,
                "created_at": created_at,
                "provenance": {"campaign_id": campaign_id,
                               "snapshot_id": snapshot["manifest"].get("snapshot_id"),
                               "manifest_path": snapshot["manifest_path"],
                                "table_sha256": contract["table_sha256"],
                               "contract_sha256": contract["contract_sha256"],
                               "evaluator_sha256": contract["evaluator_sha256"],
                               "stage_range": split[stage]},
                "metrics": result["metrics"], "attribution": result["attribution"],
                "positions": result["positions"], "risk_scenarios": result["risk_scenarios"],
                "assumptions": result["assumptions"],
                "limitations": result["limitations"],
                "equity_series": result["equity_series"],
                "ledger_path": str(ledger_path.resolve()),
            }
            trial_path.write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                              allow_nan=False), encoding="utf-8")
            report_paths = build_report(str(output))
            status = "succeeded"
            finish = {"event": "attempt_finished", "attempt": attempt,
                      "status": status, "stage": stage, "strategy": strategy,
                      "parameters": normalized_parameters, "run_id": record["run_id"],
                      "contract_sha256": contract["contract_sha256"],
                      "metrics": {"total_return": result["metrics"]["total_return"],
                                  "max_drawdown": result["metrics"]["max_drawdown"]}}
            _append_event(registry, finish)
            return {**record, "artifact_paths": {"trial": str(trial_path.resolve()),
                    "ledger": str(ledger_path.resolve()), **report_paths}}
        except Exception as exc:
            _append_event(registry, {"event": "attempt_finished", "attempt": attempt,
                                     "status": status, "error": f"{type(exc).__name__}: {exc}"})
            raise
    finally:
        lock.unlink(missing_ok=True)


def _freeze_from_history(history: list[dict]):
    frozen = [event for event in history if event.get("event") == "candidate_frozen"]
    return frozen[0] if frozen else None


def freeze_candidate(config: dict, campaign_dir: str) -> dict:
    """Select and freeze the preregistered validation winner exactly once."""
    config = validate_config(config)
    registry_dir, campaign_id = _campaign_paths(config)
    registry = registry_dir / "events.jsonl"
    lock = _locked(registry_dir)
    try:
        history = _read_events(registry)
        if _freeze_from_history(history):
            raise ValueError("candidate is already frozen")
        contract_path = registry_dir / "contract.json"
        if not contract_path.is_file():
            raise ValueError("run development and validation before freezing a candidate")
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if any(item.get("event") == "holdout_evaluation_started" for item in history):
            raise ValueError("candidate cannot be changed after holdout access")
        candidates = []
        for order, (strategy, parameters) in enumerate(_BASELINE_PARAMETERS.items()):
            successes = [item for item in history
                         if item.get("event") == "attempt_finished" and
                         item.get("status") == "succeeded" and
                         item.get("strategy") == strategy and
                         item.get("parameters") == parameters and
                         item.get("contract_sha256") == contract["contract_sha256"]]
            stages = {item.get("stage") for item in successes}
            if not {"development", "validation"}.issubset(stages):
                raise ValueError(
                    "freeze requires successful development and validation trials for all three baselines")
            validation = [item for item in successes
                          if item.get("stage") == "validation"]
            if len(validation) != 1:
                raise ValueError("each baseline must have exactly one validation trial")
            metrics = validation[0].get("metrics", {})
            total_return = metrics.get("total_return")
            max_drawdown = metrics.get("max_drawdown")
            if (isinstance(total_return, bool) or not isinstance(total_return, (int, float)) or
                    not math.isfinite(total_return) or
                    isinstance(max_drawdown, bool) or not isinstance(max_drawdown, (int, float)) or
                    not math.isfinite(max_drawdown)):
                raise ValueError("validation ranking needs finite return and drawdown metrics")
            candidates.append({"strategy": strategy, "parameters": parameters,
                               "validation_total_return": total_return,
                               "validation_max_drawdown": max_drawdown,
                               "baseline_order": order})
        selected = min(candidates, key=lambda item: (
            -item["validation_total_return"], -item["validation_max_drawdown"],
            item["baseline_order"]))
        split = json.loads((registry_dir / "split.json").read_text(encoding="utf-8"))
        ranking = [{key: value for key, value in item.items() if key != "baseline_order"}
                   for item in candidates]
        candidate = {"campaign_id": campaign_id, "strategy": selected["strategy"],
                     "parameters": selected["parameters"],
                     "selection_policy": _SELECTION_POLICY,
                     "validation_ranking": ranking,
                     "snapshot_id": contract["snapshot_id"],
                     "contract_sha256": contract["contract_sha256"],
                     "evaluator_sha256": contract["evaluator_sha256"],
                     "holdout": split["holdout"],
                     "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                         "+00:00", "Z")}
        _append_event(registry, {"event": "candidate_frozen", **candidate})
        (registry_dir / "freeze.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8")
        return candidate
    finally:
        lock.unlink(missing_ok=True)


def evaluate_holdout(config: dict, campaign_dir: str) -> dict:
    """Consume the sealed holdout before execution; any failure still spends it."""
    config = validate_config(config)
    registry_dir, campaign_id = _campaign_paths(config)
    registry = registry_dir / "events.jsonl"
    lock = _locked(registry_dir)
    try:
        history = _read_events(registry)
        frozen_event = _freeze_from_history(history)
        if frozen_event is None:
            raise ValueError("candidate must be frozen before holdout access")
        if any(item.get("event") == "holdout_evaluation_started" for item in history):
            raise ValueError("sealed holdout has already been opened")
        _append_event(registry, {"event": "holdout_evaluation_started",
                                 "campaign_id": campaign_id,
                                 "started_at": datetime.now(timezone.utc).isoformat(
                                     timespec="seconds").replace("+00:00", "Z")})
        try:
            snapshot = _load_snapshot(config)
            split = _split_dates(config)
            contract = _contract(config, snapshot, split)
            if contract["contract_sha256"] != frozen_event["contract_sha256"]:
                raise ValueError("campaign contract changed after candidate freeze")
            result = _execute_trial(config, snapshot, split, "holdout",
                                    frozen_event["strategy"],
                                    frozen_event["parameters"])
            output = Path(campaign_dir).resolve()
            output.mkdir(parents=True, exist_ok=True)
            history_now = _read_events(registry)
            attempt = sum(item.get("event") == "attempt_started" for item in history_now)
            ledger_path = output / f"holdout-{attempt:03d}-ledger.csv"
            trial_path = output / f"holdout-{attempt:03d}.json"
            _write_ledger_csv(ledger_path, result["ledger"])
            record = {"schema_version": "crypto-trial-v1",
                      "run_id": f"{campaign_id}-holdout-once", "attempt": attempt,
                      "status": "succeeded", "stage": "holdout",
                      "strategy": frozen_event["strategy"],
                      "parameters": frozen_event["parameters"],
                      "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                          "+00:00", "Z"),
                      "provenance": {"campaign_id": campaign_id,
                                     "snapshot_id": snapshot["manifest"].get("snapshot_id"),
                                     "manifest_path": snapshot["manifest_path"],
                                      "table_sha256": contract["table_sha256"],
                                     "contract_sha256": contract["contract_sha256"],
                                     "evaluator_sha256": contract["evaluator_sha256"],
                                     "stage_range": split["holdout"]},
                      "metrics": result["metrics"], "attribution": result["attribution"],
                      "positions": result["positions"],
                      "risk_scenarios": result["risk_scenarios"],
                      "assumptions": result["assumptions"],
                      "limitations": result["limitations"],
                      "equity_series": result["equity_series"],
                      "ledger_path": str(ledger_path.resolve())}
            trial_path.write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                              allow_nan=False), encoding="utf-8")
            report_paths = build_report(str(output))
            _append_event(registry, {"event": "holdout_evaluation_finished",
                                     "status": "succeeded", "run_id": record["run_id"]})
            return {**record, "status": "holdout_evaluated_once",
                    "artifact_paths": {"trial": str(trial_path.resolve()),
                    "ledger": str(ledger_path.resolve()), **report_paths}}
        except Exception as exc:
            _append_event(registry, {"event": "holdout_evaluation_finished",
                                     "status": "failed",
                                     "error": f"{type(exc).__name__}: {exc}"})
            raise
    finally:
        lock.unlink(missing_ok=True)
