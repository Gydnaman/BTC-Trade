"""Isolated risk and leg-by-leg execution contracts."""
import unittest

from crypto.risk import apply_execution_result, assess_group


class CryptoRiskTests(unittest.TestCase):
    def test_perp_margin_shortfall_is_not_offset_by_spot_profit(self):
        state = {"group_id": "carry-1", "spot_quantity": "1",
                 "perp_quantity": "-1", "spot_entry_price": "100",
                 "perp_entry_price": "100", "spot_price": "100",
                 "perp_mark_price": "100", "collateral": "2"}
        result = assess_group(state, {"spot_price": "130",
                                     "perp_mark_price": "130",
                                     "maintenance_ratio": "0.1"})
        self.assertEqual(result["spot_unrealized_pnl"], "30")
        self.assertEqual(result["perp_unrealized_pnl"], "-30")
        self.assertGreater(float(result["collateral_shortfall"]), 0)
        self.assertTrue(result["actions"])
        self.assertEqual(result["actions"][0]["group_id"], "carry-1")

    def test_positive_and_negative_funding_scenarios_change_isolated_collateral(self):
        state = {"group_id": "carry-1", "spot_quantity": "1",
                 "perp_quantity": "-1", "spot_entry_price": "100",
                 "perp_entry_price": "100", "spot_price": "100",
                 "perp_mark_price": "100", "collateral": "100"}
        paid = assess_group(state, {"spot_price": "100", "perp_mark_price": "100",
                                    "maintenance_ratio": "0.1",
                                    "funding_rate": "-0.001"})
        received = assess_group(state, {"spot_price": "100", "perp_mark_price": "100",
                                        "maintenance_ratio": "0.1",
                                        "funding_rate": "0.001"})
        self.assertEqual(paid["funding_cashflow"], "-0.1")
        self.assertEqual(received["funding_cashflow"], "0.1")
        self.assertEqual(paid["collateral_after_scenario"], "99.9")
        self.assertEqual(received["collateral_after_scenario"], "100.1")

    def test_single_leg_fill_reports_remaining_delta_and_flatten_targets(self):
        state = {"group_id": "carry-1", "spot_quantity": "0",
                 "perp_quantity": "0", "cash": "1000", "fees_paid": "0"}
        result = apply_execution_result(state, {
            "spot": {"filled_quantity": "1", "price": "100", "fee": "0.1",
                     "status": "filled"},
            "perp": {"filled_quantity": "0", "price": None, "fee": "0",
                     "status": "rejected"},
        })
        self.assertEqual(result["state"]["spot_quantity"], "1")
        self.assertEqual(result["state"]["perp_quantity"], "0")
        self.assertEqual(result["net_delta"], "1")
        self.assertTrue(result["partial_execution"])
        self.assertEqual(result["actions"][0]["target_spot_quantity"], "0")
        self.assertEqual(result["actions"][0]["target_perp_quantity"], "0")
        self.assertEqual(state["spot_quantity"], "0")  # pure function

    def test_failed_hedge_exit_surfaces_remaining_short_delta(self):
        state = {"group_id": "carry-1", "spot_quantity": "1",
                 "perp_quantity": "-1", "cash": "1000", "fees_paid": "0",
                 "spot_average_price": "100", "perp_average_price": "100",
                 "perp_collateral": "100"}
        result = apply_execution_result(state, {
            "spot": {"filled_quantity": "-1", "price": "105", "fee": "0.1",
                     "status": "filled"},
            "perp": {"filled_quantity": "0", "price": None, "fee": "0",
                     "status": "timeout"},
        })
        self.assertEqual(result["state"]["spot_quantity"], "0")
        self.assertEqual(result["state"]["perp_quantity"], "-1")
        self.assertEqual(result["net_delta"], "-1")
        self.assertTrue(result["partial_execution"])
        self.assertIn("timeout", result["leg_statuses"].values())

    def test_perpetual_close_realizes_pnl_into_isolated_collateral(self):
        state = {"group_id": "carry-1", "spot_quantity": "0",
                 "perp_quantity": "-1", "cash": "500", "fees_paid": "0",
                 "spot_average_price": "0", "perp_average_price": "100",
                 "perp_collateral": "25"}
        result = apply_execution_result(state, {
            "perp": {"filled_quantity": "1", "price": "90", "fee": "0",
                     "status": "filled"},
        })
        self.assertEqual(result["state"]["perp_quantity"], "0")
        self.assertEqual(result["state"]["perp_realized_pnl"], "10")
        self.assertEqual(result["state"]["perp_collateral"], "35")
        self.assertEqual(result["realized_perp_pnl"], "10")

    def test_risk_model_rejects_missing_and_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "maintenance_ratio"):
            assess_group({"group_id": "x", "spot_quantity": "0",
                          "perp_quantity": "0", "spot_entry_price": "1",
                          "perp_entry_price": "1", "spot_price": "1",
                          "perp_mark_price": "1", "collateral": "1"}, {})
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            assess_group({"group_id": "x", "spot_quantity": "0",
                          "perp_quantity": "0", "spot_entry_price": "1",
                          "perp_entry_price": "1", "spot_price": "1",
                          "perp_mark_price": "1", "collateral": "1"},
                         {"maintenance_ratio": "1.1"})


if __name__ == "__main__":
    unittest.main()
