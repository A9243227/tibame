# Airflow T-REC 綠電資料更新流程

本專案使用 Airflow 編排兩條 T-REC 資料更新管線：

1. 直轉供憑證成交紀錄（Direct Transaction）
2. 自用發電設備憑證成交紀錄（Self Generation）

Airflow 本身不直接爬資料；每一個 DAG Task 都是透過 `scripts/trigger_cloud_run_job.py` 啟動一個 Cloud Run Job，等待 Cloud Run Job 完整結束後，再決定是否觸發下一個 DAG。

---

## 一、整體架構

```text
Airflow
│
├── 直轉供管線
│   ├── DAG 01：主抓取
│   │   └── Cloud Run Job 01
│   ├── DAG 02：失敗補抓
│   │   └── Cloud Run Job 02
│   └── DAG 03：ETL 去重與發布
│       └── Cloud Run Job 03
│
└── 自用發電管線
    ├── DAG 01：主抓取
    │   └── Cloud Run Job 01
    ├── DAG 02：失敗補抓
    │   └── Cloud Run Job 02
    └── DAG 03：ETL 去重與發布
        └── Cloud Run Job 03
```

每一條管線都必須依序執行：

```text
DAG 01 成功
    ↓
自動觸發 DAG 02
    ↓
DAG 02 成功
    ↓
自動觸發 DAG 03
```

這不是固定時間排程等待，而是前一個 Cloud Run Job 成功完成後，才由 Airflow 觸發下一個 DAG。

---

## 二、專案結構

```text
AIRFLOW-TREC/
├─ dags/
│  ├─ 01_crawl_dag.py
│  ├─ 02_retry_failed_again.py
│  ├─ 03_etl_dag.py
│  ├─ 01_self_crawl.py
│  ├─ 02_self_retry_failed.py
│  └─ 03_self_etl.py
│
├─ scripts/
│  └─ trigger_cloud_run_job.py
│
├─ logs/
├─ docker-compose.yaml
├─ .gitignore
└─ README.md
```

---

## 三、六個 Airflow DAG 對照表

| 資料類型 | DAG 檔案 | Airflow DAG ID | 工作內容 | DAG 內設定的 Cloud Run Job 名稱 |
|---|---|---|---|---|
| 直轉供 | `01_crawl_dag.py` | `trec_update_dt_01_crawl` | 主抓取 | `trec-update-dt-01` |
| 直轉供 | `02_retry_failed_again.py` | `trec_update_dt_02_retry_failed_again` | 失敗補抓 | `trec-update-dt-02` |
| 直轉供 | `03_etl_dag.py` | `trec_update_dt_03_etl` | ETL 去重與發布 | `trec-update-dt-03` |
| 自用發電 | `01_self_crawl.py` | `trec_update_sg_01_crawl` | 主抓取 | `trec-update-sg-01` |
| 自用發電 | `02_self_retry_failed.py` | `trec_update_sg_02_self_retry_failed` | 失敗補抓 | `trec-update-sg-02` |
| 自用發電 | `03_self_etl.py` | `trec_update_sg_03_etl` | ETL 去重與發布 | `trec-update-sg-03` |

---

## 四、重要：Cloud Run Job 名稱由專案自行命名

Cloud Run Job 名稱不是由 Airflow 自動產生，也不是由 Python 檔名決定。

專案成員可以自行決定 Cloud Run Job 名稱，例如：

```text
trec-update-dt-01
trec-update-dt-02
trec-update-dt-03

trec-update-sg-01
trec-update-sg-02
trec-update-sg-03
```

但是必須遵守這個規則：

> Airflow DAG 內的 `CRAWL_JOB_NAME`、`RETRY_JOB_NAME`、`ETL_JOB_NAME`，必須與 GCP Cloud Run Jobs 中實際建立的 Job 名稱完全一致。

### 例：直轉供 DAG 01

在 `dags/01_crawl_dag.py`：

```python
CRAWL_JOB_NAME = "trec-update-dt-01"
```

代表 Airflow 會要求 `trigger_cloud_run_job.py` 啟動 GCP 中名稱完全相同的：

```text
trec-update-dt-01
```

