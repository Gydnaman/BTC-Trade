"""
布林带均值回归策略
价格跌破下轨买入，回到中轨平仓；突破上轨卖出
适合震荡市
"""
import pandas as pd
from strategy.base import BaseStrategy
from indicators.indicators import Bollinger_Bands


class BollingerStrategy(BaseStrategy):
    """
    布林带均值回归策略

    参数:
        window: 布林带计算窗口 (默认20日)
        num_std: 标准差倍数 (默认2.0)
    """

    def __init__(self, window: int = 20, num_std: float = 2.0):
        super().__init__(
            name="Bollinger",
            window=window,
            num_std=num_std,
        )
        self.window = window
        self.num_std = num_std

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        upper, middle, lower = Bollinger_Bands(close, self.window, self.num_std)

        weight = pd.Series(0.0, index=close.index)

        # 买入信号：收盘价跌破下轨
        buy = close < lower
        # 卖出信号：收盘价回到中轨上方
        sell = close > middle

        # 状态机：买入后持有，直到卖出信号
        position = 0.0
        for i in range(len(close)):
            if buy.iloc[i]:
                position = 1.0
            elif sell.iloc[i]:
                position = 0.0
            weight.iloc[i] = position

        return weight.to_frame(name="weight")
