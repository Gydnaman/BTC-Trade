"""
绩效报告与可视化模块
生成回测净值曲线、回撤图、绩效表格
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from backtest.backtester import BacktestResult
from config.settings import RESULT_DIR

# 中文字体设置
plt.rcParams.update({
    "font.sans-serif": ["SimHei", "Microsoft YaHei", "Arial"],
    "axes.unicode_minus": False,
    "figure.dpi": 150,
    "savefig.dpi": 200,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": "--",
})


def plot_equity_curve(result: BacktestResult, benchmark: pd.Series = None,
                      title: str = "策略净值曲线", save_path: str = None):
    """
    绘制净值曲线 + 回撤图

    Args:
        result: 回测结果
        benchmark: 基准净值序列（可选）
        title: 图表标题
        save_path: 保存路径，None则显示
    """
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1],
                              sharex=True, gridspec_kw={"hspace": 0.05})

    # --- 上图：净值曲线 ---
    ax1 = axes[0]
    # 归一化到1
    nav = result.portfolio_value / result.portfolio_value.iloc[0]
    ax1.plot(nav.index, nav, color="#E74C3C", linewidth=1.8, label="策略净值")

    if benchmark is not None:
        bench = benchmark / benchmark.iloc[0]
        ax1.plot(bench.index, bench, color="#3498DB", linewidth=1.2,
                 alpha=0.7, label="基准")

    ax1.set_title(title, fontsize=14, fontweight="bold")
    ax1.set_ylabel("净值", fontsize=12)
    ax1.legend(loc="upper left", framealpha=0.9)

    # --- 下图：回撤 ---
    ax2 = axes[1]
    peak = result.portfolio_value.expanding().max()
    drawdown = (result.portfolio_value - peak) / peak
    ax2.fill_between(drawdown.index, drawdown * 100, 0,
                     color="#E74C3C", alpha=0.3)
    ax2.plot(drawdown.index, drawdown * 100, color="#C0392B", linewidth=0.8)
    ax2.set_ylabel("回撤 (%)", fontsize=12)
    ax2.set_xlabel("日期", fontsize=12)

    plt.tight_layout()

    if save_path:
        path = Path(save_path) if not str(save_path).startswith("/") else Path(save_path)
        if not path.is_absolute():
            path = RESULT_DIR / save_path
        plt.savefig(path, bbox_inches="tight")
        plt.close()
        print(f"图表已保存: {path}")
    else:
        plt.show()


def plot_returns_distribution(result: BacktestResult, save_path: str = None):
    """绘制日收益率分布直方图"""
    fig, ax = plt.subplots(figsize=(10, 5))

    returns = result.daily_returns * 100
    ax.hist(returns, bins=50, color="#3498DB", alpha=0.7, edgecolor="white")

    mean_r = returns.mean()
    std_r = returns.std()
    ax.axvline(mean_r, color="#E74C3C", linewidth=2, linestyle="--",
               label=f"均值: {mean_r:.3f}%")
    ax.axvline(mean_r + std_r, color="#F39C12", linewidth=1, linestyle=":",
               label=f"+1σ: {(mean_r+std_r):.3f}%")
    ax.axvline(mean_r - std_r, color="#F39C12", linewidth=1, linestyle=":",
               label=f"-1σ: {(mean_r-std_r):.3f}%")

    ax.set_title("日收益率分布", fontsize=14, fontweight="bold")
    ax.set_xlabel("日收益率 (%)", fontsize=12)
    ax.set_ylabel("频次", fontsize=12)
    ax.legend()

    plt.tight_layout()

    if save_path:
        path = RESULT_DIR / save_path if not Path(save_path).is_absolute() else Path(save_path)
        plt.savefig(path, bbox_inches="tight")
        plt.close()
        print(f"图表已保存: {path}")
    else:
        plt.show()


def print_metrics_table(result: BacktestResult):
    """以美观格式打印绩效指标表"""
    print("\n" + "=" * 50)
    print(f"  {'回测绩效报告':^44}")
    print("=" * 50)

    metrics = result.metrics
    for key, val in metrics.items():
        if isinstance(val, float):
            if "比率" in key:
                print(f"  {key:<20s} {val:>20.2f}")
            elif "率" in key or "回撤" in key:
                print(f"  {key:<20s} {val:>20.2%}")
            else:
                print(f"  {key:<20s} {val:>20.4f}")
        else:
            print(f"  {key:<20s} {val:>20}")

    print("=" * 50 + "\n")
