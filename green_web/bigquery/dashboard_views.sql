-- green_demo_web 儀表板用 BigQuery View 建置 SQL
--
-- 建議執行方式：
--   bq query --use_legacy_sql=false --location=asia-east1 < bigquery/dashboard_views.sql
--
-- 設計目的：
--   1. 將 fact / dim / clean 表的 join 邏輯集中在 BigQuery。
--   2. 讓網站後端不用重複寫複雜 SQL。
--   3. 對齊原本 MySQL 專案中的 `vw_transaction_detail` 概念。
--   4. 讓後續 Looker Studio、API、Dashboard 都可以共用同一層資料定義。

-- ============================================================================
-- View: vw_transaction_detail
-- 用途：
--   儀表板最核心的交易明細 view。
--   將「直轉供交易」與「自用發電交易」整理成同一種欄位格式。
--
-- 來源表：
--   fact_direct_transaction
--   trec_self_generation_transaction_clean
--   dim_company
--   dim_facility
--   dim_energy_type
--   dim_supply_type
--
-- 網站用途：
--   KPI、年月日趨勢、能源類型占比、買賣方排行、交易列表、能源流向圖
--   都可以從這張 view 再彙總出來。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_transaction_detail` (
  transaction_id OPTIONS(description = "交易資料流水號，直轉供使用 transaction_id，自用發電使用 self_clean_id"),
  seller_company_name OPTIONS(description = "出售單位名稱"),
  buyer_company_name OPTIONS(description = "購買者名稱"),
  facility_name OPTIONS(description = "發電設備或案場名稱"),
  energy_type_name OPTIONS(description = "能源類型名稱，例如太陽能、風力能、水力能"),
  supply_type_name OPTIONS(description = "供電種類名稱，無資料時顯示未分類；自用發電資料固定為自用發電"),
  transaction_source_type OPTIONS(description = "交易來源代碼，direct_transaction 為直轉供，self_generation_transaction 為自用發電"),
  transaction_source_name_zh OPTIONS(description = "交易來源中文名稱"),
  transaction_date OPTIONS(description = "交易日期或憑證移轉日期"),
  transaction_mwh OPTIONS(description = "本筆交易移轉量，單位 MWh"),
  total_transfer_mwh OPTIONS(description = "來源資料中的總移轉量，單位 MWh"),
  created_at OPTIONS(description = "資料建立時間")
) AS
WITH direct_transactions AS (
  SELECT
    d.transaction_id AS transaction_id,
    seller.company_name AS seller_company_name,
    buyer.company_name AS buyer_company_name,
    f.facility_name AS facility_name,
    e.energy_type AS energy_type_name,
    COALESCE(s.supply_type_name, '未分類') AS supply_type_name,
    'direct_transaction' AS transaction_source_type,
    '直轉供憑證成交' AS transaction_source_name_zh,
    d.transaction_date AS transaction_date,
    CAST(d.transaction_transfer_mwh AS FLOAT64) AS transaction_mwh,
    CAST(d.total_transfer_mwh AS FLOAT64) AS total_transfer_mwh,
    d.created_at AS created_at
  FROM `tibametopics.trec_data.fact_direct_transaction` d
  LEFT JOIN `tibametopics.trec_data.dim_company` seller
    ON d.seller_company_id = seller.company_id
  LEFT JOIN `tibametopics.trec_data.dim_company` buyer
    ON d.buyer_company_id = buyer.company_id
  LEFT JOIN `tibametopics.trec_data.dim_facility` f
    ON d.facility_id = f.facility_id
  LEFT JOIN `tibametopics.trec_data.dim_energy_type` e
    ON d.energy_type_id = e.energy_type_id
  LEFT JOIN `tibametopics.trec_data.dim_supply_type` s
    ON d.supply_type_id = s.supply_type_id
),
self_generation_transactions AS (
  SELECT
    self_clean_id AS transaction_id,
    seller AS seller_company_name,
    buyer AS buyer_company_name,
    facility_name,
    energy_type AS energy_type_name,
    '自用發電' AS supply_type_name,
    'self_generation_transaction' AS transaction_source_type,
    '自用發電設備憑證成交' AS transaction_source_name_zh,
    transfer_date AS transaction_date,
    CAST(transfer_mwh AS FLOAT64) AS transaction_mwh,
    CAST(transfer_mwh AS FLOAT64) AS total_transfer_mwh,
    created_at
  FROM `tibametopics.trec_data.trec_self_generation_transaction_clean`
)
SELECT *
FROM direct_transactions
UNION ALL
SELECT *
FROM self_generation_transactions;

-- ============================================================================
-- View: vw_dashboard_yearly
-- 用途：
--   年度交易量、交易筆數、出售單位數、購買者數、發電設備數彙總。
--
-- 網站用途：
--   「年度交易量趨勢」圖表與「年度摘要」表格。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_yearly` (
  transaction_year OPTIONS(description = "交易年度"),
  transaction_count OPTIONS(description = "年度交易筆數"),
  seller_company_count OPTIONS(description = "年度出售單位數"),
  buyer_company_count OPTIONS(description = "年度購買者數"),
  facility_count OPTIONS(description = "年度發電設備或案場數"),
  total_transaction_mwh OPTIONS(description = "年度總成交移轉量，單位 MWh")
) AS
SELECT
  EXTRACT(YEAR FROM transaction_date) AS transaction_year,
  COUNT(*) AS transaction_count,
  COUNT(DISTINCT seller_company_name) AS seller_company_count,
  COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
  COUNT(DISTINCT facility_name) AS facility_count,
  SUM(transaction_mwh) AS total_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY transaction_year;

