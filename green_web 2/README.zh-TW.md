# green_demo_web

這是一個可以連接 BigQuery 的 T-REC 憑證資料儀表板參考專案。

這份範例包含：

- 一個簡單的 Express Web Server。
- 一個瀏覽器儀表板頁面，放在 `public/`。
- 可查詢 BigQuery 的 API。
- 本機預覽用的 mock data 模式。
- BigQuery 建表與測試資料 SQL。
- 預設對應事實表 `tibametopics.trec_data.fact_issued_certificate`，並搭配 dim 表顯示名稱。

## 需求

- Node.js 20 以上
- 已啟用 BigQuery 的 Google Cloud 專案
- 本機 Application Default Credentials，或 service account key

## 快速啟動

```bash
cd green_demo_web
npm install
cp .env.example .env
npm run dev
```

開啟瀏覽器：

```text
http://localhost:3000
```

專案預設使用 `USE_MOCK_DATA=true`，所以還沒設定 BigQuery 前也可以先看到畫面。

如果 `3000` port 已經被其他程式使用，可以改用其他 port：

```bash
PORT=41731 npm run dev
```

然後開啟：

```text
http://localhost:41731
```

## BigQuery 設定方式

1. 先建立 dataset 和 table，並匯入範例資料：

```bash
bq query --use_legacy_sql=false < bigquery/schema.sql
bq query --use_legacy_sql=false < bigquery/seed.sql
```

2. 編輯 `.env`：

```env
USE_MOCK_DATA=false
GOOGLE_CLOUD_PROJECT=tibametopics
BIGQUERY_LOCATION=asia-east1
BIGQUERY_DATASET=trec_data
BIGQUERY_TABLE=fact_issued_certificate
```

3. 本機登入 Google Cloud：

```bash
gcloud auth application-default login
```

正式環境建議使用 service account，並只給查詢 BigQuery 所需的最小權限。

## BigQuery 資料表格式

預設查詢的事實表是：

```text
`${GOOGLE_CLOUD_PROJECT}.${BIGQUERY_DATASET}.${BIGQUERY_TABLE}`
```

API 也會搭配查詢：

- `dim_facility`
- `dim_energy_type`
- `dim_company`

預設欄位：

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| raw_id | INTEGER | 原始資料 ID |
| unit_name | STRING | 發電單位名稱 |
| facility_name | STRING | 發電設備或案場名稱 |
| energy_type | STRING | 能源類型 |
| facility_address | STRING | 設備地址 |
| installed_capacity | STRING | 裝置容量 |
| shared_company | STRING | 轉供或共享公司 |
| certificate_number | STRING | 憑證號碼 |
| trec_last_issue_date | STRING | T-REC 最近發證日期 |
| generation_period | STRING | 發電期間 |
| equipment_audit_report | STRING | 設備查核報告 |
| power_generation_verification_report | STRING | 發電量查證報告 |
| transferred_mwh | STRING | 已轉供 MWh |
| remaining_mwh | STRING | 剩餘 MWh |
| created_at | TIMESTAMP | 資料建立時間 |

## API 說明

### `GET /api/summary`

回傳 T-REC KPI 數字與圖表資料。

可用查詢參數：

- `from`：開始日期，依 `created_at` 篩選，預設 `2026-01-01`
- `to`：結束日期，預設今天
- `site`：選填，指定 `facility_name`

範例：

```text
/api/summary?from=2026-01-01&to=2026-01-03
```

### `GET /api/sites`

回傳所有案場名稱，也就是 `facility_name`。

### `GET /api/health`

檢查服務是否正常，並顯示目前資料來源是 mock data 或 BigQuery。

## 專案結構

```text
green_demo_web/
  bigquery/
    schema.sql        BigQuery 建表 SQL
    seed.sql          BigQuery 範例資料 SQL
    views.sql         BigQuery clean view 與 dashboard view 建置 SQL
  public/
    index.html        前端頁面
    styles.css        頁面樣式
    app.js            前端資料載入與圖表渲染
  src/
    bigqueryClient.js BigQuery client 與 query runner
    config.js         環境變數設定
    mockData.js       本機 mock data
    queries.js        BigQuery 查詢 SQL
    server.js         Express server 與 API route
```

## 開發流程

本機開發：

```bash
npm run dev
```

正式啟動：

```bash
npm start
```

檢查 JavaScript 語法：

```bash
npm run check
```

## 用 Docker 啟動

如果要放到 GCP VM 上，建議用 Docker 啟動 Web 專案。

先準備 `.env`：

```bash
cp .env.example .env
```

如果只是先測試畫面，可以保留：

```env
USE_MOCK_DATA=true
```

如果要連 BigQuery，請改成：

