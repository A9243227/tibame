# T-REC 自用發電設備憑證成交紀錄：最終 GCS 路徑版

本專案在 Cloud Run Job 執行，抓取 T-REC 自用發電設備憑證成交資料、補抓真正失敗資料、依固定 7 欄去重，並保存年度 raw、完整 all_year、去重歷史版本、最新 BigQuery 資料與 dedup report。

```text
Cloud Run Job
↓
04 主流程：01 →（本次 failed 有資料才）02 → 03
↓
GCS
```

`/tmp` 只是 Cloud Run 執行中的暫存位置；Job 結束後，正式資料以 GCS 為準。

---

# 1. 自用發電自己的資料邏輯

自用發電只有一個 DataTables `data API`，不使用直轉供的 detail API。

```text
一筆 data API item
↓
一筆自用發電交易資料 CSV
```

固定 7 欄：

```text
出售單位
發電設備
購買者
能源類型
移轉量(MWh)
憑證發放年份
移轉日期
```

| CSV 欄位 | API 欄位 | 說明 |
|---|---|---|
| 出售單位 | `seller_name` 第一行 | 出售公司名稱 |
| 發電設備 | `case_name` | 發電設備／案件名稱 |
| 購買者 | `buyer_name` | 購買單位 |
| 能源類型 | `energy` | 能源類型 |
| 移轉量(MWh) | `power` | 移轉量 |
| 憑證發放年份 | `certification_year` | 憑證發放年份 |
| 移轉日期 | `created_at` | 資料建立／移轉日期 |

自用發電不會使用直轉供的 detail API、成交記錄 `<ol>`、供電種類、總移轉量或成交移轉量欄位。

---

# 2. 保留的年份驗證防呆

`01` 與 `02` 都保留 `validate_response_year()`。

```text
要求抓 2025
↓
Payload：search[year]=2025
↓
API 回傳 data
↓
確認每一筆 certification_year 都是 2025
↓
才可寫入 2025 年度 raw
```

若 API 回傳資料年度不一致：

```text
請求 2025
但回傳 2026
↓
不寫入 raw
↓
記入 failed
↓
由 02 retry
```

這個自用發電的防呆功能保留，沒有因為 GCS 路徑調整而移除。

---

# 3. `API_BASE_YEAR` 保持原本寫法

程式仍保留：

```python
API_BASE_YEAR = os.getenv("API_BASE_YEAR", str(datetime.now().year)).strip()
```

Cloud Run 目前請明確設定：

```text
API_BASE_YEAR=2026
```

真正決定抓取資料年度的是：

```text
YEARS_TO_CRAWL=2025
↓
search[year]=2025
```

`API_BASE_YEAR` 對應 Payload 裡的基準欄位：

```text
year=2026
```

---

# 4. 五支程式的責任

| 檔案 | 工作內容 |
|---|---|
| `01_crawl_self_generation_transaction_raw.py` | 抓取年度 raw、重建 all_year、寫入 failed 與 status。 |
| `02_retry_self_generation_transaction_failed.py` | 補抓本次 failed 或歷史 failed_retry，成功資料補進年度 raw 後重建 all_year。 |
| `03_etl_self_generation_transaction_deduplicate.py` | 讀取 all_year，以固定 7 欄去重；發布歷史去重資料、最新 BigQuery 去重資料、dedup report。 |
| `04_run_self_generation_transaction_pipeline.py` | 主流程：`01 → 02（有本次 failed 才執行）→ 03`。 |
| `05_run_self_generation_transaction_retry_pipeline.py` | Retry-only：`02（只讀 failed_retry）→ 03`；不重新抓全部主資料。 |

---

# 5. 最終 GCS 路徑

Bucket：

```text
gs://tibame-bronze/
```

