"""
数据存储模块
统一管理本地数据缓存，使用Parquet列式存储（比CSV快10倍）
"""
import pandas as pd
from pathlib import Path
from config.settings import DATA_DIR
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DataStore:
    """本地数据存储管理器"""

    def __init__(self, base_dir: Path = DATA_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, symbol: str, freq: str = "daily") -> Path:
        """根据标的和频率生成存储路径"""
        return self.base_dir / f"{symbol}_{freq}.parquet"

    def save(self, df: pd.DataFrame, symbol: str, freq: str = "daily") -> None:
        """
        保存DataFrame到Parquet

        Args:
            df: 待保存数据，要求索引为DatetimeIndex
            symbol: 标的代码
            freq: 数据频率 daily/minute
        """
        path = self._get_path(symbol, freq)
        df.to_parquet(path, engine="pyarrow")
        logger.info(f"数据已保存: {symbol} ({freq}) -> {path.name} [{len(df)} rows]")

    def load(self, symbol: str, freq: str = "daily") -> pd.DataFrame | None:
        """
        从本地加载Parquet数据

        Returns:
            DataFrame 或 None（文件不存在时）
        """
        path = self._get_path(symbol, freq)
        if not path.exists():
            logger.warning(f"本地无缓存: {symbol} ({freq})")
            return None
        df = pd.read_parquet(path)
        logger.info(f"数据已加载: {symbol} ({freq}) <- {path.name} [{len(df)} rows]")
        return df

    def exists(self, symbol: str, freq: str = "daily") -> bool:
        """检查本地是否有缓存"""
        return self._get_path(symbol, freq).exists()

    def delete(self, symbol: str, freq: str = "daily") -> None:
        """删除本地缓存"""
        path = self._get_path(symbol, freq)
        if path.exists():
            path.unlink()
            logger.info(f"已删除缓存: {symbol} ({freq})")