```env
USE_MOCK_DATA=false
GOOGLE_CLOUD_PROJECT=tibametopics
BIGQUERY_LOCATION=asia-east1
BIGQUERY_DATASET=trec_data
BIGQUERY_TABLE=fact_issued_certificate
PORT=3000
```

啟動：

```bash
docker compose up -d --build
```

查看狀態：

```bash
docker compose ps
```

查看 log：

```bash
docker compose logs -f green-demo-web
```

停止：

```bash
docker compose down
```

## 部署到 GCP VM 的建議步驟

### 第 1 步：確認 BigQuery 已經有資料

先確認 Airflow 爬蟲已經可以把資料寫進 BigQuery。

你可以先在 BigQuery Console 裡跑：

```sql
SELECT *
FROM `tibametopics.trec_data.fact_issued_certificate`
LIMIT 10;
```

如果查得到資料，再繼續部署 Web。

### 第 2 步：確認 VM 的 service account 權限

VM 綁定的 service account 至少需要：

- `BigQuery Job User`
- `BigQuery Data Viewer`

如果同一個 service account 也要給 Airflow 寫資料，還需要：

- `BigQuery Data Editor`

建議不要把 service account JSON key 放進 VM 或 container。讓 VM 直接使用自己的 service account 會比較安全。

### 第 3 步：把專案放到 VM

建議放在：

```text
/opt/green-platform/green_demo_web
```

如果你用 git，可以在 VM 上 clone 專案。

如果你先用手動上傳，也可以把整個 `green_demo_web` 資料夾放到 VM。

### 第 4 步：設定 `.env`

在 VM 裡進入專案：

```bash
cd /opt/green-platform/green_demo_web
cp .env.example .env
```

編輯 `.env`：

```env
USE_MOCK_DATA=false
GOOGLE_CLOUD_PROJECT=tibametopics
BIGQUERY_LOCATION=asia-east1
BIGQUERY_DATASET=trec_data
BIGQUERY_TABLE=fact_issued_certificate
PORT=3000
```

### 第 5 步：用 Docker 啟動 Web

```bash
docker compose up -d --build
```

確認 container 有跑起來：

```bash
docker compose ps
```

確認 API 正常：

```bash
curl http://localhost:3000/api/health
curl http://localhost:3000/api/sites
```

如果 `/api/health` 回傳：

```json
{"ok":true,"mode":"bigquery"}
```

代表 Web 已經切到 BigQuery 模式。

### 第 6 步：開放網站連線

測試階段可以先開 VM 的 `3000` port。

正式環境比較建議用 Nginx 或 Caddy 做反向代理，對外只開 `80` 和 `443`，再轉到 container 的 `3000`。

### 第 7 步：確認網站畫面

在瀏覽器打開：

```text
http://你的-vm-ip:3000
```

如果有設定 Nginx / Caddy 和網域，就改用你的正式網址。

## 建議架構

```text
GCP VM
  Airflow containers
    排程爬蟲
    寫入 BigQuery

  green-demo-web container
    查詢 BigQuery
    顯示 Dashboard

BigQuery
  作為 Airflow 和 Web 中間的資料層
```

Airflow 和 Web 建議分開 container。Airflow 負責寫資料，Web 負責讀資料，兩邊透過 BigQuery 串起來。

## 從 mock data 切換到 BigQuery

確認以下幾件事：

1. BigQuery 裡已經有 dataset 和 table。
2. `.env` 裡的 `GOOGLE_CLOUD_PROJECT`、`BIGQUERY_DATASET`、`BIGQUERY_TABLE` 都正確。
3. `USE_MOCK_DATA=false`。
4. 本機已經完成 `gcloud auth application-default login`，或有設定 `GOOGLE_APPLICATION_CREDENTIALS`。

設定完成後重新啟動服務即可。

## 建立 BigQuery View

raw 表會保留爬蟲抓到的原始字串，例如 `1,685.021 MWh`。正式儀表板建議先建立 clean view 和 dashboard view：

```bash
bq query --use_legacy_sql=false --location=asia-east1 < bigquery/views.sql
```

這份 SQL 會建立：

- `trec_issued_certificate_clean_v`：把 raw 字串轉成乾淨欄位，例如 MWh 數值、日期、裝置容量。
- `trec_dashboard_daily_v`：每日彙總。
- `trec_dashboard_energy_type_v`：能源類型彙總。
- `trec_dashboard_facility_v`：案場彙總。
- `trec_dashboard_company_v`：公司彙總。

## 你通常會修改的地方

- 如果你的資料表欄位不同，改 `src/queries.js` 裡的 SQL。
- 如果你的 BigQuery dataset 或 table 名稱不同，改 `.env`。
- 如果要調整畫面欄位或圖表，改 `public/index.html` 和 `public/app.js`。
- 如果要換成正式資料，改 `bigquery/schema.sql` 和 `bigquery/seed.sql` 作為自己的建表參考。
