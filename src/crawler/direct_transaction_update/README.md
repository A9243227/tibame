# T-REC 直轉供交易資料自動化：最終 GCS 路徑版

本專案在 Cloud Run Job 執行，抓取 T-REC 直轉供資料、補抓真正失敗資料、依固定 8 欄去重，並保存年度 raw、完整 all_year、去重歷史版本、最新 BigQuery 資料與 dedup report。

```text
Cloud Run Job
↓
04 主流程：01 →（本次 failed 有資料才）02 → 03
↓
GCS
```

`/tmp` 只是在 Cloud Run 執行中的暫存位置；Job 結束後，正式資料以 GCS 為準。

---

# 1. 五支程式的責任

| 檔案 | 工作內容 |
|---|---|
| `01_crawl_direct_transaction_raw.py` | 抓取年度 raw、重建 all_year、寫入 failed 與 status。 |
| `02_retry_direct_transaction_failed.py` | 補抓本次 failed 或歷史 failed_retry，成功資料補進年度 raw 後重建 all_year。 |
| `03_etl_direct_transaction_deduplicate.py` | 讀取 all_year，以固定 8 欄去重；發布歷史去重資料、最新 BigQuery 去重資料、dedup report。 |
| `04_run_direct_transaction_pipeline.py` | 主流程：`01 → 02（有本次 failed 才執行）→ 03`。 |
| `05_run_direct_transaction_retry_pipeline.py` | Retry-only：`02（只讀 failed_retry）→ 03`；不重新抓全部主資料。 |

---

# 2. 最終 GCS 路徑

Bucket：

```text
gs://tibame-bronze/
```

```text
gs://tibame-bronze/
│
├─ direct_transaction/
│  │
│  ├─ raw/
│  │  └─ dt=YYYY-MM-DD/
│  │     ├─ trec_direct_transaction_raw_2017_YYYYMMDD.csv
│  │     ├─ trec_direct_transaction_raw_2018_YYYYMMDD.csv
│  │     ├─ ...
│  │     ├─ trec_direct_transaction_raw_2026_YYYYMMDD.csv
│  │     └─ trec_direct_transaction_raw_all_year_YYYYMMDD.csv
│  │
│  ├─ audit/
│  │  └─ dt=YYYY-MM-DD/
│  │     └─ trec_direct_transaction_dedup_report_YYYYMMDD.csv
│  │
│  └─ control/
│     ├─ trec_direct_transaction_raw_failed.csv
│     ├─ trec_direct_transaction_raw_failed_retry.csv
│     └─ trec_direct_transaction_raw_status.csv
│
├─ old_raw_data/
│  └─ playwright_trec/
│     └─ dt=YYYY-MM-DD/
│        └─ trec_direct_transaction_raw.csv
│
└─ new_raw_data/
   └─ playwright_trec/
      └─ trec_direct_transaction_raw.csv
```

## 2.1 每個位置放什麼

| 位置 | 內容 | 是否去重 | 用途 |
|---|---|---:|---|
| `direct_transaction/raw/dt=.../年度檔` | 單一年份的爬蟲資料 | 否 | 日後只更新某一年、retry 補資料、重建 all_year 的基礎。 |
| `direct_transaction/raw/dt=.../all_year` | 各年度 raw 合併資料 | 否 | 03 的輸入。 |
| `direct_transaction/audit/dt=.../` | dedup report | 報表 | 檢查原始筆數、去重後筆數、刪除重複筆數與重複明細。 |
| `direct_transaction/control/` | failed、failed_retry、status | 控制檔 | 下一次爬蟲／retry 仍需讀取。 |
| `old_raw_data/playwright_trec/dt=.../` | 本次 03 去重後的歷史版本 | 是 | 保留每次執行的去重結果。 |
| `new_raw_data/playwright_trec/` | 最新 03 去重後結果 | 是 | BigQuery 固定讀取的最新正式 CSV。 |

**重要：**

```text
new_raw_data/playwright_trec/trec_direct_transaction_raw.csv
= 已去重資料
= BigQuery 固定讀取資料
```

不是未去重 raw。

---

# 3. 直轉供固定 8 欄去重規則

03 只有在下列 8 欄全部相同時，才視為重複，保留第一次出現資料：

```text
出售單位
發電設備
購買者
能源類型
供電種類
總移轉量(MWh)
成交日期
成交移轉量(MWh)
```

去重報表會記錄：

```text
原始資料筆數
去重後資料筆數
實際刪除重複列數
重複群組數
每個重複群組的出現次數
每個群組刪除重複筆數
8 欄重複資料明細
```

---

# 4. 主流程 04

```text
04
↓
01：抓取年度 raw、重建 all_year
↓
本次 failed.csv 有資料？
├─ 有：02 補抓本次 failed.csv
└─ 沒有：略過 02
↓
03：去重、寫 old_raw_data、new_raw_data、audit
```

04 一開始會固定同一次流程使用同一個 `PIPELINE_DT`，例如：

```text
PIPELINE_DT=2026-07-03
```

這樣即使流程跨午夜，01、02、03 仍會寫到同一個 `dt=2026-07-03`。

