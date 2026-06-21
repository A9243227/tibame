# T-REC 直轉供交易資料自動化

這是一個把「台灣再生能源憑證中心（T-REC）」直轉供交易資料，自動抓下來、整理好、存到 Google Cloud Storage（GCS）的專案。

這個專案會在 **Cloud Run Job** 裡面執行。

你可以把它想成：

```text
Cloud Run = 雲端上的小電腦
GCS = 雲端上的大檔案櫃
/tmp = 小電腦工作時用的暫存桌面
```

小電腦工作結束後，`/tmp` 裡的東西不能當成永久保存資料，所以重要 CSV 都會上傳到 GCS。

---

## 這個專案會做什麼？

整個流程會照順序跑 3 個工作：

```text
01 抓原始資料
↓
02 補抓失敗資料（真的有失敗才會跑）
↓
03 整理重複資料，做出最後乾淨版本
```

總控程式是：

```text
04_run_direct_transaction_pipeline.py
```

Cloud Run 執行這一支後，就會自動依序跑完 01、02、03。

---

## 四支 Python 程式在做什麼？

| 檔案 | 小學生版說明 |
|---|---|
| `01_crawl_direct_transaction_raw.py` | 去 T-REC 網站把交易資料抓回來。 |
| `02_retry_direct_transaction_failed.py` | 把 01 沒抓成功的資料，再試著抓一次。 |
| `03_etl_direct_transaction_deduplicate.py` | 把完全一樣的資料整理掉，只留下 1 份。 |
| `04_run_direct_transaction_pipeline.py` | 像班長一樣，叫 01、02、03 按順序工作。 |

---

# 最重要的觀念：第一次全部抓，之後只更新新年份

## 第一次：抓全部年份

第一次要把網站上的所有年份都抓下來。

Cloud Run 環境變數設定：

```text
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
```

意思是：

```text
ALL = 抓網站目前全部年份
0   = 每一年都完整抓完，不限制頁數
```

假設網站目前有 2026 到 2017 年，第一次會建立每一年的年度檔案：

```text
trec_direct_transaction_raw_2026_0621.csv
trec_direct_transaction_raw_2025_0621.csv
trec_direct_transaction_raw_2024_0621.csv
...
trec_direct_transaction_raw_2017_0621.csv
```

然後把每一年最新的資料合在一起，建立第一份完整總檔：

```text
trec_direct_transaction_raw_all_year.csv
```

流程像這樣：

```text
第一次抓 ALL
↓
抓 2026
抓 2025
抓 2024
...
抓 2017
↓
每年各自存一份年度 raw CSV
↓
把全部年度 raw CSV 合在一起
↓
產生第一份完整 all_year.csv
↓
全部上傳到 GCS
```

---

## 第二次以後：只更新 2026

下次通常不需要再把所有舊年份重新抓一次。

例如你只想更新最新的 2026 年：

```text
YEARS_TO_CRAWL=2026
MAX_PAGES_PER_YEAR=0
```

這時程式會做下面的事情：

```text
Cloud Run 開始
↓
/tmp 一開始是新的暫存空間
↓
先從 GCS 下載 2025～2017 的「最新年度檔」到 /tmp
↓
重新完整抓新的 2026
↓
建立新的 2026 年度檔
↓
把「新 2026 + 舊 2025～2017」重新合併
↓
產生新的 all_year.csv
↓
上傳回 GCS
```

所以重點是：

```text
只抓 2026
不代表 all_year 只剩 2026。

新的 all_year 會是：
新 2026 + 舊 2025 + 舊 2024 + ... + 舊 2017
```

這樣就不用每次都重抓所有舊年份，也不會把舊年度資料弄丟。

---

# /tmp 是什麼？

Cloud Run 每次開始時，都像拿到一張新的空白桌子。

這張桌子就是：

```text
/tmp
```

程式會先把需要的舊檔案，從 GCS 拿到 `/tmp`：

```text
GCS
↓
下載舊年度 raw CSV
下載舊 status CSV
下載舊 dedup report CSV
↓
/tmp
```

接著程式在 `/tmp` 裡面處理資料，最後再把結果放回 GCS：

```text
/tmp
↓
上傳年度 raw CSV
上傳 all_year CSV
上傳 status CSV
上傳 failed CSV
上傳 final CSV
上傳 dedup report CSV
↓
GCS
```

