"""
策略基类
所有策略继承此类，实现 generate_signals 方法
统一接口，方便回测引擎调用
"""
from abc import ABC, abstractmethod
import pandas as pd
from dataclasses import dataclass


@dataclass
class StrategyResult:
    """策略输出结果"""
    signals: pd.DataFrame   # 信号DataFrame，索引为日期，列为标的，值为仓位权重[-1, 1]
    params: dict            # 策略参数记录


class BaseStrategy(ABC):
    """
    策略抽象基类

    子类必须实现 generate_signals(df: pd.DataFrame) -> pd.DataFrame
    返回的DataFrame中，每个元素为目标仓位权重：
        1.0  = 满仓做多
        0.0  = 空仓
       -1.0  = 满仓做空
    """

    def __init__(self, name: str = "BaseStrategy", **params):
        self.name = name
        self.params = params

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            df: 行情数据，多标的时为Panel(索引=日期, 列=MultiIndex(asset, field))
               单标的时为普通DataFrame(列含open/high/low/close/volume)

        Returns:
            仓位权重DataFrame，索引为日期，每列为一个标的的目标权重
        """
        ...

    def __repr__(self):
        return f"<{self.name} params={self.params}>"