```text
gs://tibame-bronze/
│
├─ self_generation_transaction/
│  │
│  ├─ raw/
│  │  └─ dt=YYYY-MM-DD/
│  │     ├─ trec_self_generation_transaction_raw_2017_YYYYMMDD.csv
│  │     ├─ trec_self_generation_transaction_raw_2018_YYYYMMDD.csv
│  │     ├─ ...
│  │     ├─ trec_self_generation_transaction_raw_2026_YYYYMMDD.csv
│  │     └─ trec_self_generation_transaction_raw_all_year_YYYYMMDD.csv
│  │
│  ├─ audit/
│  │  └─ dt=YYYY-MM-DD/
│  │     └─ trec_self_generation_transaction_dedup_report_YYYYMMDD.csv
│  │
│  └─ control/
│     ├─ trec_self_generation_transaction_raw_failed.csv
│     ├─ trec_self_generation_transaction_raw_failed_retry.csv
│     └─ trec_self_generation_transaction_raw_status.csv
│
├─ old_raw_data/
│  └─ playwright_trec_self/
│     └─ dt=YYYY-MM-DD/
│        └─ trec_self_generation_transaction_raw.csv
│
└─ new_raw_data/
   └─ playwright_trec_self/
      └─ trec_self_generation_transaction_raw.csv
```

## 5.1 每個位置放什麼

| 位置 | 內容 | 是否去重 | 用途 |
|---|---|---:|---|
| `self_generation_transaction/raw/dt=.../年度檔` | 單一年份爬蟲資料 | 否 | 日後只更新某一年、retry 補資料、重建 all_year 的基礎。 |
| `self_generation_transaction/raw/dt=.../all_year` | 各年度 raw 合併資料 | 否 | 03 的輸入。 |
| `self_generation_transaction/audit/dt=.../` | dedup report | 報表 | 檢查原始筆數、去重後筆數、刪除重複筆數與重複明細。 |
| `self_generation_transaction/control/` | failed、failed_retry、status | 控制檔 | 下一次爬蟲／retry 仍需讀取。 |
| `old_raw_data/playwright_trec_self/dt=.../` | 本次 03 去重後的歷史版本 | 是 | 保留每次執行的去重結果。 |
| `new_raw_data/playwright_trec_self/` | 最新 03 去重後結果 | 是 | BigQuery 固定讀取的最新正式 CSV。 |

重要：

```text
new_raw_data/playwright_trec_self/
trec_self_generation_transaction_raw.csv
= 已去重資料
= BigQuery 固定讀取資料
```

不是未去重 raw。

---

# 6. 自用發電固定 7 欄去重規則

03 只有在下列 7 欄全部相同時，才視為重複，保留第一次出現資料：

```text
出售單位
發電設備
購買者
能源類型
移轉量(MWh)
憑證發放年份
移轉日期
```

去重報表會記錄：

```text
原始資料筆數
去重後資料筆數
實際刪除重複列數
重複群組數
每個重複群組的出現次數
每個群組刪除重複筆數
7 欄重複資料明細
```

---

# 7. 主流程 04

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

04 會固定同一次流程使用同一個 `PIPELINE_DT`。即使流程跨午夜，01、02、03 仍會寫到同一個 `dt=YYYY-MM-DD`。

04 也會移除 `FAILED_CSV_FILE`，確保主流程 02 只讀本次 01 產生的 `failed.csv`，不會誤讀歷史 `failed_retry.csv`。

---

# 8. Retry-only 流程 05

```text
05
↓
02：只讀 control/failed_retry.csv
↓
03：重建去重結果、發布 old_raw_data/new_raw_data/audit
```

05 不執行 01，不會重新抓完整年度主資料。

若 05 啟動時 `/tmp` 沒有本次 raw，02 會：

