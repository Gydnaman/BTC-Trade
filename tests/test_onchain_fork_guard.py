"""Unit tests for refusing unsafe or non-fixed fork targets."""
import unittest

from onchain.config import validate_experiment
from onchain.fork_experiment import validate_local_fork_target


class OnchainForkGuardTests(unittest.TestCase):
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
        }
        self.manifest = validate_experiment(self.config, {
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
        })

    def test_local_target_requires_fixed_verified_chain_and_block(self):
        result = validate_local_fork_target(
            "http://127.0.0.1:8545",
            self.manifest,
            observed_chain_id=1,
            observed_block_number=20_000_000,
            observed_block_hash=self.config["block_hash"],
        )

        self.assertEqual(result["status"], "preflight_ok")
        self.assertEqual(result["fork_block"], 20_000_000)
        self.assertNotIn("127.0.0.1", str(result))

    def test_public_network_and_rpc_credentials_are_rejected(self):
        for url in (
            "https://example.com",
            "http://user:secret@127.0.0.1:8545",
            "http://127.0.0.1:8545/?key=secret",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_local_fork_target(
                        url, self.manifest, observed_chain_id=1,
                        observed_block_number=20_000_000,
                        observed_block_hash=self.config["block_hash"],
                    )

    def test_chain_or_block_mismatch_is_rejected(self):
        mismatches = (
            {"observed_chain_id": 10, "observed_block_number": 20_000_000,
             "observed_block_hash": self.config["block_hash"]},
            {"observed_chain_id": 1, "observed_block_number": 19_999_999,
             "observed_block_hash": self.config["block_hash"]},
            {"observed_chain_id": 1, "observed_block_number": 20_000_000,
             "observed_block_hash": "0x" + "cd" * 32},
        )
        for values in mismatches:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    validate_local_fork_target("http://localhost:8545", self.manifest, **values)

    def test_unverified_manifest_cannot_start_a_fork(self):
        manifest = dict(self.manifest)
        manifest["identity_status"] = "unverified"

        with self.assertRaisesRegex(ValueError, "node-verified manifest"):
            validate_local_fork_target(
                "http://localhost:8545", manifest, observed_chain_id=1,
                observed_block_number=20_000_000,
                observed_block_hash=self.config["block_hash"],
            )


if __name__ == "__main__":
    unittest.main()