---

# 01：抓原始資料

01 使用 Playwright 開啟 T-REC 首頁，取得網站需要的 Cookie 和 CSRF Token。

接著不再像人一樣一直點表格和「詳情」按鈕，而是直接使用網站的 API：

```text
data API
= 取得某一年、某一頁的交易列表

detail API
= 取得每一筆交易的成交日期與成交移轉量
```

這樣通常比用 Selenium 點網頁更快，也比較不容易卡在按鈕或彈窗。

## 01 產生的主要檔案

| 檔案 | 用途 |
|---|---|
| `trec_direct_transaction_raw_YYYY_MMDD.csv` | 某一年度的原始交易資料。 |
| `trec_direct_transaction_raw_all_year.csv` | 每個年份最新年度檔合在一起的總資料。 |
| `trec_direct_transaction_raw_status.csv` | 哪些年份目前沒有資料的歷史紀錄。 |
| `trec_direct_transaction_raw_failed.csv` | 這一次 01 沒抓成功的資料清單。 |

---

## 年度沒有資料時怎麼辦？

01 切換年份後，會看網站上的年度總移轉量。

```text
year-power = 0
↓
代表這一年目前沒有資料
↓
不算失敗
↓
寫進 status.csv
```

`status.csv` 是固定檔名：

```text
trec_direct_transaction_raw_status.csv
```

它不是每次覆蓋，而是會一直把新紀錄加在最後面。

所以你以後可以知道：

```text
哪一天抓資料時
哪一個年份顯示目前沒有資料
```

---

## failed.csv 是什麼？

`failed.csv` 是「這一次 01 工作時，真正沒抓成功的清單」。

固定檔名：

```text
trec_direct_transaction_raw_failed.csv
```

每一次 01 開始時，程式只會清空這一份檔案，變成只有表頭。

```text
不會清空整個資料夾
不會刪掉年度 raw
不會刪掉 all_year
不會刪掉 status 歷史
不會刪掉最終去重資料
```

如果 01 遇到真正失敗，例如：

```text
data API 連不上
detail API 回傳錯誤
資料格式不符合預期
```

程式會立刻：

```text
更新 failed.csv
↓
上傳到 GCS
```

這樣就算 Cloud Run 中途停止，也比較不容易遺失失敗清單。

---

# 02：補抓 failed.csv 裡的資料

02 不會重新抓全部年份。

02 只看 `failed.csv` 裡面寫了什麼，再去補抓那些失敗資料。

例如：

```text
2026，第 70 頁，筆數 0
```

代表整頁 data API 失敗。

02 會：

```text
重試第 70 頁的 data API
最多 3 次
↓
成功後，再處理這一頁的每一筆 detail API
```

另一種情況：

```text
2026，第 267 頁，第 1 筆
```

代表那一頁有抓到，但第 1 筆 detail 失敗。

02 只會補這一筆。

## 02 的結果

| 情況 | 結果 |
|---|---|
| 補抓成功 | 成功資料補回該年份 raw CSV。 |
| 成功資料補回後 | 重新建立 all_year.csv。 |
| 還是失敗 | 寫入 `trec_direct_transaction_raw_failed_retry.csv`。 |
| detail 裡 `<ol></ol>` 是空白 | 代表正常沒有成交紀錄，不算失敗。 |

---

# 03：整理重複資料

01 和 02 的 raw 資料先保留原始樣子，不在那邊去重。

03 才會做整理。

03 只看這 8 欄：

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

如果 8 欄全部一模一樣，03 只留 1 筆。

03 會產生：

| 檔案 | 用途 |
|---|---|
| `trec_direct_transaction_raw.csv` | 最後乾淨、去重後的資料。 |
| `trec_direct_transaction_dedup_report.csv` | 每次去重的統計與重複資料歷史紀錄。 |

`trec_direct_transaction_dedup_report.csv` 會一直追加，不會覆蓋以前的紀錄。

---

# Cloud Run 常用環境變數

## 一定要設定

| 環境變數 | 範例 | 意思 |
|---|---|---|
| `GCS_BUCKET` | `playwright_trec` | GCS 的 Bucket 名稱。 |
| `GCS_PREFIX` | `direct_transaction` | Bucket 裡的資料夾路徑。 |
| `LOCAL_WORKDIR` | `/tmp` | Cloud Run 暫存資料夾。 |

