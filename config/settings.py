"""
全局配置中心
所有可调参数集中管理，避免硬编码散落各处

配置优先级（从高到低）：
    环境变量 > .env 文件 > dataclass 默认值

前期测试无需任何配置即可使用内置模拟数据；
接入外部 API 时，复制 .env.example 为 .env 并填入密钥即可。
"""
import os
from pathlib import Path
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env") if (PROJECT_ROOT := Path(__file__).resolve().parent.parent).exists() else None
except ImportError:
    # python-dotenv 未安装时降级：仅读取系统环境变量
    pass


# ============ 路径配置 ============
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"       # 数据缓存目录
LOG_DIR = PROJECT_ROOT / "logs"              # 日志目录
RESULT_DIR = PROJECT_ROOT / "results"        # 回测结果目录

for d in [DATA_DIR, LOG_DIR, RESULT_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _env(key: str, default: str = "") -> str:
    """从环境变量读取配置，统一入口"""
    return os.getenv(key, default)


# ============ 数据源配置 ============
@dataclass
class DataSourceConfig:
    """
    数据源配置
    - 前期测试：无需任何 token，DataLoader 在数据源不可用时自动回退到模拟数据
    - 接入真实数据：在 .env 中填入对应 token，DataLoader 自动启用
    """
    # A股数据源：akshare / tushare / baostock（优先级链，逗号分隔）
    cn_source: str = field(default_factory=lambda: _env("DATA_CN_FALLBACK", "akshare,tushare").split(",")[0])
    # 美股数据源：yfinance / alpha_vantage / polygon
    us_source: str = field(default_factory=lambda: _env("DATA_US_FALLBACK", "yfinance,polygon").split(",")[0])
    # Tushare token（https://tushare.pro 注册获取）
    tushare_token: str = field(default_factory=lambda: _env("TUSHARE_TOKEN", ""))
    # Alpha Vantage / Polygon key
    alpha_vantage_key: str = field(default_factory=lambda: _env("ALPHA_VANTAGE_KEY", ""))
    polygon_api_key: str = field(default_factory=lambda: _env("POLYGON_API_KEY", ""))
    # 请求间隔（秒），避免触发限流
    request_delay: float = field(default_factory=lambda: float(_env("DATA_REQUEST_DELAY", "0.5")))


# ============ 回测配置 ============
@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0     # 初始资金
    commission_rate: float = 0.0003          # 佣金费率（万三）
    slippage: float = 0.001                  # 滑点（千一）
    stamp_duty: float = 0.001                # 印花税（千一，卖出时收取）
    risk_free_rate: float = field(default_factory=lambda: float(_env("RISK_FREE_RATE", "0.025")))
    benchmark: str = "000300"                # 基准指数（沪深300）


# ============ 风控配置 ============
@dataclass
class RiskConfig:
    max_position_pct: float = 0.25           # 单标的最大仓位占比
    max_total_exposure: float = 1.0          # 最大总仓位
    stop_loss_pct: float = 0.08              # 单标的止损线（8%）
    max_drawdown_pct: float = 0.20           # 组合最大回撤熔断线（20%）
    max_positions: int = 10                  # 最大持仓标的数


# ============ 实盘券商配置 ============
@dataclass
class BrokerConfig:
    """实盘券商连接配置，详见 docs/BROKER_INTEGRATION.md"""
    # IB Gateway
    ib_host: str = field(default_factory=lambda: _env("IB_HOST", "127.0.0.1"))
    ib_port: int = field(default_factory=lambda: int(_env("IB_PORT", "7497")))  # 7497=模拟 7496=实盘
    ib_client_id: int = field(default_factory=lambda: int(_env("IB_CLIENT_ID", "1")))
    # QMT
    qmt_path: str = field(default_factory=lambda: _env("QMT_PATH", ""))
    qmt_account_id: str = field(default_factory=lambda: _env("QMT_ACCOUNT_ID", ""))
    # CCXT 加密货币
    ccxt_exchange: str = field(default_factory=lambda: _env("CCXT_EXCHANGE", "binance"))
    ccxt_api_key: str = field(default_factory=lambda: _env("CCXT_API_KEY", ""))
    ccxt_api_secret: str = field(default_factory=lambda: _env("CCXT_API_SECRET", ""))


# ============ 全局实例 ============
DATA_CONFIG = DataSourceConfig()
BACKTEST_CONFIG = BacktestConfig()
RISK_CONFIG = RiskConfig()
BROKER_CONFIG = BrokerConfig()
