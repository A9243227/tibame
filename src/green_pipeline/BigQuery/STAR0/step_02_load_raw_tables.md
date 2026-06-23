# Step 02 - 從 GCS 建立 BigQuery Raw Tables

這是第 2 步：把 GCS 上的 CSV 載入 BigQuery raw tables。

前置條件：

```text
Step 00 已完成：Rong_test dataset 已建立
Step 01 已完成：三個 GCS 來源檔案都找得到
```

## 1. 這一步會做什麼

這一步會建立三張 BigQuery raw tables：

```text
Rong_test.trec_direct_transaction_raw
Rong_test.trec_self_generation_transaction_raw
Rong_test.trec_issued_certificate_raw
```

資料來源：

```env
GCS_DIRECT_TRANSACTION_URI=gs://playwright_trec/direct_transaction/trec_direct_transaction_raw.csv
GCS_SELF_GENERATION_TRANSACTION_URI=gs://playwright_trec_self/self_generation_transaction/trec_self_generation_transaction_raw.csv
GCS_ISSUED_CERTIFICATE_URI=gs://tibame-bronze/raw_data/certified_issued_data/trec_issued_certificate_*_raw.csv
```

第三個來源使用 wildcard，會讀入：

```text
trec_issued_certificate_2020_raw.csv
trec_issued_certificate_2021_raw.csv
...
trec_issued_certificate_2026_raw.csv
```

## 2. 這一步不會做什麼

這一步不會：

```text
不會建立 clean tables
不會建立 dimension tables
不會建立 fact tables
不會建立 views
不會修改或刪除 GCS 上的 CSV
```

## 3. Raw Table 設計

Raw tables 的原則是：

```text
保留 CSV 原始資料樣貌
欄位先以 STRING 儲存
不要在 raw 階段做日期、數字型別轉換
```

BigQuery 沒有 MySQL 的 `AUTO_INCREMENT`，所以這一步會：

```text
1. 先把 CSV 載入 staging table
2. 再從 staging table 建立正式 raw table
3. 用 ROW_NUMBER() 產生 raw_id
4. 刪除 staging table
```

## 4.1 目前 raw CSV 欄位注意事項

直轉供憑證成交 CSV 目前是 8 欄，沒有「成交記錄原文」欄位。

因此 `trec_direct_transaction_raw` 目前欄位是：

```text
seller                         出售單位
facility_name                  發電設備
buyer                          購買者
energy_type                    能源類型
supply_type                    供電種類
total_transfer_mwh             總移轉量(MWh)
transaction_date               成交日期
transaction_transfer_mwh       成交移轉量(MWh)
```

如果未來組員的 CSV 又補回「成交記錄原文」，再另外調整 schema。

已發放憑證 CSV 目前採用組長提供的 13 欄版本，欄位順序必須和 CSV 標題列一致：

```text
unit_name                              單位名稱
facility_name                          發電設備
energy_type                            能源類型
facility_address                       發電設備地址
installed_capacity                     裝置總容量
shared_company                         發電設備共用單位
certificate_number                     證書編號
trec_last_issue_date                   T-REC 最後憑證發放日期
generation_period                      發電區間
equipment_audit_report                 再生能源設備查核報告
power_generation_verification_report   再生能源發電量查證報告
transferred_mwh                        已移轉量
remaining_mwh                          剩餘量
```

## 5. 會覆蓋同名 raw tables

這支程式使用：

```text
WRITE_TRUNCATE
CREATE OR REPLACE TABLE
```

所以如果 BigQuery 裡已經有同名 raw tables，會被重建。

目前這是測試 dataset `Rong_test`，可以接受重建。

正式 dataset 不要直接執行，必須先確認。

## 6. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/02_load_raw_tables.py
```

這支程式的主要流程：

```text
1. 讀取 BigQuery/STAR0/.env.gcp
2. 建立 BigQuery client
3. 依序處理三個 CSV 來源
4. 每個來源先載入 staging table
5. 再建立正式 raw table 並產生 raw_id
6. 印出每張 raw table 的筆數
```

## 7. 執行第 2 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/02_load_raw_tables.py
```

## 8. 成功時會看到什麼

成功時會看到三張 raw table 的建立結果，例如：

```text
已建立 raw table：tibametopics.Rong_test.trec_direct_transaction_raw，筆數：...
已建立 raw table：tibametopics.Rong_test.trec_self_generation_transaction_raw，筆數：...
已建立 raw table：tibametopics.Rong_test.trec_issued_certificate_raw，筆數：...
```

執行成功後，可以到 GCP Console 確認：

```text
BigQuery
→ Explorer
→ tibametopics
→ Rong_test
→ trec_direct_transaction_raw
→ trec_self_generation_transaction_raw
→ trec_issued_certificate_raw
```
