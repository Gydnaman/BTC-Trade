"""Static contract checks for the read-only Streamlit surface."""
from pathlib import Path
import re
import unittest

import pandas as pd

from crypto.ui.app import _equity_chart_frame


APP_SOURCE = Path(__file__).resolve().parents[1] / "crypto" / "ui" / "app.py"


class CryptoUiAppTests(unittest.TestCase):
    def test_equity_chart_accepts_mixed_iso8601_timestamp_precision(self):
        frame = _equity_chart_frame([
            {"time": "2025-12-30T00:00:00Z", "equity": 1000},
            {"time": "2025-12-30T00:00:00.005000Z", "equity": 1000.1},
        ], pd)
        self.assertEqual(len(frame), 2)
        self.assertEqual(str(frame.index.tz), "UTC")
        self.assertEqual(frame.iloc[-1]["equity"], 1000.1)

    def test_app_has_visuals_and_downloads_but_no_research_or_order_controls(self):
        source = APP_SOURCE.read_text(encoding="utf-8")
        self.assertIn("st.altair_chart", source)
        self.assertIn("utcFormat(datum.value", source)
        self.assertIn("download_button", source)
        self.assertIn('catalog["facts_file"]', source)
        self.assertNotRegex(source, r"\bst\.button\s*\(")
        self.assertNotIn("run_trial(", source)
        self.assertNotIn("place_order", source)
        self.assertNotIn("private_key", source.lower())
        self.assertNotIn(".env", source)

    def test_final_dashboard_integrates_ai_and_chain_evidence(self):
        source = APP_SOURCE.read_text(encoding="utf-8")
        self.assertIn("build_integrated_status", source)
        self.assertIn("AI 研究报告", source)
        self.assertIn("链上验证", source)
        self.assertIn("st.tabs", source)
        self.assertIn("is_synthetic", source)

    def test_research_dashboard_explains_filters_and_risk_scenario_names(self):
        source = APP_SOURCE.read_text(encoding="utf-8")
        self.assertIn('"历史回放策略"', source)
        self.assertIn('"历史回放阶段（已保存结果）"', source)
        self.assertIn('"选定区间收益"', source)
        self.assertIn("SCENARIO_LABELS", source)
        self.assertIn("风险情景释义", source)
        self.assertNotIn("日期筛选仅影响图表", source)


if __name__ == "__main__":
    unittest.main()
