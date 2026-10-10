"""Financial metric definitions and edge-case reporting contracts."""
import unittest
from datetime import datetime, timedelta, timezone

from crypto.metrics import evaluate_metrics


class CryptoMetricsTests(unittest.TestCase):
    def test_first_observation_includes_initial_fee_drawdown(self):
        metrics = evaluate_metrics([
            {"time": "2024-01-01T00:00:00Z", "equity": "999"},
            {"time": "2024-01-02T00:00:00Z", "equity": "1000"},
        ], 1000)
        self.assertAlmostEqual(metrics["max_drawdown"], -0.001)
        self.assertEqual(metrics["daily_return_count"], 2)

    def test_constant_equity_has_undefined_sharpe_and_volatility(self):
        metrics = evaluate_metrics([
            {"time": "2024-01-01T00:00:00Z", "equity": "1000"},
            {"time": "2024-01-02T00:00:00Z", "equity": "1000"},
            {"time": "2024-01-03T00:00:00Z", "equity": "1000"},
        ], 1000)
        self.assertIsNone(metrics["sharpe_daily"])
        self.assertEqual(metrics["annualized_volatility"], 0.0)
        self.assertIn("zero variance", " ".join(metrics["limitations"]))

    def test_cagr_uses_actual_elapsed_time(self):
        metrics = evaluate_metrics([
            {"time": "2024-01-01T00:00:00Z", "equity": "100"},
            {"time": "2025-01-01T00:00:00Z", "equity": "110"},
        ], 100)
        expected = 1.1 ** (365.25 / 366) - 1
        self.assertAlmostEqual(metrics["cagr"], expected, places=10)
        self.assertEqual(metrics["elapsed_days"], 366)

    def test_drawdown_uses_actual_equity_path_and_daily_sharpe(self):
        metrics = evaluate_metrics([
            {"time": "2024-01-01T00:00:00Z", "equity": "100"},
            {"time": "2024-01-02T00:00:00Z", "equity": "110"},
            {"time": "2024-01-03T00:00:00Z", "equity": "99"},
            {"time": "2024-01-04T00:00:00Z", "equity": "108"},
        ], 100)
        self.assertAlmostEqual(metrics["max_drawdown"], -0.1)
        self.assertIsNotNone(metrics["sharpe_daily"])
        self.assertEqual(metrics["annualization_basis"], "365-day UTC daily returns")

    def test_invalid_equity_series_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            evaluate_metrics([
                {"time": "2024-01-02T00:00:00Z", "equity": "100"},
                {"time": "2024-01-01T00:00:00Z", "equity": "101"},
            ], 100)

    def test_explicit_period_end_midnight_closes_previous_day_not_extra_day(self):
        start = "2025-01-01T00:00:00Z"
        end = "2025-04-01T00:00:00Z"
        origin = datetime(2025, 1, 1, tzinfo=timezone.utc)
        points = [{"time": start, "equity": "1000"}]
        points.extend({"time": (origin + timedelta(days=day)).isoformat().replace(
            "+00:00", "Z"), "equity": "1000"} for day in range(1, 91))
        metrics = evaluate_metrics(points, 1000, start_time=start)
        self.assertEqual(metrics["daily_return_count"], 90)
        self.assertEqual(metrics["end_time"], end)


if __name__ == "__main__":
    unittest.main()
