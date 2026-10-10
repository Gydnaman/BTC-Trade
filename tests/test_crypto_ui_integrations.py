"""Safe local evidence assembled for the integrated read-only dashboard."""
import json
from pathlib import Path
import tempfile
import unittest

from crypto.ui.integrations import build_integrated_status


class CryptoUiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("results/crypto/ai/trial-005-development.metadata.json", {
            "status": "fallback", "provider": "unconfigured", "model": "none",
            "prompt_version": "crypto-ai-narrative-v1", "input_sha256": "a" * 64,
        })
        self.write_text("results/crypto/ai/trial-005-development.md",
                        "# 加密资产研究分析\n\n事实来自已审计 trial。\n")
        self.write("results/crypto/onchain/synthetic-event-demo.json", {
            "manifest": {"identity_status": "unverified", "chain_id": 1},
            "summary": {
                "status": "ok", "identity_status": "unverified",
                "source_status": "synthetic_fixture", "block_range": [100, 102],
                "swap_count": 2, "reorged_rows_count": 0,
                "price_observations": [],
            },
        })
        self.write_text(
            "results/crypto/onchain/synthetic-event-demo.md",
            "# 合成工程夹具：事件演示\n\n"
            "数据来源：合成工程测试夹具；不是链上证据。\n"
            "身份核验：unverified\n交换事件数：2\n",
        )
        self.write_text(
            "docs/crypto/ONCHAIN_SETUP.md",
            "# Setup\n\n## Status on 2026-10-10\n\nObserved on this host:\n\n"
            "- WSL unavailable\n- Foundry unavailable\n- Docker Engine unavailable\n\nNext section.\n",
        )

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_text(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def test_dashboard_marks_offline_ai_and_synthetic_chain_evidence(self):
        status = build_integrated_status(self.root)

        self.assertTrue(status["ai"]["is_offline_fallback"])
        self.assertEqual(status["ai"]["metadata"]["provider"], "unconfigured")
        self.assertTrue(status["onchain"]["is_synthetic"])
        self.assertFalse(status["onchain"]["is_rpc_verified"])
        self.assertEqual(status["onchain"]["environment_checked_on"], "2026-10-10")
        self.assertEqual(status["onchain"]["environment_observations"], [
            "WSL unavailable", "Foundry unavailable", "Docker Engine unavailable",
        ])

    def test_rpc_evidence_requires_node_verified_identity(self):
        path = self.root / "results/crypto/onchain/synthetic-event-demo.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["summary"]["source_status"] = "rpc_verified"
        path.write_text(json.dumps(artifact), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "node-verified"):
            build_integrated_status(self.root)

    def test_synthetic_report_must_keep_prominent_disclaimer(self):
        self.write_text("results/crypto/onchain/synthetic-event-demo.md",
                        "# Event report\n\nTwo events.\n")

        with self.assertRaisesRegex(ValueError, "evidence label"):
            build_integrated_status(self.root)

    def test_invalid_ai_metadata_is_rejected(self):
        self.write("results/crypto/ai/trial-005-development.metadata.json", {
            "status": "fallback", "provider": "unconfigured", "model": "none",
            "prompt_version": "crypto-ai-narrative-v1", "input_sha256": "short",
        })

        with self.assertRaisesRegex(ValueError, "AI report identity"):
            build_integrated_status(self.root)

    def test_rpc_identity_cannot_be_paired_with_a_synthetic_markdown_report(self):
        path = self.root / "results/crypto/onchain/synthetic-event-demo.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["manifest"]["identity_status"] = "node_verified"
        artifact["summary"]["identity_status"] = "node_verified"
        artifact["summary"]["source_status"] = "rpc_verified"
        path.write_text(json.dumps(artifact), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "report source label"):
            build_integrated_status(self.root)

    def test_report_event_count_must_match_structured_chain_artifact(self):
        path = self.root / "results/crypto/onchain/synthetic-event-demo.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["summary"]["swap_count"] = 3
        path.write_text(json.dumps(artifact), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "event count"):
            build_integrated_status(self.root)


if __name__ == "__main__":
    unittest.main()
