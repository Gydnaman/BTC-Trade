"""Tests for fixed-identity EVM experiments."""
import unittest
from copy import deepcopy

from onchain.config import validate_experiment
from onchain.manifest import build_manifest


class OnchainConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "chain_id": 1,
            "pool_address": "0x000000000000000000000000000000000000000a",
            "token_addresses": [
                "0x0000000000000000000000000000000000000001",
                "0x0000000000000000000000000000000000000002",
            ],
            "decimals": [6, 18],
            "fee_tier": 500,
            "block_number": 20_000_000,
            "block_hash": "0x" + "ab" * 32,
            "deployment_source": "https://github.com/Uniswap/v3-periphery/blob/v1.0.0/deploys.md",
            "package_commit": "0" * 40,
            "archive_rpc_url": "https://rpc.example.invalid/secret-token",
        }
        self.metadata = {
            "historical_block_available": True,
            "chain_id": 1,
            "pool_address": self.config["pool_address"],
            "token0": self.config["token_addresses"][0],
            "token1": self.config["token_addresses"][1],
            "decimals0": 6,
            "decimals1": 18,
            "fee": 500,
            "block_number": 20_000_000,
            "block_hash": self.config["block_hash"],
        }

    def test_manifest_contains_verified_identity_but_never_rpc_url(self):
        manifest = validate_experiment(self.config, self.metadata)

        self.assertEqual(manifest["chain_id"], 1)
        self.assertEqual(manifest["pool_address"], self.config["pool_address"])
        self.assertEqual(manifest["token_addresses"], self.config["token_addresses"])
        self.assertEqual(manifest["block_hash"], self.config["block_hash"])
        self.assertEqual(manifest["identity_status"], "node_verified")
        self.assertNotIn("archive_rpc_url", manifest)
        self.assertNotIn("secret-token", str(manifest))

    def test_chain_id_mismatch_is_rejected(self):
        metadata = deepcopy(self.metadata)
        metadata["chain_id"] = 10

        with self.assertRaisesRegex(ValueError, "chain_id"):
            validate_experiment(self.config, metadata)

    def test_fixed_block_hash_mismatch_is_rejected(self):
        metadata = deepcopy(self.metadata)
        metadata["block_hash"] = "0x" + "cd" * 32

        with self.assertRaisesRegex(ValueError, "block_hash"):
            validate_experiment(self.config, metadata)

    def test_pool_tokens_decimals_and_fee_must_match(self):
        mutations = (
            ("token0", "0x0000000000000000000000000000000000000003"),
            ("decimals1", 6),
            ("fee", 3000),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                metadata = deepcopy(self.metadata)
                metadata[field] = value
                with self.assertRaises(ValueError):
                    validate_experiment(self.config, metadata)

    def test_unavailable_historical_block_is_not_a_validated_experiment(self):
        metadata = deepcopy(self.metadata)
        metadata["historical_block_available"] = False

        with self.assertRaisesRegex(RuntimeError, "historical block"):
            validate_experiment(self.config, metadata)

    def test_unverified_historical_block_availability_is_rejected(self):
        metadata = deepcopy(self.metadata)
        del metadata["historical_block_available"]

        with self.assertRaisesRegex(RuntimeError, "not verified"):
            validate_experiment(self.config, metadata)

    def test_uniswap_token_order_must_match_sorted_pool_token0_token1(self):
        config = deepcopy(self.config)
        config["token_addresses"].reverse()
        config["decimals"].reverse()

        with self.assertRaisesRegex(ValueError, "token0/token1 order"):
            build_manifest(config)


if __name__ == "__main__":
    unittest.main()
