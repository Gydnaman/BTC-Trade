"""Dual-leg ledger contracts with an independent Decimal reference case."""
import json
import unittest
from decimal import Decimal
from pathlib import Path

from crypto.ledger import funding_cashflow, replay_events


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "crypto" /
                      "carry_handcalc.json").read_text(encoding="utf-8"))


class CryptoLedgerTests(unittest.TestCase):
    def test_short_receives_positive_funding(self):
        self.assertEqual(funding_cashflow(Decimal("-1"), Decimal("113"),
                                          Decimal("0.001")), Decimal("0.113"))

    def test_hand_calculation_reconciles_all_legs_costs_and_equity(self):
        result = replay_events(FIXTURE["events"], FIXTURE["config"])
        self.assertEqual(result["final_equity"], "997.796")
        self.assertEqual(result["attribution"], {
            "spot_pnl": "10", "perp_pnl": "-12", "funding": "0.113",
            "spot_fees": "0.21", "perp_fees": "0.107", "slippage": "0",
        })
        self.assertEqual(result["positions"][0]["spot_quantity"], "0")
        self.assertEqual(result["positions"][0]["perp_quantity"], "0")
        self.assertEqual(result["positions"][0]["collateral"], "0")
        for row in result["ledger"]:
            self.assertAlmostEqual(float(row["equity"]),
                                   float(row["attributed_equity"]), delta=1e-8)

    def test_collateral_transfer_changes_free_cash_not_equity(self):
        events = [{"kind": "collateral_transfer", "event_time": "2025-01-01T00:00:00Z",
                   "sequence": 0, "payload": {"group_id": "g", "amount": "25"}}]
        result = replay_events(events, {"campaign": {"initial_equity": "100"},
                                        "costs": {"spot_fee_bps": 0,
                                                  "perp_fee_bps": 0,
                                                  "slippage_bps": 0}})
        self.assertEqual(result["ledger"][0]["free_cash"], "75")
        self.assertEqual(result["ledger"][0]["equity"], "100")

    def test_closed_group_can_release_all_residual_isolated_collateral(self):
        events = [
            {"kind": "collateral_transfer", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "25"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 1, "payload": {"group_id": "g", "side": "sell",
                                           "quantity": "1", "price": "100"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T01:00:00Z",
             "sequence": 1, "payload": {"group_id": "g", "side": "buy",
                                           "quantity": "1", "price": "90"}},
            {"kind": "collateral_transfer", "event_time": "2025-01-01T01:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "0",
                                           "withdraw_all": True}},
        ]
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        result = replay_events(events, cfg)
        self.assertEqual(result["positions"][0]["perp_quantity"], "0")
        self.assertEqual(result["positions"][0]["collateral"], "0")
        self.assertEqual(result["final_equity"], "110")
        self.assertEqual(result["ledger"][-1]["free_cash"], "110")
        self.assertEqual(result["ledger"][-1]["details"]["amount"], "-35")

    def test_withdraw_all_is_rejected_while_group_position_is_open(self):
        events = [
            {"kind": "collateral_transfer", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "25"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 1, "payload": {"group_id": "g", "side": "sell",
                                           "quantity": "1", "price": "100"}},
            {"kind": "collateral_transfer", "event_time": "2025-01-01T01:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "0",
                                           "withdraw_all": True}},
        ]
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        result = replay_events(events, cfg)
        self.assertEqual(result["ledger"][-1]["status"], "rejected_position_open")
        self.assertEqual(result["positions"][0]["collateral"], "25")

    def test_short_pays_negative_funding_rate(self):
        events = [
            {"kind": "collateral_transfer", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "25"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 1, "payload": {"group_id": "g", "side": "sell",
                                         "quantity": "1", "price": "100"}},
            {"kind": "funding", "event_time": "2025-01-01T08:00:00Z",
             "sequence": 0, "payload": {"rate": "-0.001", "mark_price": "100",
                                         "mark_price_source": "funding_endpoint",
                                         "mark_price_is_proxy": False,
                                         "mark_price_source_time": None}},
        ]
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        result = replay_events(events, cfg)
        self.assertEqual(result["attribution"]["funding"], "-0.1")
        self.assertEqual(result["positions"][0]["collateral"], "24.9")

    def test_new_position_at_settlement_does_not_receive_that_funding(self):
        events = [
            {"kind": "perp_fill", "event_time": "2025-01-01T08:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "sell",
                                         "quantity": "1", "price": "100"}},
            {"kind": "funding", "event_time": "2025-01-01T08:00:00Z",
             "sequence": 9, "payload": {"rate": "0.01", "mark_price": "100",
                                         "mark_price_source": "funding_endpoint",
                                         "mark_price_is_proxy": False,
                                         "mark_price_source_time": None}},
        ]
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        result = replay_events(events, cfg)
        self.assertEqual(result["attribution"]["funding"], "0")

    def test_slippage_is_separate_from_market_pnl_and_reconciles_equity(self):
        events = [{"kind": "spot_fill", "event_time": "2025-01-01T00:00:00Z",
                   "sequence": 0, "payload": {"group_id": "g", "side": "buy",
                                               "quantity": "1", "price": "100"}}]
        cfg = {"campaign": {"initial_equity": "1000"},
               "costs": {"spot_fee_bps": 10, "perp_fee_bps": 5,
                         "slippage_bps": 1}}
        result = replay_events(events, cfg)
        self.assertEqual(result["attribution"]["spot_pnl"], "0")
        self.assertEqual(result["attribution"]["slippage"], "0.01")
        self.assertEqual(result["final_equity"], "999.88999")

    def test_spot_outage_disables_fills_and_resume_mark_captures_gap(self):
        events = [
            {"kind": "spot_fill", "event_time": "2025-01-01T12:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "buy",
                                         "quantity": "1", "price": "100"}},
            {"kind": "spot_fill", "event_time": "2025-01-01T13:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "sell",
                                         "quantity": "1", "price": "100"}},
            {"kind": "mark", "event_time": "2025-01-01T13:00:00Z",
             "sequence": 1, "payload": {"spot_price": "100",
                                         "spot_market_available": False,
                                         "spot_mark_is_stale": True}},
            {"kind": "mark", "event_time": "2025-01-01T14:00:00Z",
             "sequence": 0, "payload": {"spot_price": "110",
                                         "spot_market_available": True,
                                         "spot_mark_is_stale": False}},
            {"kind": "spot_fill", "event_time": "2025-01-01T14:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "sell",
                                         "quantity": "1", "price": "110"}},
        ]
        # The outage policy is tied to the one source-verified Binance hour.
        events[0]["event_time"] = "2023-03-24T12:00:00Z"
        events[1]["event_time"] = "2023-03-24T13:00:00Z"
        events[2]["event_time"] = "2023-03-24T13:00:00Z"
        events[3]["event_time"] = "2023-03-24T14:00:00Z"
        events[4]["event_time"] = "2023-03-24T14:00:00Z"
        cfg = {"campaign": {"initial_equity": "1000"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0},
               "data": {"known_gaps": [{"table": "spot_ohlcv",
                                         "start": "2023-03-24T13:00:00Z",
                                         "end": "2023-03-24T14:00:00Z",
                                         "reason": "Binance spot trading system maintenance; trading resumed at 14:00 UTC",
                                         "source_url": "https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a"}]}}
        result = replay_events(events, cfg)
        self.assertEqual([row["status"] for row in result["ledger"]],
                         ["applied", "applied", "rejected_market_outage",
                          "applied", "applied"])
        outage_row = next(row for row in result["ledger"]
                          if row["kind"] == "mark")
        self.assertTrue(outage_row["spot_mark_is_stale"])
        self.assertEqual(result["final_equity"], "1010")

    def test_ledger_blocks_spot_fill_during_known_outage_without_config_gap(self):
        events = [{"kind": "spot_fill", "event_time": "2023-03-24T13:00:00Z",
                   "sequence": 0, "payload": {"group_id": "g", "side": "buy",
                                               "quantity": "1", "price": "100"}}]
        cfg = {"campaign": {"initial_equity": "1000"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0},
               "data": {"known_gaps": []}}
        result = replay_events(events, cfg)
        self.assertEqual(result["ledger"][0]["status"], "rejected_market_outage")

    def test_partial_closes_keep_average_cost_and_reconcile_both_accounts(self):
        events = [
            {"kind": "spot_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "buy",
                                         "quantity": "1", "price": "100"}},
            {"kind": "spot_fill", "event_time": "2025-01-01T01:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "buy",
                                         "quantity": "1", "price": "110"}},
            {"kind": "spot_fill", "event_time": "2025-01-01T02:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "sell",
                                         "quantity": "0.5", "price": "120"}},
            {"kind": "collateral_transfer", "event_time": "2025-01-01T03:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "1000"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T03:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "sell",
                                         "quantity": "2", "price": "100"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T04:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "side": "buy",
                                         "quantity": "0.5", "price": "90"}},
            {"kind": "mark", "event_time": "2025-01-01T05:00:00Z",
             "sequence": 0, "payload": {"spot_price": "120",
                                         "perp_mark_price": "120"}},
        ]
        cfg = {"campaign": {"initial_equity": "10000"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        result = replay_events(events, cfg)
        self.assertEqual(result["final_equity"], "10005")
        self.assertEqual(result["attribution"]["spot_pnl"], "30")
        self.assertEqual(result["attribution"]["perp_pnl"], "-25")
        self.assertEqual(result["positions"][0]["spot_avg_reference"], "105")
        self.assertEqual(result["positions"][0]["perp_quantity"], "-1.5")

    def test_funding_requires_complete_mark_price_provenance(self):
        event = {"kind": "funding", "event_time": "2025-01-01T08:00:00Z",
                 "sequence": 0,
                 "payload": {"rate": "0.001", "mark_price": "100"}}
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        with self.assertRaisesRegex(ValueError, "mark-price provenance"):
            replay_events([event], cfg)

    def test_funding_proxy_provenance_is_validated_and_preserved(self):
        event = {"kind": "funding", "event_time": "2025-01-01T08:00:00Z",
                 "sequence": 0,
                 "payload": {"rate": "0.001", "mark_price": "100",
                             "mark_price_source": "mark_ohlcv.open_proxy",
                             "mark_price_is_proxy": True,
                             "mark_price_source_time": "2025-01-01T08:00:00Z"}}
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        result = replay_events([event], cfg)
        detail = result["ledger"][0]["details"]
        self.assertEqual(detail["mark_price_source"], "mark_ohlcv.open_proxy")
        self.assertTrue(detail["mark_price_is_proxy"])
        self.assertEqual(detail["mark_price_source_time"], "2025-01-01T08:00:00Z")

    def test_funding_proxy_must_use_same_hour_candle_and_endpoint_has_no_proxy_time(self):
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0}}
        base = {"kind": "funding", "event_time": "2025-01-01T08:00:00Z",
                "sequence": 0,
                "payload": {"rate": "0.001", "mark_price": "100",
                            "mark_price_source": "mark_ohlcv.open_proxy",
                            "mark_price_is_proxy": True,
                            "mark_price_source_time": "2025-01-01T07:00:00Z"}}
        with self.assertRaisesRegex(ValueError, "same UTC hour"):
            replay_events([base], cfg)
        base["payload"] = {"rate": "0.001", "mark_price": "100",
                           "mark_price_source": "funding_endpoint",
                           "mark_price_is_proxy": False,
                           "mark_price_source_time": "2025-01-01T08:00:00Z"}
        with self.assertRaisesRegex(ValueError, "endpoint funding mark"):
            replay_events([base], cfg)

    def test_ledger_rejects_unverified_outage_policy(self):
        event = {"kind": "spot_fill", "event_time": "2025-01-01T00:00:00Z",
                 "sequence": 0,
                 "payload": {"group_id": "g", "side": "buy",
                             "quantity": "1", "price": "10"}}
        cfg = {"campaign": {"initial_equity": "100"},
               "costs": {"spot_fee_bps": 0, "perp_fee_bps": 0,
                         "slippage_bps": 0},
               "data": {"known_gaps": [{"table": "spot_ohlcv",
                                         "start": "2025-01-01T00:00:00Z",
                                         "end": "2025-01-01T01:00:00Z",
                                         "reason": "unverified",
                                         "source_url": "https://example.com"}]}}
        with self.assertRaisesRegex(ValueError, "only the documented Binance spot outage"):
            replay_events([event], cfg)


if __name__ == "__main__":
    unittest.main()
