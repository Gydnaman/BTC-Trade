"""
交易执行层
定义统一的Broker接口，提供模拟Broker实现
实盘时只需新增一个继承BaseBroker的子类对接券商API

架构设计:
    BaseBroker (抽象接口)
        ├── SimulatedBroker  (模拟撮合，用于回测验证执行逻辑)
        ├── QMTBroker        (A股实盘 - TODO)
        ├── IBBroker         (美股实盘 - TODO)
        └── CCXTBroker       (加密货币实盘 - TODO)
"""
from abc import ABC, abstractmethod
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
from math import isfinite
from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class Order:
    """订单数据结构"""
    symbol: str               # 标的代码
    direction: str            # "BUY" / "SELL"
    quantity: float           # 数量
    order_type: str = "MARKET"  # MARKET / LIMIT
    limit_price: Optional[float] = None  # 限价单价格
    status: str = "PENDING"   # PENDING / FILLED / CANCELLED / REJECTED


@dataclass
class Position:
    """持仓数据结构"""
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity


@dataclass
class Account:
    """账户状态"""
    cash: float = 1_000_000.0
    positions: dict = field(default_factory=dict)  # {symbol: Position}

    @property
    def total_value(self) -> float:
        pos_value = sum(p.market_value for p in self.positions.values())
        return self.cash + pos_value


class BaseBroker(ABC):
    """
    Broker抽象基类
    定义统一的交易接口，实盘Broker只需实现这些方法
    """

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """下单，返回订单ID"""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position:
        """查询持仓"""
        ...

    @abstractmethod
    def get_account_value(self) -> float:
        """查询账户总市值"""
        ...


class SimulatedBroker(BaseBroker):
    """
    模拟Broker
    模拟订单撮合、资金扣减、持仓更新
    用于验证策略执行逻辑，不产生真实交易

    Usage:
        broker = SimulatedBroker(initial_capital=1_000_000)
        broker.update_price("AAPL", 150.0)
        broker.place_order(Order("AAPL", "BUY", 100))
        print(broker.get_account_value())
    """

    def __init__(self, initial_capital: float = 1_000_000.0,
                 commission_rate: float = 0.0003):
        self.account = Account(cash=initial_capital)
        self.commission_rate = commission_rate
        self._orders: dict[str, Order] = {}
        self._price_cache: dict[str, float] = {}
        self._order_counter = 0

    def update_price(self, symbol: str, price: float):
        """更新标的最新价格（模拟实时行情）"""
        if not isfinite(price) or price <= 0:
            raise ValueError('Quote must be finite and positive')
        self._price_cache[symbol] = price
        if symbol in self.account.positions:
            self.account.positions[symbol].current_price = price
        for order_id, order in list(self._orders.items()):
            if order.symbol == symbol and order.status == 'PENDING':
                self._try_fill(order_id, order)

    def place_order(self, order: Order) -> str:
        """模拟下单并即时成交"""
        self._order_counter += 1
        order_id = f"ORD_{self._order_counter:06d}"
        self._orders[order_id] = order
        if (order.direction not in ('BUY', 'SELL')
                or order.order_type not in ('MARKET', 'LIMIT')
                or not isfinite(order.quantity) or order.quantity <= 0
                or order.status != 'PENDING'
                or (order.order_type == 'LIMIT' and
                    (order.limit_price is None or not isfinite(order.limit_price)
                     or order.limit_price <= 0))):
            order.status = 'REJECTED'
            return order_id
        self._try_fill(order_id, order)
        return order_id

    def _try_fill(self, order_id: str, order: Order):
        """Pending limits are retried at the next supplied quote; no partial fills."""
        price = self._price_cache.get(order.symbol, 0)
        if price <= 0:
            order.status = "REJECTED"
            logger.warning(f"订单被拒: {order.symbol} 无有效价格")
            return order_id

        if order.order_type == 'LIMIT':
            if ((order.direction == 'BUY' and price > order.limit_price)
                    or (order.direction == 'SELL' and price < order.limit_price)):
                return order_id

        # 计算交易金额和佣金
        if order.direction == "BUY":
            cost = order.quantity * price
            commission = max(cost * self.commission_rate, 5.0)
            if cost + commission > self.account.cash:
                order.status = "REJECTED"
                logger.warning(f"订单被拒: 资金不足 (需 {cost+commission:.0f}, 可用 {self.account.cash:.0f})")
                return order_id

            self.account.cash -= (cost + commission)
            self._update_position(order.symbol, order.quantity, price, is_buy=True)

        elif order.direction == "SELL":
            pos = self.account.positions.get(order.symbol)
            if not pos or pos.quantity < order.quantity:
                order.status = "REJECTED"
                logger.warning(f"订单被拒: 持仓不足 {order.symbol}")
                return order_id

            proceeds = order.quantity * price
            commission = max(proceeds * self.commission_rate, 5.0)
            self.account.cash += (proceeds - commission)
            self._update_position(order.symbol, -order.quantity, price, is_buy=False)

        order.status = "FILLED"
        self._orders[order_id] = order
        logger.info(
            f"订单成交 [{order_id}] {order.direction} {order.symbol} "
            f"x{order.quantity} @{price:.2f} | 账户总值: {self.get_account_value():.0f}"
        )
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == "PENDING":
            order.status = "CANCELLED"
            return True
        return False

    def _update_position(self, symbol: str, delta_qty: float, price: float, is_buy: bool):
        """更新持仓"""
        if symbol not in self.account.positions:
            self.account.positions[symbol] = Position(symbol=symbol)

        pos = self.account.positions[symbol]
        if is_buy:
            new_qty = pos.quantity + delta_qty
            if pos.quantity > 0:
                # 加仓：更新均价
                pos.avg_price = (pos.avg_price * pos.quantity + price * delta_qty) / new_qty
            elif pos.quantity == 0:
                pos.avg_price = price
            pos.quantity = new_qty
        else:
            pos.quantity += delta_qty  # delta_qty为负
            if pos.quantity <= 0:
                pos.quantity = 0
                pos.avg_price = 0.0

        pos.current_price = price

    def get_position(self, symbol: str) -> Position:
        return self.account.positions.get(symbol, Position(symbol=symbol))

    def get_account_value(self) -> float:
        return self.account.total_value

    def get_all_positions(self) -> pd.DataFrame:
        """返回所有持仓的DataFrame"""
        if not self.account.positions:
            return pd.DataFrame(columns=["symbol", "quantity", "avg_price", "current_price", "market_value", "pnl"])
        rows = []
        for pos in self.account.positions.values():
            if pos.quantity != 0:
                rows.append({
                    "symbol": pos.symbol,
                    "quantity": pos.quantity,
                    "avg_price": round(pos.avg_price, 2),
                    "current_price": round(pos.current_price, 2),
                    "market_value": round(pos.market_value, 2),
                    "unrealized_pnl": round(pos.unrealized_pnl, 2),
                })
        return pd.DataFrame(rows)