如果團隊把 Cloud Run Job 改名為：

```text
team-dt-crawl-01
```

就必須同步修改 DAG：

```python
CRAWL_JOB_NAME = "team-dt-crawl-01"
```

### 名稱關係

```text
Airflow DAG 檔案名稱
01_crawl_dag.py
        ↓ 不必和其他名稱相同

Airflow DAG ID
trec_update_dt_01_crawl
        ↓ 負責 Airflow DAG 之間的 Trigger

Cloud Run Job 名稱
trec-update-dt-01
        ↓ 由 CRAWL_JOB_NAME 指定

容器內真正執行的 Python 程式
01_crawl_direct_transaction_raw.py
        ↓ 由 Cloud Run Job 部署時的 --args 指定
```

因此：

```text
Airflow DAG 檔名
≠ Airflow DAG ID
≠ Cloud Run Job 名稱
≠ 容器內執行的 Python 檔名
```

四者可以不同，但彼此的對應關係要正確。

---

## 五、Cloud Run Job 的建立原則

原本的舊 Job 可以保留作為「04 全流程」備份，例如：

```text
trec-update-dt
self-update-paths
```

這兩支舊 Job 若仍執行 `04_run_..._pipeline.py`，就會在容器內一次跑完 01 → 02 → 03。

新的 Airflow 架構則應建立六支「單一階段」Cloud Run Job：

```text
直轉供
├─ trec-update-dt-01  → 只跑 01_crawl_direct_transaction_raw.py
├─ trec-update-dt-02  → 只跑 02_retry_direct_transaction_failed.py
└─ trec-update-dt-03  → 只跑 03_etl_direct_transaction_deduplicate.py

自用發電
├─ trec-update-sg-01  → 只跑 01_crawl_self_generation_transaction_raw.py
├─ trec-update-sg-02  → 只跑 02_retry_self_generation_transaction_failed.py
└─ trec-update-sg-03  → 只跑 03_etl_self_generation_transaction_deduplicate.py
```

通常可沿用原本對應流程的 Docker image，不需要為 01、02、03 分別建立三份 image。

差別是在部署 Cloud Run Job 時指定不同的 command / args：

```text
直轉供 01
--command python
--args 01_crawl_direct_transaction_raw.py

直轉供 02
--command python
--args 02_retry_direct_transaction_failed.py

直轉供 03
--command python
--args 03_etl_direct_transaction_deduplicate.py
```

自用發電也是同樣概念。

---

## 五之一、為什麼一定要改 `--command` 與 `--args`

### 1. 原本舊 Job 的問題

原本的舊 Cloud Run Job 是：

```text
trec-update-dt
self-update-paths
```

它們的 Docker image 預設通常會執行總控程式，例如：

```text
python 04_run_direct_transaction_pipeline.py
```

或：

```text
python 04_run_self_generation_transaction_pipeline.py
```

而 04 總控程式會一次跑完整流程：

```text
01 → 02 → 03
```

因此，新 Airflow 架構若仍讓 DAG 01、DAG 02、DAG 03 都呼叫舊 Job，就會造成重複執行：

```text
DAG 01
    ↓
舊 Job 跑 04
    ↓
04 已經跑完 01 → 02 → 03
    ↓
DAG 01 又觸發 DAG 02
    ↓
DAG 02 再跑一次 02
    ↓
DAG 03 再跑一次 03
```

這是錯誤架構。

### 2. 正確方法：同一個 image，建立不同 Job，覆寫 command / args

Cloud Run Job 啟動容器時，預設會使用 Docker image 裡設定的 entrypoint / command / args。

新架構要沿用原本可正常執行的 Docker image，但建立新的 Job 名稱，並在每一支 Job 設定：

```text
--command python
--args <只屬於該 Job 的 Python 程式>
```

例如：

```text
Cloud Run Job：trec-update-dt-01
實際容器指令：python 01_crawl_direct_transaction_raw.py
```

這樣 Job 01 只會跑 01，不會再跑 Docker image 預設的 04 全流程。

### 3. `--command` 與 `--args` 各自代表什麼

```text
--command python
```

代表容器要執行的程式是：

```text
python
```

