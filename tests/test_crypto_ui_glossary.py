"""Plain-language labels for the crypto dashboard."""
import unittest

from crypto.ui.glossary import (
    ATTRIBUTION_LABELS,
    DASHBOARD_FIELD_GLOSSARY,
    DASHBOARD_FIELD_LABELS,
    COMPARISON_FIELD_GLOSSARY,
    RISK_FIELD_GLOSSARY,
    SCENARIO_DESCRIPTIONS,
    SCENARIO_LABELS,
    STAGE_LABELS,
    STRATEGY_LABELS,
)


class CryptoUiGlossaryTests(unittest.TestCase):
    def test_every_registered_strategy_and_stage_has_a_chinese_label(self):
        self.assertEqual(set(STRATEGY_LABELS), {
            "cash_zero", "carry_static", "funding_filter",
        })
        self.assertEqual(set(STAGE_LABELS), {
            "development", "validation", "holdout",
        })
        self.assertTrue(all(STRATEGY_LABELS.values()))
        self.assertTrue(all(STAGE_LABELS.values()))

    def test_every_risk_scenario_has_a_plain_language_name_and_definition(self):
        scenario_codes = {
            "base", "price_gap_up_20pct", "basis_expansion_against_short",
            "negative_funding", "spot_data_outage", "slippage_1bps",
            "slippage_5bps", "slippage_15bps",
            "perpetual_entry_timeout_after_spot_fill",
        }
        self.assertEqual(set(SCENARIO_LABELS), scenario_codes)
        self.assertEqual(set(SCENARIO_DESCRIPTIONS), scenario_codes)
        self.assertTrue(all(SCENARIO_LABELS.values()))
        self.assertTrue(all(SCENARIO_DESCRIPTIONS.values()))

    def test_dashboard_and_risk_table_columns_are_documented(self):
        self.assertTrue({
            "total_return", "cagr", "max_drawdown", "sharpe_daily",
            "funding", "spot_pnl", "perp_pnl", "spot_fees",
            "perp_fees", "slippage",
        }.issubset(DASHBOARD_FIELD_GLOSSARY))
        self.assertEqual(set(RISK_FIELD_GLOSSARY), {
            "scenario", "net_delta", "collateral_shortfall",
            "estimated_exit_cost", "account_equity_after_scenario",
            "limitations",
        })
        self.assertTrue(all(ATTRIBUTION_LABELS.values()))
        self.assertTrue(all(DASHBOARD_FIELD_GLOSSARY.values()))
        self.assertTrue(all(RISK_FIELD_GLOSSARY.values()))
        self.assertTrue(set(DASHBOARD_FIELD_GLOSSARY).issubset(
            DASHBOARD_FIELD_LABELS))
        self.assertEqual(set(COMPARISON_FIELD_GLOSSARY), {
            "策略", "阶段", "样本日数", "总收益", "CAGR", "最大回撤",
            "日 Sharpe", "保证金代理", "下穿小时",
        })


if __name__ == "__main__":
    unittest.main()
