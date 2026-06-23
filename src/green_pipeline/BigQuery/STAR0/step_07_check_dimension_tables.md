# Step 07 - 檢查 BigQuery Dimension Tables

這是第 7 步：檢查第 6 步建立的四張 dimension tables。

前置條件：

```text
Step 06 已完成：四張 dimension tables 已建立
```

## 1. 這一步會做什麼

這一步會檢查：

```text
1. 四張 dimension tables 是否存在
2. 每張 dimension table 的筆數
3. 每張 dimension table 的欄位名稱與欄位型別
4. 每張 dimension table 前 5 筆資料
5. 應該唯一的欄位是否有重複
6. dim_facility 的 energy_type_id 是否能對應到 dim_energy_type
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

## 3. 唯一值檢查

每張表會檢查一個應該唯一的欄位：

```text
dim_company       company_name        公司或單位名稱
dim_energy_type   energy_type_name    能源類型名稱
dim_supply_type   supply_type_name    供電種類名稱
dim_facility      facility_match_key  發電設備判斷鍵
```

如果有重複，代表 dimension table 沒有正確去重。

## 4. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/07_check_dimension_tables.py
```

這支程式只檢查，不會修改 BigQuery table。

## 5. 執行第 7 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/07_check_dimension_tables.py
```

執行後，把終端機輸出貼回來，我再帶你判斷是否可以進入 fact tables。
