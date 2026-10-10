"""
技术指标库
纯函数实现，输入DataFrame(Series)，输出Series
所有指标只依赖pandas/numpy，无需TA-Lib
"""
import pandas as pd
import numpy as np


# ============ 均线类 ============

def SMA(series: pd.Series, window: int) -> pd.Series:
    """简单移动平均"""
    return series.rolling(window=window, min_periods=1).mean()


def EMA(series: pd.Series, span: int) -> pd.Series:
    """指数移动平均"""
    return series.ewm(span=span, adjust=False).mean()


# ============ 动量类 ============

def RSI(series: pd.Series, window: int = 14) -> pd.Series:
    """相对强弱指标"""
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def MACD(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    MACD指标
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = EMA(series, fast)
    ema_slow = EMA(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = EMA(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def momentum(series: pd.Series, window: int = 20) -> pd.Series:
    """动量（N日前价格变化率）"""
    return series.pct_change(periods=window)


# ============ 波动率类 ============

def Bollinger_Bands(series: pd.Series, window: int = 20, num_std: float = 2.0):
    """
    布林带
    Returns: (upper, middle, lower)
    """
    middle = SMA(series, window)
    std = series.rolling(window=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def ATR(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """平均真实波幅"""
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=window).mean()


def rolling_volatility(returns: pd.Series, window: int = 20) -> pd.Series:
    """滚动年化波动率"""
    return returns.rolling(window=window).std() * np.sqrt(252)
