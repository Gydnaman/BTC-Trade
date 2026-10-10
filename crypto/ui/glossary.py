"""Plain-language Chinese labels and definitions for the crypto workbench."""

STRATEGY_LABELS = {
    "cash_zero": "现金基准（空仓）",
    "carry_static": "固定持有对冲",
    "funding_filter": "正资金费率筛选",
}

STRATEGY_DESCRIPTIONS = {
    "cash_zero": "不持有 BTC，也不做永续合约；作为零收益参照。",
    "carry_static": "买入 BTC 现货并做空等量永续合约，持有到本阶段结束。",
    "funding_filter": "最近一次已结算费率为正时持有对冲组合，否则空仓。",
}

STAGE_LABELS = {
    "development": "开发期",
    "validation": "验证期",
    "holdout": "留出期（最终检验）",
}

SCENARIO_LABELS = {
    "base": "基准情景",
    "price_gap_up_20pct": "现货与永续同时跳涨 20%",
    "basis_expansion_against_short": "基差向空头不利方向扩大",
    "negative_funding": "负资金费率（空头付费）",
    "spot_data_outage": "现货市场暂不可用",
    "slippage_1bps": "滑点 1 基点",
    "slippage_5bps": "滑点 5 基点",
    "slippage_15bps": "滑点 15 基点",
    "perpetual_entry_timeout_after_spot_fill": "现货成交后，永续进场超时",
}

SCENARIO_DESCRIPTIONS = {
    "base": "按入场附近价格和默认手续费、滑点及 5% 维持保证金假设估算。",
    "price_gap_up_20pct": "假设现货和永续价格都突然上涨 20%，检查两条腿能否抵消方向变化。",
    "basis_expansion_against_short": "假设现货上涨 5%、永续标记价上涨 20%；空头合约涨得更多，测试基差风险。",
    "negative_funding": "假设资金费率为 -0.1%；该对冲组合的永续空头需要支付资金费。",
    "spot_data_outage": "假设现货腿暂时不能成交，检查无法同步调整两条腿时的风险。",
    "slippage_1bps": "假设两条腿平仓时各承受 1 个基点滑点。1 个基点等于 0.01%。",
    "slippage_5bps": "假设两条腿平仓时各承受 5 个基点滑点。1 个基点等于 0.01%。",
    "slippage_15bps": "假设两条腿平仓时各承受 15 个基点滑点。1 个基点等于 0.01%。",
    "perpetual_entry_timeout_after_spot_fill": "现货买入成功但永续空单未成交，账户暂时留下 BTC 多头敞口。",
}

DASHBOARD_FIELD_GLOSSARY = {
    "total_return": "所选 UTC 日期内账户权益相对区间起点的变化比例；包含首日收益。",
    "cagr": "按实际经过时间折算的复合年增长率，按 365.25 天折年；短区间很不稳定。",
    "max_drawdown": "按 UTC 日收盘权益计算，从此前高点到随后低点的最大跌幅。",
    "sharpe_daily": "日收益相对波动的粗略风险调整指标；样本短或波动为零时不计算。",
    "annualized_volatility": "按日收益波动折算的年化波动率，不代表最大可能亏损。",
    "daily_return_count": "用于计算区间风险指标的 UTC 日收益条数；次日 00:00 记作前一日收盘。",
    "selected_range": "当前筛选的 UTC 起止日期，开始日和结束日都包含在内。",
    "initial_equity": "区间起点权益：首个样本日取初始资金，否则取开始日 00:00 时或之前最近的权益记录。",
    "final_equity": "区间结束日的收盘权益；如果有次日 00:00 记录，会用它作为收盘标记。",
    "funding": "区间内永续合约资金费净收付；UTC 次日 00:00 的结算归到前一日，正数为收到、负数为支付。",
    "spot_pnl": "区间内 BTC 现货价格变化带来的盈亏。",
    "perp_pnl": "区间内永续合约价格变化带来的盈亏。",
    "spot_fees": "区间内现货交易手续费，按成本记为正数并从收益中扣除。",
    "perp_fees": "区间内永续合约手续费，按成本记为正数并从收益中扣除。",
    "slippage": "估算成交价相对参考价的不利差额，按成本记为正数并从收益中扣除。",
}

