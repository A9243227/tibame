# Step 11 - 檢查 BigQuery Views

這是第 11 步：檢查第 10 步建立的兩張 views。

前置條件：

```text
Step 10 已完成：兩張 views 已建立
```

## 1. 這一步會做什麼

這一步會檢查：

```text
1. 兩張 views 是否可以查詢
2. view 筆數是否與對應 fact table 一致
3. view 欄位名稱與欄位型別
4. 每張 view 前 5 筆資料
5. 交易明細 view 的來源分布
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

`vw_transaction_detail / 交易明細檢視表` 筆數應該等於：

```text
fact_transaction
```

`vw_issued_certificate_detail / 已發放憑證明細檢視表` 筆數應該等於：

```text
fact_issued_certificate
```

如果 view 筆數比 fact 少，通常代表 JOIN 找不到對應的 dimension 資料。

如果 view 筆數比 fact 多，通常代表 JOIN 造成重複對應。

## 4. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/11_check_views.py
```

這支程式只檢查，不會修改 BigQuery table 或 view。

## 5. 執行第 11 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/11_check_views.py
```

執行後，把終端機輸出貼回來，我再幫你確認整個 STAR0 BigQuery 流程是否完成。
