import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PLAYGROUND = None
TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp-tests" / "playground"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
if importlib.util.find_spec("crypto.playground") is not None:
    from crypto import playground as PLAYGROUND


class CryptoPlaygroundTests(unittest.TestCase):
    def validator(self):
        if PLAYGROUND is None:
            self.fail("crypto.playground validation API is missing")
        return PLAYGROUND.validate_playground_strategy

    def test_runner_api_exists(self):
        self.assertTrue(
            callable(getattr(PLAYGROUND, "run_playground", None)),
            "interactive development runner is missing",
        )

    def test_defaults_are_normalized_for_each_registered_strategy(self):
        validate = self.validator()
        self.assertEqual(validate("cash_zero", {}), {})
        self.assertEqual(validate("carry_static", {}), {
            "allocation_fraction": 0.25,
            "collateral_ratio": 1.0,
        })
        self.assertEqual(validate("funding_filter", {}), {
            "allocation_fraction": 0.25,
            "collateral_ratio": 1.0,
            "positive_funding_threshold": 0.0,
        })

    def test_valid_funding_filter_parameters_are_preserved(self):
        result = self.validator()(
            "funding_filter",
            {"allocation_fraction": 0.3, "collateral_ratio": 1.5,
             "positive_funding_threshold": 0.0001},
        )
        self.assertEqual(result["allocation_fraction"], 0.3)
        self.assertEqual(result["collateral_ratio"], 1.5)
        self.assertEqual(result["positive_funding_threshold"], 0.0001)

    def test_combined_allocation_and_collateral_must_leave_equity_reserve(self):
        with self.assertRaisesRegex(ValueError, "initial equity reserve"):
            self.validator()("carry_static", {
                "allocation_fraction": 0.5,
                "collateral_ratio": 2.0,
            })

    def test_market_basis_cannot_make_reserved_position_exceed_equity(self):
        with self.assertRaisesRegex(ValueError, "exceeds initial account equity"):
            PLAYGROUND._validate_position_affordability([{
                "spot_quantity": 50,
                "spot_entry_price": 10,
                "collateral": 600,
            }], 1000)

    def test_out_of_range_allocation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "allocation_fraction"):
            self.validator()("carry_static", {"allocation_fraction": 0})

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            self.validator()("carry_static", {"leverage": 5})

    def test_funding_threshold_outside_ui_bounds_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive_funding_threshold"):
            self.validator()("funding_filter", {"positive_funding_threshold": 0.1001})

    def test_boolean_numeric_parameter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "allocation_fraction"):
            self.validator()("carry_static", {"allocation_fraction": True})

    def test_unregistered_strategy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "registered"):
            self.validator()("arbitrary_python", {})

    @unittest.skipUnless(PLAYGROUND is not None and callable(getattr(PLAYGROUND, "run_playground", None)), "runner not implemented")
    def test_runner_uses_only_development_and_saves_outside_campaign_registry(self):
        if PLAYGROUND is None:
            self.fail("crypto.playground runner API is missing")
        config = {
            "market": {"exchange": "binance", "market_type": "spot_perpetual_carry",
                       "spot_symbol": "BTC/USDT", "perp_symbol": "BTC/USDT:USDT"},
            "data": {"root": "unused"},
            "costs": {"spot_fee_bps": 10, "perp_fee_bps": 5, "slippage_bps": 1},
            "campaign": {"initial_equity": 1000,
                         "cash_return_assumption_annual": 0},
        }
        snapshot = {
            "manifest": {"snapshot_id": "snapshot-test"},
            "manifest_path": "unused/manifest.json",
            "tables": {},
            "table_hashes": {"spot_ohlcv": "a" * 64, "perp_ohlcv": "b" * 64,
                             "mark_ohlcv": "c" * 64, "funding": "d" * 64},
        }
        split = {
            "policy": "chronological 60/20/20",
            "development": {"start": "2024-01-01T00:00:00Z",
                            "end": "2024-08-01T00:00:00Z"},
            "validation": {"start": "2024-08-01T00:00:00Z",
                           "end": "2024-10-01T00:00:00Z"},
            "holdout": {"start": "2024-10-01T00:00:00Z",
                        "end": "2025-01-01T00:00:00Z"},
        }
        trial_result = {
            "metrics": {"total_return": 0.01, "max_drawdown": -0.02},
            "attribution": {"funding": 12.5},
            "assumptions": {"spot_fee_bps": 10},
            "limitations": ["development-only fixture"],
            "risk_scenarios": [],
            "equity_series": [{"time": "2024-01-01T00:00:00Z", "equity": 1000}],
            "ledger": [],
        }
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp:
            with patch.object(PLAYGROUND, "_project_config", return_value=config, create=True), \
                 patch.object(PLAYGROUND, "_load_snapshot", return_value=snapshot, create=True), \
                 patch.object(PLAYGROUND, "_split_dates", return_value=split, create=True), \
                 patch.object(PLAYGROUND, "_build_strategy_events", return_value=([], []), create=True), \
                 patch.object(PLAYGROUND, "_execute_trial", return_value=trial_result, create=True) as execute:
                runner = getattr(PLAYGROUND, "run_playground", None)
                if not callable(runner):
                    self.fail("crypto.playground runner API is missing")
                record = runner(
                    "cash_zero", project_root=temp
                )
            execute.assert_called_once_with(
                config, snapshot, split, "development", "cash_zero", {},
                prepared_strategy=([], []),
            )
            trial_path = Path(record["artifact_paths"]["trial"])
            self.assertTrue(trial_path.is_file())
            self.assertEqual(
                trial_path.parent.parent,
                Path(temp) / "results" / "crypto" / "playground",
            )
            saved = json.loads(trial_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["stage"], "development")
            self.assertEqual(saved["status"], "development_only")
            self.assertEqual(saved["provenance"]["snapshot_id"], "snapshot-test")
            self.assertFalse((Path(temp) / "results" / "crypto" /
                              "campaign-registry").exists())

    @unittest.skipUnless(PLAYGROUND is not None and callable(getattr(PLAYGROUND, "run_playground", None)), "runner not implemented")
    def test_missing_audited_snapshot_fails_without_creating_result(self):
        if PLAYGROUND is None:
            self.fail("crypto.playground runner API is missing")
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp:
            with patch.object(PLAYGROUND, "_project_config",
                              return_value={"data": {"root": "missing"}}), \
                 patch.object(PLAYGROUND, "_load_snapshot",
                              side_effect=ValueError("audited manifest missing"), create=True):
                with self.assertRaisesRegex(ValueError, "manifest missing"):
                    getattr(PLAYGROUND, "run_playground", lambda **kwargs: self.fail("crypto.playground runner API is missing"))("cash_zero", project_root=temp)
            self.assertFalse((Path(temp) / "results" / "crypto" /
                              "playground").exists())


if __name__ == "__main__":
    unittest.main()
