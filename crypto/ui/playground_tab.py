"""Form-based strategy experiment panel for the BTC carry workbench."""
from __future__ import annotations

import json
from pathlib import Path

from crypto.playground import run_playground


STRATEGY_LABELS = {
    "cash_zero": "现金基准（不持仓）",
    "carry_static": "固定 Carry（买现货、空永续）",
    "funding_filter": "资金费率过滤 Carry",
}
STRATEGY_DESCRIPTIONS = {
    "cash_zero": "把初始资金留在现金中，作为零收益比较基准。",
    "carry_static": "在 development 区间首个可交易小时开仓：买入 BTC 现货、卖出等量永续；区间末平仓。",
    "funding_filter": "只使用已经结算的资金费率；高于门槛时在下一可交易小时开仓，条件不满足后再平仓。",
}


def build_playground_parameters(
    strategy: str,
    allocation_percent: float,
    collateral_ratio: float,
    threshold_bps: float,
) -> dict:
    """Convert beginner-facing percent and basis-point fields to engine units."""
    if strategy == "cash_zero":
        return {}
    parameters = {
        "allocation_fraction": float(allocation_percent) / 100.0,
        "collateral_ratio": float(collateral_ratio),
    }
    if strategy == "funding_filter":
        parameters["positive_funding_threshold"] = float(threshold_bps) / 10_000.0
    return parameters


def _percent(value) -> str:
    return "未定义" if value is None else f"{float(value):.2%}"


def _number(value, digits=3) -> str:
    return "未定义" if value is None else f"{float(value):,.{digits}f}"


def _show_result(record: dict, st, alt, pd) -> None:
    metrics = record["metrics"]
    stage = record["provenance"]["stage_range"]
    st.success("回测已完成。结果只代表 development 阶段的历史研究，不是实盘验证。")
    st.caption(
        f"UTC 区间：{stage['start']} 至 {stage['end']} · "
        f"快照：{record['provenance']['snapshot_id']} · "
        f"运行编号：{record['run_id']}"
    )

    columns = st.columns(4)
    columns[0].metric("总收益", _percent(metrics.get("total_return")))
    columns[1].metric("最大回撤", _percent(metrics.get("max_drawdown")))
    columns[2].metric("CAGR", _percent(metrics.get("cagr")))
    columns[3].metric("日 Sharpe", _number(metrics.get("sharpe_daily")))

    points = record.get("equity_series", [])
    if points:
        frame = pd.DataFrame(points)
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        chart = alt.Chart(frame).mark_line().encode(
            x=alt.X("time:T", title="时间（UTC）"),
            y=alt.Y("equity:Q", title="账户权益（USDT）"),
            tooltip=[alt.Tooltip("time:T", title="UTC 时间"),
                     alt.Tooltip("equity:Q", title="账户权益", format=",.4f")],
        ).properties(height=300)
        st.subheader("历史账户权益")
        st.altair_chart(chart, width="stretch")

    attribution = record.get("attribution", {})
    if attribution:
        from crypto.ui.glossary import ATTRIBUTION_LABELS
        rows = [{
            "收益项目": ATTRIBUTION_LABELS.get(field, field),
            "金额（USDT）": float(value),
        } for field, value in attribution.items()]
        st.subheader("收益来源")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with st.expander("本次回测使用的假设、风险情景和限制"):
        st.write("参数与费用假设")
        st.json(record.get("assumptions", {}))
        st.write("风险情景")
        st.json(record.get("risk_scenarios", []))
        st.write("研究限制")
        for limitation in record.get("limitations", []):
            st.write(f"• {limitation}")
        st.write("来源文件")
        st.json(record.get("artifact_paths", {}))

    trial_path = Path(record["artifact_paths"]["trial"])
    ledger_path = Path(record["artifact_paths"]["ledger"])
    st.download_button(
        "下载本次回测摘要（JSON）",
        data=trial_path.read_bytes(),
        file_name=trial_path.name,
        mime="application/json",
    )
    st.download_button(
        "下载事件账本（CSV）",
        data=ledger_path.read_bytes(),
        file_name=ledger_path.name,
        mime="text/csv",
    )


def render_playground_tab(st, alt, pd, *, project_root: str | Path) -> None:
    """Render a constrained form; no strategy executes until the form is submitted."""
    st.subheader("创建一次 BTC/USDT Carry 历史实验")
    st.markdown(
        "选择一个已有策略模板，再填写它的参数。这里不运行你输入的代码；"
        "每次只回测已审计数据的 development 区间。"
    )
    st.warning(
        "所有新实验都标记为 development-only。它们不会访问 validation/holdout，"
        "不会修改冻结 campaign，也不会连接交易账户或发送订单。"
    )

    strategy = st.selectbox(
        "策略模板",
        list(STRATEGY_LABELS),
        format_func=lambda item: STRATEGY_LABELS[item],
        key="playground_strategy",
    )
    st.caption(STRATEGY_DESCRIPTIONS[strategy])
    with st.form("btc_carry_playground_form"):
        allocation_percent = 25.0
        collateral_ratio = 1.0
        threshold_bps = 0.0
        if strategy != "cash_zero":
            allocation_percent = st.number_input(
                "初始权益中用于 Carry 的比例（%）",
                min_value=0.1, max_value=50.0, value=25.0, step=1.0,
                help="例如 25 表示以初始权益的 25% 计算两条腿的名义金额。",
            )
            collateral_ratio = st.number_input(
                "永续腿抵押比例（倍）",
                min_value=0.1, max_value=2.0, value=1.0, step=0.1,
                help="这是研究账本里的初始隔离抵押假设，不代表交易所保证金规则。",
            )
            st.caption(
                "参数组合按现货与永续价格接近估算：名义仓位与抵押合计最多占初始权益的95%，"
                "至少保留5%作为余量。"
            )
        if strategy == "funding_filter":
            threshold_bps = st.number_input(
                "资金费率触发门槛（基点 / 每次结算）",
                min_value=-1000.0, max_value=1000.0, value=0.0, step=0.1,
                help="1 基点 = 0.01%；门槛只比较已结算费率，进场发生在之后可交易小时。",
            )
        submitted = st.form_submit_button("运行一次开发阶段回测")

    if not submitted:
        st.info(
            "运行前需要本机存在已审计的 Binance BTC/USDT 小时数据快照。"
            "请先按 README 的“准备历史数据”步骤采集；没有数据时不会用模拟行情代替。"
        )
        return

    parameters = build_playground_parameters(
        strategy, allocation_percent, collateral_ratio, threshold_bps
    )
    try:
        record = run_playground(
            strategy, parameters, project_root=project_root
        )
    except (OSError, ValueError, RuntimeError) as exc:
        st.error(f"本次实验未运行：{exc}")
        st.info(
            "请确认快照 manifest 状态为 audited、数据文件未被移动且哈希未变化，"
            "再查看 README 或 docs/crypto/DATA.md。"
        )
        return
    _show_result(record, st, alt, pd)
