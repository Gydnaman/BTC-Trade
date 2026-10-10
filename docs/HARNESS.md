# 本地量化开发与实验 Harness

本次落地的是第一阶段：安装现成 skills、建立离线验证入口、修复已复现缺陷，
以及提供最多 10 次的开发实验入口。它不启动无人值守优化，也不连接券商。

## 已接入的 skills

| Skill | 上游 |
| --- | --- |
| backtesting-frameworks | https://github.com/wshobson/agents/tree/main/plugins/quantitative-trading/skills/backtesting-frameworks |
| systematic-debugging | https://github.com/obra/superpowers/tree/main/skills/systematic-debugging |
| test-driven-development | https://github.com/obra/superpowers/tree/main/skills/test-driven-development |
| verification-before-completion | https://github.com/obra/superpowers/tree/main/skills/verification-before-completion |

安装的是 Superpowers 的上述三个独立 skills，未安装整套插件、自动触发 hook 或多代理编排。
这些 skills 位于本机 Codex 用户目录，下一轮可自动发现；其他电脑需要单独安装。
项目 `AGENTS.md` 保存任务路由与验证约定。上游下载时使用 main 分支；本机文件
指纹记录在 `docs/skill-provenance.json`，便于识别后续变更。

## 验证命令

从项目根目录运行：

```powershell
python -B -m harness.validate
```

测试不请求行情、不产生真实订单，使用标准库 unittest 和项目现有 numpy/pandas。
任意失败或零测试均返回非零退出码。机器可读报告写入 `results/validation.json`。

当前覆盖：金叉/死叉、轮动退出、未选中标的、未来数据不改变过去信号、部分卖出税费、
单行回测、非法价格/订单、不满足限价时等待、验证失败检测、实验可复现与次数/数据约束。
信号包已从 `signal` 改为 `indicators`，外部调用需改用 `from indicators.indicators import SMA`。

## 开发实验命令

输入 CSV：第一列 `date`，其余列为各标的收盘价；日期必须唯一、升序，价格为有限正数。
只使用预先划定的开发数据，不把最终留出集传入。例子中的行情是人工合成的测试数据。

```powershell
python -B -m harness.research --prices examples/research_prices.csv --strategy ma_cross --params '{"short_window":2,"long_window":3}' --output results/experiments/demo --max-trials 3
```

可选策略：`ma_cross`、`bollinger`（单标的）、`momentum`（多标的）。
每次 CLI 执行先跑回归测试，再写入 `contract.json` 和独立的 `trial-NNN.json`。
报告包含数据/评估代码/策略代码指纹、软件版本、参数、费用、净值与日收益。
同目录的数据、评估代码、费用或试验预算变化会被拒绝；同时运行会被锁阻止。
异常退出后若留下 `.running`，应确认没有运行进程再手工移除该锁文件。

当前固定开发费用假设：佣金 0.0003、滑点 0.001、印花税 0、无风险利率 0.025。
这不是 A 股/美股实际费率表。修改费用属于评估合同变更，需新建经记录的实验。
只允许有限、非负、总和不超过 1 的目标权重。预算限制成功落盘的试验；失败尝试、
跨目录试验需在实验记录中一并计数。不得为了调参反复创建目录绕过预算。

## 已知边界与后续顺序

1. 当前回测仍是信号滞后一行的收盘到收盘权重收益近似，未解决完整成交时点、
   权重漂移产生的再平衡费用及股数/现金账本。交易记录不是逐笔可成交账本。
2. 风控类尚未整合到回测和 Broker；研究入口的总仓位检查不等于止损和回撤熔断。
3. 模拟 Broker 支持报价驱动的限价等待/成交/撤销；未提供资金冻结、部分成交、
   交易所撮合规则、持久化与重启恢复，费用与向量化回测尚不统一。
4. 真实数据缓存的区间覆盖、来源切换与复权元数据仍需下一阶段重构。
5. 尚未实现独立留出集、滚动样本外验证、多重试验校正或自动选优/推广。

因此所有实验标记 `development_only`。先完成成交/资金模型与风控闭环，
再接入真实数据审计和样本外验证，最后才考虑 RD-Agent 或更长的自动研究循环。

设计参考：https://github.com/TraderAlice/Auto-Quant 。本项目使用自主实现的轻量入口，
没有迁移或复制它的交易引擎，也没有安装 RD-Agent/TraderHarness。
