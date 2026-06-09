# 程式碼與資料庫說明文件

## Python 程式說明

---

### utils_v5.py

共用工具模組。

主要功能：

- 讀取 `.env`
- 建立 MySQL 連線
- 執行 SQL 檔案
- 清理空值
- 清理數值欄位
- 清理日期欄位
- 讀取 CSV

主要 Function：

#### load_db_config()

讀取 `.env` 資料庫設定。

#### get_connection()

建立 MySQL 連線。

#### clean_empty()

將空字串、NULL、NaN 轉為 None。

#### clean_decimal()

將數值欄位轉為 Decimal。

#### clean_int()

將數值轉為整數。

#### clean_date()

將日期轉換為 YYYY-MM-DD 格式。

#### execute_sql_file()

執行 SQL 檔案。

---

### 01_import_trec_all_csv_v5.py

用途：

匯入全部交易資料。

來源：

trec_all_raw.csv

主要 Function：

#### import_trec_all_raw()

將 CSV 寫入：

trec_all_raw

資料表。

主要欄位：

- seller
- facility_name
- buyer
- energy_type
- supply_type
- total_transfer_mwh
- transaction_date
- transaction_transfer_mwh

---

### 02_import_trec_direct_csv_v5.py

用途：

匯入直接供應資料。

來源：

trec_direct_supply_raw.csv

主要 Function：

#### import_trec_direct_supply_raw()

將 CSV 寫入：

trec_direct_supply_raw

資料表。

主要欄位：

- seller
- facility_name
- buyer
- energy_type
- transfer_mwh
- certificate_year
- transfer_date

---

### 03_import_trec_certificate_csv_v5.py

用途：

匯入憑證資料。

來源：

trec_certificate_raw.csv

主要 Function：

#### import_trec_certificate_raw()

將 CSV 寫入：

trec_certificate_raw

資料表。

主要欄位：

- certificate_no
- transferred_mwh
- balance_mwh
- facility_location
- capacity
- generation_period

---

### 04_build_normalized_tables_v5.py

用途：

建立維度表與事實表。

主要 Function：

#### build_dimension_tables()

建立：

- company
- company_alias
- facility
- energy_type
- supply_type

#### build_transaction_fact()

建立：

transaction_fact

交易事實表。

#### build_certificate_fact()

建立：

certificate_fact

憑證事實表。

---

### 05_create_views_v5.py

用途：

建立分析 View。

建立：

- vw_transaction_detail
- vw_top_buyers
- vw_top_sellers
- vw_sankey_data
- vw_energy_analysis
- vw_certificate_detail

---

### 06_check_database_v5.py

用途：

檢查資料表筆數。

功能：

確認 ETL 是否成功完成。

---

### 07_dashboard_sankey_top10_v5.py

用途：

建立 Sankey Diagram。

功能：

分析綠電交易流向：

賣家 → 買家

並輸出：

output/sankey_top10_v5.html

---

### 08_check_raw_columns_v5.py

用途：

檢查 Raw Table 欄位。

功能：

確認：

- 欄位名稱
- 欄位型態
- COMMENT 註解

是否正確建立。

---

### 99_run_all_v5.py

用途：

ETL 主程式。

執行流程：

1. 建立資料庫
2. 匯入全部交易資料
3. 匯入直接供應資料
4. 匯入憑證資料
5. 建立維度表
6. 建立事實表
7. 建立 View
8. 建立 Sankey Diagram

---

# SQL 程式說明

---

## 01_create_database_and_tables_v5.sql

用途：

建立 MySQL_GREEN 資料庫。

建立資料表：

### Raw Table

- trec_all_raw
- trec_direct_supply_raw
- trec_certificate_raw

### Dimension Table

- company
- company_alias
- facility
- energy_type
- supply_type

### Fact Table

- transaction_fact
- certificate_fact

---

## 02_create_views_v5.sql

用途：

建立分析 View。

建立 View：

### vw_transaction_detail

交易明細分析。

### vw_top_buyers

前十大買家分析。

### vw_top_sellers

前十大賣家分析。

### vw_sankey_data

Sankey 圖資料來源。

### vw_energy_analysis

能源類型分析。

### vw_certificate_detail

憑證明細分析。

### vw_certificate_energy_summary

能源憑證分析。

### vw_certificate_company_summary

公司憑證分析。

---

# ETL 流程

CSV 原始資料
↓
Raw Table
↓
Dimension Table
↓
Fact Table
↓
Analysis View
↓
Sankey Diagram
↓
Tableau Dashboard