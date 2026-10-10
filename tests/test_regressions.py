"""Offline, hand-calculable contracts for the initial engineering milestone."""
import unittest
import numpy as np
import pandas as pd

from strategy.ma_cross import MACrossStrategy
from strategy.momentum import MomentumStrategy
from backtest.backtester import Backtester
from config.settings import BacktestConfig
from execution.broker import Order, SimulatedBroker


class StrategyTests(unittest.TestCase):
    def test_future_prices_do_not_change_past_signals(self):
        data = pd.DataFrame({'A': [3., 2, 1, 2, 3, 2, 1], 'B': [1., 2, 3, 2, 1, 2, 3]})
        changed = data.copy()
        changed.iloc[5:] *= 100
        for strategy in [MACrossStrategy(1, 2), MomentumStrategy(1, 1, 1)]:
            left = data if isinstance(strategy, MomentumStrategy) else data.A.to_frame('close')
            right = changed if isinstance(strategy, MomentumStrategy) else changed.A.to_frame('close')
            pd.testing.assert_frame_equal(strategy.generate_signals(left).iloc[:5],
                                          strategy.generate_signals(right).iloc[:5])

    def test_death_cross_exits(self):
        data = pd.DataFrame({'close': [3, 2, 1, 2, 3, 2, 1]})
        self.assertEqual(MACrossStrategy(1, 2).generate_signals(data).weight.tolist(),
                         [0, 0, 0, 1, 1, 0, 0])

    def test_rotation_exits_deselected_asset(self):
        data = pd.DataFrame({'A': [1, 2, 2, 2], 'B': [1, 1, 2, 2]})
        result = MomentumStrategy(1, 1, 1).generate_signals(data)
        self.assertEqual(result.iloc[2].tolist(), [0, 1])
        self.assertTrue((result.sum(axis=1) <= 1).all())
        self.assertTrue(np.isfinite(result.to_numpy()).all())

    def test_unselected_columns_are_numeric_zero(self):
        data = pd.DataFrame({'A': [1, 2, 4], 'B': [1, 1, 1]})
        result = MomentumStrategy(1, 1, 1).generate_signals(data)
        self.assertEqual(result.B.tolist(), [0, 0, 0])


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.prices = pd.DataFrame({'A': [100.] * 4},
                                   index=pd.date_range('2024-01-01', periods=4))
        self.config = BacktestConfig(commission_rate=0, slippage=0, stamp_duty=.001)

    def test_half_position_sale_tax_is_linear(self):
        signals = pd.DataFrame({'A': [.5, 0, 0, 0]}, index=self.prices.index)
        result = Backtester(self.config).run(self.prices, signals)
        self.assertAlmostEqual(result.daily_returns.iloc[2], -.0005)

    def test_one_row_is_valid_flat_result(self):
        result = Backtester().run(self.prices.iloc[:1], self.prices.iloc[:1] * 0)
        self.assertEqual(result.metrics['总收益率'], 0)
        self.assertEqual(result.portfolio_value.iloc[0], 1_000_000)

    def test_invalid_prices_rejected(self):
        for value in [0, -1, np.nan, np.inf]:
            with self.subTest(value=value):
                prices = self.prices.copy()
                prices.iloc[1, 0] = value
                with self.assertRaises(ValueError):
                    Backtester().run(prices, self.prices * 0)


class BrokerTests(unittest.TestCase):
    def test_invalid_orders_do_not_mutate_account(self):
        orders = [Order('A', 'BUY', q) for q in [-1, 0, np.nan, np.inf]]
        orders += [Order('A', 'HOLD', 1), Order('A', 'BUY', 1, 'BOGUS')]
        for order in orders:
            with self.subTest(order=order):
                broker = SimulatedBroker(1000)
                broker.update_price('A', 100)
                broker.place_order(order)
                self.assertEqual(order.status, 'REJECTED')
                self.assertEqual(broker.account.cash, 1000)
                self.assertEqual(broker.get_position('A').quantity, 0)

    def test_non_marketable_limit_waits_then_fills(self):
        broker = SimulatedBroker(1000)
        broker.update_price('A', 100)
        order = Order('A', 'BUY', 1, 'LIMIT', 90)
        broker.place_order(order)
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(broker.account.cash, 1000)
        broker.update_price('A', 85)
        self.assertEqual(order.status, 'FILLED')
        self.assertEqual(broker.account.cash, 910)

    def test_invalid_quote_rejected(self):
        broker = SimulatedBroker()
        for price in [0, -1, np.nan, np.inf]:
            with self.subTest(price=price), self.assertRaises(ValueError):
                broker.update_price('A', price)


if __name__ == '__main__':
    unittest.main()
