"""Read-only campaign catalog and dashboard evidence shaping."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from crypto.ui.catalog import load_campaign_catalog
from crypto.ui.view_model import build_dashboard_model


class CryptoUiViewModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "campaign"
        self.root.mkdir()

    def write_trial(self, stem="trial-001", *, status="succeeded",
                    equity_series=None, ledger_path=None, risk_scenarios=None):
        ledger = self.root / f"{stem}-ledger.csv"
        with ledger.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "event_time", "kind", "status", "details", "equity",
                "spot_pnl", "perp_pnl", "funding", "spot_fees",
                "perp_fees", "slippage", "perp_collateral",
                "spot_quantity", "perp_quantity",
            ])
            writer.writeheader()
            writer.writerows([
                {"event_time": "2025-01-01T08:00:00Z", "kind": "funding",
                 "status": "applied", "details": json.dumps({"cashflow": "1.25"}),
                 "equity": "1001.25", "spot_pnl": "0", "perp_pnl": "0",
                 "funding": "1.25", "spot_fees": "0", "perp_fees": "0",
                 "slippage": "0", "perp_collateral": "0",
                 "spot_quantity": "0", "perp_quantity": "0"},
                {"event_time": "2025-01-02T08:00:00Z", "kind": "funding",
                 "status": "applied", "details": json.dumps({"cashflow": "-0.25"}),
                 "equity": "1001.00", "spot_pnl": "0", "perp_pnl": "0",
                 "funding": "1.00", "spot_fees": "0", "perp_fees": "0",
                 "slippage": "0", "perp_collateral": "0",
                 "spot_quantity": "0", "perp_quantity": "0"},
                {"event_time": "2025-01-02T09:00:00Z", "kind": "funding",
                 "status": "rejected", "details": json.dumps({"cashflow": "9"}),
                 "equity": "1001.00", "spot_pnl": "0", "perp_pnl": "0",
                 "funding": "1.00", "spot_fees": "0", "perp_fees": "0",
                 "slippage": "0", "perp_collateral": "0",
                 "spot_quantity": "0", "perp_quantity": "0"},
                {"event_time": "2025-01-03T00:00:00Z", "kind": "funding",
                 "status": "applied", "details": json.dumps({"cashflow": "-0.10"}),
                 "equity": "1001.00", "spot_pnl": "0", "perp_pnl": "0",
                 "funding": "0.90", "spot_fees": "0", "perp_fees": "0",
                 "slippage": "0", "perp_collateral": "0",
                 "spot_quantity": "0", "perp_quantity": "0"},
            ])
        record = {
            "run_id": f"run-{stem}", "status": status, "stage": "validation",
            "strategy": "carry_static", "created_at": "2025-01-04T00:00:00Z",
            "metrics": {
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-03T00:00:00Z",
                "initial_equity": "1000", "final_equity": "1001",
                "total_return": "0.001", "cagr": "0.1",
                "max_drawdown": "-0.002", "sharpe_daily": "1.5",
                "annualized_volatility": "0.02",
                "daily_return_count": 2, "elapsed_days": 2,
                "average_collateral_utilization": "0.2", "peak_residual_delta": "0",
                "annualization_basis": "365-day UTC daily returns",
                "max_drawdown_basis": "UTC daily close samples including initial equity",
                "limitations": ["annualized metrics are unstable for this sample"],
            },
            "attribution": {"funding": "0.9", "spot_pnl": "-0.2",
                            "perp_pnl": "0.3", "spot_fees": "0.05",
                            "perp_fees": "0.03", "slippage": "0.02"},
            "risk_scenarios": risk_scenarios if risk_scenarios is not None else [],
            "assumptions": {"perp_fee_bps": 5, "slippage_bps": 1},
            "provenance": {"snapshot_id": "snapshot-test",
                           "market": "BTC/USDT"},
            "equity_series": equity_series if equity_series is not None else [
                {"time": "2025-01-01T00:00:00Z", "equity": "1000.00"},
                {"time": "2025-01-02T00:00:00Z", "equity": "1001.25"},
                {"time": "2025-01-03T00:00:00Z", "equity": "1001.00"},
            ],
            "ledger_path": str(ledger_path or ledger.name),
        }
        trial_file = self.root / f"{stem}.json"
        trial_file.write_text(json.dumps(record), encoding="utf-8")
        audit = {
            "run_id": record["run_id"], "stage": record["stage"],
            "strategy": record["strategy"],
            "snapshot_id": record["provenance"]["snapshot_id"],
            "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
            "status": "no_breach_observed_under_declared_margin_proxy",
            "breach_observations": 0, "mark_observations": 0,
        }
        (self.root / f"{stem}-margin-audit.json").write_text(
            json.dumps(audit), encoding="utf-8")
        campaign_path = self.root / "campaign-feasibility.json"
        if campaign_path.is_file():
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        else:
            campaign = {
                "schema_version": "crypto-campaign-feasibility-v1",
                "snapshot_id": "snapshot-test", "candidate_strategy": "carry_static",
                "status": "candidate_has_margin_breaches",
                "candidate_breach_stages": ["development"],
                "stages": {"development": {}, "validation": {}, "holdout": {}},
                "trial_audits": [],
            }
        campaign["trial_audits"] = [
            item for item in campaign["trial_audits"]
            if item.get("run_id") != audit["run_id"]
        ]
        campaign["trial_audits"].append(audit)
        campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
        facts_path = self.root / "facts.json"
        facts_path.write_text(json.dumps({
            "schema_version": "crypto-facts-v1",
            "provenance": {"snapshot_id": "snapshot-test"},
        }), encoding="utf-8")
        return trial_file

    def test_catalog_lists_only_successful_trials_and_keeps_verified_paths(self):
        self.write_trial("trial-001")
        self.write_trial("trial-002", status="failed")

        catalog = load_campaign_catalog(str(self.root))

        self.assertEqual([row["trial_id"] for row in catalog["trials"]], ["trial-001"])
        self.assertEqual(catalog["trials"][0]["ledger_file"], "trial-001-ledger.csv")

    def test_catalog_rejects_ledger_paths_outside_campaign_directory(self):
        outside = Path(self.temp.name) / "outside.csv"
        outside.write_text("not,used\n", encoding="utf-8")
        self.write_trial("trial-001", ledger_path=outside)

        with self.assertRaisesRegex(ValueError, "inside campaign directory"):
            load_campaign_catalog(str(self.root))

    def test_catalog_rejects_margin_audit_symlink_outside_campaign(self):
        self.write_trial("trial-001")
        outside = Path(self.temp.name) / "outside-audit.json"
        outside.write_text("{}", encoding="utf-8")
        audit_path = self.root / "trial-001-margin-audit.json"
        audit_path.unlink()
        try:
            audit_path.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")

        with self.assertRaisesRegex(ValueError, "inside campaign directory"):
            load_campaign_catalog(str(self.root))

    def test_catalog_requires_matching_campaign_snapshot(self):
        self.write_trial("trial-001")
        campaign_path = self.root / "campaign-feasibility.json"
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        campaign["snapshot_id"] = "different-snapshot"
        campaign_path.write_text(json.dumps(campaign), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "campaign snapshot"):
            load_campaign_catalog(str(self.root))

    def test_catalog_requires_facts_for_the_campaign_snapshot(self):
        self.write_trial("trial-001")
        facts_path = self.root / "facts.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        facts["provenance"]["snapshot_id"] = "different-snapshot"
        facts_path.write_text(json.dumps(facts), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "facts snapshot"):
            load_campaign_catalog(str(self.root))

    def test_catalog_can_skip_global_facts_for_stage_scoped_consumers(self):
        self.write_trial("trial-001")
        (self.root / "facts.json").write_text(
            '{"holdout": "must not be loaded"}', encoding="utf-8")
        (self.root / "holdout-001.json").write_text(
            "sealed holdout content must not be parsed", encoding="utf-8")

        catalog = load_campaign_catalog(
            str(self.root), include_facts=False, include_holdout=False)

        self.assertEqual([row["trial_id"] for row in catalog["trials"]], ["trial-001"])
        self.assertNotIn("facts_file", catalog)

    def test_dashboard_filters_equity_and_applied_funding_by_inclusive_utc_dates(self):
        self.write_trial("trial-001")

        model = build_dashboard_model(str(self.root), "trial-001",
                                      "2025-01-02", "2025-01-02")

        self.assertEqual(model["summary"]["total_return"], "0.001")
        self.assertEqual(model["equity_series"], [
            {"time": "2025-01-02T00:00:00Z", "equity": 1001.25},
            {"time": "2025-01-03T00:00:00Z", "equity": 1001.0},
        ])
        self.assertEqual(model["funding_series"], [
            {"date": "2025-01-02", "cashflow":  -0.35},
        ])
        self.assertEqual(model["selected_summary"]["initial_equity"], 1001.25)
        self.assertEqual(model["selected_summary"]["final_equity"], 1001.0)
        self.assertAlmostEqual(
            model["selected_summary"]["total_return"], 1001.0 / 1001.25 - 1)
        self.assertEqual(model["selected_summary"]["daily_return_count"], 1)
        self.assertEqual(
            {row["component"]: row["amount"] for row in model["attribution_rows"]}
            ["funding"], -0.35)
        self.assertEqual(model["selected_summary"]["funding"], -0.35)
        self.assertEqual(model["risk_scenarios"], [])
        self.assertEqual(model["metric_limitations"], [
            "annualized metrics are unstable for this sample",
        ])
        self.assertEqual(model["campaign_feasibility"]["candidate_breach_stages"],
                         ["development"])

    def test_full_date_range_uses_the_same_daily_closes_as_trial_metrics(self):
        self.write_trial("trial-001")

        model = build_dashboard_model(str(self.root), "trial-001")

        self.assertEqual(model["coverage"], {
            "start": "2025-01-01", "end": "2025-01-02",
        })
        self.assertEqual(model["selected_summary"]["daily_return_count"],
                         model["summary"]["daily_return_count"])
        self.assertAlmostEqual(model["selected_summary"]["total_return"],
                               float(model["summary"]["total_return"]))
        self.assertEqual(model["selected_summary"]["funding"], 0.9)

    def test_zero_variance_window_reports_zero_volatility(self):
        self.write_trial("trial-001", equity_series=[
            {"time": "2025-01-01T00:00:00Z", "equity": "1000"},
            {"time": "2025-01-02T00:00:00Z", "equity": "1000"},
            {"time": "2025-01-03T00:00:00Z", "equity": "1000"},
        ])

        model = build_dashboard_model(str(self.root), "trial-001")

        self.assertEqual(model["selected_summary"]["annualized_volatility"], 0.0)
        self.assertIsNone(model["selected_summary"]["sharpe_daily"])

    def test_dashboard_rejects_missing_equity_fields(self):
        self.write_trial("trial-001", equity_series=[{"time": "2025-01-01T00:00:00Z"}])

        with self.assertRaisesRegex(ValueError, "equity"):
            build_dashboard_model(str(self.root), "trial-001")

    def test_dashboard_rejects_missing_required_metrics_and_attribution(self):
        self.write_trial("trial-001")
        trial_path = self.root / "trial-001.json"
        record = json.loads(trial_path.read_text(encoding="utf-8"))
        del record["metrics"]["total_return"]
        trial_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metrics.total_return"):
            build_dashboard_model(str(self.root), "trial-001")

        record["metrics"]["total_return"] = "0.001"
        del record["attribution"]["funding"]
        trial_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "attribution.funding"):
            build_dashboard_model(str(self.root), "trial-001")

    def test_dashboard_rejects_non_finite_or_out_of_coverage_equity(self):
        for equity_series, error in (
            ([{"time": "2025-01-01T00:00:00Z", "equity": "NaN"}], "finite"),
            ([{"time": "2024-12-31T23:00:00Z", "equity": "1000"}], "coverage"),
            ([{"time": "2025-01-02T00:00:00Z", "equity": "1000"},
              {"time": "2025-01-01T00:00:00Z", "equity": "1000"}], "ordered"),
        ):
            with self.subTest(error=error):
                self.write_trial("trial-001", equity_series=equity_series)
                with self.assertRaisesRegex(ValueError, error):
                    build_dashboard_model(str(self.root), "trial-001")
                for path in self.root.iterdir():
                    path.unlink()

    def test_dashboard_rejects_dates_outside_audited_coverage(self):
        self.write_trial("trial-001")

        with self.assertRaisesRegex(ValueError, "coverage"):
            build_dashboard_model(str(self.root), "trial-001", "2024-12-31", "2025-01-02")

    def test_catalog_requires_campaign_feasibility_artifact(self):
        self.write_trial("trial-001")
        (self.root / "campaign-feasibility.json").unlink()

        with self.assertRaisesRegex(ValueError, "campaign-feasibility"):
            load_campaign_catalog(str(self.root))


if __name__ == "__main__":
    unittest.main()
