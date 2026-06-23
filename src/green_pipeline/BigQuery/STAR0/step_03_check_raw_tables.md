# Step 03 - 檢查 BigQuery Raw Tables

這是第 3 步：檢查 Step 02 建好的三張 raw tables。

前置條件：

```text
Step 00 已完成：Rong_test dataset 已建立
Step 01 已完成：三個 GCS 來源檔案都找得到
Step 02 已完成：三張 raw tables 已建立
```

## 1. 這一步會做什麼

這一步會檢查：

```text
1. 三張 raw table 是否存在
2. 三張 raw table 的筆數
3. 三張 raw table 的欄位名稱與欄位型別
4. 每張 raw table 前 5 筆資料
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

## 3. 目前預期筆數

Step 02 成功時得到的筆數：

```text
trec_direct_transaction_raw              9605 筆
trec_self_generation_transaction_raw      461 筆
trec_issued_certificate_raw             15364 筆
```

如果 Step 03 查到的筆數不同，代表 raw table 可能被重新載入過，或 GCS 來源資料有更新。

## 4. 目前 raw table 欄位

### trec_direct_transaction_raw / 直轉供憑證成交

```text
raw_id                         流水號
seller                         出售單位
facility_name                  發電設備
buyer                          購買者
energy_type                    能源類型
supply_type                    供電種類
total_transfer_mwh             總移轉量(MWh)
transaction_date               成交日期
transaction_transfer_mwh       成交移轉量(MWh)
created_at                     資料建立時間
```

### trec_self_generation_transaction_raw / 自用發電設備憑證成交

```text
raw_id                         流水號
seller                         出售單位
facility_name                  發電設備
buyer                          購買者
energy_type                    能源類型
transfer_mwh                   移轉量(MWh)
certificate_year               憑證發放年份
transfer_date                  移轉日期
created_at                     資料建立時間
```

### trec_issued_certificate_raw / 已發放憑證

組長目前指定使用 13 欄版本。

```text
raw_id                         流水號
unit_name                      單位名稱
facility_name                  發電設備
energy_type                    能源類型
facility_address               發電設備地址
installed_capacity             裝置總容量
shared_company                 發電設備共用單位
certificate_number             證書編號
trec_last_issue_date           T-REC 最後憑證發放日期
generation_period              發電區間
equipment_audit_report         再生能源設備查核報告
power_generation_verification_report 再生能源發電量查證報告
transferred_mwh                已移轉量
remaining_mwh                  剩餘量
created_at                     資料建立時間
```

## 5. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/03_check_raw_tables.py
```

這支程式會：

```text
1. 讀取 BigQuery/STAR0/.env.gcp
2. 連線到 BigQuery
3. 查詢三張 raw tables 的 row count
4. 印出每張 raw table 的 schema
5. 印出每張 raw table 前 5 筆資料
```

## 6. 執行第 3 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/03_check_raw_tables.py
```

如果執行結果中三張表都能印出筆數、欄位、前 5 筆資料，就表示 raw tables 基本檢查通過。
