"""Build traceable JSON facts and a concise Markdown run report."""
import json
from pathlib import Path


def _pct(value):
    return "未定义" if value is None else f"{value:.2%}"


def build_report(run_dir: str) -> dict:
    """Report the newest successful trial saved in a campaign output folder."""
    root = Path(run_dir)
    candidates = sorted([*root.glob("trial-*.json"), *root.glob("holdout-*.json")])
    if not candidates:
        raise ValueError("no saved trial is available for reporting")
    valid_records = []
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"trial artifact is invalid: {path.name}") from exc
        if value.get("status") == "succeeded":
            valid_records.append((value.get("created_at", ""), path.name, path, value))
    if not valid_records:
        raise ValueError("no successful trial is available for reporting")
    _, _, trial_path, record = max(
        valid_records,
        key=lambda item: (item[0], item[3].get("stage") == "holdout", item[1]))

    facts = {
        "schema_version": "crypto-facts-v1",
        "run_id": record["run_id"],
        "provenance": record["provenance"],
        "metrics": record["metrics"],
        "attribution": record["attribution"],
        "risks": record["risk_scenarios"],
        "limitations": record["limitations"],
        "evidence": {
            "metrics": {"file": trial_path.name, "json_pointer": "/metrics"},
            "attribution": {"file": trial_path.name, "json_pointer": "/attribution"},
            "risk_scenarios": {"file": trial_path.name,
                                "json_pointer": "/risk_scenarios"},
            "event_ledger": record.get("ledger_path"),
        },
    }
    margin_path = root / f"{trial_path.stem}-margin-audit.json"
    campaign_feasibility_path = root / "campaign-feasibility.json"
    margin_audit = (json.loads(margin_path.read_text(encoding="utf-8"))
                    if margin_path.is_file() else None)
    campaign_feasibility = (
        json.loads(campaign_feasibility_path.read_text(encoding="utf-8"))
        if campaign_feasibility_path.is_file() else None)
    if margin_audit is not None:
        facts["margin_feasibility"] = margin_audit
        facts["evidence"]["margin_audit"] = {
            "file": margin_path.name, "json_pointer": "/"}
    if campaign_feasibility is not None:
        facts["campaign_feasibility"] = campaign_feasibility
        facts["evidence"]["campaign_feasibility"] = {
            "file": campaign_feasibility_path.name, "json_pointer": "/"}
    facts_path = root / "facts.json"
    facts_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2,
                                     allow_nan=False), encoding="utf-8")

    metrics = record["metrics"]
    attribution = record["attribution"]
    sharpe = metrics.get("sharpe_daily")
    sharpe_label = "未定义" if sharpe is None else f"{sharpe:.3f}"
    report = [
        "# Crypto carry research run",
        "",
        f"- Run: `{record['run_id']}`",
        f"- Baseline: `{record['strategy']}` ({record['stage']})",
        f"- Snapshot: `{record['provenance']['snapshot_id']}`",
        f"- Period: {metrics.get('start_time')} → {metrics.get('end_time')} UTC",
        "",
        "## Performance",
        "",
        f"- Total return: {_pct(metrics.get('total_return'))}",
        f"- CAGR: {_pct(metrics.get('cagr'))}",
        f"- Maximum drawdown: {_pct(metrics.get('max_drawdown'))}",
        f"- Annualized volatility: {_pct(metrics.get('annualized_volatility'))}",
        f"- Daily Sharpe: {sharpe_label}",
        "",
        "## Metric basis and sample limits",
        "",
        f"- Sample: {metrics.get('daily_return_count', 'unknown')} daily samples over {metrics.get('elapsed_days', 'unknown')} days.",
        f"- Annualization: {metrics.get('annualization_basis', 'not specified')}.",
        f"- Maximum drawdown: {metrics.get('max_drawdown_basis', 'not specified')}.",
    ]
    report.extend(f"- {item}" for item in metrics.get("limitations", []))
    if margin_audit is not None:
        report.extend(["", "## Isolated margin audit", "",
                       f"- Status: `{margin_audit['status']}` across {margin_audit['mark_observations']} hourly mark observations."])
        if margin_audit.get("breach_observations"):
            report.append(
                f"- Below the declared maintenance proxy: {margin_audit['breach_observations']} observations; first at {margin_audit['first_breach_time']} UTC; minimum margin headroom {margin_audit['minimum_headroom']:.2f} USDT.")
        report.extend(f"- {item}" for item in margin_audit.get("limitations", []))
    if campaign_feasibility is not None:
        report.extend(["", "## Frozen candidate feasibility across stages", "",
                       f"- Candidate: `{campaign_feasibility.get('candidate_strategy')}`; status: `{campaign_feasibility.get('status')}`."])
        for stage in campaign_feasibility.get("candidate_breach_stages", []):
            audit = campaign_feasibility.get("stages", {}).get(stage) or {}
            report.append(
                f"- `{stage}` had {audit.get('breach_observations')} hourly observations below the declared maintenance proxy; first at {audit.get('first_breach_time')} UTC. The positive accounting replay return is not executable under this isolated-margin assumption.")
        report.extend(f"- {item}" for item in campaign_feasibility.get("limitations", []))
    report.extend([
        "",
        "## P&L attribution (USDT)",
        "",
    ])
    for key in ("spot_pnl", "perp_pnl", "funding", "spot_fees", "perp_fees", "slippage"):
        report.append(f"- {key}: {attribution.get(key, '0')}")
    report.extend(["", "## Limitations", ""])
    report.extend(f"- {item}" for item in record["limitations"])
    report.extend(["", "## Evidence", "",
                   f"- Metrics and attribution: `{trial_path.name}`",
                   f"- Event ledger: `{record.get('ledger_path')}`",
                   f"- Structured facts: `facts.json`", ""])
    report_path = root / "report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    return {"facts_path": str(facts_path.resolve()),
            "report_path": str(report_path.resolve()),
            "run_id": record["run_id"]}