-- ============================================================================
-- View: vw_dashboard_monthly
-- 用途：
--   月度交易量彙總，並拆出直轉供與自用發電兩種來源。
--
-- 網站用途：
--   「每月交易量趨勢」折線圖。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_monthly` (
  transaction_month OPTIONS(description = "交易月份，取該月第一天作為月份代表日期"),
  transaction_count OPTIONS(description = "月交易筆數"),
  total_transaction_mwh OPTIONS(description = "月總成交移轉量，單位 MWh"),
  direct_transaction_mwh OPTIONS(description = "月直轉供成交移轉量，單位 MWh"),
  self_generation_transaction_mwh OPTIONS(description = "月自用發電成交移轉量，單位 MWh")
) AS
SELECT
  DATE_TRUNC(transaction_date, MONTH) AS transaction_month,
  COUNT(*) AS transaction_count,
  SUM(transaction_mwh) AS total_transaction_mwh,
  SUM(IF(transaction_source_type = 'direct_transaction', transaction_mwh, 0)) AS direct_transaction_mwh,
  SUM(IF(transaction_source_type = 'self_generation_transaction', transaction_mwh, 0)) AS self_generation_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY transaction_month;

-- ============================================================================
-- View: vw_dashboard_daily
-- 用途：
--   日交易量彙總，並拆出直轉供與自用發電兩種來源。
--
-- 網站用途：
--   使用者在篩選列把「分析粒度」切成「日」時使用。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_daily` (
  transaction_day OPTIONS(description = "交易日期"),
  transaction_count OPTIONS(description = "日交易筆數"),
  total_transaction_mwh OPTIONS(description = "日總成交移轉量，單位 MWh"),
  direct_transaction_mwh OPTIONS(description = "日直轉供成交移轉量，單位 MWh"),
  self_generation_transaction_mwh OPTIONS(description = "日自用發電成交移轉量，單位 MWh")
) AS
SELECT
  transaction_date AS transaction_day,
  COUNT(*) AS transaction_count,
  SUM(transaction_mwh) AS total_transaction_mwh,
  SUM(IF(transaction_source_type = 'direct_transaction', transaction_mwh, 0)) AS direct_transaction_mwh,
  SUM(IF(transaction_source_type = 'self_generation_transaction', transaction_mwh, 0)) AS self_generation_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY transaction_day;

