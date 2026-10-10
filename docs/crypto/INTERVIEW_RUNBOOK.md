# 面试演示运行手册

## 开始前

从项目根目录启动 PowerShell。工作台依赖安装在独立环境，不改股票项目依赖：

```powershell
uv pip install --python .venv/Scripts/python.exe --requirement requirements-crypto-ui.lock --require-hashes
```

## 演示顺序（约 5 分钟）

1. 启动只读工作台：

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run crypto/ui/app.py --server.address 127.0.0.1 --server.port 8501
   ```

   打开 `http://127.0.0.1:8501`。页面有“策略回测 / AI 研究报告 / 链上验证”三个页签，只读，不跑新回测或交易。

2. 先展示冻结候选与一次性 holdout：`carry_static` 在 275 个日样本上为 +0.39%。立即补充：样本不足一年，年化统计不稳定。
3. 打开 campaign 可行性与保证金审计：development 阶段有 12,601/19,704 小时低于代理线。解释这是简化代理，不是交易所强平复现；因此不能按 +0.39% 作产品承诺。
4. 选择 `trial-005` 的 `funding_filter` development，展示 -4.26% 及 1,202/17,799 小时下穿，说明失败方案也保留并追溯。
5. 展示收益归因，解释 spot P&L、perp P&L、funding、双腿手续费和滑点分别从哪里来。
6. 切到“AI 研究报告”：当前展示 `trial-005` development 的确定性事实报告，provider 为 `unconfigured`，没有在线 LLM 调用；报告不读取已消费的 holdout。
7. 切到“链上验证”：先指出红色合成夹具提示，再看事件样例和环境检查。真实 RPC、池身份、`eth_getLogs` 与 Anvil fork 测试仍未完成；示例区块和地址不是实链数据。

## 验证与输出

完整回归：

```powershell
\.venv\Scripts\python.exe -B -m harness.validate
```

完整回归：177 项通过，1 项因 Windows 符号链接创建权限跳过；结构化记录保存在 `results/crypto/v8-validation.json`。Streamlit AppTest 无异常，三个页签和 7 个下载控件均成功渲染；本机 `127.0.0.1:8501/_stcore/health` 返回 `ok`。AI 报告位于 `results/crypto/ai/trial-005-development.md`；链上合成示例位于 `results/crypto/onchain/synthetic-event-demo.md`。这两份文件都标明数据来源。

五页面试展示稿：`C:\Users\Lenovo\Documents\Codex\2026-09-15\ni\crypto-carry-deliverable\crypto-carry-interview-brief-v2.pptx`。收益归因图可编辑；验证回执在同一工作区的 `.codex-work/v7-build`。

## 不要这样讲

- 不说“策略已盈利”或“可以实盘”：holdout 收益很小，样本短，development 保证金代理不可行。
- 不说年化 Sharpe 已验证：275 个日样本不足一年。
- 不说已完成真实链上交易、套利或 approve/swap 测试：没有真实 RPC/Anvil 证据。
- 不说接入了在线 LLM：当前 provider 未配置，仅有可替换接口、拒绝越权输出的测试和确定性回退。
