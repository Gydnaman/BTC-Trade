"""
量化交易系统 - 主入口
演示完整工作流：数据获取 → 信号生成 → 回测 → 绩效报告

运行方式:
    cd quant_trading
    python main.py
"""
import sys
from pathlib import Path

# 确保项目根目录在path中
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np
from data.data_loader import DataLoader
from strategy.ma_cross import MACrossStrategy
from strategy.bollinger import BollingerStrategy
from backtest.backtester import Backtester
from report.plotting import plot_equity_curve, plot_returns_distribution, print_metrics_table
from utils.logger import setup_logger

logger = setup_logger("main")


def generate_sample_data(start: str = "2022-01-01", end: str = "2024-12-31") -> pd.DataFrame:
    """
    生成模拟行情数据（当无法联网获取真实数据时使用）
    使用几何布朗运动模拟价格走势
    """
    logger.info("生成模拟行情数据...")
    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)

    np.random.seed(42)
    # 模拟3只标的
    symbols = ["STOCK_A", "STOCK_B", "STOCK_C"]
    prices = {}

    for i, sym in enumerate(symbols):
        # 不同标的有不同的漂移率和波动率
        mu = 0.08 + i * 0.03
        sigma = 0.15 + i * 0.05
        rets = np.random.normal(mu / 252, sigma / np.sqrt(252), n)
        price = 100 * np.exp(np.cumsum(rets))
        prices[sym] = price

    df = pd.DataFrame(prices, index=dates)
    df.index.name = "date"

    # 构造OHLCV
    result = {}
    for sym in df.columns:
        close = df[sym]
        result[sym] = pd.DataFrame({
            "open": close * (1 + np.random.uniform(-0.005, 0.005, n)),
            "high": close * (1 + np.abs(np.random.normal(0, 0.01, n))),
            "low": close * (1 - np.abs(np.random.normal(0, 0.01, n))),
            "close": close,
            "volume": np.random.randint(1_000_000, 10_000_000, n),
        }, index=dates)

    return result


def run_single_asset_backtest():
    """
    演示1：单标的双均线策略回测
    使用模拟数据（如已安装akshare可替换为真实数据）
    """
    print("\n" + "#" * 60)
    print("#  演示1: 单标的 - 双均线交叉策略")
    print("#" * 60)

    # --- 1. 获取数据 ---
    # 尝试从真实数据源获取，失败则用模拟数据
    loader = DataLoader()
    symbol = "000001.SZ"

    try:
        data = loader.get_daily(symbol, start="2022-01-01", market="cn")
        if data.empty:
            raise Exception("数据为空")
        logger.info(f"成功获取真实数据: {symbol}")
    except Exception as e:
        logger.warning(f"无法获取真实数据({e})，使用模拟数据")
        sample = generate_sample_data()
        data = sample["STOCK_A"]

    # --- 2. 生成信号 ---
    strategy = MACrossStrategy(short_window=5, long_window=20)
    signals = strategy.generate_signals(data)

    # signals是单列DataFrame，转为适合回测引擎的格式
    price_df = data[["close"]].rename(columns={"close": symbol})
    signal_df = signals.rename(columns={"weight": symbol})

    # --- 3. 回测 ---
    bt = Backtester()
    result = bt.run(price_df, signal_df)

    # --- 4. 报告 ---
    print_metrics_table(result)
    plot_equity_curve(result, title=f"双均线策略 - {symbol}", save_path="ma_cross_equity.png")
    plot_returns_distribution(result, save_path="ma_cross_returns.png")

    return result


def run_multi_asset_backtest():
    """
    演示2：多标的动量策略回测
    """
    print("\n" + "#" * 60)
    print("#  演示2: 多标的 - 动量轮动策略")
    print("#" * 60)

    # --- 1. 获取数据 ---
    sample = generate_sample_data()

    # 构造收盘价面板
    price_df = pd.DataFrame({sym: data["close"] for sym, data in sample.items()})
    price_df.index.name = "date"

    # --- 2. 生成信号 ---
    from strategy.momentum import MomentumStrategy
    strategy = MomentumStrategy(lookback=20, hold_period=5, top_n=2)
    signals = strategy.generate_signals(price_df)

    # --- 3. 回测 ---
    bt = Backtester()
    result = bt.run(price_df, signals)

    # --- 4. 报告 ---
    print_metrics_table(result)
    plot_equity_curve(result, title="动量轮动策略 (3只模拟标的)", save_path="momentum_equity.png")

    return result


def run_bollinger_backtest():
    """
    演示3：布林带均值回归策略
    """
    print("\n" + "#" * 60)
    print("#  演示3: 单标的 - 布林带均值回归策略")
    print("#" * 60)

    sample = generate_sample_data()
    data = sample["STOCK_B"]
    symbol = "STOCK_B"

    strategy = BollingerStrategy(window=20, num_std=2.0)
    signals = strategy.generate_signals(data)

    price_df = data[["close"]].rename(columns={"close": symbol})
    signal_df = signals.rename(columns={"weight": symbol})

    bt = Backtester()
    result = bt.run(price_df, signal_df)

    print_metrics_table(result)
    plot_equity_curve(result, title=f"布林带策略 - {symbol}", save_path="bollinger_equity.png")

    return result


def demo_broker():
    """
    演示4：模拟Broker下单流程
    """
    print("\n" + "#" * 60)
    print("#  演示4: 模拟Broker - 订单执行流程")
    print("#" * 60)

    from execution.broker import SimulatedBroker, Order

    broker = SimulatedBroker(initial_capital=500_000)

    # 模拟行情
    broker.update_price("AAPL", 150.0)
    broker.update_price("GOOG", 2800.0)

    # 下单
    broker.place_order(Order("AAPL", "BUY", 1000))
    broker.place_order(Order("GOOG", "BUY", 50))

    # 查看持仓
    print("\n--- 当前持仓 ---")
    print(broker.get_all_positions().to_string(index=False))
    print(f"\n账户总市值: ${broker.get_account_value():,.2f}")

    # 模拟价格变动
    print("\n--- 价格变动: AAPL 150->155, GOOG 2800->2750 ---")
    broker.update_price("AAPL", 155.0)
    broker.update_price("GOOG", 2750.0)
    print(broker.get_all_positions().to_string(index=False))
    print(f"账户总市值: ${broker.get_account_value():,.2f}")


if __name__ == "__main__":
    print("=" * 60)
    print("  量化交易系统 - 骨架演示")
    print("  作者: CFA/FRM Quant Framework")
    print("=" * 60)

    # 运行所有演示
    run_single_asset_backtest()
    run_multi_asset_backtest()
    run_bollinger_backtest()
    demo_broker()

    print("\n" + "=" * 60)
    print("  所有演示完成！结果图表已保存到 results/ 目录")
    print("=" * 60)