-- ============================================================================
-- View: vw_dashboard_energy_type
-- 用途：
--   依能源類型彙總交易量與交易筆數。
--
-- 網站用途：
--   「能源類型占比」甜甜圈圖與能源類型篩選選項。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_energy_type` (
  energy_type_name OPTIONS(description = "能源類型名稱"),
  transaction_count OPTIONS(description = "該能源類型交易筆數"),
  total_transaction_mwh OPTIONS(description = "該能源類型總成交移轉量，單位 MWh")
) AS
SELECT
  COALESCE(energy_type_name, '未分類') AS energy_type_name,
  COUNT(*) AS transaction_count,
  SUM(transaction_mwh) AS total_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY energy_type_name;

-- ============================================================================
-- View: vw_dashboard_source
-- 用途：
--   依交易來源彙總交易量與交易筆數。
--   目前來源包含：
--     direct_transaction：直轉供憑證成交
--     self_generation_transaction：自用發電設備憑證成交
--
-- 網站用途：
--   「交易來源」篩選選項與交易來源分析。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_source` (
  transaction_source_type OPTIONS(description = "交易來源代碼"),
  transaction_source_name_zh OPTIONS(description = "交易來源中文名稱"),
  transaction_count OPTIONS(description = "該交易來源交易筆數"),
  total_transaction_mwh OPTIONS(description = "該交易來源總成交移轉量，單位 MWh")
) AS
SELECT
  transaction_source_type,
  transaction_source_name_zh,
  COUNT(*) AS transaction_count,
  SUM(transaction_mwh) AS total_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY transaction_source_type, transaction_source_name_zh;

-- ============================================================================
-- View: vw_dashboard_supply_type
-- 用途：
--   依供電種類彙總交易量與交易筆數。
--
-- 網站用途：
--   「供電種類」篩選選項與供電類型分析。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_supply_type` (
  supply_type_name OPTIONS(description = "供電種類名稱"),
  transaction_count OPTIONS(description = "該供電種類交易筆數"),
  total_transaction_mwh OPTIONS(description = "該供電種類總成交移轉量，單位 MWh")
) AS
SELECT
  COALESCE(supply_type_name, '未分類') AS supply_type_name,
  COUNT(*) AS transaction_count,
  SUM(transaction_mwh) AS total_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY supply_type_name;

-- ============================================================================
-- View: vw_dashboard_seller
-- 用途：
--   依出售單位彙總交易量、交易筆數、買方數、案場數。
--
-- 網站用途：
--   「Top 10 出售單位排行」與「重點公司摘要」。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_seller` (
  seller_company_name OPTIONS(description = "出售單位名稱"),
  transaction_count OPTIONS(description = "該出售單位交易筆數"),
  buyer_company_count OPTIONS(description = "該出售單位對應的購買者數"),
  facility_count OPTIONS(description = "該出售單位對應的發電設備或案場數"),
  total_transaction_mwh OPTIONS(description = "該出售單位總成交移轉量，單位 MWh")
) AS
SELECT
  COALESCE(seller_company_name, '未填寫出售單位') AS seller_company_name,
  COUNT(*) AS transaction_count,
  COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
  COUNT(DISTINCT facility_name) AS facility_count,
  SUM(transaction_mwh) AS total_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY seller_company_name;

-- ============================================================================
-- View: vw_dashboard_buyer
-- 用途：
--   依購買者彙總交易量、交易筆數、賣方數、案場數。
--
-- 網站用途：
--   「Top 10 購買者排行」與公司角色切換為「購買者」時的摘要。
-- ============================================================================
CREATE OR REPLACE VIEW `tibametopics.trec_data.vw_dashboard_buyer` (
  buyer_company_name OPTIONS(description = "購買者名稱"),
  transaction_count OPTIONS(description = "該購買者交易筆數"),
  seller_company_count OPTIONS(description = "該購買者對應的出售單位數"),
  facility_count OPTIONS(description = "該購買者對應的發電設備或案場數"),
  total_transaction_mwh OPTIONS(description = "該購買者總成交移轉量，單位 MWh")
) AS
SELECT
  COALESCE(buyer_company_name, '未填寫購買者') AS buyer_company_name,
  COUNT(*) AS transaction_count,
  COUNT(DISTINCT seller_company_name) AS seller_company_count,
  COUNT(DISTINCT facility_name) AS facility_count,
  SUM(transaction_mwh) AS total_transaction_mwh
FROM `tibametopics.trec_data.vw_transaction_detail`
GROUP BY buyer_company_name;
