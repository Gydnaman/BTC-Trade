"""Deterministic cash-and-position contracts for the isolated spot baseline."""
import unittest
from datetime import datetime, timedelta, timezone

from crypto.gap_policy import SUPPORTED_KNOWN_GAP
from crypto.spot import run_spot


START = datetime(2025, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def iso(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def candle(open_time, open_price, close_price=None):
    close_price = open_price if close_price is None else close_price
    return {"open_time": iso(open_time), "close_time": iso(open_time + HOUR),
            "available_time": iso(open_time + HOUR), "open": open_price,
            "high": max(open_price, close_price), "low": min(open_price, close_price),
            "close": close_price, "volume": 10}


def config():
    return {"campaign": {"initial_equity": 1000},
            "costs": {"spot_fee_bps": 10, "slippage_bps": 0},
            "data": {"known_gaps": []}}


class CryptoSpotTests(unittest.TestCase):
    def test_buy_and_sell_match_independent_fee_hand_calculation(self):
        bars = [candle(START, 100), candle(START + HOUR, 110)]
        orders = [{"time": iso(START), "side": "buy", "quantity": 1},
                  {"time": iso(START + HOUR), "side": "sell", "quantity": 1}]
        result = run_spot(bars, orders, config())
        self.assertEqual(result["final_equity"], "1009.79")
        self.assertEqual(result["final_cash"], "1009.79")
        self.assertEqual(result["final_quantity"], "0")
        self.assertEqual(result["costs"]["fees"], "0.21")
        self.assertEqual([row["status"] for row in result["orders"]],
                         ["filled", "filled"])
        self.assertEqual([row["equity"] for row in result["equity"]],
                         ["999.9", "1009.79"])

    def test_cash_shortage_and_oversell_are_rejected_without_mutation(self):
        bars = [candle(START, 100), candle(START + HOUR, 110)]
        orders = [{"time": iso(START), "side": "buy", "quantity": 11},
                  {"time": iso(START + HOUR), "side": "sell", "quantity": 1}]
        result = run_spot(bars, orders, config())
        self.assertEqual([row["status"] for row in result["orders"]],
                         ["rejected_insufficient_cash", "rejected_insufficient_position"])
        self.assertEqual(result["final_cash"], "1000")
        self.assertEqual(result["final_quantity"], "0")
        self.assertEqual(result["costs"]["fees"], "0")

    def test_unclosed_position_is_reported_and_marked_to_last_close(self):
        bars = [candle(START, 100, 105)]
        result = run_spot(bars, [{"time": iso(START), "side": "buy", "quantity": 1}],
                          config())
        self.assertTrue(result["open_position"])
        self.assertEqual(result["final_quantity"], "1")
        self.assertEqual(result["final_equity"], "1004.9")
        self.assertEqual(result["equity"][-1]["equity"], "1004.9")

    def test_outage_order_is_not_carried_forward_to_the_resume_bar(self):
        outage_start = datetime(2023, 3, 24, 13, tzinfo=timezone.utc)
        outage_end = outage_start + HOUR
        bars = [candle(outage_start - HOUR, 100), candle(outage_end, 110)]
        cfg = config()
        cfg["data"]["known_gaps"] = [SUPPORTED_KNOWN_GAP]
        result = run_spot(bars, [{"time": iso(outage_start), "side": "buy",
                                  "quantity": 1}], cfg)
        self.assertEqual(result["orders"][0]["status"], "rejected_market_outage")
        self.assertEqual(result["final_quantity"], "0")

    def test_spot_runner_enforces_outage_without_optional_gap_declaration(self):
        outage_start = datetime(2023, 3, 24, 13, tzinfo=timezone.utc)
        outage_end = outage_start + HOUR
        bars = [candle(outage_start - HOUR, 100), candle(outage_end, 110)]
        result = run_spot(bars, [{"time": iso(outage_start), "side": "buy",
                                  "quantity": 1}], config())
        self.assertEqual(result["orders"][0]["status"], "rejected_market_outage")
        self.assertEqual(result["final_quantity"], "0")

    def test_spot_runner_rejects_fabricated_gap_config(self):
        cfg = config()
        cfg["data"]["known_gaps"] = [{"table": "spot_ohlcv",
                                        "start": "2025-01-01T00:00:00Z",
                                        "end": "2025-01-01T01:00:00Z",
                                        "reason": "unverified",
                                        "source_url": "https://example.com"}]
        with self.assertRaisesRegex(ValueError, "only the documented Binance spot outage"):
            run_spot([], [], cfg)


if __name__ == "__main__":
    unittest.main()
