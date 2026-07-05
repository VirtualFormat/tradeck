# openbb-akshare-provider

AKShare extension for OpenBB Platform — A 股深度数据接入。

## 数据覆盖

| Fetcher | AKShare 函数 | 说明 |
|---|---|---|
| `StockQuote` | `stock_zh_a_spot_em` | A 股实时报价 |
| `EquityHistorical` | `stock_zh_a_hist` | A 股历史 K 线 |
| `IndexHistorical` | `stock_zh_index_daily_em` | A 股指数历史 |
| `FundamentalsMetrics` | `stock_financial_em` | A 股财务指标 |
| `NorthFlow` | `stock_hsgt_north_net_flow_in_em` | 北向资金 |
| `MarginTrading` | `stock_margin_detail_szse` | 融资融券 |
| `DragonTigerList` | `stock_lhb_detail_em` | 龙虎榜 |
| `ConceptBoards` | `stock_board_concept_name_em` | 板块/概念 |

## 安装

```bash
pip install -e packages/openbb-akshare-provider
openbb-build
```
