# 量化交易系统 (Quant Trading Framework)

> 新增开发入口：`python -B -m harness.validate`。
> Skills、受约束实验命令和当前实现边界见 [本地 Harness 指南](docs/HARNESS.md)。
> 下文原始路线图中的“风控下单前强制检查”等描述尚未全部实现，以该指南为准。

> 面向 CFA/FRM 持证人的量化交易系统骨架，覆盖**研究 → 回测 → 风控 → 实盘**完整工作流。
>
> **设计哲学**：开箱即用的模拟数据测试，可插拔的外部 API 接入。前期无需任何配置即可验证策略逻辑；接入真实数据与实盘交易时，只需编辑 `.env` 并继承基类实现接口。

---

## 目录
- [快速开始](#快速开始)
- [核心设计：模拟数据优先，API 可插拔](#核心设计模拟数据优先api-可插拔)
- [三阶段工作流](#三阶段工作流)
- [项目结构](#项目结构)
- [配置系统](#配置系统)
- [接入外部数据源](#接入外部数据源)
- [接入实盘券商](#接入实盘券商)
- [添加自定义策略](#添加自定义策略)
- [绩效指标](#绩效指标)
- [技术栈](#技术栈)
- [开发路线图](#开发路线图)
- [注意事项与风险声明](#注意事项与风险声明)

---

## 快速开始

```bash
# 1. 安装依赖（核心库，不含可选数据源/券商SDK）
pip install -r requirements.txt

# 2. 直接运行（内置模拟数据，无需任何API配置）
python main.py
```

运行后将依次演示：单标的双均线策略、多标的动量轮动、布林带均值回归、模拟Broker下单。结果图表自动保存到 `results/`。

## 加密资产研究原型

加密研究使用独立 Python 3.12 环境和配置，不接入旧 `main.py` 的模拟数据回退，也不读取交易账户凭证。

```powershell
# 在项目目录中执行
.venv\Scripts\python.exe -m crypto.cli --config crypto/config.example.json --collect
```

此命令只读取 Binance 公共行情接口，将 BTC/USDT 现货、线性永续、永续标记价格小时 K 线与离散资金费率保存到配置目录。随后生成带 SHA-256 的 `manifest.json`。未说明的数据缺口会导致审计失败；唯一允许豁免的是配置逐字段匹配官方公告的 Binance 现货停机小时，且不补造价格柱。现货与双腿账本都会在该固定时段拒绝现货成交。早期资金费空结算价用带来源标记的同小时 mark 开盘代理，manifest 记录代理数量。合成行情不会用于正式研究。交易手续费配置只是可见的研究假设，交易所规则元数据是抓取当天的快照。

`crypto.spot.run_spot` 提供独立现货现金账本，`crypto.ledger.replay_events` 提供 Decimal 双腿事件账本；详见[数据边界](docs/crypto/DATA.md)、[双腿账本](docs/crypto/LEDGER.md)和[现货对照状态](docs/crypto/SPOT_COMPARISON.md)。

依赖清单：`requirements-crypto.in` 是安装约束，`requirements-crypto.lock` 是本机 Python 3.12 完整解析结果。输出 Parquet 与来源记录保存在 `data_cache/crypto/`。

---

## 核心设计：模拟数据优先，API 可插拔

```
┌─────────────────────────────────────────────────────────────┐
│                    DataLoader.get_daily()                    │
│                      (统一数据接口)                            │
├──────────────┬────────────────┬──────────────────────────────┤
│  本地缓存命中? │  是 → 返回缓存  │                              │
│      ↓ 否     │                │  否 → 回退模拟数据(GBM)        │
│  .env已配置?  │── 是 → 调用API ─┤  (保证测试环境零依赖)          │
└──────────────┴────────────────┴──────────────────────────────┘
```

| 阶段 | 数据来源 | 配置要求 | 目的 |
|------|---------|---------|------|
| **开发调试** | 内置模拟数据（几何布朗运动） | 无 | 验证策略/回测/报告逻辑 |
| **历史回测** | 真实行情 API | `.env` 填 token | 真实数据回测、参数寻优 |
| **实盘监控** | 实时行情 + 券商 API | `.env` + 券商SDK | 实盘信号生成与执行 |

---

## 三阶段工作流

```
研究阶段                    验证阶段                    实盘阶段
─────────                  ─────────                  ─────────
模拟数据测试  ──→  接入真实数据回测  ──→  模拟盘验证  ──→  实盘交易
  (阶段一)           (阶段二)            (阶段二.5)        (阶段三)
   零配置            编辑 .env          SimulatedBroker   BaseBroker子类
```

### 阶段一：开发调试（当前默认）
无需任何配置。`main.py` 的 `generate_sample_data()` 生成 GBM 模拟行情，验证策略信号生成、回测引擎、绩效报告全链路。

### 阶段二：历史回测
```bash
cp .env.example .env          # 复制配置模板
# 编辑 .env，填入数据源 token（详见下方"接入外部数据源"）
pip install akshare           # 或 tushare / yfinance
python main.py                # 自动启用真实数据
```

### 阶段三：实盘交易
```bash
# 编辑 .env，填入券商 API 配置（详见 docs/BROKER_INTEGRATION.md）
# 实现 BaseBroker 子类对接券商
```

---

## 项目结构

```
quant_trading/
├── main.py                  # 主入口，运行演示工作流
├── requirements.txt         # Python依赖（核心+可选分组）
├── .env.example             # API密钥与连接配置模板
│
├── config/                  # 配置层
│   └── settings.py          # 全局参数（环境变量注入，杜绝硬编码）
│
├── data/                    # 数据层
│   ├── data_loader.py       # 多源数据获取（统一接口，API可插拔）
│   └── data_store.py        # 本地缓存（Parquet列式存储）
│
├── indicators/                  # 信号层
│   └── indicators.py        # 技术指标库（SMA/EMA/RSI/MACD/布林带/ATR）
│
├── strategy/                # 策略层
│   ├── base.py              # 策略抽象基类（统一仓位信号接口）
│   ├── ma_cross.py          # 双均线交叉策略
│   ├── momentum.py          # 多标的动量轮动策略
│   └── bollinger.py         # 布林带均值回归策略
│
├── backtest/                # 回测层
│   └── backtester.py        # 向量化回测引擎（含交易成本模拟，防前视偏差）
│
├── risk/                    # 风控层
│   └── risk_manager.py      # 仓位限制/止损/回撤熔断/Kelly公式
│
├── execution/               # 执行层
│   └── broker.py            # BaseBroker抽象 + SimulatedBroker实现
│
├── report/                  # 报告层
│   └── plotting.py          # 净值曲线/回撤图/绩效表
│
├── docs/                    # 专业文档
│   ├── DATA_SOURCES.md      # 数据源接入详细指南
│   └── BROKER_INTEGRATION.md# 实盘券商对接详细指南
│
├── utils/                   # 工具层
│   └── logger.py            # 统一日志（文件+控制台）
│
├── data_cache/              # 数据缓存（自动生成）
├── logs/                    # 日志文件（自动生成）
└── results/                 # 回测结果图表（自动生成）
```

### 架构数据流
```
数据获取 → 信号生成 → 回测验证 → 风控检查 → 实盘执行
   ↑                                              ↓
   └──────────── 监控迭代 ←───────────────────────┘
```

### 各层职责

| 层 | 职责 | 关键类 | 接口约定 |
|----|------|--------|---------|
| **config** | 集中管理参数，环境变量注入 | `BacktestConfig`, `RiskConfig`, `BrokerConfig` | `.env` > 默认值 |
| **data** | 多源获取+本地缓存，统一列名 | `DataLoader`, `DataStore` | `get_daily()` 返回标准OHLCV |
| **signal** | 纯函数技术指标，可复用 | `SMA()`, `RSI()`, `MACD()` | Series进Series出 |
| **strategy** | 策略逻辑，统一仓位信号 | `BaseStrategy`, `MACrossStrategy` | `generate_signals()` 返回权重[-1,1] |
| **backtest** | 向量化回测，含佣金/滑点/印花税 | `Backtester`, `BacktestResult` | T日信号→T+1持仓（防前视偏差） |
| **risk** | 仓位管理/止损/回撤熔断 | `RiskManager` | 下单前强制检查 |
| **execution** | 模拟撮合，实盘对接券商API | `SimulatedBroker`, `BaseBroker` | 4方法接口契约 |
| **report** | 净值曲线/回撤图/绩效指标 | `plot_equity_curve()` | 图表存 `results/` |

---

## 配置系统

所有参数通过 `config/settings.py` 集中管理，遵循**配置优先级**：

```
环境变量 > .env 文件 > dataclass 默认值
```

### 配置分组

| 配置类 | 管理内容 | 关键参数 |
|--------|---------|---------|
| `DataSourceConfig` | 数据源选择与token | `cn_source`, `tushare_token`, `request_delay` |
| `BacktestConfig` | 回测参数 | `initial_capital`, `commission_rate`, `slippage`, `stamp_duty` |
| `RiskConfig` | 风控阈值 | `max_position_pct`, `stop_loss_pct`, `max_drawdown_pct` |
| `BrokerConfig` | 实盘券商连接 | `ib_port`, `qmt_path`, `ccxt_exchange` |

### 前期测试（零配置）

无需 `.env` 文件。系统检测到数据源不可用时，自动回退到模拟数据：

```python
# main.py 中的容错逻辑
try:
    data = loader.get_daily(symbol, market="cn")
    if data.empty:
        raise Exception("数据为空")
except Exception:
    data = generate_sample_data()["STOCK_A"]  # 回退模拟数据
```

### 接入真实数据（编辑 .env）

```bash
cp .env.example .env
```

`.env` 完整字段说明见文件内注释，涵盖：
- **数据源**：Tushare / Alpha Vantage / Polygon / Wind / Binance
- **实盘券商**：QMT / IBKR / CCXT
- **运行环境**：数据源优先级、限流、无风险利率、日志级别

---

## 接入外部数据源

> 完整指南见 [docs/DATA_SOURCES.md](./docs/DATA_SOURCES.md)

### 数据源对比

| 数据源 | 市场 | 费用 | 是否需token | 推荐场景 |
|--------|------|------|------------|---------|
| **AKShare** | A股 | 免费 | 否 | 原型开发、日线回测 |
| **Tushare** | A股 | 免费+积分 | 是 | 因子研究、财务数据 |
| **Baostock** | A股 | 免费 | 否 | 长历史回测（1990起） |
| **yfinance** | 美股 | 免费 | 否 | 美股/ETF日线 |
| **Polygon.io** | 美股/期权 | 付费(免费限频) | 是 | 期权链、分钟级 |
| **Wind/Choice** | 全市场 | 付费(机构) | 客户端授权 | 机构实盘 |
| **CCXT** | 加密 | 免费 | 否(行情)/是(交易) | 加密货币 |

### 快速接入示例（AKShare，A股）

```bash
pip install akshare
# 无需 .env 配置，DataLoader 默认调用
```

```python
from data.data_loader import DataLoader
df = DataLoader().get_daily("000001.SZ", start="2024-01-01", market="cn")
```

### 快速接入示例（Tushare，A股）

```bash
pip install tushare
```

```env
# .env
TUSHARE_TOKEN=你的token
DATA_CN_FALLBACK=tushare,akshare
```

### 数据契约

所有数据源经 `DataLoader._standardize()` 统一为：
```
索引:  DatetimeIndex | 列: open,high,low,close,volume | 类型: float64 | 升序去重
```

---

## 接入实盘券商

> 完整指南见 [docs/BROKER_INTEGRATION.md](./docs/BROKER_INTEGRATION.md)

### 实盘前置条件
```
[ ] 策略已通过至少 1 年样本外回测
[ ] 模拟盘（SimulatedBroker）至少 1 个月验证
[ ] 实盘账户已开通程序化交易权限
[ ] API密钥已配置最小权限（交易+查询，禁止出金）
[ ] 已设置风控熔断 + 应急平仓方案
```

### Broker 接口契约

继承 `BaseBroker`，实现 4 个方法即可接入任意券商：

```python
from execution.broker import BaseBroker, Order

class MyBroker(BaseBroker):
    def place_order(self, order: Order) -> str: ...      # 下单 → 订单ID
    def cancel_order(self, order_id: str) -> bool: ...   # 撤单
    def get_position(self, symbol: str) -> Position: ...  # 查持仓
    def get_account_value(self) -> float: ...            # 查账户净值
```

### 支持的券商

| 券商 | 市场 | 配置项 | 文档章节 |
|------|------|--------|---------|
| **QMT** | A股 | `QMT_PATH`, `QMT_ACCOUNT_ID` | [BROKER_INTEGRATION §4](./docs/BROKER_INTEGRATION.md#4-a股实盘qmt) |
| **IBKR** | 全球 | `IB_HOST`, `IB_PORT`(7497模拟/7496实盘) | [BROKER_INTEGRATION §5](./docs/BROKER_INTEGRATION.md#5-全球实盘盈透证券-ibkr) |
| **CCXT** | 加密 | `CCXT_EXCHANGE`, `CCXT_API_KEY` | [BROKER_INTEGRATION §6](./docs/BROKER_INTEGRATION.md#6-加密货币ccxt) |

> ⚠️ IBKR 强烈建议先用 `IB_PORT=7497` 连接 paper trading，至少运行 2 周后再切实盘。

---

## 添加自定义策略

继承 `BaseStrategy`，实现 `generate_signals()` 返回目标仓位权重：

```python
from strategy.base import BaseStrategy
from indicators.indicators import RSI

class MyRSIStrategy(BaseStrategy):
    def __init__(self, period=14, oversold=30, overbought=70):
        super().__init__(name="RSI", period=period,
                         oversold=oversold, overbought=overbought)

    def generate_signals(self, df) -> pd.DataFrame:
        close = df["close"]
        rsi = RSI(close, self.params["period"])

        weight = pd.Series(0.0, index=close.index)
        weight[rsi < self.params["oversold"]] = 1.0    # 超卖买入
        weight[rsi > self.params["overbought"]] = 0.0  # 超买卖出
        weight = weight.replace(0.0, pd.NA).ffill().fillna(0.0)

        return weight.to_frame(name="weight")
```

**仓位权重约定**：`1.0`=满仓做多，`0.0`=空仓，`-1.0`=满仓做空

---

## 绩效指标

| 指标 | 含义 | 参考标准 |
|------|------|---------|
| 年化收益率 | 年化后的复合收益 | >15% 优秀 |
| 夏普比率 | 单位风险超额收益 | >1.0 合格, >2.0 优秀 |
| 最大回撤 | 峰值到谷底最大跌幅 | <20% 为佳 |
| Calmar比率 | 年化收益/最大回撤 | >1.0 良好 |
| 胜率 | 盈利交易日占比 | 因策略而异 |
| 盈亏比 | 平均盈利/平均亏损 | >1.5 为佳 |

> 回测引擎默认 **T日信号 → T+1日持仓**，避免前视偏差。交易成本含佣金（万三）、滑点（千一）、印花税（千一，卖出单边）。

---

## 技术栈

- **语言**: Python 3.10+
- **核心库**: pandas, numpy, scipy, matplotlib
- **存储**: Parquet (pyarrow)
- **数据源**: AKShare(A股), yfinance(美股), Tushare(A股), Polygon(美股/期权), Wind/Choice(机构)
- **回测**: 内置向量化引擎（可替换为 VectorBT/Backtrader）
- **实盘**: QMT(A股), IB(全球), CCXT(加密货币)

---

## 开发路线图

- [x] 项目骨架 + 3个示例策略
- [x] 向量化回测引擎 + 交易成本模拟
- [x] 模拟Broker + 风控模块
- [x] **配置系统环境变量注入 + API可插拔文档**
- [ ] 参数优化模块（网格搜索/Walk-forward）
- [ ] 实盘Broker对接（QMT/IB）完整实现
- [ ] 实时监控Dashboard（Streamlit）
- [ ] 机器学习因子挖掘（LightGBM）
- [ ] 期权波动率套利策略（利用BSM/IV分析能力）

---

## 注意事项与风险声明

### 工程规范
1. **回测≠实盘**：回测结果好不代表实盘能赚钱，务必先模拟盘验证
2. **防范过拟合**：使用样本外测试、Walk-forward分析
3. **密钥安全**：API Key 放 `.env`（已 gitignore），生产环境用密钥管理服务
4. **数据质量**：免费数据有缺失/复权错误，回测前务必校验（清单见 [DATA_SOURCES.md §10](./docs/DATA_SOURCES.md)）

### 风险声明
> 程序化交易可能因网络延迟、API 限流、行情异常、策略缺陷等因素造成超出预期的损失。实盘前请充分评估，仅使用可承受亏损的资金。本系统不构成任何投资建议。
