# Step 01 - 檢查 GCS 來源檔案

這是第 1 步：確認 GCS 上的三個 CSV 來源可以被找到。

這一步只做檢查：

```text
確認三個 GCS 路徑存在
確認 wildcard 可以找到多個年份檔案
```

這一步不會：

```text
不會建立 BigQuery table
不會讀 CSV 內容
不會修改 GCS 檔案
不會刪除任何資料
```

## 1. 目前已確認的 GCS 來源

```env
GCS_DIRECT_TRANSACTION_URI=gs://playwright_trec/direct_transaction/trec_direct_transaction_raw.csv
GCS_SELF_GENERATION_TRANSACTION_URI=gs://playwright_trec_self/self_generation_transaction/trec_self_generation_transaction_raw.csv
GCS_ISSUED_CERTIFICATE_URI=gs://tibame-bronze/raw_data/certified_issued_data/trec_issued_certificate_*_raw.csv
```

第三個使用 `*` wildcard，因為已發放憑證目前是依年份分成多個 CSV：

```text
trec_issued_certificate_2020_raw.csv
trec_issued_certificate_2021_raw.csv
...
trec_issued_certificate_2026_raw.csv
```

## 2. 更新設定檔

請打開：

```text
BigQuery/STAR0/.env.gcp
```

確認除了第 0 步的三個設定外，也有下面三個 GCS 設定：

```env
GCS_DIRECT_TRANSACTION_URI=gs://playwright_trec/direct_transaction/trec_direct_transaction_raw.csv
GCS_SELF_GENERATION_TRANSACTION_URI=gs://playwright_trec_self/self_generation_transaction/trec_self_generation_transaction_raw.csv
GCS_ISSUED_CERTIFICATE_URI=gs://tibame-bronze/raw_data/certified_issued_data/trec_issued_certificate_*_raw.csv
```

完整設定範例：

```env
GCP_PROJECT_ID=tibametopics
BQ_DATASET_ID=Rong_test
BQ_LOCATION=asia-east1
GCS_DIRECT_TRANSACTION_URI=gs://playwright_trec/direct_transaction/trec_direct_transaction_raw.csv
GCS_SELF_GENERATION_TRANSACTION_URI=gs://playwright_trec_self/self_generation_transaction/trec_self_generation_transaction_raw.csv
GCS_ISSUED_CERTIFICATE_URI=gs://tibame-bronze/raw_data/certified_issued_data/trec_issued_certificate_*_raw.csv
```

## 3. 先閱讀程式

先打開：

```text
BigQuery/STAR0/Python/01_check_gcs_sources.py
```

這支程式的行為：

```text
1. 讀取 BigQuery/STAR0/.env.gcp
2. 檢查沒有 * 的 gs:// 路徑是否存在
3. 檢查有 * 的 gs:// 路徑可以匹配到哪些檔案
4. 印出找到的檔案清單
```

## 4. 執行第 1 步

如果終端機在 `BigQuery` 資料夾：

```bash
uv run python STAR0/Python/01_check_gcs_sources.py
```

## 5. 成功時會看到什麼

成功時會看到三個來源檢查結果。

直轉供交易與自用發電設備交易應各找到 1 個檔案。

已發放憑證應找到多個年份檔案，例如：

```text
trec_issued_certificate_2020_raw.csv
trec_issued_certificate_2021_raw.csv
...
trec_issued_certificate_2026_raw.csv
```

如果某個來源顯示找不到，先不要進入下一步，應回 GCS Console 確認路徑是否貼錯。
