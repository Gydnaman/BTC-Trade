"""
风控模块
负责仓位管理、止损、组合风险限制
基于FRM风险管理框架设计
"""
import pandas as pd
import numpy as np
from config.settings import RiskConfig
from utils.logger import setup_logger

logger = setup_logger(__name__)


class RiskManager:
    """
    风险管理器

    功能:
    1. 单标的仓位限制 (max_position_pct)
    2. 组合总仓位限制 (max_total_exposure)
    3. 单标的止损 (stop_loss_pct)
    4. 组合最大回撤熔断 (max_drawdown_pct)
    5. 最大持仓数量 (max_positions)
    """

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()

    def check_position_limit(self, symbol: str, target_weight: float,
                             current_weights: dict) -> float:
        """
        检查单标的仓位是否超限，返回调整后的权重

        Args:
            symbol: 标的代码
            target_weight: 目标权重
            current_weights: 当前所有持仓权重 {symbol: weight}
        """
        # 单标的仓位上限
        max_w = self.config.max_position_pct
        if abs(target_weight) > max_w:
            target_weight = np.sign(target_weight) * max_w
            logger.warning(f"{symbol} 仓位超限，截断至 {max_w:.1%}")

        # 检查持仓数量
        current_holdings = [s for s, w in current_weights.items() if abs(w) > 0]
        if target_weight != 0 and symbol not in current_holdings:
            if len(current_holdings) >= self.config.max_positions:
                logger.warning(f"持仓数已达上限 {self.config.max_positions}，跳过 {symbol}")
                return 0.0

        return target_weight

    def check_total_exposure(self, weights: dict) -> dict:
        """
        检查组合总仓位，若超限则等比例缩减

        Args:
            weights: 目标权重字典 {symbol: weight}

        Returns:
            调整后的权重字典
        """
        total = sum(abs(w) for w in weights.values())
        max_exp = self.config.max_total_exposure

        if total > max_exp:
            scale = max_exp / total
            weights = {s: w * scale for s, w in weights.items()}
            logger.warning(f"总仓位 {total:.1%} 超限，等比缩减至 {max_exp:.1%}")

        return weights

    def check_stop_loss(self, symbol: str, entry_price: float,
                        current_price: float, current_weight: float) -> float:
        """
        止损检查

        Args:
            symbol: 标的
            entry_price: 建仓价格
            current_price: 当前价格
            current_weight: 当前仓位

        Returns:
            止损后调整的仓位（0表示清仓）
        """
        if entry_price <= 0 or current_weight == 0:
            return current_weight

        pnl_pct = (current_price - entry_price) / entry_price
        if current_weight < 0:  # 做空反向计算
            pnl_pct = -pnl_pct

        if pnl_pct <= -self.config.stop_loss_pct:
            logger.warning(
                f"{symbol} 触发止损: 亏损 {pnl_pct:.2%} <= -{self.config.stop_loss_pct:.0%}"
            )
            return 0.0

        return current_weight

    def check_drawdown(self, portfolio_value: pd.Series) -> bool:
        """
        最大回撤熔断检查

        Args:
            portfolio_value: 组合净值序列

        Returns:
            True=正常, False=触发熔断应停止交易
        """
        if len(portfolio_value) < 2:
            return True

        peak = portfolio_value.expanding().max()
        drawdown = (portfolio_value - peak) / peak
        current_dd = drawdown.iloc[-1]

        if current_dd <= -self.config.max_drawdown_pct:
            logger.error(
                f"组合回撤 {current_dd:.2%} 触发熔断线 -{self.config.max_drawdown_pct:.0%}，停止交易"
            )
            return False

        return True

    @staticmethod
    def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
        """
        Kelly公式计算最优仓位比例

        f* = (p * b - q) / b
        其中 p=胜率, q=1-p, b=盈亏比

        Args:
            win_rate: 胜率 (0~1)
            win_loss_ratio: 平均盈利/平均亏损

        Returns:
            Kelly最优比例 (建议实际使用时乘以0.5作为半Kelly)
        """
        p = win_rate
        q = 1 - p
        b = win_loss_ratio
        if b <= 0:
            return 0.0
        kelly = (p * b - q) / b
        # 半Kelly更稳健
        return max(0.0, kelly * 0.5)
