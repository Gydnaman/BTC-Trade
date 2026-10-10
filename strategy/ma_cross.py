"""
双均线交叉策略
经典趋势跟踪策略：短期均线上穿长期均线买入，下穿卖出
"""
import pandas as pd
from strategy.base import BaseStrategy
from indicators.indicators import SMA


class MACrossStrategy(BaseStrategy):
    """
    双均线交叉策略

    参数:
        short_window: 短期均线周期 (默认5日)
        long_window: 长期均线周期 (默认20日)
    """

    def __init__(self, short_window: int = 5, long_window: int = 20):
        super().__init__(
            name="MA_Cross",
            short_window=short_window,
            long_window=long_window,
        )
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成信号：短均线上穿长均线 -> +1，下穿 -> 0

        Args:
            df: 单标的日频数据，需包含 close 列

        Returns:
            单列DataFrame，列名为 'weight'，值为目标仓位
        """
        close = df["close"]
        ma_short = SMA(close, self.short_window)
        ma_long = SMA(close, self.long_window)

        # 金叉/死叉
        golden_cross = (ma_short > ma_long) & (ma_short.shift(1) <= ma_long.shift(1))
        death_cross = (ma_short < ma_long) & (ma_short.shift(1) >= ma_long.shift(1))

        # 生成仓位：持有状态延续直到反向信号
        weight = pd.Series(float('nan'), index=close.index)
        weight[golden_cross] = 1.0
        # 死叉清仓（已为0，但显式标注）
        weight[death_cross] = 0.0

        # 前向填充：金叉后持续持有直到死叉
        weight = weight.ffill().fillna(0.0)

        return weight.to_frame(name="weight")
