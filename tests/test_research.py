import tempfile
import unittest
from pathlib import Path
import pandas as pd


class ResearchTests(unittest.TestCase):
    def test_runs_are_reproducible_and_bounded(self):
        from harness.research import run_experiment
        prices = pd.DataFrame({'A': [3., 2, 1, 2, 3, 2, 1]},
                              index=pd.date_range('2024-01-01', periods=7))
        with tempfile.TemporaryDirectory() as tmp:
            first = run_experiment(prices, 'ma_cross', {'short_window': 1, 'long_window': 2}, Path(tmp), max_trials=2)
            second = run_experiment(prices, 'ma_cross', {'short_window': 1, 'long_window': 2}, Path(tmp), max_trials=2)
            self.assertEqual(first['metrics'], second['metrics'])
            self.assertEqual(first['data_hash'], second['data_hash'])
            self.assertEqual(first['status'], 'development_only')
            with self.assertRaises(ValueError):
                run_experiment(prices, 'ma_cross', {}, Path(tmp), max_trials=2)

    def test_changed_dataset_cannot_share_experiment(self):
        from harness.research import run_experiment
        prices = pd.DataFrame({'A': [100., 101, 102]},
                              index=pd.date_range('2024-01-01', periods=3))
        with tempfile.TemporaryDirectory() as tmp:
            run_experiment(prices, 'ma_cross', {}, Path(tmp))
            prices.iloc[-1, 0] = 200
            with self.assertRaises(ValueError):
                run_experiment(prices, 'ma_cross', {}, Path(tmp))