```text
--args 01_crawl_direct_transaction_raw.py
```

代表把這個檔名傳給 `python`：

```text
python 01_crawl_direct_transaction_raw.py
```

所以：

```text
--command python
--args 01_crawl_direct_transaction_raw.py
```

等同容器內執行：

```bash
python 01_crawl_direct_transaction_raw.py
```

### 4. 六支新 Job 的 `--args` 對照表

| 資料類型 | 新 Cloud Run Job 名稱 | `--command` | `--args` | 容器實際只跑 |
|---|---|---|---|---|
| 直轉供 | `trec-update-dt-01` | `python` | `01_crawl_direct_transaction_raw.py` | 01 主抓取 |
| 直轉供 | `trec-update-dt-02` | `python` | `02_retry_direct_transaction_failed.py` | 02 失敗補抓 |
| 直轉供 | `trec-update-dt-03` | `python` | `03_etl_direct_transaction_deduplicate.py` | 03 ETL |
| 自用發電 | `trec-update-sg-01` | `python` | `01_crawl_self_generation_transaction_raw.py` | 01 主抓取 |
| 自用發電 | `trec-update-sg-02` | `python` | `02_retry_self_generation_transaction_failed.py` | 02 失敗補抓 |
| 自用發電 | `trec-update-sg-03` | `python` | `03_etl_self_generation_transaction_deduplicate.py` | 03 ETL |

> Cloud Run Job 名稱可以由團隊自己訂；上表是目前 Airflow DAG 使用的名稱。若團隊改 Job 名稱，必須同步修改相對應 DAG 的 `CRAWL_JOB_NAME`、`RETRY_JOB_NAME` 或 `ETL_JOB_NAME`。

### 5. 建立前先複製舊 Job 的完整固定設定

不要只複製 image 與 `--args`。

每一支新 Job 都應從對應舊 Job 複製固定設定，例如：

```text
容器 image
Service Account
CPU
Memory
task timeout
max retries
GCS_BUCKET
GCS_PREFIX
LOCAL_WORKDIR
YEARS_TO_CRAWL
MAX_PAGES_PER_YEAR
SAVE_EVERY_PAGES
API_TIMEOUT_MS
其他原本已驗證可用的靜態環境變數
```

先在 PowerShell 匯出舊 Job 設定：

```powershell
gcloud.cmd run jobs describe trec-update-dt `
  --project tibametopics `
  --region asia-east1 `
  --format=yaml > trec-update-dt-old.yaml

gcloud.cmd run jobs describe self-update-paths `
  --project tibametopics `
  --region asia-east1 `
  --format=yaml > self-update-paths-old.yaml
```

從這兩份 YAML 確認 image、環境變數、資源與 Service Account，再建立新的 Job。

### 6. 建立新 Job 的方法

以下命令示範「唯一需要因 01 / 02 / 03 而不同的核心部分」：

```powershell
$PROJECT_ID = "tibametopics"
$REGION = "asia-east1"

# 從舊 Job 設定複製真正的 image 路徑，不要自行猜測。
$DT_IMAGE = "<從 trec-update-dt 複製的 image>"
$SG_IMAGE = "<從 self-update-paths 複製的 image>"
```

#### 直轉供 Job 01：只跑 01

```powershell
gcloud.cmd run jobs deploy trec-update-dt-01 `
  --project $PROJECT_ID `
  --region $REGION `
  --image $DT_IMAGE `
  --command python `
  --args 01_crawl_direct_transaction_raw.py `
  <其餘固定設定請依 trec-update-dt-old.yaml 複製>
```

#### 直轉供 Job 02：只跑 02

```powershell
gcloud.cmd run jobs deploy trec-update-dt-02 `
  --project $PROJECT_ID `
  --region $REGION `
  --image $DT_IMAGE `
  --command python `
  --args 02_retry_direct_transaction_failed.py `
  <其餘固定設定請依 trec-update-dt-old.yaml 複製>
```

#### 直轉供 Job 03：只跑 03

```powershell
gcloud.cmd run jobs deploy trec-update-dt-03 `
  --project $PROJECT_ID `
  --region $REGION `
  --image $DT_IMAGE `
  --command python `
  --args 03_etl_direct_transaction_deduplicate.py `
  <其餘固定設定請依 trec-update-dt-old.yaml 複製>
```

