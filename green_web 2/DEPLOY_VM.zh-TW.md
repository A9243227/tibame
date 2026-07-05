# green_demo_web 放到 GCP VM 部署步驟

這個專案建議用 Docker 跑在 GCP VM 上。容器會同時提供：

- 網頁畫面
- `/api/dashboard` 後端 API
- BigQuery view 資料查詢

## 1. VM 權限

在 GCP 建 VM 時，建議讓 VM 使用一個 Service Account，並給它這些 IAM 權限：

- BigQuery Job User
- BigQuery Data Viewer

如果只查 `tibametopics.trec_data` 這個資料集，也可以把 Data Viewer 權限只給在該 dataset 上。

在 GCP VM 上通常不需要放 JSON 金鑰檔。程式會透過 VM 的 Service Account 連 BigQuery。

## 2. VM 防火牆

如果要讓組員從瀏覽器連進來，要開防火牆。

常見做法：

- 測試用：開 TCP `3000`
- 正式用：開 TCP `80`，再把容器對外映射到 80

如果只要組內看，建議防火牆來源限制成公司或學校的固定 IP，不要開 `0.0.0.0/0`。

## 3. VM 安裝 Docker

登入 VM 後安裝 Docker 和 compose plugin。

Ubuntu / Debian 可用：

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

執行完 `usermod` 後，登出 VM 再登入一次。

## 4. 放專案到 VM

可以用 Git，也可以用 `scp` 上傳整個 `green_demo_web` 資料夾。

例如用 Git：

```bash
git clone <你的 repo 網址> green_demo_web
cd green_demo_web
```

如果用上傳方式，就進到專案資料夾：

```bash
cd green_demo_web
```

## 5. 建立 VM 用的 `.env`

在 VM 的專案資料夾建立 `.env`：

```bash
cat > .env <<'EOF'
PORT=3000
WEB_PORT=3000
USE_MOCK_DATA=false
GOOGLE_CLOUD_PROJECT=tibametopics
BIGQUERY_LOCATION=asia-east1
BIGQUERY_DATASET=trec_data
BIGQUERY_TABLE=fact_issued_certificate
DAILY_CACHE_ENABLED=true
DAILY_CACHE_DIR=.cache
EOF
```

重點：

- `USE_MOCK_DATA=false`：代表真的查 BigQuery
- `BIGQUERY_LOCATION=asia-east1`：你的 BigQuery dataset 是這個位置
- `WEB_PORT=3000`：外部用 `http://VM外部IP:3000` 連
- `DAILY_CACHE_ENABLED=true`：同一天同條件的 dashboard 查詢只會第一次打 BigQuery，後面讀快取

如果要改成 80 port：

```env
WEB_PORT=80
```

然後網址會變成：

```text
http://VM外部IP/
```

## 6. 啟動網站

在 VM 的專案資料夾執行：

```bash
docker compose up -d --build
```

看狀態：

```bash
docker compose ps
```

看 log：

```bash
docker compose logs -f green-demo-web
```

## 7. 測試是否成功

在 VM 上測：

```bash
curl http://localhost:3000/api/health
```

如果看到類似：

```json
{"ok":true,"mode":"bigquery"}
```

代表後端已經用 BigQuery 模式啟動。

再測 dashboard：

```bash
curl "http://localhost:3000/api/dashboard?recordPageSize=1"
```

## 8. 給組員看的網址

如果 `WEB_PORT=3000`：

```text
http://VM外部IP:3000/
```

如果 `WEB_PORT=80`：

```text
http://VM外部IP/
```

VM 外部 IP 可以在 GCP Console 的 Compute Engine VM 頁面看到。

## 9. 更新程式

之後如果程式有更新，在 VM 專案資料夾執行：

```bash
git pull
docker compose up -d --build
```

如果是用上傳檔案，就重新上傳後再執行：

```bash
docker compose up -d --build
```

## 10. 停止網站

```bash
docker compose down
```
