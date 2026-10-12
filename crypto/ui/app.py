"""Interactive BTC Carry experiments plus read-only research evidence."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

from crypto.ui.catalog import load_campaign_catalog
from crypto.ui.glossary import (
    ATTRIBUTION_LABELS,
    COMPARISON_FIELD_GLOSSARY,
    DASHBOARD_FIELD_GLOSSARY,
    DASHBOARD_FIELD_LABELS,
    RISK_FIELD_GLOSSARY,
    RISK_FIELD_LABELS,
    RISK_LIMITATION_LABELS,
    SCENARIO_DESCRIPTIONS,
    SCENARIO_LABELS,
    STAGE_LABELS,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_LABELS,
)
from crypto.ui.integrations import build_integrated_status
from crypto.ui.view_model import build_dashboard_model
from crypto.ui.playground_tab import render_playground_tab


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAMPAIGN_DIR = PROJECT_ROOT / "results" / "crypto" / "btc-carry-v3-20261010"


def _format_percent(value) -> str:
    if value is None:
        return "未定义"
    return f"{float(value):.2%}"


def _format_number(value, digits=2) -> str:
    if value is None:
        return "未定义"
    return f"{float(value):,.{digits}f}"


def _equity_chart_frame(points, pandas_module=None):
    """Build the UTC chart index from ISO 8601 timestamps with mixed precision."""
    if pandas_module is None:
        import pandas as pandas_module
    frame = pandas_module.DataFrame(points)
    frame["time"] = pandas_module.to_datetime(
        frame["time"], format="ISO8601", utc=True)
    return frame.set_index("time")


def _render_research_tab(campaign_dir, catalog, st, alt, pd) -> None:
    """Render the existing backtest workbench inside the integrated page."""
    trials = catalog["trials"]
    campaign = catalog["campaign_feasibility"]
    candidate_strategy = campaign.get("candidate_strategy")
    if campaign.get("candidate_breach_stages"):
        stages = ", ".join(campaign["candidate_breach_stages"])
        st.error(
            f"研究可行性提醒：候选策略 {STRATEGY_LABELS.get(candidate_strategy, candidate_strategy)} "
            f"在 {stages} 阶段低于模拟的隔离保证金线；该阶段账面收益不代表可执行。"
        )
    st.warning(
        "这是历史研究回放。筛选会按已完成试验重算区间统计和图表，不会启动策略或发送交易订单。"
    )

    root = Path(catalog["campaign_dir"])
    strategy_options = list(dict.fromkeys(row["strategy"] for row in trials))
    default_strategy = (candidate_strategy if candidate_strategy in strategy_options
                        else strategy_options[0])
    selected_strategy = st.selectbox(
        "历史回放策略", strategy_options,
        index=strategy_options.index(default_strategy),
        format_func=lambda strategy: STRATEGY_LABELS.get(strategy, strategy),
        key="crypto_strategy",
    )
    st.caption(STRATEGY_DESCRIPTIONS.get(selected_strategy, ""))
    strategy_trials = [row for row in trials
                       if row["strategy"] == selected_strategy]
    stage_options = list(dict.fromkeys(row["stage"] for row in strategy_trials))
    default_stage = ("holdout" if "holdout" in stage_options else
                     "validation" if "validation" in stage_options else stage_options[0])
    selected_stage = st.selectbox(
        "历史回放阶段（已保存结果）", stage_options,
        index=stage_options.index(default_stage),
        format_func=lambda stage: STAGE_LABELS.get(stage, stage),
        key=f"crypto_stage_{selected_strategy}",
    )
    selected = next(row for row in strategy_trials
                    if row["stage"] == selected_stage)
    selected_id = selected["trial_id"]
    start_default = date.fromisoformat(selected["start_time"][:10])
    end_default = date.fromisoformat(selected["end_time"][:10])
    if selected["end_time"][11:19] == "00:00:00":
        end_default -= timedelta(days=1)
    selected_dates = st.date_input(
        "历史回放日期范围（UTC，含首尾日）",
        value=(start_default, end_default),
        min_value=start_default,
        max_value=end_default,
        key=f"chart_date_range_{selected_id}",
        help="收益、回撤、资金费和归因会按所选日期更新。不同研究阶段各自独立计算。",
    )
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_day, end_day = selected_dates
    elif isinstance(selected_dates, date):
        start_day = end_day = selected_dates
    else:
        st.error("日期筛选格式无效。")
        return
    try:
        model = build_dashboard_model(
            str(root), selected_id, start_day.isoformat(), end_day.isoformat())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"无法构建图表：{exc}")
        return

    summary = model["selected_summary"]
    st.subheader(
        f"{STRATEGY_LABELS.get(model['strategy'], model['strategy'])} · "
        f"{STAGE_LABELS.get(model['stage'], model['stage'])}"
    )
    st.caption(
        f"查看 {model['selected_range']['start']} 至 {model['selected_range']['end']} UTC · "
        f"完整阶段 {model['coverage']['start']} 至 {model['coverage']['end']} · "
        f"运行编号 `{model['run_id']}` · 数据快照 `{model['provenance'].get('snapshot_id', 'unknown')}`"
    )
    st.caption("区间收益从开始日 00:00 起算，首尾日都包含。次日 00:00 记录作为前一日收盘，资金费也按此归日。保证金审计和跨阶段对照使用完整阶段数据。")

    metric_columns = st.columns(5)
    metric_columns[0].metric("选定区间收益", _format_percent(summary.get("total_return")))
    metric_columns[1].metric("CAGR", _format_percent(summary.get("cagr")))
    metric_columns[2].metric("最大回撤", _format_percent(summary.get("max_drawdown")))
    metric_columns[3].metric("日 Sharpe", _format_number(summary.get("sharpe_daily"), 3))
    metric_columns[4].metric(
        "区间资金费 · USDT", _format_number(
            next((row["amount"] for row in model["attribution_rows"]
                  if row["component"] == "funding"), None)))

    if model["selected_metric_limitations"]:
        st.info("所选区间的指标限制：" + "；".join(model["selected_metric_limitations"]))
    audit = model["margin_audit"]
    if audit.get("breach_observations", 0):
        st.error(
            f"完整阶段有 {audit['breach_observations']:,}/{audit['mark_observations']:,} "
            "个小时标记低于模拟的维持保证金与估算退出成本阈值。"
            f"首次：{audit.get('first_breach_time')} UTC。"
        )
    elif audit.get("status") == "not_applicable_no_open_perpetual":
        st.info("该现金基线没有永续持仓，保证金审计不适用。")
    else:
        st.success("完整阶段未观察到小时级保证金代理下穿；这不等于交易所强平检查。")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("所选区间的账户权益 · USDT")
        equity_frame = _equity_chart_frame(model["equity_series"], pd).reset_index()
        equity_chart = alt.Chart(equity_frame).mark_line().encode(
            x=alt.X("time:T", title="日期（UTC）", axis=alt.Axis(
                labelExpr="utcFormat(datum.value, '%Y-%m-%d')")),
            y=alt.Y("equity:Q", title="权益（USDT）"),
            tooltip=[alt.Tooltip("time:T", title="UTC 时间"),
                     alt.Tooltip("equity:Q", title="权益（USDT）", format=",.4f")],
        ).properties(height=330)
        st.altair_chart(equity_chart, width="stretch")
    with right:
        st.subheader("所选区间的每日资金费 · USDT")
        funding_frame = pd.DataFrame(model["funding_series"], columns=["date", "cashflow"])
        if funding_frame.empty:
            st.info("所选期间没有资金费结算。")
        else:
            funding_frame["date"] = pd.to_datetime(funding_frame["date"], utc=True)
            funding_chart = alt.Chart(funding_frame).mark_bar().encode(
                x=alt.X("date:T", title="日期（UTC）", axis=alt.Axis(
                    labelExpr="utcFormat(datum.value, '%Y-%m-%d')")),
                y=alt.Y("cashflow:Q", title="资金费（USDT）"),
                tooltip=[alt.Tooltip("date:T", title="UTC 日期"),
                         alt.Tooltip("cashflow:Q", title="资金费（USDT）", format=",.6f")],
            ).properties(height=330)
            st.altair_chart(funding_chart, width="stretch")

    st.subheader("收益来源 · 选定区间 USDT")
    attribution_frame = pd.DataFrame(model["attribution_rows"]).set_index("component")
    attribution_frame.index = [ATTRIBUTION_LABELS.get(item, item)
                               for item in attribution_frame.index]
    attribution_chart = alt.Chart(attribution_frame.reset_index()).mark_bar().encode(
        y=alt.Y("component:N", title="收益项目", sort="-x"),
        x=alt.X("amount:Q", title="USDT"),
        tooltip=[alt.Tooltip("component:N", title="项目"),
                 alt.Tooltip("amount:Q", title="USDT", format=",.6f")],
    ).properties(height=270)
    st.altair_chart(attribution_chart, width="stretch")
    st.dataframe(attribution_frame.rename(columns={"amount": "USDT"}),
                 width="stretch")

    st.subheader("各策略完整阶段对照（不受日期筛选影响）")
    comparison_rows = []
    for trial in trials:
        comparison_rows.append({
            "策略": STRATEGY_LABELS.get(trial["strategy"], trial["strategy"]),
            "阶段": STAGE_LABELS.get(trial["stage"], trial["stage"]),
            "样本日数": trial["daily_return_count"],
            "总收益": _format_percent(trial["total_return"]),
            "CAGR": _format_percent(trial["cagr"]),
            "最大回撤": _format_percent(trial["max_drawdown"]),
            "日 Sharpe": _format_number(trial["sharpe_daily"], 3),
            "保证金代理": trial["margin_status"],
            "下穿小时": trial["margin_breaches"],
        })
    st.dataframe(pd.DataFrame(comparison_rows), hide_index=True,
                 width="stretch")

    st.subheader("风险情景（按当前策略和阶段；不随日期筛选变动）")
    if model["risk_scenarios"]:
        risk_rows = [{
            "压力情景": SCENARIO_LABELS.get(row.get("scenario"), row.get("scenario")),
            "净 BTC 敞口": _format_number(row.get("net_delta"), 6),
            "保证金缺口 · USDT": _format_number(row.get("collateral_shortfall")),
            "估算退出成本 · USDT": _format_number(row.get("estimated_exit_cost")),
            "情景后账户权益 · USDT": _format_number(
                row.get("account_equity_after_scenario")),
            "模型限制": "；".join(
                RISK_LIMITATION_LABELS.get(item, item)
                for item in row.get("limitations", [])),
        } for row in model["risk_scenarios"]]
        st.dataframe(pd.DataFrame(risk_rows), hide_index=True,
                     width="stretch")
    else:
        st.info("此基线没有永续风险情景。")

    with st.expander("字段说明和风险情景释义"):
        st.markdown("#### 看板指标与收益来源")
        dashboard_rows = [{"页面显示": DASHBOARD_FIELD_LABELS.get(key, key),
                           "字段名": key, "含义": meaning}
                          for key, meaning in DASHBOARD_FIELD_GLOSSARY.items()]
        st.dataframe(pd.DataFrame(dashboard_rows), hide_index=True,
                     width="stretch")
        st.markdown("#### 完整阶段对照表")
        comparison_rows = [{"字段": field, "含义": meaning}
                           for field, meaning in COMPARISON_FIELD_GLOSSARY.items()]
        st.dataframe(pd.DataFrame(comparison_rows), hide_index=True,
                     width="stretch")
        st.markdown("#### 风险表字段")
        risk_field_rows = [{"页面显示": RISK_FIELD_LABELS[field],
                            "字段名": field, "含义": meaning}
                           for field, meaning in RISK_FIELD_GLOSSARY.items()]
        st.dataframe(pd.DataFrame(risk_field_rows), hide_index=True,
                     width="stretch")
        st.markdown("#### 风险情景释义")
        scenario_codes = list(dict.fromkeys(
            row.get("scenario") for row in model["risk_scenarios"]
            if row.get("scenario") in SCENARIO_LABELS))
        scenario_rows = [{
            "情景代码": code,
            "中文名称": SCENARIO_LABELS[code],
            "含义": SCENARIO_DESCRIPTIONS[code],
        } for code in scenario_codes]
        st.dataframe(pd.DataFrame(scenario_rows), hide_index=True,
                     width="stretch")

    with st.expander("假设、数据来源与限制"):
        st.json({
            "假设": model["assumptions"],
            "来源": model["provenance"],
            "保证金审计": audit,
            "campaign 可行性": campaign,
            "限制": model["limitations"],
            "指标限制": model["metric_limitations"],
        })
    st.subheader("下载原始证据")
    trial_path = root / model["source_files"]["trial"]
    ledger_path = root / model["source_files"]["ledger"]
    facts_path = root / catalog["facts_file"]
    download_columns = st.columns(4)
    download_columns[0].download_button(
        "下载当前试验 JSON", data=trial_path.read_bytes(),
        file_name=trial_path.name, mime="application/json")
    download_columns[1].download_button(
        "下载冻结数据 facts.json", data=facts_path.read_bytes(),
        file_name=facts_path.name, mime="application/json")
    download_columns[2].download_button(
        "下载当前账本 CSV", data=ledger_path.read_bytes(),
        file_name=ledger_path.name, mime="text/csv")
    campaign_path = root / catalog["campaign_file"]
    download_columns[3].download_button(
        "下载 campaign 审计", data=campaign_path.read_bytes(),
        file_name=campaign_path.name, mime="application/json")


def _render_ai_tab(st, integrated: dict) -> None:
    ai = integrated["ai"]
    metadata = ai["metadata"]
    st.subheader("AI 研究报告 · trial-005 / development")
    if ai["is_offline_fallback"]:
        st.warning("当前未配置 LLM provider。下方是由已审计事实生成的确定性报告，不是在线模型回答。")
    else:
        st.info(f"报告状态：{metadata['status']} · provider：{metadata['provider']}")
    st.caption(
        f"{ai['trial_id']} · {ai['stage']} · provider `{metadata['provider']}` · "
        f"输入哈希 `{metadata['input_sha256'][:16]}…` · prompt `{metadata['prompt_version']}`"
    )
    st.markdown(ai["report"])
    st.download_button(
        "下载 AI 研究报告", data=ai["report"],
        file_name="trial-005-development.md", mime="text/markdown")
    with st.expander("报告状态与来源元数据"):
        st.json(metadata)


def _render_chain_tab(st, pd, integrated: dict) -> None:
    chain = integrated["onchain"]
    summary = chain["summary"]
    if chain["is_synthetic"]:
        st.error("合成工程夹具演示：以下区块、地址和 Swap 数据不是链上证据。真实 RPC 与 Anvil fork 尚未验收。")
    elif chain["is_rpc_verified"]:
        st.success("链身份与 canonical 事件已由节点核验。")
    else:
        st.warning("尚未满足真实 RPC 核验条件；不能将此结果描述为链上验证。")

    columns = st.columns(3)
    columns[0].metric("事件来源", "Synthetic fixture" if chain["is_synthetic"] else summary["source_status"])
    columns[1].metric("Swap 事件", f"{summary['swap_count']}（示例）" if chain["is_synthetic"] else str(summary["swap_count"]))
    columns[2].metric("池身份", chain["manifest"]["identity_status"])
    st.caption(
        f"区块范围 {summary['block_range'][0]}–{summary['block_range'][1]} · "
        f"审计状态 `{summary['status']}` · 这里只演示事件处理，不表示交易者成交或套利收益。"
    )
    prices = summary.get("price_observations", [])
    if prices:
        st.subheader("Swap 后价格观察（合成夹具）")
        st.dataframe(pd.DataFrame(prices), hide_index=True, width="stretch")
    if chain["environment_observations"]:
        checked = chain["environment_checked_on"] or "日期未记录"
        st.subheader(f"环境检查（记录日期：{checked}）")
        for item in chain["environment_observations"]:
            st.write(f"• {item}")
    with st.expander("事件报告与限制"):
        st.markdown(chain["report"])
    st.download_button(
        "下载链上演示 artifact（JSON）",
        data=json.dumps(chain["artifact"], ensure_ascii=False, indent=2),
        file_name="synthetic-event-demo.json", mime="application/json")
    st.download_button(
        "下载链上演示报告（Markdown）", data=chain["report"],
        file_name="synthetic-event-demo.md", mime="text/markdown")


def render_app(campaign_dir: str | Path = DEFAULT_CAMPAIGN_DIR) -> None:
    """Render a local strategy playground and any available frozen evidence."""
    import altair as alt
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="BTC Carry 研究工作台", page_icon="₿",
                       layout="wide")
    st.title("BTC Carry 研究工作台")
    st.caption("策略实验只运行历史 development 数据；其余页面读取本地保存的研究证据。")

    catalog = None
    catalog_error = None
    try:
        catalog = load_campaign_catalog(str(campaign_dir))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        catalog_error = str(exc)
    trials = catalog.get("trials", []) if catalog else []

    integrated = None
    integrated_error = None
    try:
        integrated = build_integrated_status(PROJECT_ROOT)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        integrated_error = str(exc)

    status_columns = st.columns(3)
    campaign = (catalog.get("campaign_feasibility") or {}) if catalog else {}
    candidate = campaign.get("candidate_strategy")
    holdout = next((row for row in trials
                    if row["stage"] == "holdout" and row["strategy"] == candidate), None)
    if holdout:
        status_columns[0].metric(
            "一次性 holdout", _format_percent(holdout["total_return"]),
            f"{holdout['daily_return_count']} 日 · 已消费",
        )
    else:
        status_columns[0].metric(
            "历史 holdout", "尚无本地记录" if not trials else "无可用记录"
        )

    if integrated:
        ai_status = integrated["ai"]["metadata"]["status"]
        ai_label = "事实回退（离线）" if ai_status == "fallback" else "模型解读"
        chain_label = (
            "未核验 · 合成样例" if integrated["onchain"]["is_synthetic"]
            else "RPC 已核验" if integrated["onchain"]["is_rpc_verified"]
            else "未核验"
        )
    else:
        ai_label = "本地报告不可用"
        chain_label = "本地示例不可用"
    status_columns[1].metric("AI 报告", ai_label, "只展示已保存报告")
    status_columns[2].metric("链上状态", chain_label, "示例不等于真实链上验证")

    playground_tab, research_tab, ai_tab, chain_tab = st.tabs(
        ["策略实验", "历史回放", "AI 研究报告", "链上验证"]
    )
    with playground_tab:
        render_playground_tab(st, alt, pd, project_root=PROJECT_ROOT)
    with research_tab:
        if catalog and trials:
            _render_research_tab(campaign_dir, catalog, st, alt, pd)
        elif catalog_error:
            st.info(
                "尚无可读取的冻结 campaign artifact。策略实验页仍可使用；"
                f"历史回放暂不可用：{catalog_error}"
            )
        else:
            st.info("本机还没有已完成的冻结研究结果；可先运行策略实验。")
    with ai_tab:
        if integrated:
            _render_ai_tab(st, integrated)
        else:
            st.info(
                "未找到本机保存的 AI 报告 artifact。此页面不会自动调用 AI。"
                + (f" 详情：{integrated_error}" if integrated_error else "")
            )
    with chain_tab:
        if integrated:
            _render_chain_tab(st, pd, integrated)
        else:
            st.info(
                "未找到本机保存的链上事件演示 artifact；本页面不会自动连接 RPC。"
                + (f" 详情：{integrated_error}" if integrated_error else "")
            )


if __name__ == "__main__":
    render_app()