#### 自用發電 Job 01：只跑 01

```powershell
gcloud.cmd run jobs deploy trec-update-sg-01 `
  --project $PROJECT_ID `
  --region $REGION `
  --image $SG_IMAGE `
  --command python `
  --args 01_crawl_self_generation_transaction_raw.py `
  <其餘固定設定請依 self-update-paths-old.yaml 複製>
```

#### 自用發電 Job 02：只跑 02

```powershell
gcloud.cmd run jobs deploy trec-update-sg-02 `
  --project $PROJECT_ID `
  --region $REGION `
  --image $SG_IMAGE `
  --command python `
  --args 02_retry_self_generation_transaction_failed.py `
  <其餘固定設定請依 self-update-paths-old.yaml 複製>
```

#### 自用發電 Job 03：只跑 03

```powershell
gcloud.cmd run jobs deploy trec-update-sg-03 `
  --project $PROJECT_ID `
  --region $REGION `
  --image $SG_IMAGE `
  --command python `
  --args 03_etl_self_generation_transaction_deduplicate.py `
  <其餘固定設定請依 self-update-paths-old.yaml 複製>
```

> 上方的 `<其餘固定設定...>` 不是可直接執行的 PowerShell 內容。正式部署前，必須把原本舊 Job 已驗證可用的 CPU、Memory、timeout、Service Account 與靜態環境變數完整補上。

### 7. 已經建立新 Job，但 `--args` 寫錯時怎麼改

不需要重新建另一支 Job。

直接更新該 Job 的 command / args，例如：

```powershell
gcloud.cmd run jobs update trec-update-dt-01 `
  --project tibametopics `
  --region asia-east1 `
  --command python `
  --args 01_crawl_direct_transaction_raw.py
```

更新自用發電 Job 03 的例子：

```powershell
gcloud.cmd run jobs update trec-update-sg-03 `
  --project tibametopics `
  --region asia-east1 `
  --command python `
  --args 03_etl_self_generation_transaction_deduplicate.py
```

### 8. 不能改的東西與可以改的東西

```text
不用改：
- 原本爬蟲 Python 檔名
- Airflow DAG 檔名
- Airflow DAG ID（除非團隊決定重命名）
- 舊的 04 全流程 Job（建議保留當備份）

需要建立或確認：
- 6 支新的 Cloud Run Job
- 每支 Job 的 --command python
- 每支 Job 的 --args 是否對應自己的 01、02、03 程式
- DAG 裡的 CRAWL_JOB_NAME / RETRY_JOB_NAME / ETL_JOB_NAME
  是否與 GCP 實際 Cloud Run Job 名稱完全一致
```


---

## 六、PIPELINE_DT：同一輪資料處理的快照日期

每一次由 DAG 01 開始的流程，都會使用一個共用的 `pipeline_dt`。

範例：

```text
pipeline_dt = 2026-07-05
```

DAG 01 會把同一個日期傳給 DAG 02；DAG 02 再傳給 DAG 03。

```text
DAG 01：2026-07-05
    ↓
DAG 02：2026-07-05
    ↓
DAG 03：2026-07-05
```

Airflow 呼叫 Cloud Run Job 時，會以該次執行覆寫：

```text
PIPELINE_DT=2026-07-05
```

因此 Cloud Run 裡的 01、02、03 程式都必須使用 `PIPELINE_DT` 寫入或讀取同一個快照目錄，例如：

```text
gs://<bucket>/<prefix>/dt=2026-07-05/
```

### 為什麼要依日期隔離？

因為之後可能發生：

```text
7/05 的 DAG 01 成功
7/05 的 DAG 02 失敗
7/06 又跑了一次新的 DAG 01
7/08 才想補跑 7/05 的 DAG 02
```

若 GCS 中間檔沒有依 `dt=YYYY-MM-DD` 隔離，7/05 的 failed 檔可能被 7/06 的資料覆蓋。

---

## 七、正常啟動方式

正常情況下，只需要從 Airflow UI 手動啟動 DAG 01。