04 也會強制移除 `FAILED_CSV_FILE`，確保主流程的 02 只讀本次 01 剛產生的 `failed.csv`，不會誤讀歷史 `failed_retry.csv`。

---

# 5. Retry-only 流程 05

```text
05
↓
02：只讀 control/failed_retry.csv
↓
03：重建去重結果、發布 old_raw_data/new_raw_data/audit
```

05 不會執行 01，也不會重新抓全部年度主資料。

若 05 啟動時 `/tmp` 沒有本次 raw，02 會：

```text
找到 direct_transaction/raw/ 下最新可用 dt 快照
↓
複製每年度 raw 到 /tmp，並改成本次 PIPELINE_DT 檔名
↓
建立新的 raw/dt=本次日期/ 快照
↓
補抓 failed_retry 成功資料
↓
03 去重並重新發布
```

因此 Retry-only 不會直接修改舊的 `raw/dt=.../` 快照。

---

# 6. 首次正式執行與部分年度更新

## 第一次建立此架構

第一次在這套路徑執行時，請使用：

```text
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
```

因為 01 需要先建立完整的 2017～2026 年度 raw 快照。

## 之後只更新 2026

```text
YEARS_TO_CRAWL=2026
MAX_PAGES_PER_YEAR=0
```

01 會：

```text
找到 raw/ 下最新快照
↓
沿用舊的 2017～2025 年度 raw
↓
重新抓新的 2026 年度 raw
↓
建立本次新的完整 raw/dt=.../ 年度快照與 all_year
```

所以本次的 `raw/dt=.../` 仍包含所有年度，不會只剩 2026。

---

# 7. failed、failed_retry、status

| 檔案 | 位置 | 規則 |
|---|---|---|
| `trec_direct_transaction_raw_failed.csv` | `direct_transaction/control/` | 本次 01 的失敗清單；每次 01 開始重設。主流程 04 的 02 只處理它。 |
| `trec_direct_transaction_raw_failed_retry.csv` | `direct_transaction/control/` | 已 retry 但仍失敗的歷史 backlog；05 才處理。 |
| `trec_direct_transaction_raw_status.csv` | `direct_transaction/control/` | 「目前沒有資料」歷史紀錄；append 保留。 |

直轉供 detail API 的成交記錄 `<ol></ol>` 空白，是正常「沒有成交紀錄」，不是 failed，不需要 retry。

---

# 8. Cloud Run 環境變數

## 8.1 所有 Job 基本設定

```text
LOCAL_WORKDIR=/tmp
GCS_BUCKET=tibame-bronze
GCS_PREFIX=direct_transaction
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec
PIPELINE_TIMEZONE=Asia/Taipei
HEADLESS=true
API_BASE_YEAR=2026
```

`HISTORICAL_DEDUP_PREFIX` 與 `LATEST_DEDUP_PREFIX` 不設定也可；03 程式的預設值就是上述兩個位置。明確設定可以讓 Cloud Run Job 設定更容易檢查。

## 8.2 主資料抓取設定

```text
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
SAVE_EVERY_PAGES=10
PAGE_LENGTH=10
API_TIMEOUT_MS=30000
YEAR_CHANGE_WAIT_SECONDS=2
DATA_API_SLEEP_SECONDS=2
DETAIL_API_SLEEP_SECONDS=1
DATA_API_RETRY_MAX=3
DETAIL_API_RETRY_MAX=3
API_RETRY_SLEEP_SECONDS=3
```

`search[year]` 才是實際資料篩選年份；`API_BASE_YEAR` 是目前網站 Payload 中的基準 `year` 參數。

---

# 9. 部署前測試

請先使用獨立測試 Prefix，避免有限頁數測試成為正式年度快照：

```text
GCS_PREFIX=direct_transaction_test
YEARS_TO_CRAWL=2026
MAX_PAGES_PER_YEAR=2
SAVE_EVERY_PAGES=1
```

同時，測試 03 的去重發布位置時，請改成獨立位置：

```text
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec_test
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec_test
```

確認會出現：

```text
direct_transaction_test/raw/dt=YYYY-MM-DD/
direct_transaction_test/audit/dt=YYYY-MM-DD/
direct_transaction_test/control/
old_raw_data/playwright_trec_test/dt=YYYY-MM-DD/trec_direct_transaction_raw.csv
new_raw_data/playwright_trec_test/trec_direct_transaction_raw.csv
```

正式執行前改回：

```text
GCS_PREFIX=direct_transaction
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
```

---

# 10. Dockerfile 與 requirements

`Dockerfile` 預設執行：

```dockerfile
CMD ["python", "-u", "04_run_direct_transaction_pipeline.py"]
```

這次 GCS 最終路徑版只修改：

```text
01：預設 GCS_PREFIX
02：預設 GCS_PREFIX
03：去重後歷史資料／最新 BigQuery 資料的發布位置
04：GCS 輸出摘要
05：Retry-only 說明
README
```

`Dockerfile` 與 `requirements.txt` 不需要改內容，但因為 Python 檔案已改，仍需要重新 build image 再 deploy Cloud Run Job。
