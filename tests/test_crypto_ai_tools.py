"""Stage-scoped, read-only tool boundary tests for the AI research layer."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crypto.ai.facts import load_facts
from crypto.ai.tools import call_tool, clear_tool_call_log, get_tool_call_log


TABLE_HASHES = {
    "spot_ohlcv": "a" * 64,
    "perp_ohlcv": "b" * 64,
    "mark_ohlcv": "c" * 64,
    "funding": "d" * 64,
}


class CryptoAiToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.root = self.project / "results" / "crypto" / "campaign"
        self.root.mkdir(parents=True)
        self.manifest_path = (
            self.project / "data_cache" / "crypto" / "snapshot" / "manifest.json"
        )
        self.manifest_path.parent.mkdir(parents=True)
        self.write_manifest()
        self.root.joinpath("facts.json").write_text(
            '{"run_id":"sealed-holdout","metrics":{"final_equity":999999}}',
            encoding="utf-8",
        )
        self.campaign = {
            "schema_version": "crypto-campaign-feasibility-v1",
            "snapshot_id": "snapshot-test",
            "candidate_strategy": "funding_filter",
            "status": "candidate_has_margin_breaches",
            "candidate_breach_stages": ["development"],
            "stages": {"development": {}, "validation": {}, "holdout": {}},
            "trial_audits": [],
        }
        for index, stage in ((1, "development"), (2, "validation")):
            self.write_trial(f"trial-{index:03d}", stage)
        self.write_trial("holdout-006", "holdout")
        self.root.joinpath("holdout-006.json").write_text(
            "sealed holdout content must not be opened", encoding="utf-8")
        self.root.joinpath("campaign-feasibility.json").write_text(
            json.dumps(self.campaign), encoding="utf-8")
        self.project_patch = patch("crypto.ai.facts.PROJECT_ROOT", self.project)
        self.project_patch.start()
        self.addCleanup(self.project_patch.stop)
        clear_tool_call_log()

    def write_manifest(self):
        manifest = {
            "schema_version": "crypto-snapshot-v1",
            "snapshot_id": "snapshot-test",
            "status": "audited",
            "tables": {name: {"sha256": digest}
                       for name, digest in TABLE_HASHES.items()},
        }
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def write_trial(self, trial_id, stage):
        ledger_name = f"{trial_id}-ledger.csv"
        ledger_path = self.root / ledger_name
        with ledger_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "event_time", "kind", "status", "details", "equity",
            ])
            writer.writeheader()
            writer.writerow({
                "event_time": "2025-01-01T00:00:00Z", "kind": "fill",
                "status": "applied", "details": json.dumps({"quantity": "1"}),
                "equity": "997.796",
            })
        ledger_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
        run_id = f"run-{trial_id}"
        record = {
            "schema_version": "crypto-trial-v1", "run_id": run_id,
            "status": "succeeded", "stage": stage,
            "strategy": "funding_filter", "created_at": "2025-01-02T00:00:00Z",
            "provenance": {
                "campaign_id": "campaign", "snapshot_id": "snapshot-test",
                "manifest_path": str(self.manifest_path),
                "table_sha256": dict(TABLE_HASHES),
                "contract_sha256": "e" * 64, "evaluator_sha256": "f" * 64,
            },
            "metrics": {
                "initial_equity": 1000.0, "final_equity": 997.796,
                "total_return": -0.002204, "cagr": None,
                "max_drawdown": -0.002204, "annualized_volatility": None,
                "sharpe_daily": None, "daily_return_count": 1,
                "elapsed_days": 1, "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-02T00:00:00Z",
                "annualization_basis": "365-day UTC daily returns",
                "max_drawdown_basis": "UTC daily close samples including initial equity",
                "limitations": ["single observation; annualized metrics are undefined"],
            },
            "attribution": {
                "spot_pnl": "2.0", "perp_pnl": "-2.5", "funding": "0.1",
                "spot_fees": "1.0", "perp_fees": "0.3", "slippage": "0.504",
            },
            "risk_scenarios": [{
                "scenario": "base", "net_delta": "0",
                "limitations": ["scenario only"],
            }],
            "assumptions": {"perp_fee_bps": 5},
            "limitations": ["historical funding is observed after settlement"],
            "equity_series": [
                {"time": "2025-01-01T00:00:00Z", "equity": 1000.0},
                {"time": "2025-01-02T00:00:00Z", "equity": 997.796},
            ],
            "ledger_path": ledger_name,
        }
        trial_path = self.root / f"{trial_id}.json"
        trial_path.write_text(json.dumps(record), encoding="utf-8")
        audit = {
            "run_id": run_id, "stage": stage, "strategy": "funding_filter",
            "snapshot_id": "snapshot-test", "ledger_sha256": ledger_hash,
            "status": "no_breach_observed_under_declared_margin_proxy",
            "breach_observations": 0, "mark_observations": 1,
            "limitations": ["not an exchange liquidation model"],
        }
        (self.root / f"{trial_id}-margin-audit.json").write_text(
            json.dumps(audit), encoding="utf-8")
        self.campaign["trial_audits"].append({
            "run_id": run_id, "stage": stage, "strategy": "funding_filter",
            "snapshot_id": "snapshot-test", "ledger_sha256": ledger_hash,
        })
        self.root.joinpath("campaign-feasibility.json").write_text(
            json.dumps(self.campaign), encoding="utf-8")
        return trial_path

    def test_loads_stage_scoped_facts_without_opening_global_holdout_facts(self):
        facts = load_facts(str(self.root), "trial-002")

        self.assertEqual(facts["stage"], "validation")
        self.assertEqual(facts["metrics"]["final_equity"], 997.796)
        self.assertEqual(facts["run_id"], "run-trial-002")
        self.assertNotEqual(facts["metrics"]["final_equity"], 999999)
        self.assertNotIn("holdout", json.dumps(facts).lower())

    def test_holdout_trial_is_rejected(self):
        with self.assertRaises(PermissionError):
            load_facts(str(self.root), "holdout-006")

    def test_manifest_hash_mismatch_is_rejected(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["tables"]["funding"]["sha256"] = "0" * 64
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "manifest hash"):
            load_facts(str(self.root), "trial-002")

    def test_trial_schema_and_required_fact_fields_are_checked(self):
        trial_path = self.root / "trial-002.json"
        record = json.loads(trial_path.read_text(encoding="utf-8"))
        record["schema_version"] = "unknown-schema"
        trial_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity or status"):
            load_facts(str(self.root), "trial-002")

        record["schema_version"] = "crypto-trial-v1"
        del record["metrics"]["final_equity"]
        trial_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "final_equity"):
            load_facts(str(self.root), "trial-002")

    def test_allowed_tools_return_trial_facts_and_evidence(self):
        summary = call_tool("get_summary", {"trial_id": "trial-002"}, str(self.root))
        attribution = call_tool("get_attribution", {"trial_id": "trial-002"}, str(self.root))
        risks = call_tool("get_risks", {"trial_id": "trial-002"}, str(self.root))
        evidence = call_tool("get_evidence", {
            "trial_id": "trial-002", "evidence_id": "metrics",
        }, str(self.root))

        self.assertEqual(summary["metrics"]["final_equity"], 997.796)
        self.assertEqual(attribution["attribution"]["funding"], "0.1")
        self.assertEqual(risks["risks"][0]["scenario"], "base")
        self.assertEqual(evidence["value"]["final_equity"], 997.796)
        self.assertEqual(evidence["evidence_id"], "metrics")

    def test_forbidden_tools_holdout_and_arbitrary_paths_are_rejected(self):
        for name in ("change_fees", "execute_code", "read_holdout"):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                call_tool(name, {}, str(self.root))
        with self.assertRaises(PermissionError):
            call_tool("get_summary", {"trial_id": "holdout-006"}, str(self.root))
        with self.assertRaises(PermissionError):
            call_tool("get_summary", {"trial_id": "../trial-002"}, str(self.root))
        with self.assertRaises(PermissionError):
            call_tool("get_evidence", {
                "trial_id": "trial-002", "evidence_id": "../facts.json",
            }, str(self.root))

    def test_unknown_evidence_id_is_rejected(self):
        with self.assertRaises(KeyError):
            call_tool("get_evidence", {
                "trial_id": "trial-002", "evidence_id": "not_real",
            }, str(self.root))

    def test_denial_log_does_not_store_untrusted_arguments_or_secrets(self):
        with self.assertRaises(PermissionError):
            call_tool("get_summary", {
                "trial_id": "trial-002", "api_key": "do-not-log-this",
            }, str(self.root))

        self.assertNotIn("do-not-log-this", json.dumps(get_tool_call_log()))


if __name__ == "__main__":
    unittest.main()
