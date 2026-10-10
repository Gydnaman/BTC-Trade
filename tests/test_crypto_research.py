"""Campaign budget, immutable contracts and one-time holdout contracts."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from crypto.ledger import replay_events
from crypto.research import (REGISTERED_STRATEGIES, _assert_research_availability,
                             _build_strategy_events, _risk_scenarios,
                             _write_ledger_csv,
                             evaluate_holdout, freeze_candidate, run_trial)


def config(root, *, stage="development", strategy="cash_zero", budget=10):
    return {
        "market": {"exchange": "binance", "market_type": "spot_perpetual_carry",
                   "spot_symbol": "BTC/USDT", "perp_symbol": "BTC/USDT:USDT"},
        "data": {"mode": "real_snapshot", "root": "unused", "timeframe": "1h",
                 "start": "2023-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z",
                 "known_gaps": []},
        "costs": {"spot_fee_bps": 10, "perp_fee_bps": 5,
                  "slippage_bps": 1},
        "campaign": {"initial_equity": 1000, "max_attempts": budget,
                     "campaign_id": "carry-contract-test", "registry_root": str(root),
                     "stage": stage, "strategy": strategy, "parameters": {}},
    }


def fake_snapshot(snapshot_id="snapshot-a"):
    return {"manifest": {"status": "audited", "snapshot_id": snapshot_id,
                          "config": {"market": {
                              "exchange": "binance", "market_type": "spot_perpetual_carry",
                              "spot_symbol": "BTC/USDT", "perp_symbol": "BTC/USDT:USDT"}},
                          "tables": {"spot_ohlcv": {"sha256": "a" * 64},
                                     "perp_ohlcv": {"sha256": "b" * 64},
                                     "mark_ohlcv": {"sha256": "c" * 64},
                                     "funding": {"sha256": "d" * 64}}},
            "manifest_path": "snapshot/manifest.json", "tables": {}}


def fake_trial(*args, **kwargs):
    strategy = args[4] if len(args) > 4 else "cash_zero"
    outcomes = {"cash_zero": (0.01, -0.01),
                "carry_static": (0.03, -0.10),
                "funding_filter": (0.03, -0.04)}
    total_return, drawdown = outcomes[strategy]
    return {"metrics": {"final_equity": 1000, "total_return": total_return,
                        "start_time": "2023-01-01T00:00:00Z",
                        "end_time": "2024-01-01T00:00:00Z",
                        "max_drawdown": drawdown},
            "equity_series": [], "ledger": [], "positions": [],
            "attribution": {}, "risk_scenarios": [], "assumptions": {},
            "limitations": ["test executor; not a research result"]}


def run_all_baselines(cfg, output_dir):
    for strategy in ("cash_zero", "carry_static", "funding_filter"):
        cfg["campaign"]["strategy"] = strategy
        for stage in ("development", "validation"):
            cfg["campaign"]["stage"] = stage
            run_trial(cfg, str(output_dir))


class CryptoResearchTests(unittest.TestCase):
    def test_stress_equity_includes_uncommitted_account_cash(self):
        costs = {"spot_fee_bps": 0, "perp_fee_bps": 0, "slippage_bps": 0}
        cash = _risk_scenarios([], costs, 1000)
        self.assertEqual(cash[0]["account_equity_after_scenario"], "1000")

        group = {"group_id": "carry", "spot_quantity": 2,
                 "perp_quantity": -2, "spot_entry_price": 100,
                 "perp_entry_price": 100, "spot_price": 100,
                 "perp_mark_price": 100, "collateral": 200}
        stressed = _risk_scenarios([group], costs, 1000)
        self.assertEqual(stressed[0]["account_equity_after_scenario"], "1000")
        self.assertEqual(stressed[1]["account_equity_after_scenario"], "1000")

    def test_only_three_registered_baselines_are_executable(self):
        self.assertEqual(set(REGISTERED_STRATEGIES),
                         {"cash_zero", "carry_static", "funding_filter"})
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(Path(tmp), strategy="arbitrary_code")
            with patch("crypto.research._load_snapshot", return_value=fake_snapshot()), \
                    self.assertRaisesRegex(ValueError, "registered baseline"):
                run_trial(cfg, str(Path(tmp) / "artifacts"))
            events = (Path(tmp) / "carry-contract-test" / "events.jsonl").read_text()
            self.assertIn('"event": "attempt_finished"', events)
            self.assertIn('"status": "failed"', events)

    def test_attempt_budget_is_shared_across_output_directory_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root, budget=1)
            with patch("crypto.research._load_snapshot", return_value=fake_snapshot()), \
                    patch("crypto.research._execute_trial", side_effect=fake_trial):
                run_trial(cfg, str(root / "first-output"))
                with self.assertRaisesRegex(ValueError, "budget exhausted"):
                    run_trial(cfg, str(root / "different-output"))
            events = [json.loads(line) for line in
                      (root / "carry-contract-test" / "events.jsonl").read_text().splitlines()]
            starts = [event for event in events if event["event"] == "attempt_started"]
            self.assertEqual(len(starts), 2)
            self.assertEqual([event["attempt"] for event in starts], [1, 2])

    def test_dataset_change_does_not_reuse_the_campaign_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root, budget=3)
            with patch("crypto.research._load_snapshot",
                       side_effect=[fake_snapshot("snapshot-a"),
                                    fake_snapshot("snapshot-b")]), \
                    patch("crypto.research._execute_trial", side_effect=fake_trial):
                run_trial(cfg, str(root / "runs"))
                with self.assertRaisesRegex(ValueError, "contract changed"):
                    run_trial(cfg, str(root / "runs"))
            events = [json.loads(line) for line in
                      (root / "carry-contract-test" / "events.jsonl").read_text().splitlines()]
            self.assertEqual(sum(event["event"] == "attempt_started" for event in events), 2)

    def test_holdout_is_inaccessible_before_freeze_and_once_after_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root, stage="development", strategy="carry_static", budget=10)
            with patch("crypto.research._load_snapshot", return_value=fake_snapshot()), \
                    patch("crypto.research._execute_trial", side_effect=fake_trial):
                with self.assertRaisesRegex(ValueError, "candidate must be frozen"):
                    evaluate_holdout(cfg, str(root / "runs"))
                run_all_baselines(cfg, root / "runs")
                candidate = freeze_candidate(cfg, str(root / "runs"))
                self.assertEqual(candidate["strategy"], "funding_filter")
                cfg["campaign"]["stage"] = "validation"
                with self.assertRaisesRegex(ValueError, "already frozen"):
                    run_trial(cfg, str(root / "runs"))
                first = evaluate_holdout(cfg, str(root / "runs"))
                self.assertEqual(first["status"], "holdout_evaluated_once")
                facts = json.loads(Path(first["artifact_paths"]["facts_path"]).read_text())
                self.assertEqual(facts["run_id"], "carry-contract-test-holdout-once")
                with self.assertRaisesRegex(ValueError, "already been opened"):
                    evaluate_holdout(cfg, str(root / "runs"))
            events = [json.loads(line) for line in
                      (root / "carry-contract-test" / "events.jsonl").read_text().splitlines()]
            self.assertEqual(sum(event["event"] == "holdout_evaluation_started"
                                 for event in events), 1)

    def test_freeze_requires_a_successful_validation_trial_for_same_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root, stage="development", strategy="carry_static")
            with patch("crypto.research._load_snapshot", return_value=fake_snapshot()), \
                    patch("crypto.research._execute_trial", side_effect=fake_trial):
                run_trial(cfg, str(root / "runs"))
                with self.assertRaisesRegex(ValueError, "development and validation"):
                    freeze_candidate(cfg, str(root / "runs"))

    def test_changed_campaign_artifact_directory_does_not_change_registry_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root, budget=2)
            cfg["campaign"]["stage"] = "holdout"
            with patch("crypto.research._load_snapshot", return_value=fake_snapshot()):
                with self.assertRaisesRegex(ValueError, "cannot run holdout through run_trial"):
                    run_trial(cfg, str(root / "one"))
                with self.assertRaisesRegex(ValueError, "cannot run holdout through run_trial"):
                    run_trial(cfg, str(root / "two"))
            events = [json.loads(line) for line in
                      (root / "carry-contract-test" / "events.jsonl").read_text().splitlines()]
            self.assertEqual(sum(event["event"] == "attempt_started" for event in events), 2)

    def test_result_affecting_risk_free_assumption_is_in_campaign_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root)
            with patch("crypto.research._load_snapshot", return_value=fake_snapshot()), \
                    patch("crypto.research._execute_trial", side_effect=fake_trial):
                run_trial(cfg, str(root / "runs"))
                cfg["campaign"]["cash_return_assumption_annual"] = 0.02
                with self.assertRaisesRegex(ValueError, "contract changed"):
                    run_trial(cfg, str(root / "runs"))

    def test_snapshot_market_must_match_the_configured_instrument(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config(root)
            snapshot = fake_snapshot()
            snapshot["manifest"]["config"]["market"]["spot_symbol"] = "ETH/USDT"
            with patch("crypto.research._load_snapshot", return_value=snapshot), \
                    self.assertRaisesRegex(ValueError, "market does not match"):
                run_trial(cfg, str(root / "runs"))

    def test_delayed_market_availability_is_rejected_by_research_assumptions(self):
        tables = {name: [{"close_time": "2025-01-01T01:00:00Z",
                          "available_time": "2025-01-01T02:00:00Z"}]
                  for name in ("spot_ohlcv", "perp_ohlcv", "mark_ohlcv")}
        tables["funding"] = [{"settlement_time": "2025-01-01T00:00:00Z",
                              "available_time": "2025-01-01T01:00:00Z"}]
        with self.assertRaisesRegex(ValueError, "publication-at-close"):
            _assert_research_availability(tables)

    def test_funding_filter_releases_collateral_after_each_flatten(self):
        origin = datetime(2025, 1, 1, tzinfo=timezone.utc)

        def stamp(hour):
            return (origin + timedelta(hours=hour)).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z")

        def bars():
            return [{"open_time": stamp(hour), "close_time": stamp(hour + 1),
                     "available_time": stamp(hour + 1), "open": 100, "high": 100,
                     "low": 100, "close": 100, "volume": 1}
                    for hour in range(10)]

        rows = bars()
        funding = [{"settlement_time": stamp(hour),
                    "available_time": stamp(hour),
                    "rate": "0.001" if hour % 2 == 0 else "-0.001",
                    "mark_price": "100", "mark_price_source": "funding_endpoint",
                    "mark_price_is_proxy": False, "mark_price_source_time": None}
                   for hour in range(8)]
        config_data = {"campaign": {"initial_equity": 1000},
                       "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                                 "slippage_bps": 0},
                       "data": {"known_gaps": []}}
        tables = {"spot_ohlcv": rows, "perp_ohlcv": rows,
                  "mark_ohlcv": rows, "funding": funding}
        stage = {"start": stamp(0), "end": stamp(10)}
        events, groups = _build_strategy_events(
            config_data, tables, stage, "funding_filter", {})
        replay = replay_events(events, config_data)
        rejected = [row for row in replay["ledger"]
                    if row["kind"] in {"spot_fill", "perp_fill", "collateral_transfer"}
                    and row["status"] != "applied"]
        self.assertEqual(rejected, [])
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(row["spot_quantity"] == "0" and
                            row["perp_quantity"] == "0" and
                            row["collateral"] == "0"
                            for row in replay["positions"]))

    def test_csv_ledger_preserves_funding_mark_provenance_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.csv"
            _write_ledger_csv(path, [{"event_time": "2025-01-01T00:00:00Z",
                                      "kind": "funding", "sequence": 0,
                                      "details": {"mark_price_source": "mark_ohlcv.open_proxy",
                                                  "mark_price_is_proxy": True,
                                                  "mark_price_source_time": "2025-01-01T00:00:00Z"}}])
            import csv
            with path.open(encoding="utf-8", newline="") as handle:
                detail = json.loads(next(csv.DictReader(handle))["details"])
            self.assertTrue(detail["mark_price_is_proxy"])
            self.assertEqual(detail["mark_price_source"], "mark_ohlcv.open_proxy")


if __name__ == "__main__":
    unittest.main()