## 01 抓資料時常用

| 環境變數 | 範例 | 意思 |
|---|---|---|
| `YEARS_TO_CRAWL` | `ALL` | 抓全部網站年份。 |
| `YEARS_TO_CRAWL` | `2026` | 只抓 2026。 |
| `YEARS_TO_CRAWL` | `2026,2025` | 只抓 2026 和 2025。 |
| `MAX_PAGES_PER_YEAR` | `0` | 不限制頁數，完整抓完。 |
| `MAX_PAGES_PER_YEAR` | `2` | 測試用，每年只抓前 2 頁。 |
| `SAVE_EVERY_PAGES` | `10` | 每完成 10 頁就存檔並上傳。 |
| `PAGE_LENGTH` | `10` | 每一頁抓 10 筆資料。 |
| `API_TIMEOUT_MS` | `30000` | API 最多等待 30 秒。 |
| `YEAR_CHANGE_WAIT_SECONDS` | `2` | 切換年份後等 2 秒。 |
| `DATA_API_SLEEP_SECONDS` | `2` | 一頁做完後，等 2 秒再抓下一頁。 |
| `DETAIL_API_SLEEP_SECONDS` | `1` | 每筆 detail 做完後，等 1 秒再做下一筆。 |
| `HEADLESS` | `true` | Cloud Run 不顯示瀏覽器畫面。 |

> `YEARS_TO_CRAWL` 沒有設定時，程式預設只抓 `2026`。  
> 不要設定成 `YEARS_TO_CRAWL=""`，空白不是預設 2026，會變成沒有年份可以抓。

## 02 補抓失敗資料時常用

| 環境變數 | 範例 | 意思 |
|---|---|---|
| `DATA_API_RETRY_MAX` | `3` | data API 最多重試 3 次。 |
| `DETAIL_API_RETRY_MAX` | `3` | detail API 最多重試 3 次。 |
| `API_RETRY_SLEEP_SECONDS` | `3` | 每次重試前等 3 秒。 |
| `FAILED_CSV_FILE` | 不設定 | 預設讀 01 的 failed.csv。 |
| `FAILED_CSV_FILE` | `trec_direct_transaction_raw_failed_retry.csv` | 想再補抓上次仍失敗的資料時才設定。 |

---

# 第一次正式執行建議

第一次先做小測試：

```text
YEARS_TO_CRAWL=2026
MAX_PAGES_PER_YEAR=2
SAVE_EVERY_PAGES=1
```

先確認 GCS 裡有看到：

```text
年度 raw CSV
all_year.csv
failed.csv
status.csv（有無資料年份時才會有）
final raw CSV
dedup report CSV
```

測試沒問題後，再正式抓全部年份：

```text
YEARS_TO_CRAWL=ALL
MAX_PAGES_PER_YEAR=0
SAVE_EVERY_PAGES=10
```

---

# Cloud Run 執行時會發生什麼？

```text
Cloud Run Job 開始
↓
04 啟動
↓
01 抓原始資料
↓
01 有 failed.csv 資料嗎？
├─ 沒有：直接去 03
└─ 有：執行 02 補抓
↓
03 去重
↓
把結果上傳 GCS
↓
Cloud Run Job 結束
```

---

# 重要提醒

1. 01 不做 checkpoint。
   - 程式中斷後，下次仍從第 1 頁開始抓。
   - 但是程式每 10 頁會保存一次，避免資料完全不見。

2. raw 階段不去重。
   - 01 和 02 先保留原始資料。
   - 03 才會去除完全相同的 8 欄資料。

3. Cloud Run 的 `/tmp` 不是永久資料夾。
   - 真正要保存的 CSV 都在 GCS。

4. Cloud Run 的服務帳號要有 GCS 讀寫權限。
   - 不然程式不能下載舊年度檔，也不能上傳新檔。

---

# 專案檔案

```text
01_crawl_direct_transaction_raw.py
02_retry_direct_transaction_failed.py
03_etl_direct_transaction_deduplicate.py
04_run_direct_transaction_pipeline.py
Dockerfile
requirements.txt
README.md
```

---

# 使用的套件

```text
google-cloud-storage
playwright
pandas
```

- `google-cloud-storage`：讀寫 GCS。
- `playwright`：開網站並使用 API 抓資料。
- `pandas`：03 用來整理與去重資料。
