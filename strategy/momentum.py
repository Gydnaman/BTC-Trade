"""
动量策略
买入过去N日涨幅最高的标的，定期调仓
适合多标的截面选股
"""
import pandas as pd
import numpy as np
from strategy.base import BaseStrategy
from indicators.indicators import momentum


class MomentumStrategy(BaseStrategy):
    """
    截面动量策略

    参数:
        lookback: 动量计算回看周期 (默认20日)
        hold_period: 调仓间隔 (默认5日)
        top_n: 选股数量 (默认5)
    """

    def __init__(self, lookback: int = 20, hold_period: int = 5, top_n: int = 5):
        super().__init__(
            name="Momentum",
            lookback=lookback,
            hold_period=hold_period,
            top_n=top_n,
        )
        self.lookback = lookback
        self.hold_period = hold_period
        self.top_n = top_n

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成多标的动量信号

        Args:
            df: 多标的收盘价面板，索引=日期，列=标的代码

        Returns:
            仓位权重DataFrame，索引=日期，列=标的，值为等权目标仓位
        """
        # 计算每个标的的N日动量
        mom = df.pct_change(periods=self.lookback, fill_method=None)

        # 每隔 hold_period 调仓
        rebalance_dates = mom.index[::self.hold_period]

        signals = pd.DataFrame(np.nan, index=df.index, columns=df.columns)

        for date in rebalance_dates:
            signals.loc[date] = 0.0
            if date not in mom.index:
                continue
            row = mom.loc[date].dropna()
            if len(row) < self.top_n:
                continue
            # 选出动量最高的top_n只，等权配置
            top_stocks = row.nlargest(self.top_n).index
            signals.loc[date, top_stocks] = 1.0 / self.top_n

        # 前向填充：调仓日之间保持持仓不变
        signals = signals.ffill().fillna(0.0)

        return signals
