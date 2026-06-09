# V5 Final 資料字典

## Raw Table 欄位對照

| 英文欄位 | 中文說明 |
|---|---|
| seller | 出售單位 |
| facility_name | 發電設備 |
| buyer | 購買者 |
| energy_type | 能源類型 |
| supply_type | 供電種類 |
| transfer_mwh | 移轉量(MWh) |
| transaction_transfer_mwh | 成交移轉量(MWh) |
| total_transfer_mwh | 總移轉量(MWh) |
| certificate_year | 憑證發放年份 |
| transaction_date | 交易日期 / 成交日期 |
| transfer_date | 移轉日期 |
| facility_location | 發電設備地址 |
| capacity | 裝置總容量 |
| co_owner | 發電設備共用單位 |
| certificate_no | 證書編號 |
| vintage_year | 憑證發放年份 |
| transferred_mwh | 已移轉量(MWh) |
| balance_mwh | 剩餘量(MWh) |
| trec_date | T-REC最後憑證發放日期 |
| generation_period | 發電區間 |
| inspection_report | 再生能源設備查核報告 |
| verification_report | 再生能源發電量查證報告 |

## 資料流程

```text
CSV
 ↓
Raw Tables
 ↓
Dimension Tables
 ↓
Fact Tables
 ↓
Views
 ↓
Tableau / Sankey
```
