# BTC/USDT 策略实验台与新手 README 设计

## 目标
让初学者可以用受限表单定义当前项目支持的 BTC/USDT 现货—永续 Carry 基线，并对已审计的历史数据运行隔离的开发阶段回测；同时让 README 能带读者理解项目组成、关键术语、运行路径和研究限制。

## 范围
- 仅支持 cash_zero、carry_static、funding_filter 三种已注册基线。
- 参数只允许策略定义的资金分配比例、抵押比例和已结算资金费门槛；校验有限数值与参数范围。
- 只读取本机已有且通过 manifest、哈希和时间完整性审计的 Binance BTC/USDT 快照。
- 交互式运行只使用固定时间序列切分中的 development 段，结果写到独立 results/crypto/playground/，与 campaign registry、validation、holdout 隔离。
- UI 不收集行情、不调用 AI/RPC、不使用账户密钥、不下单。
- README 采用面向初学者的中文学习路线；准确介绍通用量化骨架与加密 Carry 子系统的边界，提供安装、运行、数据准备、回测结果阅读、代码目录与限制说明，并链接深入文档。

## 架构与数据流
1. crypto/playground.py 提供策略参数校验与单次实验 API，复用现有数据快照审计、策略事件生成、Decimal 双腿账本、指标和风险情景逻辑。它不经过正式 run_trial，因此不读写 campaign registry，也不可能触碰一次性 holdout。
2. crypto/ui/playground_tab.py 展示表单、解释字段、运行状态、结果指标、权益曲线、收益归因和明确的 development-only 提示。未配置或未审计的数据以可操作错误说明停止，绝不退回模拟数据。
3. crypto/ui/app.py 将新试验表单与历史只读研究回放分开；缺少本地 campaign artifact 时仍可展示试验入口，并说明历史、AI、链上页面暂不可用的原因。
4. README 先回答系统是什么、能做什么、不能做什么，再给出概念图、术语、初次上手路径、目录地图、结果解释和深入文档链接；细节保留在 docs/ 中。

## 结果与限制
每次运行生成唯一子目录，包含 JSON 元数据与账本 CSV；记录 strategy、规范化参数、development 区间、快照 ID、表哈希、费用、假设、指标、归因和限制。报告醒目标为 development_only，不给出实盘或收益保证结论。初版不提供任意 Python、自然语言解析、validation/holdout 参数搜索、真实账户/API 或下单。

## 错误处理
参数不支持时在运行前拒绝；缺失 manifest、哈希不匹配、数据审计失败、目录不可写或账本事件被拒绝时显示可读错误，不留下看似成功的 trial。运行 artifact 只写入固定 playground 根目录。

## 验收
- 无网络单元测试覆盖策略参数、development 隔离、来源记录和试验输出隔离。
- UI 测试确认表单显式提交、development-only 标签和数据缺失提示。
- 项目完整验证 python -B -m harness.validate 通过。
- README 的命令、目录和实现状态与代码及深入文档一致，不把愿景写成已实现功能。
