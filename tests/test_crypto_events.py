"""Stable event-time ordering contracts for the crypto ledger."""
import unittest

from crypto.events import sort_events


class CryptoEventTests(unittest.TestCase):
    def test_funding_precedes_same_time_fills_then_sequence_breaks_ties(self):
        events = [
            {"kind": "perp_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 8, "payload": {}},
            {"kind": "spot_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 2, "payload": {}},
            {"kind": "funding", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 9, "payload": {}},
            {"kind": "mark", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 99, "payload": {}},
        ]
        ordered = sort_events(events)
        self.assertEqual([row["kind"] for row in ordered],
                         ["funding", "mark", "spot_fill", "perp_fill"])

    def test_invalid_sequence_and_unknown_event_kind_are_rejected(self):
        base = {"event_time": "2025-01-01T00:00:00Z", "payload": {}}
        with self.assertRaisesRegex(ValueError, "sequence"):
            sort_events([{**base, "kind": "mark", "sequence": True}])
        with self.assertRaisesRegex(ValueError, "kind"):
            sort_events([{**base, "kind": "send_order", "sequence": 0}])

    def test_collateral_deposits_precede_fills_and_withdrawals_follow_them(self):
        events = [
            {"kind": "collateral_transfer", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "-10"}},
            {"kind": "perp_fill", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 0, "payload": {}},
            {"kind": "collateral_transfer", "event_time": "2025-01-01T00:00:00Z",
             "sequence": 9, "payload": {"group_id": "g", "amount": "10"}},
        ]
        ordered = sort_events(events)
        self.assertEqual([row["payload"].get("amount", "fill") for row in ordered],
                         ["10", "fill", "-10"])

    def test_withdraw_all_is_ordered_after_same_time_position_closes(self):
        events = [
            {"kind": "perp_fill", "event_time": "2025-01-01T01:00:00Z",
             "sequence": 1, "payload": {"group_id": "g", "side": "buy",
                                           "quantity": "1", "price": "100"}},
            {"kind": "collateral_transfer", "event_time": "2025-01-01T01:00:00Z",
             "sequence": 0, "payload": {"group_id": "g", "amount": "0",
                                           "withdraw_all": True}},
        ]
        ordered = sort_events(events)
        self.assertEqual([event["kind"] for event in ordered],
                         ["perp_fill", "collateral_transfer"])


if __name__ == "__main__":
    unittest.main()