```text
找到 self_generation_transaction/raw/ 下最新可用 dt 快照
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

# 9. failed、failed_retry、status

| 檔案 | 位置 | 規則 |
|---|---|---|
| `trec_self_generation_transaction_raw_failed.csv` | `self_generation_transaction/control/` | 本次 01 的失敗清單；每次 01 開始重設。主流程 04 的 02 只處理它。 |
| `trec_self_generation_transaction_raw_failed_retry.csv` | `self_generation_transaction/control/` | 已 retry 但仍失敗的歷史 backlog；05 才處理。 |
| `trec_self_generation_transaction_raw_status.csv` | `self_generation_transaction/control/` | 「目前沒有資料」歷史紀錄；append 保留。 |

---

# 10. Cloud Run 環境變數

所有 Job：

```text
LOCAL_WORKDIR=/tmp
GCS_BUCKET=tibame-bronze
GCS_PREFIX=self_generation_transaction
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec_self
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec_self
PIPELINE_TIMEZONE=Asia/Taipei
HEADLESS=true
API_BASE_YEAR=2026
```

`HISTORICAL_DEDUP_PREFIX` 與 `LATEST_DEDUP_PREFIX` 不設定也可；03 程式的預設值就是上述位置。明確設定可以讓 Cloud Run Job 設定更容易檢查。

主資料 Job：

```text
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
PAGE_LENGTH=10
SAVE_EVERY_PAGES=10
API_TIMEOUT_MS=30000
DATA_API_SLEEP_SECONDS=1
DATA_API_RETRY_MAX=3
API_RETRY_SLEEP_SECONDS=3
```

Retry-only Job 不需要 `YEARS_TO_CRAWL`。

不要在 Cloud Run Job 固定設定 `FAILED_CSV_FILE`：04 會清掉它，05 才會自行指定歷史 `failed_retry.csv`。

---

# 11. 第一次正式執行與部分年度更新

第一次建立這套路徑時，請使用：

```text
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
```

因為 01 需要先建立完整的年度 raw 快照。

日後只更新 2026：

```text
YEARS_TO_CRAWL=2026
MAX_PAGES_PER_YEAR=0
```

01 會：

```text
找到 raw/ 下最新快照
↓
沿用舊的其他年度 raw
↓
重新抓新的 2026 年度 raw
↓
建立本次新的完整 raw/dt=.../ 年度快照與 all_year
```

本次新快照仍會包含所有年度，不會只剩 2026。

---

# 12. 建置與部署

Dockerfile 預設執行：

```text
04_run_self_generation_transaction_pipeline.py
```

在包含 Dockerfile、01～05、README、requirements.txt 的資料夾開 PowerShell：

```powershell
$PROJECT_ID = "tibametopics"
$REGION = "asia-east1"
$IMAGE = "asia-east1-docker.pkg.dev/tibametopics/playwright-trec-self/self-generation-transaction:latest"

gcloud.cmd builds submit --tag $IMAGE .
```

主資料 Job 部署的核心環境變數應包含：

```text
GCS_BUCKET=tibame-bronze
GCS_PREFIX=self_generation_transaction
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec_self
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec_self
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
API_BASE_YEAR=2026
```

Retry-only Job 使用同一 image，將 command 改為：

```text
python -u 05_run_self_generation_transaction_retry_pipeline.py
```

主 Job 與 Retry-only Job 不要同時執行，因為兩者都會寫同一套 raw、control、old_raw_data、new_raw_data 與 audit 路徑。

---

# 13. 測試建議

先使用正式 Bucket 的測試根目錄：

```text
GCS_BUCKET=tibame-bronze
GCS_PREFIX=self_generation_transaction_test
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec_self_test
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec_self_test
YEARS_TO_CRAWL=2026
MAX_PAGES_PER_YEAR=2
SAVE_EVERY_PAGES=1
```

確認有：

```text
self_generation_transaction_test/raw/dt=YYYY-MM-DD/
self_generation_transaction_test/audit/dt=YYYY-MM-DD/
self_generation_transaction_test/control/
old_raw_data/playwright_trec_self_test/dt=YYYY-MM-DD/
new_raw_data/playwright_trec_self_test/
```

測試成功後，才改回正式：

```text
GCS_BUCKET=tibame-bronze
GCS_PREFIX=self_generation_transaction
HISTORICAL_DEDUP_PREFIX=old_raw_data/playwright_trec_self
LATEST_DEDUP_PREFIX=new_raw_data/playwright_trec_self
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
SAVE_EVERY_PAGES=10
```
