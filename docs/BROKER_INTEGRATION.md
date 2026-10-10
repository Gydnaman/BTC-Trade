# 实盘券商对接指南 (Broker Integration)

> 本系统执行层采用**抽象基类 + 模板方法**设计：`BaseBroker` 定义统一交易接口，`SimulatedBroker` 提供回测/模拟验证实现，实盘对接只需继承 `BaseBroker` 实现若干方法。**实盘有真实资金风险，务必先经充分模拟验证。**

## 目录
- [1. 实盘对接前置条件](#1-实盘对接前置条件)
- [2. Broker 接口契约](#2-broker-接口契约)
- [3. 券商对比](#3-券商对比)
- [4. A股实盘：QMT](#4-a股实盘qmt)
- [5. 全球实盘：盈透证券 IBKR](#5-全球实盘盈透证券-ibkr)
- [6. 加密货币：CCXT](#6-加密货币ccxt)
- [7. 自定义券商接入](#7-自定义券商接入)
- [8. 实盘风控红线](#8-实盘风控红线)
- [9. 实盘部署检查清单](#9-实盘部署检查清单)

---

## 1. 实盘对接前置条件

```
[ ] 策略已通过至少 1 年样本外回测
[ ] 策略已通过模拟盘（SimulatedBroker）至少 1 个月验证
[ ] 已理解并接受回测与实盘的差异（滑点、部分成交、延迟、停牌）
[ ] 实盘账户已开通程序化交易权限
[ ] API 密钥已配置最小权限（交易+查询，禁止出金）
[ ] 已设置风控熔断机制（最大回撤、单笔亏损、日内交易次数）
[ ] 已准备应急方案：断网/宕机时的手动平仓流程
```

> ⚠️ **风险声明**：程序化交易可能因网络延迟、API 限流、行情异常、策略缺陷等因素造成超出预期的损失。实盘前请充分评估，仅使用可承受亏损的资金。

---

## 2. Broker 接口契约

`BaseBroker` 定义了所有券商必须实现的统一接口：

| 方法 | 签名 | 说明 |
|------|------|------|
| `place_order` | `(order: Order) -> str` | 下单，返回订单ID |
| `cancel_order` | `(order_id: str) -> bool` | 撤单 |
| `get_position` | `(symbol: str) -> Position` | 查询单标的持仓 |
| `get_account_value` | `() -> float` | 查询账户总市值 |

`Order` 数据结构：
```python
@dataclass
class Order:
    symbol: str                    # 标的代码
    direction: str                 # "BUY" / "SELL"
    quantity: float                # 数量
    order_type: str = "MARKET"     # MARKET / LIMIT
    limit_price: Optional[float] = None  # 限价单价格
    status: str = "PENDING"        # PENDING / FILLED / CANCELLED / REJECTED
```

> 实盘 Broker 建议额外实现：`get_realtime_quote()`、`get_orders()`（查当日委托）、`flush()`（同步持仓状态），以支持实时监控循环。

---

## 3. 券商对比

| 券商/接口 | 市场 | 门槛 | 延迟 | 文档 | 推荐场景 |
|-----------|------|------|------|------|---------|
| **QMT (迅投)** | A股 | 需开通QMT权限(资金门槛) | 低 | 中 | A股实盘首选 |
| **PTrade** | A股 | 恒生电子，券商提供 | 低 | 中 | A股备选 |
| **easytrader** | A股 | 模拟键鼠，无门槛 | 高 | 弱 | 仅个人测试 |
| **IBKR (盈透)** | 全球 | 开户即可，无资金门槛 | 极低 | 完善 | 美股/港股/期货/期权 |
| **CCXT** | 加密 | 注册交易所即可 | 低 | 完善 | 加密货币 |
| **CTP** | 期货 | 期货开户 | 极低 | 完善 | 商品期货 |

---

## 4. A股实盘：QMT

### 4.1 准备
1. 在支持 QMT 的券商（国金、华泰、中泰等）开户并申请 QMT 权限
2. 下载安装 QMT 客户端（含 Mini QMT）
3. `.env` 配置：
   ```
   QMT_PATH=C:/QMT/userdata_mini
   QMT_ACCOUNT_ID=你的资金账号
   QMT_TRADE_PASSWORD=你的交易密码
   ```
4. 安装 SDK（随 QMT 客户端附带 `xtquant`）

### 4.2 实现示例

```python
# execution/qmt_broker.py
from execution.broker import BaseBroker, Order, Position
from config.settings import BROKER_CONFIG
from utils.logger import setup_logger
from xtquant import xttrader, xtdata

logger = setup_logger(__name__)


class QMTBroker(BaseBroker):
    """A股 QMT 实盘 Broker"""

    def __init__(self):
        self.path = BROKER_CONFIG.qmt_path
        self.account_id = BROKER_CONFIG.qmt_account_id
        self.session = xttrader.XtQuantTrader(self.path, self.session_id)
        self.account = xttrader.StockAccount(self.account_id)

        if not self.session.connect():
            raise ConnectionError("QMT 连接失败，请检查客户端是否运行")
        self.session.start()
        self.subscribe()  # 订阅账户状态
        logger.info(f"QMT 已连接: {self.account_id}")

    def place_order(self, order: Order) -> str:
        """下单，返回 QMT 订单ID"""
        seq = self.session.order_stock(
            self.account,
            order.symbol,
            xttrader.STOCK_BUY if order.direction == "BUY" else xttrader.STOCK_SELL,
            int(order.quantity),
            xttrader.FIX_PRICE if order.order_type == "LIMIT" else xttrader.LATEST_PRICE,
            order.limit_price or -1,
            "",
            "",
        )
        logger.info(f"QMT下单: {order.direction} {order.symbol} x{order.quantity} seq={seq}")
        return str(seq)

    def cancel_order(self, order_id: str) -> bool:
        return self.session.cancel_order_stock(self.account, int(order_id))

    def get_position(self, symbol: str) -> Position:
        detail = self.session.query_stock_positions(self.account)
        for pos in detail:
            if pos.stock_code == symbol:
                return Position(
                    symbol=symbol,
                    quantity=pos.volume,
                    avg_price=pos.open_price,
                    current_price=xtdata.get_full_tick([symbol])[symbol]["lastPrice"],
                )
        return Position(symbol=symbol)

    def get_account_value(self) -> float:
        asset = self.session.query_stock_asset(self.account)
        return asset.total_asset if asset else 0.0
```

### 4.3 注意事项
- A股 T+1 交易，当日买入不可卖出
- 涨跌停板限制：下单价格需在限价区间内
- 最小交易单位 100 股（1 手）
- 印花税卖出单边 0.1%，佣金万三左右

---

## 5. 全球实盘：盈透证券 IBKR

### 5.1 准备
1. 开户 https://www.interactivebrokers.com
2. 下载并运行 **TWS** 或 **IB Gateway**（轻量推荐）
3. TWS 设置：`Configuration → API → Settings → Enable ActiveX and Socket Clients`
4. `.env` 配置：
   ```
   IB_HOST=127.0.0.1
   IB_PORT=7497        # 7497=模拟盘(paper)  7496=实盘(live)
   IB_CLIENT_ID=1
   ```
5. 安装 SDK：
   ```bash
   pip install ib_insync
   ```

### 5.2 实现示例

```python
# execution/ib_broker.py
from execution.broker import BaseBroker, Order, Position
from config.settings import BROKER_CONFIG
from utils.logger import setup_logger
from ib_insync import IB, Stock, MarketOrder, LimitOrder

logger = setup_logger(__name__)


class IBBroker(BaseBroker):
    """盈透证券实盘 Broker"""

    def __init__(self):
        self.ib = IB()
        self.ib.connect(
            BROKER_CONFIG.ib_host,
            BROKER_CONFIG.ib_port,
            clientId=BROKER_CONFIG.ib_client_id,
        )
        logger.info(f"IBKR 已连接 (port={BROKER_CONFIG.ib_port})")

    def place_order(self, order: Order) -> str:
        contract = Stock(order.symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)

        if order.order_type == "LIMIT":
            trade = self.ib.placeOrder(
                contract,
                LimitOrder(
                    "BUY" if order.direction == "BUY" else "SELL",
                    order.quantity,
                    order.limit_price,
                ),
            )
        else:
            trade = self.ib.placeOrder(
                contract,
                MarketOrder(
                    "BUY" if order.direction == "BUY" else "SELL",
                    order.quantity,
                ),
            )
        logger.info(f"IBKR下单: {order.direction} {order.symbol} x{order.quantity}")
        return str(trade.order.orderId)

    def cancel_order(self, order_id: str) -> bool:
        orders = self.ib.openOrders()
        for o in orders:
            if str(o.orderId) == order_id:
                self.ib.cancelOrder(o)
                return True
        return False

    def get_position(self, symbol: str) -> Position:
        positions = self.ib.positions()
        for p in positions:
            if p.contract.symbol == symbol:
                ticker = self.ib.reqMktData(p.contract, "", False, False)
                self.ib.sleep(0.5)
                return Position(
                    symbol=symbol,
                    quantity=p.position,
                    avg_price=p.avgCost / p.position if p.position else 0,
                    current_price=ticker.last or ticker.close,
                )
        return Position(symbol=symbol)

    def get_account_value(self) -> float:
        account = self.ib.managedAccounts()[0]
        summary = self.ib.accountSummary(account)
        for item in summary:
            if item.tag == "NetLiquidation":
                return float(item.value)
        return 0.0
```

### 5.3 模拟盘先行
**强烈建议先用 `IB_PORT=7497` 连接 paper trading 账户**，至少运行 2 周验证后再切换实盘端口 `7496`。

---

## 6. 加密货币：CCXT

### 6.1 准备
1. 在交易所（Binance/OKX/Bybit）注册并创建 API Key
2. **权限设置**：仅开启"读取+交易"，**关闭"提现"**
3. `.env` 配置：
   ```
   CCXT_EXCHANGE=binance
   CCXT_API_KEY=你的key
   CCXT_API_SECRET=你的secret
   ```
4. 安装 SDK：
   ```bash
   pip install ccxt
   ```

### 6.2 实现示例

```python
# execution/ccxt_broker.py
import ccxt
from execution.broker import BaseBroker, Order, Position
from config.settings import BROKER_CONFIG
from utils.logger import setup_logger

logger = setup_logger(__name__)


class CCXTBroker(BaseBroker):
    """加密货币交易所实盘 Broker（CCXT 统一接口）"""

    def __init__(self):
        exchange_class = getattr(ccxt, BROKER_CONFIG.ccxt_exchange)
        self.exchange = exchange_class({
            "apiKey": BROKER_CONFIG.ccxt_api_key,
            "secret": BROKER_CONFIG.ccxt_api_secret,
            "enableRateLimit": True,
        })
        self.exchange.load_markets()
        logger.info(f"CCXT 已连接: {BROKER_CONFIG.ccxt_exchange}")

    def place_order(self, order: Order) -> str:
        resp = self.exchange.create_order(
            symbol=order.symbol,
            type=order.order_type.lower(),
            side=order.direction.lower(),
            amount=order.quantity,
            price=order.limit_price,
        )
        logger.info(f"CCXT下单: {order.direction} {order.symbol} x{order.quantity}")
        return resp["id"]

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.exchange.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    def get_position(self, symbol: str) -> Position:
        balance = self.exchange.fetch_balance()
        base = symbol.split("/")[0]  # "BTC/USDT" -> "BTC"
        amount = balance.get(base, {}).get("free", 0)
        ticker = self.exchange.fetch_ticker(symbol)
        return Position(
            symbol=symbol,
            quantity=amount,
            avg_price=0.0,
            current_price=ticker["last"],
        )

    def get_account_value(self) -> float:
        balance = self.exchange.fetch_balance()
        return balance.get("USDT", {}).get("total", 0.0)
```

---

## 7. 自定义券商接入

任何券商只需继承 `BaseBroker` 实现 4 个方法即可接入系统：

```python
# execution/my_broker.py
from execution.broker import BaseBroker, Order, Position

class MyBroker(BaseBroker):
    def place_order(self, order: Order) -> str:
        # 调用券商 API 下单
        ...

    def cancel_order(self, order_id: str) -> bool:
        ...

    def get_position(self, symbol: str) -> Position:
        ...

    def get_account_value(self) -> float:
        ...
```

**接入约定**：
1. `place_order` 返回字符串型订单ID，用于后续撤单
2. 异常不吞没：网络/权限错误应抛出，由上层风控决定是否重试
3. 状态同步：实盘 Broker 建议定期调用 `query_positions` 同步真实持仓，防止状态漂移
4. 日志：所有下单/撤单/持仓变动必须记录，便于事后复盘

---

## 8. 实盘风控红线

实盘运行时，以下风控由 `RiskManager` 在下单前强制检查，不可绕过：

| 风控项 | 默认阈值 | 说明 |
|--------|---------|------|
| 单标的最大仓位 | 25% | 防止集中度风险 |
| 最大总仓位 | 100% | 禁止加杠杆 |
| 单标的止损 | -8% | 触发即平仓 |
| 组合最大回撤 | -20% | 触发即停止交易 |
| 最大持仓数 | 10 | 防止过度分散 |
| 单笔最大金额 | 见 `RiskConfig` | 防止下错单（胖手指） |

> 实盘建议额外增加：**日内最大交易次数**、**API 异常熔断**（连续 N 次失败暂停）、**盘前盘后禁止交易**。

---

## 9. 实盘部署检查清单

```
[ ] 策略回测：样本外夏普 > 1.0，最大回撤 < 20%
[ ] 模拟盘验证：连续 1 个月，实盘信号与模拟一致
[ ] 密钥安全：.env 已 gitignore，生产用密钥管理服务
[ ] 网络冗余：主备网络，断网自动告警
[ ] 进程守护：systemd / supervisord 守护进程，崩溃自动重启
[ ] 日志留存：交易日志保留至少 1 年，便于审计
[ ] 监控告警：账户净值/持仓异常时短信/微信告警
[ ] 应急平仓：一键平仓脚本，断电断网可手动执行
[ ] 资金隔离：实盘仅使用可承受亏损的资金
[ ] 合规检查：了解当地程序化交易法规（如A股报备要求）
```
