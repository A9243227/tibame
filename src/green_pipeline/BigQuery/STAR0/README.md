# STAR0 - BigQuery Step 0

這個資料夾用來從零開始，一步一步建立 GCP BigQuery 流程。

目前第 0 步只做一件事：

```text
建立 BigQuery dataset：Rong_test
```

這裡不使用上一版 `BigQuery/Python/` 裡已經寫好的完整 pipeline。
每一步會獨立建立一支小程式，先閱讀，再執行。

## 步驟文件

```text
README.md：第 0 步，建立 BigQuery dataset
step_01_check_gcs_sources.md：第 1 步，檢查 GCS 來源檔案
step_02_load_raw_tables.md：第 2 步，從 GCS 建立 BigQuery raw tables
step_03_check_raw_tables.md：第 3 步，檢查 BigQuery raw tables
step_04_create_clean_tables.md：第 4 步，建立 BigQuery clean tables
step_05_check_clean_tables.md：第 5 步，檢查 BigQuery clean tables
step_06_create_dimension_tables.md：第 6 步，建立 BigQuery dimension tables
step_07_check_dimension_tables.md：第 7 步，檢查 BigQuery dimension tables
step_08_create_fact_tables.md：第 8 步，建立 BigQuery fact tables
step_09_check_fact_tables.md：第 9 步，檢查 BigQuery fact tables
step_10_create_views.md：第 10 步，建立 BigQuery views
step_11_check_views.md：第 11 步，檢查 BigQuery views
```

## 0. 先理解三個設定值

第 0 步需要三個設定：

```env
GCP_PROJECT_ID=你的GCP專案ID
BQ_DATASET_ID=Rong_test
BQ_LOCATION=asia-east1
```

### GCP_PROJECT_ID 是什麼

`GCP_PROJECT_ID` 是 GCP 專案 ID。

它告訴 Python 程式：

```text
我要在哪一個 GCP 專案裡建立 BigQuery dataset？
```

注意：要填的是 **Project ID**，不是 Project name。

Project name 可能是人類好讀的名稱，例如：

```text
Green Energy Project
```

Project ID 通常比較像：

```text
tibame-green-energy-123456
airy-caster-428901
```

### BQ_DATASET_ID 是什麼

`BQ_DATASET_ID` 是 BigQuery 資料集名稱。

這次組長要求測試用你的名字加 test，所以我們填：

```env
BQ_DATASET_ID=Rong_test
```

建立完成後，BigQuery 會看到：

```text
Project
└── Rong_test
```

### BQ_LOCATION 是什麼

`BQ_LOCATION` 是 BigQuery dataset 的地區。

它告訴 BigQuery：

```text
Rong_test 這個 dataset 要建立在哪個資料中心區域？
```

目前先使用：

```env
BQ_LOCATION=asia-east1
```

`asia-east1` 是台灣區域。BigQuery dataset 建立後，location 不能修改。

## 1. 到 GCP Console 找 Project ID

打開 GCP Console：

```text
https://console.cloud.google.com/
```

左上角會看到目前選擇的專案。

操作路徑：

```text
GCP Console 左上角專案選擇器
→ 點目前專案
→ 找 Project ID
```

你要複製的是 Project ID，例如：

```text
tibame-green-energy-123456
```

不是 Project name。

## 2. 確認 BigQuery Location

如果組長已經指定 location，就照組長指定的填。

如果組長沒有指定，先用：

```env
BQ_LOCATION=asia-east1
```

如果你想確認既有 dataset 的 location：

```text
GCP Console
→ 搜尋 BigQuery
→ 進入 BigQuery
→ 左側 Explorer 點一個既有 dataset
→ Details
→ Location
```

注意：如果既有正式 dataset 不是 `asia-east1`，測試 dataset 最好跟正式 dataset 用同一個 location。

## 3. 建立設定檔

先複製範例設定：

```bash
cp BigQuery/STAR0/.env.gcp.example BigQuery/STAR0/.env.gcp
```

然後修改：

```env
GCP_PROJECT_ID=你剛剛查到的Project ID
BQ_DATASET_ID=Rong_test
BQ_LOCATION=asia-east1
```

實際範例：

```env
GCP_PROJECT_ID=tibame-green-energy-123456
BQ_DATASET_ID=Rong_test
BQ_LOCATION=asia-east1
```

如果你不確定 Project ID，不要猜。先回 GCP Console 左上角專案選擇器確認。

## 4. 先閱讀程式

先打開這支程式閱讀：

```text
BigQuery/STAR0/Python/00_create_dataset.py
```

這支程式的行為：

```text
1. 讀取 BigQuery/STAR0/.env.gcp
2. 取得 GCP_PROJECT_ID、BQ_DATASET_ID、BQ_LOCATION
3. 連線到 BigQuery
4. 建立 Rong_test dataset
5. 如果 Rong_test 已存在，就視為成功，不重複建立
```

它不會做這些事：

```text
不會讀 GCS
不會建立 raw table
不會建立 clean table
不會建立 dimension / fact / view
不會刪除任何資料
```

## 5. 執行第 0 步

在專案根目錄執行：

```bash
uv run python BigQuery/STAR0/Python/00_create_dataset.py
```

這支程式只會建立 dataset，不會建立 raw table，也不會讀 GCS。

## 6. 成功時會看到什麼

終端機應該會印出類似：

```text
============================================================
BigQuery dataset 已確認
Project ID：tibame-green-energy-123456
Dataset ID：Rong_test
Location：asia-east1
============================================================
```

如果出現這段，表示程式已經成功確認或建立 dataset。

## 7. 到 GCP Console 確認結果

執行成功後，到 GCP Console 的 BigQuery Explorer 應該會看到：

```text
你的 GCP project
└── Rong_test
```

操作路徑：

```text
GCP Console
→ 搜尋 BigQuery
→ 進入 BigQuery
→ 左側 Explorer
→ 展開你的 Project
→ 找 Rong_test
```

## 8. 常見錯誤

### 找不到 .env.gcp

可能原因：

```text
你還沒有複製 .env.gcp.example
```

處理方式：

```bash
cp BigQuery/STAR0/.env.gcp.example BigQuery/STAR0/.env.gcp
```

### 請先設定 GCP_PROJECT_ID

可能原因：

```text
BigQuery/STAR0/.env.gcp 裡的 GCP_PROJECT_ID 還是空的或沒有改
```

處理方式：

```text
回 GCP Console 左上角專案選擇器複製 Project ID
填入 GCP_PROJECT_ID=
```

### 權限不足

可能原因：

```text
你的 Google 帳號沒有建立 BigQuery dataset 的權限
```

需要請組長或 GCP 管理者確認你是否有類似權限：

```text
BigQuery Job User
BigQuery Data Editor
BigQuery Admin 或可以建立 dataset 的權限
```

### Location 填錯

BigQuery dataset 建立後不能改 location。

如果你填錯 location，測試 dataset 可能需要刪掉重建。正式環境不要自己刪，先問組長。
