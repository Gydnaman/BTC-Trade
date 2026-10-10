"""Configuration contracts for the independent crypto research entry point."""
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto.cli import main
from crypto.config import load_config, validate_config


def valid_config():
    return {
        "market": {
            "exchange": "binance",
            "market_type": "spot_perpetual_carry",
            "spot_symbol": "BTC/USDT",
            "perp_symbol": "BTC/USDT:USDT",
        },
        "data": {
            "mode": "real_snapshot",
            "root": "data_cache/crypto",
            "timeframe": "1h",
            "start": "2023-01-01T00:00:00Z",
            "end": "2026-10-01T00:00:00Z",
        },
        "costs": {
            "spot_fee_bps": 10,
            "perp_fee_bps": 5,
            "slippage_bps": 1,
        },
        "campaign": {
            "initial_equity": 1000,
            "max_attempts": 10,
        },
    }


class CryptoConfigTests(unittest.TestCase):
    def test_valid_config_is_returned_without_inventing_fields(self):
        config = valid_config()
        self.assertEqual(validate_config(config), config)

    def test_market_type_is_required(self):
        config = valid_config()
        del config["market"]["market_type"]
        with self.assertRaisesRegex(ValueError, "market_type"):
            validate_config(config)

    def test_unknown_market_type_is_rejected(self):
        config = valid_config()
        config["market"]["market_type"] = "spot_margin"
        with self.assertRaisesRegex(ValueError, "market_type"):
            validate_config(config)

    def test_unimplemented_exchange_is_rejected(self):
        config = valid_config()
        config["market"]["exchange"] = "other"
        with self.assertRaisesRegex(ValueError, "binance"):
            validate_config(config)

    def test_only_hourly_candles_are_accepted_in_mvp(self):
        config = valid_config()
        config["data"]["timeframe"] = "5m"
        with self.assertRaisesRegex(ValueError, "1h"):
            validate_config(config)

    def test_negative_fee_is_rejected(self):
        config = valid_config()
        config["costs"]["spot_fee_bps"] = -1
        with self.assertRaisesRegex(ValueError, "spot_fee_bps"):
            validate_config(config)

    def test_synthetic_data_is_rejected_for_research(self):
        config = valid_config()
        config["data"]["mode"] = "synthetic"
        with self.assertRaisesRegex(ValueError, "real_snapshot"):
            validate_config(config)

    def test_data_times_must_be_explicitly_timezone_aware(self):
        config = valid_config()
        config["data"]["start"] = "2023-01-01T00:00:00"
        with self.assertRaisesRegex(ValueError, "data.start"):
            validate_config(config)

    def test_data_end_must_be_after_start(self):
        config = valid_config()
        config["data"]["end"] = config["data"]["start"]
        with self.assertRaisesRegex(ValueError, "data.end"):
            validate_config(config)

    def test_range_boundaries_must_align_to_the_hour(self):
        config = valid_config()
        config["data"]["start"] = "2023-01-01T00:30:00Z"
        with self.assertRaisesRegex(ValueError, "hour"):
            validate_config(config)

    def test_known_gap_requires_a_cited_aligned_range_within_data_window(self):
        config = valid_config()
        config["data"]["known_gaps"] = [{
            "table": "spot_ohlcv",
            "start": "2023-03-24T13:00:00Z",
            "end": "2023-03-24T14:00:00Z",
            "reason": "Binance spot trading system maintenance; trading resumed at 14:00 UTC",
            "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a",
        }]
        self.assertEqual(validate_config(config)["data"]["known_gaps"],
                         config["data"]["known_gaps"])
        config["data"]["known_gaps"][0]["source_url"] = "http://example.com"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_config(config)

    def test_known_gap_cannot_be_expanded_or_relabelled(self):
        config = valid_config()
        config["data"]["known_gaps"] = [{
            "table": "spot_ohlcv",
            "start": "2023-03-24T12:00:00Z",
            "end": "2023-03-24T14:00:00Z",
            "reason": "maintenance",
            "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a",
        }]
        with self.assertRaisesRegex(ValueError, "only the documented Binance spot outage"):
            validate_config(config)

    def test_known_gap_rejects_other_market_tables_and_multiple_declarations(self):
        config = valid_config()
        gap = {
            "table": "perp_ohlcv",
            "start": "2023-03-24T13:00:00Z",
            "end": "2023-03-24T14:00:00Z",
            "reason": "Binance spot trading system maintenance; trading resumed at 14:00 UTC",
            "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a",
        }
        config["data"]["known_gaps"] = [gap]
        with self.assertRaisesRegex(ValueError, "only the documented Binance spot outage"):
            validate_config(config)
        config["data"]["known_gaps"] = [gap, gap]
        with self.assertRaisesRegex(ValueError, "only the documented Binance spot outage"):
            validate_config(config)

    def test_non_utc_offsets_are_normalized_to_utc(self):
        config = valid_config()
        config["data"]["start"] = "2023-01-01T08:00:00+08:00"
        config["data"]["end"] = "2026-10-01T08:00:00+08:00"
        result = validate_config(config)
        self.assertEqual(result["data"]["start"], "2023-01-01T00:00:00Z")
        self.assertEqual(result["data"]["end"], "2026-10-01T00:00:00Z")

    def test_campaign_budget_is_capped_at_ten(self):
        config = valid_config()
        config["campaign"]["max_attempts"] = 11
        with self.assertRaisesRegex(ValueError, "max_attempts"):
            validate_config(config)

    def test_cash_return_assumption_must_be_valid_for_daily_compounding(self):
        config = valid_config()
        config["campaign"]["cash_return_assumption_annual"] = -1
        with self.assertRaisesRegex(ValueError, "cash_return_assumption_annual"):
            validate_config(config)

    def test_load_config_reads_json_and_validates(self):
        # Use an existing fixture path so this read-only contract works in
        # restricted Windows environments that disallow random temp folders.
        path = Path(__file__).parent / "fixtures" / "crypto" / "config-valid.json"
        loaded = load_config(str(path))
        self.assertEqual(loaded["market"]["spot_symbol"], "BTC/USDT")

    def test_cli_rejects_config_without_audited_snapshot(self):
        self.assertEqual(main(["--config", str(Path(__file__).parent / "fixtures" /
                                                "crypto" / "config-valid.json")]), 2)

    def test_cli_collect_runs_explicitly_and_returns_audit_status(self):
        config_path = str(Path(__file__).parent / "fixtures" / "crypto" /
                          "config-valid.json")
        result = {"manifest": {"status": "audited", "snapshot_id": "abc123"},
                  "manifest_path": "data_cache/crypto/manifest.json"}
        with patch("crypto.cli.collect_snapshot", return_value=result) as collect:
            self.assertEqual(main(["--config", config_path, "--collect"]), 0)
        collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
