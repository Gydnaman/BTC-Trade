"""Synthetic engineering tests for bounded Uniswap-style Swap log handling."""
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import unittest

from onchain.events import (
    audit_logs,
    bounded_block_ranges,
    normalize_logs,
    summarize_pool,
)


FIXTURE = Path(__file__).parent / "fixtures" / "onchain" / "logs.json"


class OnchainEventTests(unittest.TestCase):
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
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["fixture_type"], "synthetic_engineering_fixture")
        self.logs = fixture["logs"]

    def test_normalize_sorts_and_deduplicates_by_transaction_and_log_index(self):
        duplicate = deepcopy(self.logs[0])
        rows = normalize_logs([self.logs[1], self.logs[0], duplicate], self.manifest)

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["block_number"] for row in rows], [100, 102])
        self.assertEqual(rows[0]["duplicate_copies"], 1)
        self.assertEqual(rows[0]["amount0_units"], "-1.234567")
        self.assertEqual(rows[0]["amount1_units"], "2")

    def test_conflicting_duplicate_log_identity_is_rejected(self):
        conflict = deepcopy(self.logs[0])
        conflict["amount0"] = 5

        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            normalize_logs([self.logs[0], conflict], self.manifest)

    def test_reincluded_transaction_log_survives_until_canonical_reorg_audit(self):
        old_log = deepcopy(self.logs[0])
        replacement = deepcopy(old_log)
        replacement["block_number"] = 101
        replacement["block_hash"] = "0x" + "bb" * 32
        rows = normalize_logs([old_log, replacement], self.manifest)
        audit = audit_logs(rows, {
            100: "0x" + "cc" * 32,
            101: replacement["block_hash"],
        }, block_range=(100, 101))

        self.assertEqual(len(rows), 2)
        self.assertEqual(audit["reorged_rows_count"], 1)
        self.assertEqual(len(audit["canonical_rows"]), 1)
        self.assertEqual(audit["canonical_rows"][0]["block_number"], 101)

    def test_large_abi_integer_amount_is_not_rounded_during_decimal_scaling(self):
        row = deepcopy(self.logs[0])
        row["amount0"] = 10**70 + 123
        row["amount1"] = -(10**70 + 456)
        manifest = deepcopy(self.manifest)
        manifest["decimals"] = [0, 0]
        normalized = normalize_logs([row], manifest)[0]

        self.assertEqual(normalized["amount0_units"], str(10**70 + 123))
        self.assertEqual(normalized["amount1_units"], str(-(10**70 + 456)))

    def test_abi_signed_and_unsigned_widths_are_enforced(self):
        for field, value in (("amount0", 2**255),
                             ("sqrt_price_x96", 2**160),
                             ("liquidity", 2**128),
                             ("tick", 2**23)):
            with self.subTest(field=field):
                row = deepcopy(self.logs[0])
                row[field] = value
                with self.assertRaises(ValueError):
                    normalize_logs([row], self.manifest)

    def test_gross_flow_keeps_small_decimal_residuals_when_summing_large_values(self):
        rows = []
        for index in range(2):
            row = deepcopy(self.logs[0])
            row["transaction_hash"] = "0x" + str(index + 3) * 64
            row["log_index"] = index
            row["amount0"] = 10**30 + 1
            rows.append(row)
        normalized = normalize_logs(rows, self.manifest)
        audit = audit_logs(normalized, {100: self.logs[0]["block_hash"]}, block_range=(100, 100))
        summary = summarize_pool(audit, self.manifest, source_status="synthetic_fixture")

        self.assertEqual(summary["gross_token0_volume"], "2000000000000000000000000.000002")

    def test_logs_from_another_chain_or_pool_are_rejected(self):
        for field, value in (("chain_id", 10),
                             ("pool_address", "0x000000000000000000000000000000000000000b")):
            with self.subTest(field=field):
                row = deepcopy(self.logs[0])
                row[field] = value
                with self.assertRaises(ValueError):
                    normalize_logs([row], self.manifest)

    def test_audit_prunes_reorged_logs_and_reports_missing_block_coverage(self):
        rows = normalize_logs(self.logs, self.manifest)
        canonical_blocks = {
            100: self.logs[0]["block_hash"],
            101: "0x" + "bb" * 32,
            102: "0x" + "dd" * 32,
        }
        audit = audit_logs(rows, canonical_blocks, block_range=(100, 102))

        self.assertEqual(audit["status"], "reorg_detected")
        self.assertEqual(audit["reorged_rows_count"], 1)
        self.assertEqual(len(audit["canonical_rows"]), 1)
        self.assertEqual(audit["canonical_rows"][0]["block_number"], 100)
        self.assertEqual(audit["missing_blocks"], [])

        incomplete = audit_logs(rows, {100: self.logs[0]["block_hash"], 102: self.logs[1]["block_hash"]},
                                block_range=(100, 102))
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertEqual(incomplete["missing_blocks"], [101])

    def test_event_summary_uses_decimal_scaling_and_explains_limits(self):
        rows = normalize_logs(self.logs, self.manifest)
        audit = audit_logs(rows, {
            100: self.logs[0]["block_hash"],
            101: "0x" + "bb" * 32,
            102: self.logs[1]["block_hash"],
        }, block_range=(100, 102))
        summary = summarize_pool(audit, self.manifest, source_status="synthetic_fixture")

        self.assertEqual(summary["swap_count"], 2)
        self.assertEqual(summary["block_range"], [100, 102])
        self.assertEqual(summary["identity_status"], "unverified")
        self.assertEqual(summary["source_status"], "synthetic_fixture")
        self.assertEqual(summary["gross_token0_volume"], "4.234567")
        self.assertEqual(summary["gross_token1_volume"], "6")
        self.assertEqual(summary["price_observations"][0]["token1_per_token0"], "0.000000000001")
        self.assertTrue(any("not an executable quote" in item for item in summary["limitations"]))
        self.assertTrue(any("not on-chain evidence" in item for item in summary["limitations"]))

    def test_incomplete_audit_cannot_be_summarized_as_zero_or_partial_swaps(self):
        audit = audit_logs([], {100: "0x" + "aa" * 32}, block_range=(100, 102))

        with self.assertRaisesRegex(ValueError, "incomplete block coverage"):
            summarize_pool(audit, self.manifest, source_status="synthetic_fixture")

    def test_missing_query_block_coverage_cannot_be_reported_as_zero_swaps(self):
        audit = audit_logs([], {100: "0x" + "aa" * 32}, block_range=(100, 102))

        self.assertEqual(audit["status"], "incomplete")
        self.assertEqual(audit["missing_blocks"], [101, 102])

    def test_audit_rejects_rows_without_event_identity_as_invalid_data(self):
        with self.assertRaisesRegex(ValueError, "event identity"):
            audit_logs([{"block_number": 100}], {100: "0x" + "aa" * 32},
                       block_range=(100, 100))

    def test_nonpositive_batch_limits_are_rejected_by_manifest_validation(self):
        manifest = deepcopy(self.manifest)
        manifest["max_batch_blocks"] = 0

        with self.assertRaises(ValueError):
            summarize_pool({"status": "ok", "canonical_rows": self.logs}, manifest,
                           source_status="synthetic_fixture")

    def test_unverified_identity_cannot_be_reported_as_rpc_verified(self):
        rows = normalize_logs(self.logs[:1], self.manifest)
        audit = audit_logs(rows, {100: self.logs[0]["block_hash"]}, block_range=(100, 100))

        with self.assertRaisesRegex(ValueError, "node-verified manifest"):
            summarize_pool(audit, self.manifest, source_status="rpc_verified")

    def test_event_queries_are_split_into_bounded_inclusive_ranges(self):
        self.assertEqual(
            bounded_block_ranges(1, 2501, self.manifest),
            [(1, 1000), (1001, 2000), (2001, 2501)],
        )
        with self.assertRaisesRegex(ValueError, "exceeds manifest limit"):
            bounded_block_ranges(1, 10_001, self.manifest)


if __name__ == "__main__":
    unittest.main()
