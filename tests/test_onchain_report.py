"""Tests for clearly labeled, deterministic on-chain event reports."""
import unittest

from onchain.report import render_pool_report


class OnchainReportTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "schema_version": "onchain-manifest-v1",
            "identity_status": "unverified",
            "chain_id": 1,
            "pool_address": "0x000000000000000000000000000000000000000a",
            "token_addresses": [
                "0x0000000000000000000000000000000000000001",
                "0x0000000000000000000000000000000000000002",
            ],
            "decimals": [6, 18],
            "fee_tier": 500,
            "block_number": 100,
            "block_hash": "0x" + "ab" * 32,
            "deployment_source": "https://github.com/Uniswap/v3-periphery/blob/v1.0.0/deploys.md",
            "package_commit": "0" * 40,
            "confirmation_depth": 64,
            "max_event_blocks": 10_000,
            "max_batch_blocks": 1_000,
        }
        self.summary = {
            "status": "ok",
            "identity_status": "unverified",
            "source_status": "synthetic_fixture",
            "block_range": [100, 102],
            "swap_count": 2,
            "duplicate_count": 1,
            "reorged_rows_count": 0,
            "gross_token0_volume": "4.234567",
            "gross_token1_volume": "6",
            "net_token0_delta": "1.765433",
            "net_token1_delta": "-2",
            "price_observations": [{
                "block_number": 100,
                "transaction_hash": "0x" + "11" * 32,
                "token1_per_token0": "0.000000000001",
                "tick": 0,
            }, {
                "block_number": 102,
                "transaction_hash": "0x" + "22" * 32,
                "token1_per_token0": "0.000000000004",
                "tick": 13863,
            }],
            "liquidity_observations": [{
                "block_number": 100,
                "transaction_hash": "0x" + "11" * 32,
                "liquidity_raw": 9000,
            }, {
                "block_number": 102,
                "transaction_hash": "0x" + "22" * 32,
                "liquidity_raw": 12000,
            }],
            "limitations": ["Synthetic engineering fixture only; it is not on-chain evidence."],
        }

    def test_report_labels_synthetic_data_and_keeps_scope_limitations(self):
        report = render_pool_report(self.summary, self.manifest)

        self.assertIn("合成工程夹具", report)
        self.assertIn("身份核验：unverified", report)
        self.assertIn("交换事件数：2", report)
        self.assertIn("0.000000000001", report)
        self.assertIn("not on-chain evidence", report)

    def test_report_refuses_rpc_verified_label_without_node_verified_manifest(self):
        summary = dict(self.summary)
        summary["source_status"] = "rpc_verified"

        with self.assertRaisesRegex(ValueError, "node-verified manifest"):
            render_pool_report(summary, self.manifest)

    def test_report_requires_a_complete_audit_and_matching_identity(self):
        summary = dict(self.summary)
        summary["status"] = "incomplete"
        with self.assertRaisesRegex(ValueError, "complete audited summary"):
            render_pool_report(summary, self.manifest)

        summary = dict(self.summary)
        summary["identity_status"] = "node_verified"
        with self.assertRaisesRegex(ValueError, "identity does not match"):
            render_pool_report(summary, self.manifest)

    def test_report_refuses_inconsistent_event_observation_counts(self):
        summary = dict(self.summary)
        summary["swap_count"] = 3

        with self.assertRaisesRegex(ValueError, "observation counts"):
            render_pool_report(summary, self.manifest)


if __name__ == "__main__":
    unittest.main()
