# 数据源接入指南 (Data Sources)

> 本系统采用**数据源解耦**设计：`DataLoader` 统一对外暴露 `get_daily()` 接口，内部通过 `_fetch_cn / _fetch_us` 分发到具体数据源。前期测试无需任何 API，系统自动回退到内置几何布朗运动模拟数据；接入真实数据时，只需在 `.env` 中填入对应 token。

## 目录
- [1. 三阶段数据策略](#1-三阶段数据策略)
- [2. 数据源对比](#2-数据源对比)
- [3. 标准化数据契约](#3-标准化数据契约)
- [4. 接入步骤（通用）](#4-接入步骤通用)
- [5. A股数据源](#5-a股数据源)
- [6. 美股数据源](#6-美股数据源)
- [7. 专业终端数据源](#7-专业终端数据源)
- [8. 加密货币数据源](#8-加密货币数据源)
- [9. 自定义数据源接入](#9-自定义数据源接入)
- [10. 数据质量校验清单](#10-数据质量校验清单)

---

## 1. 三阶段数据策略

| 阶段 | 数据来源 | 目的 | 是否需要配置 |
|------|---------|------|-------------|
| **阶段一：开发调试** | 内置模拟数据（GBM 几何布朗运动） | 验证策略逻辑、回测引擎、报告生成 | 否，开箱即用 |
| **阶段二：历史回测** | 真实历史行情 API | 真实数据回测、参数寻优、样本外检验 | 是，填入 token |
| **阶段三：实盘监控** | 实时行情 API | 实盘信号生成与执行 | 是，需低延迟源 |

> 系统默认运行在阶段一。当 `DataLoader` 检测到数据源可用且 `.env` 已配置时，自动升级到阶段二。

---

## 2. 数据源对比

| 数据源 | 市场 | 频率 | 费用 | 质量 | 延迟 | 推荐场景 |
|--------|------|------|------|------|------|---------|
| **AKShare** | A股 | 日/分/Tick | 免费 | 中 | 实时 | 原型开发、日线回测 |
| **Tushare** | A股 | 日/分/财务 | 免费+积分制 | 高 | 准实时 | 因子研究、财务数据 |
| **Baostock** | A股 | 日/分/周/月 | 免费 | 中 | 日终 | 长历史回测（1990起） |
| **yfinance** | 美股 | 日/分 | 免费 | 中 | 15分钟 | 美股/ETF日线 |
| **Alpha Vantage** | 全球 | 日/分 | 免费(限频) | 中 | 实时 | 外汇/加密补充 |
| **Polygon.io** | 美股/期权 | Tick级 | 付费(免费限频) | 高 | 实时 | 期权链、分钟级 |
| **Wind** | 全市场 | 全频率 | 付费(机构) | 顶级 | 实时 | 机构实盘 |
| **Choice** | A股/港美 | 全频率 | 付费(机构) | 顶级 | 实时 | 机构实盘 |
| **CCXT** | 加密 | Tick级 | 免费 | 高 | 实时 | 加密货币实盘 |

---

## 3. 标准化数据契约

所有数据源经 `DataLoader._standardize()` 统一为以下格式：

```
索引:  DatetimeIndex (UTC-naive, 交易日历对齐)
列名:  open | high | low | close | volume
类型:  float64
排序:  按日期升序
去重:  保留首次出现
```

**复权处理**：A股默认前复权（`qfq`），美股默认 `auto_adjust=True`。
如需后复权或不复权，在对应 `_fetch_*` 方法中修改 `adjust` 参数。

---

## 4. 接入步骤（通用）

```bash
# 1. 安装对应数据源 SDK
pip install akshare          # 或 tushare / yfinance / alpha_vantage / polygon

# 2. 复制配置模板
cp .env.example .env

# 3. 编辑 .env，填入 token（见各数据源章节）

# 4. 验证连接
python -c "from data.data_loader import DataLoader; print(DataLoader().get_daily('000001.SZ', '2024-01-01').tail())"
```

---

## 5. A股数据源

### 5.1 AKShare（推荐入门，无需 token）

```bash
pip install akshare
```

无需配置 `.env`，`DataLoader._fetch_cn()` 默认调用 `ak.stock_zh_a_hist()`。

```python
from data.data_loader import DataLoader
df = DataLoader().get_daily("000001.SZ", start="2024-01-01", market="cn")
```

如需代理，在 `.env` 中设置：
```
AKSHARE_PROXY=http://127.0.0.1:7890
```

### 5.2 Tushare（推荐因子研究，需积分）

1. 注册 https://tushare.pro，获取 token
2. `.env` 填入：
   ```
   TUSHARE_TOKEN=你的token
   ```
3. 安装 SDK：
   ```bash
   pip install tushare
   ```
4. 修改 `config/settings.py` 的数据源优先级（或环境变量）：
   ```
   DATA_CN_FALLBACK=tushare,akshare
   ```

> Tushare 高级接口（分钟线、财务、龙虎榜）需 2000+ 积分，免费用户积分有限。

### 5.3 Baostock（推荐长历史）

```bash
pip install baostock
```

无需 token，支持 1990 年至今的 A 股数据。在 `DataLoader` 中新增 `_fetch_baostock()` 方法即可（见[第9节](#9-自定义数据源接入)）。

---

## 6. 美股数据源

### 6.1 yfinance（推荐入门）

```bash
pip install yfinance
```

无需 token，`DataLoader._fetch_us()` 默认调用。

```python
df = DataLoader().get_daily("AAPL", start="2024-01-01", market="us")
```

### 6.2 Polygon.io（推荐实盘/分钟级）

1. 注册 https://polygon.io，获取 API Key
2. `.env` 填入：
   ```
   POLYGON_API_KEY=你的key
   ```
3. 安装 SDK：
   ```bash
   pip install polygon-api-client
   ```
4. 实现 `_fetch_polygon()`（见[第9节](#9-自定义数据源接入)）

---

## 7. 专业终端数据源

> 机构实盘常用，需购买授权并安装本地客户端。接入后数据质量最高，支持 Tick 级实时推送。

### 7.1 Wind（万得）

```bash
# 需先安装 Wind 终端客户端，再安装 Python 接口
pip install WindPy
```

```python
# 在 DataLoader 中新增 _fetch_wind()
from WindPy import w
w.start()
data = w.wsd("000001.SZ", "open,high,low,close,volume", "2024-01-01", "2024-12-31", "PriceAdj=F")
```

`.env` 中设置 `WIND_ENABLE=true` 启用。

### 7.2 Choice（东方财富）

```bash
pip install EmQuantAPI
```

```python
from EmQuantAPI import c
c.start("ForceLoginParams=1", "")
data = c.csd("000001.SZ", "open,high,low,close,volume", "2024-01-01", "2024-12-31", "adjuststyle=fq")
```

---

## 8. 加密货币数据源

### 8.1 CCXT（统一接口，推荐）

```bash
pip install ccxt
```

```python
import ccxt
exchange = ccxt.binance()
ohlcv = exchange.fetch_ohlcv("BTC/USDT", "1d", limit=100)
# 转为标准 DataFrame 后即可进入回测引擎
```

实盘交易密钥配置见 [BROKER_INTEGRATION.md](./BROKER_INTEGRATION.md)。

---

## 9. 自定义数据源接入

`DataLoader` 采用模板方法模式，新增数据源只需实现一个 `_fetch_*` 方法：

```python
# data/data_loader.py 中新增方法
def _fetch_polygon(self, symbol: str, start: str, end: str) -> pd.DataFrame:
    """从 Polygon.io 获取美股数据"""
    from polygon import RESTClient
    from config.settings import DATA_CONFIG

    client = RESTClient(DATA_CONFIG.polygon_api_key)
    aggs = client.get_aggs(symbol, 1, "day", start, end)

    return pd.DataFrame([{
        "date": a.timestamp,
        "open": a.open, "high": a.high,
        "low": a.low, "close": a.close, "volume": a.volume,
    } for a in aggs])
```

然后在 `get_daily()` 的分发逻辑中加入：
```python
elif market == "us" and self.config.polygon_api_key:
    df = self._fetch_polygon(symbol, start, end)
```

**接入约定**：
1. 返回原始 DataFrame（列名不限），`_standardize()` 会统一格式
2. 异常时返回空 DataFrame，由上层决定是否回退模拟数据
3. 加密货币、期货等新市场，扩展 `market` 参数取值

---

## 10. 数据质量校验清单

接入真实数据后，务必执行以下校验（职业量化实践）：

- [ ] **完整性**：交易日无缺失行（对比交易所交易日历）
- [ ] **准确性**：抽样与官方行情源交叉验证（如新浪/东财）
- [ ] **复权一致性**：检查除权除息日前后价格连续性
- [ ] **成交量合理性**：无 0 成交量异常、无数量级突变
- [ ] **OHLC 逻辑**：`low <= open,close <= high` 恒成立
- [ ] **时区对齐**：跨市场数据统一为 UTC-naive 或显式标注时区
- [ ] **存活偏差**：确认退市/ST 标的是否纳入回测样本
- [ ] **前视偏差**：确认数据时间戳为**收盘后可得**（非盘中实时）

```python
# 快速校验脚本
from data.data_loader import DataLoader

df = DataLoader().get_daily("000001.SZ", "2024-01-01")
assert (df["low"] <= df[["open", "close"]].min(axis=1)).all(), "Low 异常"
assert (df["high"] >= df[["open", "close"]].max(axis=1)).all(), "High 异常"
assert df.index.is_monotonic_increasing, "索引未排序"
assert not df.index.duplicated().any(), "存在重复日期"
print("数据校验通过")
```
