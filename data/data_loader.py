"""
数据获取模块
支持多数据源：AKShare(A股) / yfinance(美股) / Tushare(A股)
自动缓存到本地，避免重复请求
"""
import time
import pandas as pd
from config.settings import DATA_CONFIG
from data.data_store import DataStore
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DataLoader:
    """
    统一数据获取接口
    优先读本地缓存，无缓存则从API拉取并存储

    Usage:
        loader = DataLoader()
        df = loader.get_daily("000001.SZ", start="2020-01-01")
        df = loader.get_daily("AAPL", start="2020-01-01", market="us")
    """

    def __init__(self):
        self.store = DataStore()
        self._delay()

    def _delay(self):
        """请求间隔，防止触发API限流"""
        time.sleep(DATA_CONFIG.request_delay)

    def get_daily(
        self,
        symbol: str,
        start: str = "2020-01-01",
        end: str | None = None,
        market: str = "cn",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        获取日频行情数据（OHLCV）

        Args:
            symbol: 标的代码。A股如"000001.SZ"，美股如"AAPL"
            start: 起始日期 YYYY-MM-DD
            end: 结束日期，默认今天
            market: "cn" 或 "us"
            use_cache: 是否优先使用本地缓存

        Returns:
            标准化的DataFrame，列: open/high/low/close/volume，索引为DatetimeIndex
        """
        if use_cache and self.store.exists(symbol):
            return self.store.load(symbol)

        if end is None:
            end = pd.Timestamp.now().strftime("%Y-%m-%d")

        logger.info(f"从API获取: {symbol} [{start} ~ {end}] market={market}")

        if market == "cn":
            df = self._fetch_cn(symbol, start, end)
        elif market == "us":
            df = self._fetch_us(symbol, start, end)
        else:
            raise ValueError(f"不支持的市场: {market}")

        if df is not None and len(df) > 0:
            df = self._standardize(df)
            self.store.save(df, symbol)
            return df

        logger.error(f"获取数据失败: {symbol}")
        return pd.DataFrame()

    def _fetch_cn(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """从AKShare获取A股日K数据"""
        try:
            import akshare as ak
            # AKShare股票代码格式: "000001" (不带后缀)
            code = symbol.split(".")[0]
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust="qfq",  # 前复权
            )
            return df
        except ImportError:
            logger.error("未安装akshare，请运行: pip install akshare")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"AKShare获取失败: {e}")
            return pd.DataFrame()

    def _fetch_us(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """从yfinance获取美股日K数据"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, auto_adjust=True)
            return df
        except ImportError:
            logger.error("未安装yfinance，请运行: pip install yfinance")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"yfinance获取失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def _standardize(df: pd.DataFrame) -> pd.DataFrame:
        """
        将不同数据源的列名统一为标准格式
        标准列: open, high, low, close, volume
        """
        col_map = {
            # AKShare中文列名
            "开盘": "open", "最高": "high", "最低": "low",
            "收盘": "close", "成交量": "volume",
            "日期": "date",
            # yfinance列名（已是英文小写，无需映射）
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        }
        df = df.rename(columns=col_map)

        # 确保索引为DatetimeIndex
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        df.index = pd.to_datetime(df.index)
        df.index.name = "date"

        # 只保留标准列
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep].sort_index()
        df = df[~df.index.duplicated(keep="first")]  # 去重
        return df.dropna()
