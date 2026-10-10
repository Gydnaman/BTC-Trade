"""
回测引擎
向量化回测，基于pandas/numpy实现，无需第三方回测库
支持单标的和多标的，包含交易成本模拟

核心逻辑:
    1. 策略生成目标仓位信号
    2. 按信号计算每日收益
    3. 扣除交易成本（佣金+滑点+印花税）
    4. 计算绩效指标
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from config.settings import BacktestConfig
from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class BacktestResult:
    """回测结果容器"""
    portfolio_value: pd.Series      # 组合净值序列
    daily_returns: pd.Series        # 日收益率
    trades: pd.DataFrame            # 交易记录
    metrics: dict                   # 绩效指标

    def summary(self) -> pd.DataFrame:
        """以DataFrame形式输出绩效摘要"""
        return pd.DataFrame(
            list(self.metrics.items()), columns=["指标", "值"]
        ).set_index("指标")


class Backtester:
    """
    向量化回测引擎

    Usage:
        bt = Backtester()
        result = bt.run(price_df, signals_df)
        print(result.summary())
    """

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()

    def run(self, prices: pd.DataFrame, signals: pd.DataFrame) -> BacktestResult:
        """
        执行回测

        Args:
            prices: 收盘价面板，索引=日期，列=标的
            signals: 仓位信号，索引=日期，列=标的，值=目标权重[-1,1]

        Returns:
            BacktestResult 对象
        """
        # 对齐索引和列
        common_cols = prices.columns.intersection(signals.columns)
        common_idx = prices.index.intersection(signals.index)
        prices = prices.loc[common_idx, common_cols].copy()
        signals = signals.loc[common_idx, common_cols].copy()

        if prices.empty:
            logger.error("回测数据为空")
            return self._empty_result()

        if not np.isfinite(prices.to_numpy(dtype=float)).all() or (prices <= 0).any().any():
            raise ValueError('Prices must be finite and positive')

        logger.info(
            f"回测开始: {prices.index[0].date()} ~ {prices.index[-1].date()} "
            f"| {len(common_cols)} 标的 | {len(prices)} 交易日"
        )

        # 1. 计算标的日收益率
        asset_returns = prices.pct_change(fill_method=None).fillna(0.0)

        # 2. 仓位信号（T日信号 -> T+1日持仓，避免前视偏差）
        positions = signals.shift(1).fillna(0.0)

        # 3. 计算交易成本
        turnover = (positions - positions.shift(1).fillna(0.0)).abs()
        cost_rate = self.config.commission_rate + self.config.slippage
        # 卖出加收印花税（仅A股）
        sell_turnover = (positions - positions.shift(1).fillna(0.0)).clip(upper=0).abs()
        daily_cost = (turnover * cost_rate + sell_turnover * self.config.stamp_duty).sum(axis=1)

        # 4. 组合日收益 = 仓位加权收益 - 交易成本
        portfolio_returns = (positions * asset_returns).sum(axis=1) - daily_cost

        # 5. 组合净值
        portfolio_value = (1 + portfolio_returns).cumprod() * self.config.initial_capital

        # 6. 交易记录
        trades = self._extract_trades(positions, prices)

        # 7. 绩效指标
        metrics = self._calc_metrics(portfolio_returns, portfolio_value)

        logger.info(
            f"回测完成 | 年化收益 {metrics['年化收益率']:.2%} "
            f"| 夏普 {metrics['夏普比率']:.2f} "
            f"| 最大回撤 {metrics['最大回撤']:.2%}"
        )

        return BacktestResult(
            portfolio_value=portfolio_value,
            daily_returns=portfolio_returns,
            trades=trades,
            metrics=metrics,
        )

    def _extract_trades(self, positions: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
        """提取交易记录"""
        turnover = positions.diff().fillna(positions)
        trade_records = []
        for date in turnover.index:
            for col in turnover.columns:
                delta = turnover.loc[date, col]
                if abs(delta) > 1e-6:
                    trade_records.append({
                        "date": date,
                        "symbol": col,
                        "weight_change": delta,
                        "price": prices.loc[date, col],
                        "action": "BUY" if delta > 0 else "SELL",
                    })
        if not trade_records:
            return pd.DataFrame(columns=["date", "symbol", "weight_change", "price", "action"])
        return pd.DataFrame(trade_records).set_index("date")

    def _calc_metrics(self, returns: pd.Series, portfolio_value: pd.Series) -> dict:
        """计算绩效指标"""
        total_days = len(returns)
        if total_days == 0:
            return {}

        ann_factor = 252  # 年化因子

        # 总收益率
        total_return = portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1

        # 年化收益率
        years = total_days / ann_factor
        ann_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # 年化波动率
        ann_vol = returns.std() * np.sqrt(ann_factor) if total_days > 1 else 0.0

        # 夏普比率
        sharpe = (ann_return - self.config.risk_free_rate) / ann_vol if ann_vol > 0 else 0

        # 最大回撤
        peak = portfolio_value.expanding().max()
        drawdown = (portfolio_value - peak) / peak
        max_dd = drawdown.min()

        # Calmar比率
        calmar = ann_return / abs(max_dd) if max_dd != 0 else 0

        # 胜率
        win_rate = (returns > 0).sum() / (returns != 0).sum() if (returns != 0).sum() > 0 else 0

        # 盈亏比
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        profit_loss_ratio = (wins.mean() / abs(losses.mean())) if len(losses) > 0 and losses.mean() != 0 else 0

        return {
            "总收益率": round(total_return, 4),
            "年化收益率": round(ann_return, 4),
            "年化波动率": round(ann_vol, 4),
            "夏普比率": round(sharpe, 2),
            "最大回撤": round(max_dd, 4),
            "Calmar比率": round(calmar, 2),
            "胜率": round(win_rate, 4),
            "盈亏比": round(profit_loss_ratio, 2),
            "交易天数": total_days,
        }

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            portfolio_value=pd.Series(dtype=float),
            daily_returns=pd.Series(dtype=float),
            trades=pd.DataFrame(),
            metrics={},
        )
