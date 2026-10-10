"""Reports always expose the most recently executed successful artifact."""
import json
import tempfile
import unittest
from pathlib import Path

from crypto.report import build_report


def record(run_id, created_at, stage):
    return {
        "schema_version": "crypto-trial-v1", "run_id": run_id,
        "status": "succeeded", "created_at": created_at,
        "strategy": "carry_static", "stage": stage,
        "provenance": {"snapshot_id": "snap-1", "stage_range": {}},
        "metrics": {"start_time": "2025-01-01T00:00:00Z",
                    "end_time": "2025-02-01T00:00:00Z",
                    "total_return": 0.01, "cagr": 0.12,
                    "max_drawdown": -0.02,
                    "annualized_volatility": 0.1, "sharpe_daily": 0.8},
        "attribution": {"funding": "2.5"}, "risk_scenarios": [],
        "limitations": [], "ledger_path": "ledger.csv",
    }


class CryptoReportTests(unittest.TestCase):
    def test_report_shows_sample_length_and_metric_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trial = record("holdout-sample", "2026-10-01T00:00:00Z", "holdout")
            trial["metrics"].update({
                "daily_return_count": 275,
                "annualization_basis": "365-day UTC daily returns",
                "max_drawdown_basis": "UTC daily close samples including initial equity",
                "limitations": ["less than one year; annualized metrics are unstable"],
            })
            (root / "holdout-001.json").write_text(json.dumps(trial), encoding="utf-8")
            build_report(str(root))
            report = (root / "report.md").read_text(encoding="utf-8")
        self.assertIn("275 daily samples", report)
        self.assertIn("UTC daily close samples including initial equity", report)
        self.assertIn("annualized metrics are unstable", report)

    def test_report_selects_newer_holdout_even_when_filename_sorts_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trial-009.json").write_text(
                json.dumps(record("dev-009", "2026-01-01T00:00:00Z", "validation")),
                encoding="utf-8")
            (root / "holdout-010.json").write_text(
                json.dumps(record("holdout-once", "2026-01-02T00:00:00Z", "holdout")),
                encoding="utf-8")

            artifacts = build_report(str(root))

            facts = json.loads(Path(artifacts["facts_path"]).read_text(encoding="utf-8"))
            report = Path(artifacts["report_path"]).read_text(encoding="utf-8")
            self.assertEqual(facts["run_id"], "holdout-once")
            self.assertIn("holdout-once", report)
            self.assertEqual(facts["evidence"]["metrics"]["file"], "holdout-010.json")


if __name__ == "__main__":
    unittest.main()