DASHBOARD_FIELD_LABELS = {
    "total_return": "选定区间收益",
    "cagr": "CAGR",
    "max_drawdown": "最大回撤",
    "sharpe_daily": "日 Sharpe",
    "annualized_volatility": "年化波动率",
    "daily_return_count": "日收益样本数",
    "selected_range": "查看日期范围",
    "initial_equity": "区间起始权益",
    "final_equity": "区间结束权益",
    "funding": "资金费净收付",
    "spot_pnl": "现货价格盈亏",
    "perp_pnl": "永续价格盈亏",
    "spot_fees": "现货手续费",
    "perp_fees": "永续手续费",
    "slippage": "滑点成本",
}

COMPARISON_FIELD_GLOSSARY = {
    "策略": "参与比较的策略名称；每个策略在各自已完成的研究阶段单独列一行。",
    "阶段": "开发期、验证期或留出期；留出期是最后一次检验。",
    "样本日数": "用于计算该完整阶段绩效的 UTC 日收益条数。",
    "总收益": "该完整阶段结束权益相对起始权益的变化比例。",
    "CAGR": "该完整阶段按实际经过时间折算的复合年增长率。",
    "最大回撤": "该完整阶段按 UTC 日收盘权益观察到的最大跌幅。",
    "日 Sharpe": "该完整阶段的日收益风险调整指标；不表示未来收益保证。",
    "保证金代理": "模拟保证金检查的结果；它不等同于交易所的真实强平规则。",
    "下穿小时": "完整阶段中，权益低于模型维持保证金与退出成本门槛的小时标记数。",
}

ATTRIBUTION_LABELS = {
    "spot_pnl": "现货价格盈亏",
    "perp_pnl": "永续价格盈亏",
    "funding": "资金费净收付",
    "spot_fees": "现货手续费",
    "perp_fees": "永续手续费",
    "slippage": "滑点成本",
}

RISK_FIELD_LABELS = {
    "scenario": "情景",
    "net_delta": "净 BTC 敞口",
    "collateral_shortfall": "保证金缺口",
    "estimated_exit_cost": "估算退出成本",
    "account_equity_after_scenario": "情景后账户权益",
    "limitations": "模型限制",
}

RISK_FIELD_GLOSSARY = {
    "scenario": "假设发生的市场或成交压力条件；本表是一组模拟，不是历史发生记录。",
    "net_delta": "现货 BTC 数量加永续合约 BTC 等价数量；接近 0 表示方向敞口大致抵消。单位为 BTC。",
    "collateral_shortfall": "按模型里的逐仓和维持保证金假设，永续保证金不足的金额；0 不代表交易所保证不会强平。单位为 USDT。",
    "estimated_exit_cost": "按设定手续费和滑点估算关闭两条腿的成本。单位为 USDT。",
    "account_equity_after_scenario": "计入现货价值、永续盈亏、资金费和估算退出成本后的模拟权益。单位为 USDT。",
    "limitations": "当前情景模型没有还原交易所逐笔撮合、真实强平价格或小时内成交过程。",
}

RISK_LIMITATION_LABELS = {
    "isolated perpetual margin; spot profit is not cross-collateral":
        "永续腿按逐仓计算，现货浮盈不会自动补入合约保证金。",
    "maintenance ratio and costs are scenario assumptions, not historical exchange rules":
        "维持保证金率和费用是压力假设，不是交易所历史规则。",
    "hourly bars cannot identify liquidation or leg execution prices":
        "小时 K 线无法还原真实强平时点和两条腿的成交价格。",
}
