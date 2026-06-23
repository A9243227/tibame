# Step 05 - 檢查 BigQuery Clean Tables

這是第 5 步：檢查組員建立好的三張 clean tables。

前置條件：

```text
Step 00 已完成：Rong_test dataset 已建立
Step 01 已完成：三個 GCS 來源檔案都找得到
Step 02 已完成：三張 raw tables 已建立
Step 03 已完成：三張 raw tables 檢查通過
Step 04 已完成：三張 clean tables 已建立
```

## 1. 這一步會做什麼

這一步會檢查：

```text
1. 三張 clean table 是否存在
2. 三張 clean table 的筆數
3. raw table 與 clean table 的筆數是否符合規則
4. 三張 clean table 的欄位名稱與欄位型別
5. 每張 clean table 前 5 筆資料
```

## 2. 這一步不會做什麼

這一步只查詢，不修改資料。

不會：

```text
不會建立 table
不會刪除 table
不會覆蓋資料
不會修改 GCS 檔案
```

## 3. 預期檢查重點

前兩張交易表的 raw table 與 clean table 筆數應一致：

```text
trec_direct_transaction_raw              對應 trec_direct_transaction_clean
trec_self_generation_transaction_raw      對應 trec_self_generation_transaction_clean
```

已發放憑證 clean table 會拆分 `shared_company / 發電設備共用單位`，所以 clean 筆數可以大於 raw 筆數：

```text
trec_issued_certificate_raw               對應 trec_issued_certificate_clean
```

三張 clean table 都應保留：

```text
source_raw_id / 來源 raw table 的 raw_id
```

如果一筆 raw 被拆成多筆 clean，多筆 clean 應使用相同的 `source_raw_id`。

## 4. Clean Table 欄位重點

### trec_direct_transaction_clean / 直轉供憑證成交清理表

```text
clean_id                       流水號
source_raw_id                  來源 raw table 的 raw_id
seller                         出售單位
facility_name                  發電設備
buyer                          購買者
energy_type                    能源類型
supply_type                    供電種類
total_transfer_mwh             總移轉量(MWh)，NUMERIC
transaction_date               成交日期，DATE
transaction_transfer_mwh       成交移轉量(MWh)，NUMERIC
created_at                     資料建立時間
```

### trec_self_generation_transaction_clean / 自用發電設備憑證成交清理表

```text
clean_id                       流水號
source_raw_id                  來源 raw table 的 raw_id
seller                         出售單位
facility_name                  發電設備
buyer                          購買者
energy_type                    能源類型
transfer_mwh                   移轉量(MWh)，NUMERIC
certificate_year               憑證發放年份，INTEGER
transfer_date                  移轉日期，DATE
created_at                     資料建立時間
```

### trec_issued_certificate_clean / 已發放憑證清理表

目前採用組長提供的 13 欄版本，所以沒有：

```text
certificate_year               憑證發放年份
```

目前應包含：

```text
clean_id                       流水號
source_raw_id                  來源 raw table 的 raw_id
unit_name                      單位名稱
facility_name                  發電設備
energy_type                    能源類型
facility_address               發電設備地址
installed_capacity_kw          裝置總容量(kW)，NUMERIC
shared_company                 發電設備共用單位
certificate_number             證書編號
trec_last_issue_date           T-REC 最後憑證發放日期，DATE
generation_start_date          發電區間開始日期，DATE
generation_end_date            發電區間結束日期，DATE
equipment_audit_report         再生能源設備查核報告
power_generation_verification_report 再生能源發電量查證報告
transferred_mwh                已移轉量，NUMERIC
remaining_mwh                  剩餘量，NUMERIC
created_at                     資料建立時間
```

## 5. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/05_check_clean_tables.py
```

這支程式會：

```text
1. 讀取 BigQuery/STAR0/.env.gcp
2. 連線到 BigQuery
3. 比對 raw table 與 clean table 筆數
4. 印出每張 clean table 的 schema
5. 印出每張 clean table 前 5 筆資料
```

## 6. 執行第 5 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/05_check_clean_tables.py
```

如果三張表都能印出筆數、欄位、前 5 筆資料，且 raw/clean 筆數一致，就可以進入下一步建立 dimension tables。
