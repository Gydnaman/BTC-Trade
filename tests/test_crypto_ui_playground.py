from importlib.util import find_spec
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLAYGROUND_TAB = None
if find_spec("crypto.ui.playground_tab") is not None:
    from crypto.ui import playground_tab as PLAYGROUND_TAB


class CryptoPlaygroundUiTests(unittest.TestCase):
    def test_playground_tab_module_exists(self):
        self.assertIsNotNone(
            PLAYGROUND_TAB,
            "strategy experiment tab has not been implemented",
        )

    def test_parameter_builder_converts_percent_and_basis_points(self):
        self.assertIsNotNone(PLAYGROUND_TAB, "strategy experiment tab is missing")
        self.assertEqual(
            PLAYGROUND_TAB.build_playground_parameters(
                "funding_filter", 25, 1.0, 1.0
            ),
            {
                "allocation_fraction": 0.25,
                "collateral_ratio": 1.0,
                "positive_funding_threshold": 0.0001,
            },
        )

    def test_cash_baseline_does_not_receive_carry_parameters(self):
        self.assertIsNotNone(PLAYGROUND_TAB, "strategy experiment tab is missing")
        self.assertEqual(
            PLAYGROUND_TAB.build_playground_parameters(
                "cash_zero", 25, 1.0, 0
            ),
            {},
        )

    def test_ui_uses_an_explicit_form_submit_not_free_text_code(self):
        self.assertIsNotNone(PLAYGROUND_TAB, "strategy experiment tab is missing")
        source = (ROOT / "crypto" / "ui" / "playground_tab.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("st.form(", source)
        self.assertIn("st.form_submit_button(", source)
        self.assertIn("run_playground(", source)
        self.assertNotIn("st.text_area(", source)
        self.assertNotIn("exec(", source)

    def test_app_exposes_experiments_without_requiring_frozen_results(self):
        source = (ROOT / "crypto" / "ui" / "app.py").read_text(encoding="utf-8")
        self.assertIn("render_playground_tab", source)
        self.assertIn("策略实验", source)
        self.assertNotIn(
            'if not trials:\\n        st.info("尚无已完成的研究结果。")\\n        return',
            source,
        )

    def test_historical_filters_are_labeled_and_not_global_sidebar_controls(self):
        source = (ROOT / "crypto" / "ui" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("st.sidebar.selectbox", source)
        self.assertNotIn("st.sidebar.date_input", source)
        self.assertIn("历史回放策略", source)
        self.assertIn("历史回放阶段（已保存结果）", source)


if __name__ == "__main__":
    unittest.main()
