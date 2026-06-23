# Step 09 - 檢查 BigQuery Fact Tables

這是第 9 步：檢查第 8 步建立的兩張 fact tables。

前置條件：

```text
Step 08 已完成：兩張 fact tables 已建立
```

## 1. 這一步會做什麼

這一步會檢查：

```text
1. 兩張 fact tables 是否存在
2. 兩張 fact tables 的筆數
3. 兩張 fact tables 的欄位名稱與欄位型別
4. 兩張 fact tables 前 5 筆資料
5. fact_transaction 的來源分布
6. clean table 與 fact table 的筆數是否一致
7. 主要 dimension id 是否有空值
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

`fact_transaction / 交易事實表` 應該等於兩張交易 clean table 加總：

```text
trec_direct_transaction_clean
+ trec_self_generation_transaction_clean
= fact_transaction
```

`fact_issued_certificate / 已發放憑證事實表` 目前應該等於：

```text
trec_issued_certificate_clean
```

如果筆數不同，通常代表必要欄位缺漏，或 dimension table 沒有對應到。

## 4. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/09_check_fact_tables.py
```

這支程式只檢查，不會修改 BigQuery table。

## 5. 執行第 9 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/09_check_fact_tables.py
```

執行後，把終端機輸出貼回來，我再帶你判斷是否可以進入 views。
