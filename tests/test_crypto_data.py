"""Offline data-normalization and audit contracts using synthetic fixtures."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from crypto.data import (audit_dataset, fetch_pages, instrument_key,
                         normalize_records, resolve_funding_mark_prices,
                         time_range_ms)


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "crypto" /
                      "time_edges.json").read_text(encoding="utf-8"))
HOUR = FIXTURE["timeframe_ms"]
T0 = FIXTURE["same_instant_ms"]


def iso_ms(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def bar(timestamp):
    return {
        "open_time": iso_ms(timestamp),
        "close_time": iso_ms(timestamp + HOUR),
        "available_time": iso_ms(timestamp + HOUR),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 3.0,
    }


def funding(timestamp):
    return {
        "settlement_time": iso_ms(timestamp),
        "available_time": iso_ms(timestamp),
        "rate": 0.001,
        "mark_price": 101.0,
        "mark_price_source": "funding_endpoint",
        "mark_price_is_proxy": False,
        "mark_price_source_time": None,
    }


def tables_with_hours(count):
    rows = [bar(T0 + i * HOUR) for i in range(count)]
    return {
        "spot_ohlcv": list(rows),
        "perp_ohlcv": list(rows),
        "mark_ohlcv": list(rows),
        "funding": [funding(T0 + i * 8 * HOUR) for i in (1, 2)],
    }


class CryptoDataTests(unittest.TestCase):
    def test_config_iso_times_convert_to_utc_epoch_milliseconds(self):
        start, end = time_range_ms({"start": "2023-01-01T08:00:00+08:00",
                                    "end": "2023-01-01T02:00:00-06:00"})
        self.assertEqual(start, 1672531200000)
        self.assertEqual(end, 1672560000000)

    def test_instrument_cache_key_is_safe_and_market_specific(self):
        common = {"exchange": "Binance", "base": "BTC", "quote": "USDT",
                  "settlement": "USDT", "timeframe": "1h"}
        spot = instrument_key({**common, "market_type": "spot", "settlement": ""})
        perp = instrument_key({**common, "market_type": "linear_perpetual"})
        self.assertNotEqual(spot, perp)
        self.assertNotIn("/", spot)
        self.assertNotIn("\\", perp)

    def test_millisecond_and_microsecond_schemas_normalize_same_candle(self):
        ms = FIXTURE["same_instant_ms"]
        us = FIXTURE["same_instant_us"]
        template = ["100", "102", "99", "101", "3"]
        records_ms = normalize_records([[ms, *template]], {
            "kind": "ohlcv", "timestamp_unit": "ms", "timeframe_ms": HOUR,
            "start_ms": ms, "end_ms": ms + HOUR, "as_of_ms": ms + HOUR,
        })
        records_us = normalize_records([[us, *template]], {
            "kind": "ohlcv", "timestamp_unit": "us", "timeframe_ms": HOUR,
            "start_ms": ms, "end_ms": ms + HOUR, "as_of_ms": ms + HOUR,
        })
        self.assertEqual(records_ms, records_us)
        self.assertEqual(records_ms[0]["open_time"], iso_ms(ms))
        self.assertEqual(records_ms[0]["available_time"], iso_ms(ms + HOUR))

    def test_unclosed_candles_are_excluded(self):
        rows = normalize_records([
            [T0, "100", "102", "99", "101", "3"],
            [T0 + HOUR, "101", "103", "100", "102", "2"],
        ], {"kind": "ohlcv", "timestamp_unit": "ms", "timeframe_ms": HOUR,
            "start_ms": T0, "end_ms": T0 + 2 * HOUR, "as_of_ms": T0 + HOUR})
        self.assertEqual([row["open_time"] for row in rows], [iso_ms(T0)])

    def test_boolean_prices_are_not_treated_as_market_data(self):
        with self.assertRaisesRegex(ValueError, "numeric"):
            normalize_records([[T0, True, 102, 99, 101, 3]], {
                "kind": "ohlcv", "timestamp_unit": "ms", "timeframe_ms": HOUR,
                "start_ms": T0, "end_ms": T0 + HOUR, "as_of_ms": T0 + HOUR,
            })

    def test_funding_is_kept_as_discrete_events(self):
        events = normalize_records([
            {"timestamp": T0 + 8 * HOUR, "fundingRate": "0.001",
             "markPrice": "101"},
            {"timestamp": T0 + 12 * HOUR, "fundingRate": "-0.0005",
             "markPrice": "102"},
        ], {"kind": "funding", "timestamp_unit": "ms",
            "start_ms": T0, "end_ms": T0 + 24 * HOUR})
        self.assertEqual(len(events), 2)
        self.assertEqual([row["rate"] for row in events], [0.001, -0.0005])
        self.assertEqual([row["settlement_time"] for row in events],
                         [iso_ms(T0 + 8 * HOUR), iso_ms(T0 + 12 * HOUR)])

    def test_missing_funding_endpoint_mark_is_recorded_without_fabrication(self):
        events = normalize_records([
            {"timestamp": T0 + HOUR, "fundingRate": "0.001", "markPrice": ""},
        ], {"kind": "funding", "timestamp_unit": "ms",
            "start_ms": T0, "end_ms": T0 + 2 * HOUR})
        self.assertEqual(events[0]["mark_price"], None)
        self.assertEqual(events[0]["mark_price_source"], "missing")
        self.assertFalse(events[0]["mark_price_is_proxy"])

    def test_funding_mark_proxy_uses_only_the_same_hour_mark_open(self):
        event_time = T0 + HOUR + 7
        events = normalize_records([
            {"timestamp": event_time, "fundingRate": "0.001", "markPrice": ""},
            {"timestamp": T0 + 2 * HOUR, "fundingRate": "-0.001",
             "markPrice": "103"},
        ], {"kind": "funding", "timestamp_unit": "ms",
            "start_ms": T0, "end_ms": T0 + 3 * HOUR})
        mark_bars = [bar(T0 + HOUR), bar(T0 + 2 * HOUR)]
        mark_bars[0]["open"] = 102.5
        mark_bars[0]["close"] = 109.0
        resolved = resolve_funding_mark_prices(events, mark_bars, HOUR)
        self.assertEqual(resolved[0]["mark_price"], 102.5)
        self.assertEqual(resolved[0]["mark_price_source"], "mark_ohlcv.open_proxy")
        self.assertTrue(resolved[0]["mark_price_is_proxy"])
        self.assertEqual(resolved[0]["mark_price_source_time"], iso_ms(T0 + HOUR))
        self.assertEqual(resolved[1]["mark_price"], 103.0)
        self.assertEqual(resolved[1]["mark_price_source"], "funding_endpoint")
        self.assertFalse(resolved[1]["mark_price_is_proxy"])

    def test_unmatched_funding_mark_remains_missing(self):
        event_time = T0 + HOUR + 7
        events = normalize_records([
            {"timestamp": event_time, "fundingRate": "0.001", "markPrice": ""},
        ], {"kind": "funding", "timestamp_unit": "ms",
            "start_ms": T0, "end_ms": T0 + 2 * HOUR})
        resolved = resolve_funding_mark_prices(events, [], HOUR)
        self.assertIsNone(resolved[0]["mark_price"])
        result = audit_dataset({**tables_with_hours(2), "funding": resolved},
                              {"start": iso_ms(T0), "end": iso_ms(T0 + 2 * HOUR),
                               "timeframe_ms": HOUR})
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("mark" in error for error in result["errors"]))

    def test_audit_counts_mark_price_proxies(self):
        tables = tables_with_hours(24)
        tables["funding"][0]["mark_price_source"] = "mark_ohlcv.open_proxy"
        tables["funding"][0]["mark_price_is_proxy"] = True
        tables["funding"][0]["mark_price_source_time"] = tables["mark_ohlcv"][8]["open_time"]
        tables["mark_ohlcv"][8]["open"] = tables["funding"][0]["mark_price"]
        result = audit_dataset(tables, {"start": iso_ms(T0),
                                        "end": iso_ms(T0 + 24 * HOUR),
                                        "timeframe_ms": HOUR})
        self.assertEqual(result["status"], "audited", result["errors"])
        self.assertEqual(result["funding_mark_price_proxy_count"], 1)

    def test_audit_accepts_a_cited_exchange_outage_without_fabricating_a_bar(self):
        gap_start = 1679662800000  # 2023-03-24 13:00 UTC
        gap_end = gap_start + HOUR
        tables = {name: [bar(gap_start - HOUR), bar(gap_start), bar(gap_end)]
                  for name in ("spot_ohlcv", "perp_ohlcv", "mark_ohlcv")}
        missing_time = gap_start
        tables["spot_ohlcv"] = [row for row in tables["spot_ohlcv"]
                                if row["open_time"] != iso_ms(missing_time)]
        tables["funding"] = [funding(missing_time)]
        outage = {"table": "spot_ohlcv", "start": iso_ms(missing_time),
                  "end": iso_ms(missing_time + HOUR),
                  "reason": "Binance spot trading system maintenance; trading resumed at 14:00 UTC",
                  "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a"}
        result = audit_dataset(tables, {"start": iso_ms(gap_start - HOUR),
                                        "end": iso_ms(gap_end + HOUR),
                                        "timeframe_ms": HOUR,
                                        "known_gaps": [outage]})
        self.assertEqual(result["status"], "audited", result["errors"])
        self.assertEqual(len(tables["spot_ohlcv"]), 2)
        self.assertEqual(result["known_gaps"][0]["missing_candles"], 1)
        self.assertEqual(result["coverage"]["common_price_range"]["candles"], 2)

    def test_audit_rejects_fabricated_gap_even_with_https_citation(self):
        tables = tables_with_hours(4)
        missing_time = T0 + HOUR
        tables["spot_ohlcv"] = [row for row in tables["spot_ohlcv"]
                                if row["open_time"] != iso_ms(missing_time)]
        manifest = {"start": iso_ms(T0), "end": iso_ms(T0 + 4 * HOUR),
                    "timeframe_ms": HOUR,
                    "known_gaps": [{"table": "spot_ohlcv",
                                    "start": iso_ms(missing_time),
                                    "end": iso_ms(missing_time + HOUR),
                                    "reason": "Binance spot trading system maintenance; trading resumed at 14:00 UTC",
                                    "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a"}]}
        result = audit_dataset(tables, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("only the documented Binance spot outage" in error
                            for error in result["errors"]))

    def test_audit_rejects_undocumented_or_malformed_outage_gaps(self):
        tables = tables_with_hours(4)
        missing_time = T0 + HOUR
        tables["spot_ohlcv"] = [row for row in tables["spot_ohlcv"]
                                if row["open_time"] != iso_ms(missing_time)]
        tables["funding"] = [funding(missing_time)]
        manifest = {"start": iso_ms(T0), "end": iso_ms(T0 + 4 * HOUR),
                    "timeframe_ms": HOUR,
                    "known_gaps": [{"table": "spot_ohlcv",
                                    "start": iso_ms(missing_time),
                                    "end": iso_ms(missing_time + HOUR),
                                    "reason": "unverified", "source_url": ""}]}
        result = audit_dataset(tables, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("known gap" in error for error in result["errors"]))

    def test_pagination_advances_without_repeating_the_last_candle(self):
        calls = []

        def fetch_page(since_ms, limit):
            calls.append((since_ms, limit))
            if since_ms == T0:
                return [[T0, "100", "102", "99", "101", "3"],
                        [T0 + HOUR, "101", "103", "100", "102", "2"]]
            return [[T0 + 2 * HOUR, "102", "104", "101", "103", "1"]]

        rows = fetch_pages(fetch_page, T0, T0 + 3 * HOUR,
                           timeframe_ms=HOUR, limit=2)
        self.assertEqual([row[0] for row in rows],
                         [T0, T0 + HOUR, T0 + 2 * HOUR])
        self.assertEqual(calls, [(T0, 2), (T0 + 2 * HOUR, 2)])

    def test_audit_accepts_variable_funding_intervals(self):
        tables = tables_with_hours(24)
        tables["funding"] = [funding(T0 + hours * HOUR) for hours in (8, 12, 20)]
        manifest = {"start": iso_ms(T0), "end": iso_ms(T0 + 24 * HOUR),
                    "timeframe_ms": HOUR}
        result = audit_dataset(tables, manifest)
        self.assertEqual(result["status"], "audited", result["errors"])

    def test_audit_rejects_duplicate_bars_and_reports_gaps(self):
        tables = tables_with_hours(3)
        tables["spot_ohlcv"] = [bar(T0), bar(T0), bar(T0 + 2 * HOUR)]
        tables["perp_ohlcv"] = [bar(T0), bar(T0 + 2 * HOUR)]
        tables["mark_ohlcv"] = [bar(T0), bar(T0 + HOUR), bar(T0 + 2 * HOUR)]
        tables["funding"] = [funding(T0 + 2 * HOUR)]
        manifest = {"start": iso_ms(T0), "end": iso_ms(T0 + 3 * HOUR),
                    "timeframe_ms": HOUR}
        result = audit_dataset(tables, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["errors"])
        self.assertIn("spot_ohlcv", result["gaps"])

    def test_audit_flags_suspicious_funding_gap_without_assuming_eight_hour_cadence(self):
        tables = tables_with_hours(72)
        tables["funding"] = [funding(T0 + hours * HOUR) for hours in (8, 12, 48)]
        manifest = {"start": iso_ms(T0), "end": iso_ms(T0 + 72 * HOUR),
                    "timeframe_ms": HOUR}
        result = audit_dataset(tables, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertIn("funding", result["gaps"])


if __name__ == "__main__":
    unittest.main()
