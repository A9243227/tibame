-- =========================================================
-- Taiwan Green Power Project V5 Final
-- 分析 View 建立檔
-- 用途：將 Fact Table 與 Dimension Table 進行關聯，
-- 建立分析層 View，提供 Tableau、Power BI、
-- Sankey Diagram 與後續 SQL 分析使用。
-- =========================================================

USE Tibame_G3;

-- =========================================================
-- View：vw_transaction_detail
-- 用途：將綠電交易事實表(transaction_fact)與各維度表(company、facility、energy_type、
-- supply_type)進行 JOIN。
-- 功能：將原本只有 ID 的資料轉換為可閱讀名稱，方便後續分析與報表使用。
-- 主要分析：
-- 賣家、買家、能源類型、供電種類、
-- 移轉量(MWh)、交易日期
-- =========================================================
CREATE OR REPLACE VIEW vw_transaction_detail AS
SELECT
    tf.transaction_id,
    tf.raw_id,
    seller.company_name AS seller,
    buyer.company_name AS buyer,
    f.facility_name,
    et.energy_type_name,
    st.supply_type_name,
    tf.transfer_mwh,
    tf.transaction_date,
    tf.source_table
FROM transaction_fact tf
LEFT JOIN company seller ON tf.seller_company_id = seller.company_id
LEFT JOIN company buyer ON tf.buyer_company_id = buyer.company_id
LEFT JOIN facility f ON tf.facility_id = f.facility_id
LEFT JOIN energy_type et ON tf.energy_type_id = et.energy_type_id
LEFT JOIN supply_type st ON tf.supply_type_id = st.supply_type_id;

-- =========================================================
-- View：vw_top_buyers
-- 用途：統計綠電購買量最高的企業。
-- 功能：將所有交易依照買家進行加總，計算累積購買綠電量(MWh)。
-- 應用：
-- Tableau 排名分析
-- 前十大買家分析
-- =========================================================
CREATE OR REPLACE VIEW vw_top_buyers AS
SELECT buyer, SUM(transfer_mwh) AS total_mwh
FROM vw_transaction_detail
WHERE buyer IS NOT NULL
GROUP BY buyer
ORDER BY total_mwh DESC;
-- =========================================================
-- View：vw_top_sellers
-- 用途：統計綠電銷售量最高的企業。
-- 功能：將所有交易依照賣家進行加總，計算累積售出綠電量(MWh)。
-- 應用：
-- 前十大售電公司分析
-- 綠電供應商排名分析
-- =========================================================

CREATE OR REPLACE VIEW vw_top_sellers AS
SELECT seller, SUM(transfer_mwh) AS total_mwh
FROM vw_transaction_detail
WHERE seller IS NOT NULL
GROUP BY seller
ORDER BY total_mwh DESC;

-- =========================================================
-- View：vw_sankey_data
-- 用途：提供 Sankey Diagram 使用資料。
-- 功能：將賣家視為 Source，買家視為 Target，移轉量(MWh)視為 Flow Value。
-- 應用：
-- Sankey Diagram
-- 綠電流向分析
-- =========================================================

CREATE OR REPLACE VIEW vw_sankey_data AS
SELECT
    seller AS source,
    buyer AS target,
    SUM(transfer_mwh) AS value
FROM vw_transaction_detail
WHERE seller IS NOT NULL
  AND buyer IS NOT NULL
  AND transfer_mwh IS NOT NULL
GROUP BY seller, buyer
HAVING value > 0
ORDER BY value DESC;

-- =========================================================
-- View：vw_energy_analysis
-- 用途：分析各能源類型的交易量。
-- 功能：將交易資料依能源類型進行加總。
-- 分析項目：太陽能、風力、水力、生質能、地熱
-- =========================================================
CREATE OR REPLACE VIEW vw_energy_analysis AS
SELECT
    energy_type_name,
    SUM(transfer_mwh) AS total_mwh
FROM vw_transaction_detail
WHERE energy_type_name IS NOT NULL
GROUP BY energy_type_name
ORDER BY total_mwh DESC;

-- =========================================================
-- View：vw_certificate_detail
-- 用途：將綠電憑證資料與維度表進行整合。
-- 功能：將憑證資訊轉換為完整分析資料。
-- 主要分析：、憑證編號、設備名稱、能源類型、持有人、共同持有人、已移轉量、剩餘量
-- =========================================================
CREATE OR REPLACE VIEW vw_certificate_detail AS
SELECT
    cf.certificate_fact_id,
    cf.raw_id,
    seller.company_name AS seller,
    co_owner.company_name AS co_owner,
    f.facility_name,
    f.facility_location,
    f.capacity,
    et.energy_type_name,
    cf.certificate_no,
    cf.vintage_year,
    cf.transferred_mwh,
    cf.balance_mwh,
    cf.trec_last_issue_date,
    cf.generation_period,
    cf.inspection_report,
    cf.verification_report
FROM certificate_fact cf
LEFT JOIN company seller ON cf.seller_company_id = seller.company_id
LEFT JOIN company co_owner ON cf.co_owner_company_id = co_owner.company_id
LEFT JOIN facility f ON cf.facility_id = f.facility_id
LEFT JOIN energy_type et ON cf.energy_type_id = et.energy_type_id;

-- =========================================================
-- View：vw_certificate_energy_summary
-- 用途：分析各能源類型的憑證分布狀況。
-- 功能：目前還想不到XDDD
-- 統計：
-- 1. 已移轉量
-- 2. 剩餘量
-- 3. 憑證數量
-- =========================================================
CREATE OR REPLACE VIEW vw_certificate_energy_summary AS
SELECT
    energy_type_name,
    SUM(transferred_mwh) AS total_transferred_mwh,
    SUM(balance_mwh) AS total_balance_mwh,
    COUNT(*) AS certificate_count
FROM vw_certificate_detail
WHERE energy_type_name IS NOT NULL
GROUP BY energy_type_name
ORDER BY total_balance_mwh DESC;

-- =========================================================
-- View：vw_certificate_company_summary
-- 用途：分析各公司持有的綠電憑證狀況。
-- 功能：跟上面一樣建好玩的還不知道有沒有用
-- 統計：
-- 1. 已移轉量
-- 2. 剩餘量
-- 3. 持有憑證數量
-- 應用：
-- 公司綠電憑證排名分析
-- RE100 採購分析
-- =========================================================
CREATE OR REPLACE VIEW vw_certificate_company_summary AS
SELECT
    seller,
    SUM(transferred_mwh) AS total_transferred_mwh,
    SUM(balance_mwh) AS total_balance_mwh,
    COUNT(*) AS certificate_count
FROM vw_certificate_detail
WHERE seller IS NOT NULL
GROUP BY seller
ORDER BY total_balance_mwh DESC;
