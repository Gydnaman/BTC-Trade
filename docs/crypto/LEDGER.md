# 双腿账本与事件时间

`crypto.events.sort_events` 和 `crypto.ledger.replay_events` 提供离线研究账本；它们不会连接交易所账户，也不发送订单。账本以 Decimal 处理 USDT 现金、现货数量、永续有符号数量、独立抵押、费用、滑点和资金费。

## 事件格式

每条事件包含 `kind`、带时区的 `event_time`、整数 `sequence` 和对象 `payload`。当前类型为 `spot_fill`、`perp_fill`、`collateral_transfer`、`funding`、`mark` 和 `risk`。成交事件使用 `group_id`、`side`、正数 `quantity` 和参考市场价 `price`；线性永续卖出为负持仓，买入为正持仓。抵押转账正数代表从自由现金转入永续抵押，负数代表取回。

相同 UTC 毫秒内按 funding、抵押存入、价格标记、成交、抵押取回、风险事件排序；同类事件再按 `sequence` 排序。这让结算发生在该时点新成交之前，避免刚开仓就领取已结算资金费，也确保平仓后才能取回抵押。配置的滑点作用于参考价格得到实际成交价，费用按实际成交名义额计算。

## 账本与归因

总权益按自由现金＋现货市值＋永续抵押＋永续未实现盈亏计算。抵押划转只改变账户分项，不改变总权益。`attribution` 分别汇总现货价格盈亏、永续价格盈亏、资金费、两腿费用和滑点；每条事件后都校验账本权益与归因权益的差额不超过 1e-8 USDT。

`tests/fixtures/crypto/carry_handcalc.json` 是独立手算例：初始 1000 USDT，现货买入 1@100、永续做空 1@101，正资金费 0.001，现货退出价 110、永续退出/结算标记价 113。四次费用合计 0.317，正资金费收入 0.113，最终权益必须为 **997.796 USDT**。

资金费事件必须包含 `mark_price_source`、`mark_price_is_proxy` 和 `mark_price_source_time`。来源只能是交易所结算事件或同一 UTC 小时的 `mark_ohlcv.open_proxy`；账本会拒绝不完整、时间不匹配的来源声明，并把精确来源时间写进事件明细。早期数据的同小时 mark 开盘代理并非精确结算标记价；应在结果中保留代理计数，并用费率/价格敏感性情景检验其影响。

Binance 现货 `2023-03-24 13:00–14:00 UTC` 官方停机时段是账本内置的不可交易区间；即使事件配置漏了缺口注释，现货成交仍会被拒绝。可以用 `mark` 事件把最后可观察价标成 `spot_mark_is_stale=true`、`spot_market_available=false`；恢复时更新到首个可成交价，期间不能产生现货成交。该陈旧价格只是账本估值假设，不代表停机时存在可成交的市场报价。

运行离线契约测试：

```powershell
.venv\Scripts\python.exe -B -m unittest tests.test_crypto_events tests.test_crypto_ledger -v
```
