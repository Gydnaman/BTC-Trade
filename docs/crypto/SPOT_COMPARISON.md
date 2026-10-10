# 现货账本对照状态

独立 spot cash ledger 已按固定成交做 Decimal 手算校验：初始现金 1000、买入 1@100、卖出 1@110、两次手续费各 10 bps，最终现金和权益为 1009.79。现金不足、超额卖出、未平仓持仓和停机期间拒单也有离线回归测试。它验证交易现金语义，尚未构成 Freqtrade 引擎对照。

Freqtrade 交叉核对暂未运行。当前主机的 Docker CLI 为 29.8.0，但 `docker version` 无法连接 Docker Desktop Linux Engine named pipe；因此没有构建或执行 Freqtrade 容器，也没有生成引擎间的信号/成交/权益差异报告。恢复 Docker Engine 后，必须在同一冻结行情哈希、固定信号时间和费用假设下运行比较；在此之前不能宣称交叉框架核对通过。
