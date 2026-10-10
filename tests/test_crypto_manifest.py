"""Provenance and content-hash contracts for crypto snapshots."""
import hashlib
import unittest
from pathlib import Path

from crypto.manifest import build_manifest, sha256_file


class CryptoManifestTests(unittest.TestCase):
    def test_sha256_file_matches_independent_digest(self):
        path = Path(__file__).parent / "fixtures" / "crypto" / "time_edges.json"
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(sha256_file(str(path)), expected)

    def test_manifest_records_failed_audit_and_source_hashes(self):
        path = Path(__file__).parent / "fixtures" / "crypto" / "time_edges.json"
        config = {"market": {"exchange": "binance", "market_type":
                              "spot_perpetual_carry"}, "data": {"start":
                              "2023-01-01T00:00:00Z", "end":
                              "2023-01-02T00:00:00Z"}}
        manifest = build_manifest(
            config, {"spot_ohlcv": [{"open_time": "2023-01-01T00:00:00Z"}]},
            {"spot_ohlcv": str(path)}, {"status": "failed", "errors": ["gap"]},
            {"markets_retrieved_at": "2026-10-10T00:00:00Z"},
            retrieved_at="2026-10-10T01:00:00Z",
            source_files={"spot_source_records": str(path)})
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["tables"]["spot_ohlcv"]["sha256"],
                         sha256_file(str(path)))
        self.assertEqual(manifest["tables"]["spot_ohlcv"]["path"], path.name)
        self.assertEqual(manifest["retrieved_at"], "2026-10-10T01:00:00Z")
        self.assertEqual(manifest["market_rules"]["markets_retrieved_at"],
                         "2026-10-10T00:00:00Z")
        self.assertEqual(manifest["source_records"]["spot_source_records"]["sha256"],
                         sha256_file(str(path)))

    def test_manifest_exposes_funding_proxy_count_and_known_data_gap(self):
        path = Path(__file__).parent / "fixtures" / "crypto" / "time_edges.json"
        config = {"market": {}, "data": {"known_gaps": []}}
        tables = {"funding": [
            {"mark_price_source": "funding_endpoint"},
            {"mark_price_source": "mark_ohlcv.open_proxy"},
        ]}
        audit = {"status": "audited", "errors": [],
                 "funding_mark_price_proxy_count": 1,
                 "known_gaps": [{"table": "spot_ohlcv", "missing_candles": 1}]}
        manifest = build_manifest(config, tables, {}, audit, {})
        self.assertEqual(manifest["funding_mark_pricing"]["endpoint_mark_price_rows"], 1)
        self.assertEqual(manifest["funding_mark_pricing"]["mark_ohlcv_open_proxy_rows"], 1)
        self.assertFalse(manifest["funding_mark_pricing"]["proxy_is_exact_settlement_price"])
        self.assertEqual(manifest["known_gaps"], audit["known_gaps"])


if __name__ == "__main__":
    unittest.main()
