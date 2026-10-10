"""Read-only AI and on-chain evidence for the final local workbench."""
from __future__ import annotations

import json
from pathlib import Path
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _project_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"integrated evidence must remain inside project: {relative}") from exc
    if not candidate.is_file():
        raise ValueError(f"integrated evidence is missing: {relative}")
    return candidate


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid {label} artifact") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} artifact must be an object")
    return value


def _observed_environment(setup_text: str) -> tuple[str | None, list[str]]:
    match = re.search(r"^## Status on (\d{4}-\d{2}-\d{2})\s*$", setup_text, re.MULTILINE)
    status_date = match.group(1) if match else None
    marker = "Observed on this host:"
    if marker not in setup_text:
        return status_date, []
    items = []
    for line in setup_text.split(marker, 1)[1].splitlines():
        if not line.strip():
            if items:
                break
            continue
        if not line.startswith("- "):
            break
        items.append(line[2:].strip())
    return status_date, items


def build_integrated_status(project_root: str | Path) -> dict:
    """Load fixed, project-local AI and chain evidence; never query a provider or node."""
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError("project root does not exist")

    ai_meta_path = _project_file(
        root, "results/crypto/ai/trial-005-development.metadata.json")
    ai_report_path = _project_file(
        root, "results/crypto/ai/trial-005-development.md")
    ai_metadata = _read_object(ai_meta_path, "AI metadata")
    ai_report = ai_report_path.read_text(encoding="utf-8")
    if (ai_metadata.get("status") not in {"fallback", "generated"} or
            not isinstance(ai_metadata.get("provider"), str) or
            not isinstance(ai_metadata.get("model"), str) or
            not isinstance(ai_metadata.get("prompt_version"), str) or
            not isinstance(ai_metadata.get("input_sha256"), str) or
            not _SHA256.fullmatch(ai_metadata["input_sha256"]) or
            not ai_report.startswith("# 加密资产研究分析")):
        raise ValueError("AI report identity or metadata is invalid")

    onchain_json_path = _project_file(
        root, "results/crypto/onchain/synthetic-event-demo.json")
    onchain_report_path = _project_file(
        root, "results/crypto/onchain/synthetic-event-demo.md")
    setup_path = _project_file(root, "docs/crypto/ONCHAIN_SETUP.md")
    chain_artifact = _read_object(onchain_json_path, "on-chain")
    chain_report = onchain_report_path.read_text(encoding="utf-8")
    summary = chain_artifact.get("summary")
    manifest = chain_artifact.get("manifest")
    if not isinstance(summary, dict) or not isinstance(manifest, dict):
        raise ValueError("on-chain artifact requires summary and manifest")
    source_status = summary.get("source_status")
    identity_status = manifest.get("identity_status")
    if source_status not in {"synthetic_fixture", "rpc_verified"}:
        raise ValueError("on-chain source status is invalid")
    if summary.get("identity_status") != identity_status:
        raise ValueError("on-chain summary and manifest identity do not match")
    if source_status == "rpc_verified" and identity_status != "node_verified":
        raise ValueError("RPC evidence requires a node-verified manifest")
    if source_status == "synthetic_fixture" and identity_status != "unverified":
        raise ValueError("synthetic evidence must remain unverified")
    block_range = summary.get("block_range")
    swap_count = summary.get("swap_count")
    if (not isinstance(block_range, list) or len(block_range) != 2 or
            any(isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in block_range) or block_range[1] < block_range[0] or
            isinstance(swap_count, bool) or not isinstance(swap_count, int) or swap_count < 0):
        raise ValueError("on-chain range or event count is invalid")
    is_synthetic = source_status == "synthetic_fixture"
    if is_synthetic:
        if (not chain_report.startswith("# 合成工程夹具") or
                "数据来源：合成工程测试夹具" not in chain_report or
                "不是链上证据" not in chain_report):
            raise ValueError("synthetic on-chain report is missing its evidence label")
    elif (not chain_report.startswith("# Uniswap V3 池事件分析") or
          "数据来源：经节点核验的 RPC 事件" not in chain_report):
        raise ValueError("on-chain report source label does not match RPC metadata")
    identity_line = f"身份核验：{identity_status}"
    if identity_line not in chain_report:
        raise ValueError("on-chain report identity does not match structured artifact")
    event_match = re.search(r"^交换事件数：(\d+)\s*$", chain_report, re.MULTILINE)
    if not event_match or int(event_match.group(1)) != swap_count:
        raise ValueError("on-chain report event count differs from structured artifact")
    is_rpc_verified = (
        summary.get("status") == "ok" and source_status == "rpc_verified" and
        identity_status == "node_verified" and summary.get("reorged_rows_count") == 0
    )
    setup_text = setup_path.read_text(encoding="utf-8")
    setup_date, environment_observations = _observed_environment(setup_text)
    return {
        "ai": {
            "metadata": ai_metadata,
            "report": ai_report,
            "trial_id": "trial-005",
            "stage": "development",
            "is_model_generated": ai_metadata["status"] == "generated",
            "is_offline_fallback": ai_metadata["status"] == "fallback",
        },
        "onchain": {
            "artifact": chain_artifact,
            "report": chain_report,
            "summary": summary,
            "manifest": manifest,
            "is_synthetic": is_synthetic,
            "is_rpc_verified": is_rpc_verified,
            "environment_checked_on": setup_date,
            "environment_observations": environment_observations,
        },
    }
