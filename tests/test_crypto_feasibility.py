"""Post-run audit for isolated perpetual maintenance pressure."""
import unittest
import json

from crypto.feasibility import audit_margin_observations


class CryptoFeasibilityTests(unittest.TestCase):
    @staticmethod
    def perp_fill(stamp, quantity, price, collateral, realized_pnl):
        return {"kind": "perp_fill", "event_time": stamp,
                "status": "applied", "perp_quantity": str(quantity),
                "perp_mark": str(price), "perp_collateral": str(collateral),
                "perp_pnl": str(realized_pnl),
                "details": json.dumps({"execution_price": str(price)})}

    @staticmethod
    def mark(stamp, quantity, price, collateral, cumulative_pnl):
        return {"kind": "mark", "event_time": stamp,
                "status": "applied", "perp_quantity": str(quantity),
                "perp_mark": str(price), "perp_collateral": str(collateral),
                "perp_pnl": str(cumulative_pnl)}

    def test_finds_first_hourly_maintenance_shortfall_without_cross_margin_cash(self):
        ledger = [
            self.perp_fill("2025-01-01T00:00:00Z", -1, 100, 20, 0),
            self.mark("2025-01-01T00:00:00Z", -1, 100, 20, 1000),
            {"kind": "funding", "event_time": "2025-01-01T01:00:00Z",
             "status": "applied", "perp_quantity": "-1", "perp_mark": "100",
             "perp_collateral": "4.99", "perp_pnl": "0"},
            self.mark("2025-01-01T01:00:00Z", -1, 100, 4.99, 1000),
        ]
        result = audit_margin_observations(ledger, 0.05, 5, 1)
        self.assertEqual(result["status"], "infeasible_under_declared_margin_proxy")
        self.assertEqual(result["mark_observations"], 2)
        self.assertEqual(result["breach_observations"], 1)
        self.assertEqual(result["first_breach_time"], "2025-01-01T01:00:00Z")
        self.assertLess(result["minimum_headroom"], 0)

    def test_cash_only_run_is_not_applicable_not_margin_feasible(self):
        result = audit_margin_observations([
            {"kind": "mark", "event_time": "2025-01-01T00:00:00Z",
             "status": "applied", "perp_quantity": "0", "perp_mark": "100",
             "perp_collateral": "0", "perp_pnl": "0"},
        ], 0.05, 5, 1)
        self.assertEqual(result["status"], "not_applicable_no_open_perpetual")
        self.assertEqual(result["mark_observations"], 0)

    def test_invalid_open_position_mark_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "perp_mark"):
            audit_margin_observations([
                self.perp_fill("2025-01-01T00:00:00Z", -1, 100, 100, 0),
                self.mark("2025-01-01T00:00:00Z", -1, "NaN", 100, 0),
            ], 0.05, 5, 1)

    def test_prior_realized_profit_does_not_cover_a_new_isolated_group_loss(self):
        ledger = [
            self.perp_fill("2025-01-01T00:00:00Z", -1, 200, 200, 0),
            self.perp_fill("2025-01-01T01:00:00Z", 0, 100, 300, 100),
            {"kind": "collateral_transfer", "event_time": "2025-01-01T01:00:00Z",
             "status": "applied", "perp_quantity": "0", "perp_mark": "100",
             "perp_collateral": "0", "perp_pnl": "100"},
            self.perp_fill("2025-01-01T02:00:00Z", -1, 100, 100, 100),
            # The exported perp_pnl includes +100 realized on the closed group
            # and -95 unrealized on this group; the current group lost 95.
            self.mark("2025-01-01T03:00:00Z", -1, 195, 100, 5),
        ]
        result = audit_margin_observations(ledger, 0.05, 5, 1)
        self.assertEqual(result["breach_observations"], 1)
        self.assertEqual(result["minimum_margin_equity"], 5)
        self.assertLess(result["minimum_headroom"], 0)

    def test_add_to_position_uses_weighted_average_entry_price(self):
        ledger = [
            self.perp_fill("2025-01-01T00:00:00Z", 1, 100, 20, 0),
            self.perp_fill("2025-01-01T01:00:00Z", 2, 120, 20, 0),
            self.mark("2025-01-01T02:00:00Z", 2, 105, 20, -10),
        ]
        result = audit_margin_observations(ledger, 0.05, 5, 1)
        # Average entry is 110, so the current long group has -10 UPNL.
        self.assertEqual(result["minimum_margin_equity"], 10)

    def test_partial_reduction_keeps_remaining_position_entry_basis(self):
        ledger = [
            self.perp_fill("2025-01-01T00:00:00Z", -2, 100, 20, 0),
            self.perp_fill("2025-01-01T01:00:00Z", -1, 110, 20, -10),
            self.mark("2025-01-01T02:00:00Z", -1, 105, 20, -15),
        ]
        result = audit_margin_observations(ledger, 0.05, 5, 1)
        # The remaining short is still based at 100, so its UPNL is -5.
        self.assertEqual(result["minimum_margin_equity"], 15)

    def test_direction_flip_starts_new_position_at_flip_execution_price(self):
        ledger = [
            self.perp_fill("2025-01-01T00:00:00Z", -1, 100, 20, 0),
            self.perp_fill("2025-01-01T01:00:00Z", 1, 120, 10, -20),
            self.mark("2025-01-01T02:00:00Z", 1, 110, 10, -30),
        ]
        result = audit_margin_observations(ledger, 0.05, 5, 1)
        # The short was closed and a fresh long opened at 120: UPNL is -10.
        self.assertEqual(result["minimum_margin_equity"], 0)


if __name__ == "__main__":
    unittest.main()
