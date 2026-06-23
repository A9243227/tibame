# Step 06 - 建立 BigQuery Dimension Tables

這是第 6 步：從三張 clean tables 建立四張 dimension tables。

前置條件：

```text
Step 00 已完成：Rong_test dataset 已建立
Step 01 已完成：三個 GCS 來源檔案都找得到
Step 02 已完成：三張 raw tables 已建立
Step 03 已完成：三張 raw tables 檢查通過
Step 04 已完成：三張 clean tables 已建立
Step 05 已完成：三張 clean tables 檢查通過
```

## 1. 這一步會做什麼

這一步會建立四張 dimension tables：

```text
dim_company       公司維度表
dim_energy_type   能源類型維度表
dim_supply_type   供電種類維度表
dim_facility      發電設備維度表
```

dimension table 的用途是把 clean tables 裡重複出現的文字資料整理成主檔。

後面的 fact tables 不會直接存公司名稱或能源名稱，而是存：

```text
company_id
energy_type_id
supply_type_id
facility_id
```

這樣資料比較一致，也比較容易做查詢與分析。

## 2. 這一步會覆蓋什麼

這支程式會使用：

```sql
CREATE OR REPLACE TABLE
```

所以如果以下四張表已經存在，會被重新建立：

```text
dim_company
dim_energy_type
dim_supply_type
dim_facility
```

這是測試資料集 `Rong_test` 的流程。正式環境不能直接覆蓋，必須先確認。

## 3. Dimension Table 欄位

### dim_company / 公司維度表

來源欄位：

```text
seller      出售單位
buyer       購買者
unit_name   單位名稱
```

欄位：

```text
company_id      公司維度主鍵
company_name    公司或單位名稱
is_seller       是否出現在出售單位欄位
is_buyer        是否出現在購買者欄位
is_unit_name    是否出現在已發放憑證的單位名稱欄位
created_at      資料建立時間
```

注意：

```text
shared_company / 發電設備共用單位
```

目前保留在 clean table，不放進 `dim_company`。

### dim_energy_type / 能源類型維度表

來源欄位：

```text
energy_type     能源類型
```

欄位：

```text
energy_type_id      能源類型維度主鍵
energy_type_name    能源類型名稱
created_at          資料建立時間
```

### dim_supply_type / 供電種類維度表

來源欄位：

```text
supply_type     供電種類
```

目前只來自：

```text
trec_direct_transaction_clean
```

欄位：

```text
supply_type_id      供電種類維度主鍵
supply_type_name    供電種類名稱
created_at          資料建立時間
```

### dim_facility / 發電設備維度表

來源欄位：

```text
facility_name           發電設備
energy_type             能源類型
facility_address        發電設備地址
installed_capacity_kw   裝置總容量(kW)
```

欄位：

```text
facility_id             發電設備維度主鍵
facility_match_key      發電設備判斷鍵
facility_name           發電設備名稱
facility_address        發電設備地址
installed_capacity_kw   裝置容量(kW)
energy_type_id          能源類型維度主鍵
created_at              資料建立時間
```

## 4. 發電設備判斷規則

如果有 `facility_address / 發電設備地址`：

```text
facility_name + energy_type_id + facility_address
```

如果沒有 `facility_address / 發電設備地址`：

```text
facility_name + energy_type_id + NO_ADDRESS
```

這個組合會存成：

```text
facility_match_key / 發電設備判斷鍵
```

## 5. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/06_create_dimension_tables.py
```

重點閱讀：

```text
第 64 行開始：build_dimension_tables_sql()
```

這個函式裡面就是建立四張 dimension tables 的 SQL。

## 6. 執行第 6 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/06_create_dimension_tables.py
```

執行成功後，終端機會印出四張 dimension tables 的筆數。

執行完成後，下一步跑第 7 步檢查。
