# Step 08 - 建立 BigQuery Fact Tables

這是第 8 步：從 clean tables 與 dimension tables 建立兩張 fact tables。

前置條件：

```text
Step 06 已完成：四張 dimension tables 已建立
Step 07 已完成：四張 dimension tables 檢查通過
```

## 1. 這一步會做什麼

這一步會建立兩張 fact tables：

```text
fact_transaction          交易事實表
fact_issued_certificate   已發放憑證事實表
```

fact table 會儲存主要分析資料，並用 id 對應 dimension tables。

例如不直接重複存公司名稱，而是存：

```text
seller_company_id
buyer_company_id
unit_company_id
facility_id
energy_type_id
supply_type_id
```

## 2. 這一步會覆蓋什麼

這支程式會使用：

```sql
CREATE OR REPLACE TABLE
```

所以如果以下兩張表已經存在，會被重新建立：

```text
fact_transaction
fact_issued_certificate
```

這是測試資料集 `Rong_test` 的流程。正式環境不能直接覆蓋，必須先確認。

## 3. fact_transaction / 交易事實表

來源：

```text
trec_direct_transaction_clean
trec_self_generation_transaction_clean
```

欄位：

```text
transaction_id             交易事實表主鍵
source_table               來源 clean table 名稱
source_raw_id              來源 raw table 的 raw_id
source_clean_id            來源 clean table 的 clean_id
transaction_source_type    交易來源類型
seller_company_id          出售單位公司維度主鍵
buyer_company_id           購買者公司維度主鍵
facility_id                發電設備維度主鍵
energy_type_id             能源類型維度主鍵
supply_type_id             供電種類維度主鍵
certificate_year           憑證發放年份
transaction_date           交易或移轉日期
transaction_mwh            交易或移轉量(MWh)
total_transfer_mwh         總移轉量(MWh)
created_at                 資料建立時間
```

交易來源類型：

```text
direct_transaction             直轉供憑證成交
self_generation_transaction    自用發電設備憑證成交
```

## 4. fact_issued_certificate / 已發放憑證事實表

來源：

```text
trec_issued_certificate_clean
```

欄位：

```text
issued_certificate_id                    已發放憑證事實表主鍵
source_raw_id                            來源 raw table 的 raw_id
source_clean_id                          來源 clean table 的 clean_id
unit_company_id                          單位名稱公司維度主鍵
facility_id                              發電設備維度主鍵
energy_type_id                           能源類型維度主鍵
shared_company                           發電設備共用單位
certificate_number                       證書編號
trec_last_issue_date                     T-REC 最後憑證發放日期
generation_start_date                    發電區間開始日期
generation_end_date                      發電區間結束日期
transferred_mwh                          已移轉量
remaining_mwh                            剩餘量
equipment_audit_report                   再生能源設備查核報告
power_generation_verification_report     再生能源發電量查證報告
created_at                               資料建立時間
```

注意：

因為第 4 步 clean table 已經把 `shared_company / 發電設備共用單位` 拆分，所以這張 fact table 會保留：

```text
source_clean_id
shared_company
```

這樣才能追蹤一筆 raw 被拆成多筆 clean / fact 的情況。

## 5. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/08_create_fact_tables.py
```

重點閱讀：

```text
第 57 行開始：build_fact_tables_sql()
```

## 6. 執行第 8 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/08_create_fact_tables.py
```

執行完成後，下一步跑第 9 步檢查。
