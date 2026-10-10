# Crypto 数据快照

## 运行

在 QuantTrading 项目目录启动，使用独立环境：

```powershell
.venv\Scripts\python.exe -m crypto.cli --config crypto/config.example.json --collect
```

`--collect` 是显式操作；不传时，CLI 只检查已有 `manifest.json` 是否经过审计。收集器只访问公开 Binance 行情接口，不设置 API key，也不调用下单、账户或杠杆接口。

## 输出

- 现货小时 OHLCV、USDⓈ-M BTCUSDT 永续成交小时 OHLCV、永续 mark-price 小时 OHLCV、离散 funding settlement 各为一个 Parquet 文件。
- 每表另存 CCXT 返回的原始记录 JSON，作为本次标准化的输入证据；这不是 HTTP 原始报文。
- `manifest.json` 记录配置、覆盖、缺口、SHA-256、CCXT 版本、来源记录文件名和当前市场 precision/limits 快照时间。
- 下载区间采用 UTC 左闭右开。K 线 timestamp 明确按毫秒解释，未收盘 candle 丢弃。`available_time` 对历史 candle 是“收盘时可用”的建模假设，不代表保存了当时 API 首次发布时间。
- 资金费保留为结算事件。正负费率均不填充到相邻小时。费率在结算后才进入策略信息集，研究入场延至之后的完整小时。
- Binance 公共资金费历史在本次覆盖的历史区间返回空 `markPrice`。为保留完整结算事件，收集器仅在同一 UTC 小时存在标记价格 K 线时，显式使用该小时 `mark_ohlcv.open` 作为代理值；Parquet 的 `mark_price_source` 会标为 `mark_ohlcv.open_proxy`、`mark_price_is_proxy=true`，并记录来源 K 线时间。它不是精确结算标记价，manifest 会记录代理条数。没有同小时价格时保留空值并让审计失败，绝不借用相邻时段价格。
- 现货历史在 `2023-03-24 13:00–14:00 UTC` 缺一根小时线，而永续和标记价小时线存在。币安官方公告说明现货交易于 `14:00 UTC` 恢复（[公告](https://www.binance.com/en/support/announcement/detail/813a31506e9f478ea8c1058b425df87a)）。配置和 manifest 将这一小时记录为有来源的现货停机缺口；没有构造零收益 K 线。回测必须把该小时标记为现货不可交易/价格不可观测，禁止现货成交与调仓，并在恢复交易时处理价格跳变；不能把它当普通小时无声前向填充。

## 审计规则

三个小时价格表必须在请求区间内覆盖每个完整小时、OHLCV 合法、无重复，且时间戳一致；唯一可豁免的缺口是上文所述 Binance 现货停机小时，配置必须逐字段匹配其官方来源、时间和原因，配置、manifest 审计及两个回放入口都会拒绝其他声明。缺失的 bar 仍然缺失并计入 manifest。每个资金费事件必须有正数标记价及可验证的来源；代理值必须严格等于对应同小时 mark K 线的 open。资金费结算间隔可以变化，不按固定八小时插值；连续结算空档超过 24 小时会作为可疑缺口进入审计失败。任何未说明的缺口或 audit 失败仍保存带哈希的数据和失败 manifest 以便定位，但 CLI 返回 1，后续策略不接受该快照。

市场 precision、最小数量和杠杆档位仅记录抓取当天的市场元数据，不能推断历史规则。历史 candle 数据不包含当时 API 的首次发布时间、order book 深度、双腿同时成交或资金费预测快照。