### 啟動直轉供流程

在 Airflow UI 執行：

```text
trec_update_dt_01_crawl
```

流程：

```text
trec_update_dt_01_crawl
    ↓
trec_update_dt_02_retry_failed_again
    ↓
trec_update_dt_03_etl
```

### 啟動自用發電流程

在 Airflow UI 執行：

```text
trec_update_sg_01_crawl
```

流程：

```text
trec_update_sg_01_crawl
    ↓
trec_update_sg_02_self_retry_failed
    ↓
trec_update_sg_03_etl
```

---

## 八、中間失敗時如何補跑

### 情境 A：DAG 01 成功，但 DAG 02 失敗

不用重跑 DAG 01。

手動 Trigger DAG 02，並在 Airflow 的 Config 輸入原本的日期：

```json
{
  "pipeline_dt": "2026-07-05"
}
```

DAG 02 成功後，會自動觸發 DAG 03。

### 情境 B：只有 DAG 03 失敗

不用重跑 DAG 01 或 DAG 02。

手動 Trigger DAG 03，並輸入同一個日期：

```json
{
  "pipeline_dt": "2026-07-05"
}
```

---

## 九、trigger_cloud_run_job.py 的專案設定

`scripts/trigger_cloud_run_job.py` 會：

1. 接收 Airflow 傳入的 `--job-name` 與 `--pipeline-dt`。
2. 使用 Google Cloud Run API 啟動指定的 Cloud Run Job。
3. 在該次 Cloud Run Execution 覆寫 `PIPELINE_DT`。
4. 每 30 秒檢查一次 Execution 狀態。
5. 成功時回傳 exit code 0；失敗或取消時拋出錯誤，讓 Airflow Task 失敗。

### 部署到 tibametopics 前必改

請確認檔案中的專案 ID 是：

```python
PROJECT_ID = "tibametopics"
REGION = "asia-east1"
```

如果 `PROJECT_ID` 還是其他舊專案，例如：

```python
PROJECT_ID = "project-c865579e-705e-4adb-aca"
```

Airflow 就會跑去錯的 GCP 專案找 Cloud Run Job。

---

## 十、Airflow Docker 啟動

在 `AIRFLOW-TREC` 根目錄執行：

```bash
docker compose up -d
```

確認容器：

```bash
docker compose ps
```

停止容器：

```bash
docker compose down
```

Airflow UI：

```text
http://localhost:8080
```

---

## 十一、部署到 VM 前的檢查清單

```text
[ ] 6 支 DAG 檔案都放在 dags/
[ ] trigger_cloud_run_job.py 放在 scripts/
[ ] trigger_cloud_run_job.py 的 PROJECT_ID = "tibametopics"
[ ] 每個 DAG 內的 Cloud Run Job 名稱與 GCP 實際 Job 名稱完全相同
[ ] 6 支 Cloud Run Job 都已建立
[ ] 每支 Cloud Run Job 都使用正確的 --args，只跑自己的 01、02 或 03
[ ] Cloud Run Job 的 Service Account 有讀寫對應 GCS Bucket 的權限
[ ] Airflow 所在 VM 的身分有啟動 Cloud Run Job 的權限
[ ] 01、02、03 程式均以 PIPELINE_DT 使用對應 dt=YYYY-MM-DD 快照目錄
[ ] 直轉供與自用發電各自手動測試過 01 → 02 → 03
```

---

## 十二、目前的核心規則

```text
1. Cloud Run Job 名稱由專案自行決定。
2. DAG 中的 CRAWL_JOB_NAME / RETRY_JOB_NAME / ETL_JOB_NAME 必須與實際 Job 名稱完全一致。
3. DAG 01、02、03 不使用固定時間等待。
4. DAG 01 成功後觸發 DAG 02；DAG 02 成功後觸發 DAG 03。
5. 同一輪流程必須傳遞完全相同的 pipeline_dt。
6. GCS 中間資料必須以 dt=YYYY-MM-DD 隔離，才能安全補跑下游 DAG。
7. 舊的 04 全流程 Cloud Run Job 可以保留當備份，但不可讓新 01、02、03 DAG 共用它。
```
