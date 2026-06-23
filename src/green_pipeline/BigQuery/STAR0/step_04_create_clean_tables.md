# Step 04 - 建立 BigQuery Clean Tables

這是第 4 步：從三張 raw tables 建立三張 clean tables。

前置條件：

```text
Step 00 已完成：Rong_test dataset 已建立
Step 01 已完成：三個 GCS 來源檔案都找得到
Step 02 已完成：三張 raw tables 已建立
Step 03 已完成：三張 raw tables 檢查通過
```

## 1. 這一步會做什麼

這一步會建立三張 clean tables：

```text
Rong_test.trec_direct_transaction_clean
Rong_test.trec_self_generation_transaction_clean
Rong_test.trec_issued_certificate_clean
```

clean table 會做基本清理：

```text
空字串轉成 NULL
常見全形符號轉半形符號
日期字串轉成 DATE
MWh / kW 數字字串轉成 NUMERIC
發電區間拆成 generation_start_date / generation_end_date
保留 source_raw_id，對應來源 raw table 的 raw_id
拆分 shared_company / 發電設備共用單位
```

## 2. 這一步不會做什麼

這一步不會：

```text
不會修改 raw tables
不會修改 GCS 檔案
不會建立 dimension tables
不會建立 fact tables
不會建立 views
```

## 3. 會覆蓋同名 clean tables

這支程式使用：

```text
CREATE OR REPLACE TABLE
```

所以如果 BigQuery 裡已經有同名 clean tables，會被重建。

目前這是測試 dataset `Rong_test`，可以接受重建。

## 4. 已發放憑證欄位注意事項

目前 `trec_issued_certificate_raw` 採用組長提供的 13 欄版本，沒有：

```text
certificate_year       憑證發放年份
```

因此 `trec_issued_certificate_clean` 也不會建立 `certificate_year` 欄位。

三張 clean tables 都應保留：

```text
source_raw_id / 來源 raw table 的 raw_id
```

如果 clean ETL 把一筆 raw 拆成多筆 clean，例如 `shared_company / 發電設備共用單位` 拆分，多筆 clean 應使用同一個 `source_raw_id`。

目前拆分規則：

```text
shared_company / 發電設備共用單位 會先做符號正規化
頓號「、」會轉成逗號「,」
再用逗號「,」拆成多筆 clean rows
```

目前已發放憑證 clean table 會包含：

```text
source_raw_id
unit_name
facility_name
energy_type
facility_address
installed_capacity_kw
shared_company
certificate_number
trec_last_issue_date
generation_start_date
generation_end_date
equipment_audit_report
power_generation_verification_report
transferred_mwh
remaining_mwh
```

## 5. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/04_create_clean_tables.py
```

這支程式的主要流程：

```text
1. 讀取 BigQuery/STAR0/.env.gcp
2. 建立 BigQuery client
3. 執行 BigQuery SQL
4. 從 raw tables 建立三張 clean tables
5. 印出三張 clean tables 的筆數
```

## 6. 執行第 4 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/04_create_clean_tables.py
```

執行成功後，下一步會建立 Step 05 檢查 clean tables。
