# Step 10 - 建立 BigQuery Views

這是第 10 步：建立兩張閱讀用 views。

前置條件：

```text
Step 08 已完成：兩張 fact tables 已建立
Step 09 已完成：兩張 fact tables 檢查通過
```

## 1. 這一步會做什麼

這一步會建立兩張 views：

```text
vw_transaction_detail             交易明細檢視表
vw_issued_certificate_detail      已發放憑證明細檢視表
```

view 的用途是把 fact table 裡的 id 轉回人看得懂的名稱。

例如：

```text
seller_company_id 轉成 seller_company_name
facility_id       轉成 facility_name
energy_type_id    轉成 energy_type_name
```

## 2. 這一步會覆蓋什麼

這支程式會使用：

```sql
CREATE OR REPLACE VIEW
```

所以如果以下兩張 view 已經存在，會被重新建立：

```text
vw_transaction_detail
vw_issued_certificate_detail
```

這是測試資料集 `Rong_test` 的流程。正式環境不能直接覆蓋，必須先確認。

## 3. vw_transaction_detail / 交易明細檢視表

來源：

```text
fact_transaction
dim_company
dim_facility
dim_energy_type
dim_supply_type
```

欄位：

```text
transaction_id              交易事實表主鍵
source_table                來源 clean table 名稱
source_raw_id               來源 raw table 的 raw_id
source_clean_id             來源 clean table 的 clean_id
transaction_source_type     交易來源類型
transaction_source_name     交易來源中文名稱
seller_company_name         出售單位名稱
buyer_company_name          購買者名稱
facility_name               發電設備名稱
energy_type_name            能源類型名稱
supply_type_name            供電種類名稱
certificate_year            憑證發放年份
transaction_date            交易或移轉日期
transaction_mwh             交易或移轉量(MWh)
total_transfer_mwh          總移轉量(MWh)
created_at                  資料建立時間
```

注意：

這張 view 不顯示 `facility_address / 發電設備地址` 與 `installed_capacity_kw / 裝置容量(kW)`。

原因是兩張交易來源 clean table 沒有地址與容量欄位，避免讓使用者誤以為交易資料本身有提供這些資訊。

## 4. vw_issued_certificate_detail / 已發放憑證明細檢視表

來源：

```text
fact_issued_certificate
dim_company
dim_facility
dim_energy_type
```

欄位：

```text
issued_certificate_id                    已發放憑證事實表主鍵
source_raw_id                            來源 raw table 的 raw_id
source_clean_id                          來源 clean table 的 clean_id
unit_company_name                        單位名稱
facility_name                            發電設備名稱
facility_address                         發電設備地址
installed_capacity_kw                    裝置容量(kW)
energy_type_name                         能源類型名稱
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

## 5. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/10_create_views.py
```

重點閱讀：

```text
第 57 行開始：build_views_sql()
```

## 6. 執行第 10 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/10_create_views.py
```

執行完成後，下一步跑第 11 步檢查。
