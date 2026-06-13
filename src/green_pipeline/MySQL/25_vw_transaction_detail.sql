-- ============================================================
-- 檢視表名稱：vw_transaction_detail
-- 中文名稱：交易明細檢視表
-- 用途：將 fact table 的維度 ID 轉回名稱，方便閱讀與查詢。
-- 輸出欄位：
-- transaction_id：交易事實表主鍵
-- source_raw_id：來源 raw_id
-- transaction_source_type：交易來源類型
-- seller_company_name：出售單位名稱
-- buyer_company_name：購買者名稱
-- facility_name：發電設備名稱
-- energy_type_name：能源類型名稱
-- supply_type_name：供電種類名稱
-- certificate_year：憑證年份
-- transaction_date：交易或移轉日期
-- transaction_mwh：交易或移轉量(MWh)
-- total_transfer_mwh：總移轉量(MWh)
-- created_at：資料建立時間
-- ============================================================

USE green_energy_exchange_db;

CREATE OR REPLACE VIEW vw_transaction_detail AS
SELECT
    f.transaction_id AS transaction_id,
    f.source_raw_id AS source_raw_id,
    f.transaction_source_type AS transaction_source_type,
    seller.company_name AS seller_company_name,
    buyer.company_name AS buyer_company_name,
    facility.facility_name AS facility_name,
    energy.energy_type_name AS energy_type_name,
    supply.supply_type_name AS supply_type_name,
    f.certificate_year AS certificate_year,
    f.transaction_date AS transaction_date,
    f.transaction_mwh AS transaction_mwh,
    f.total_transfer_mwh AS total_transfer_mwh,
    f.created_at AS created_at
FROM fact_transaction f
JOIN dim_company seller ON f.seller_company_id = seller.company_id
JOIN dim_company buyer ON f.buyer_company_id = buyer.company_id
JOIN dim_facility facility ON f.facility_id = facility.facility_id
JOIN dim_energy_type energy ON f.energy_type_id = energy.energy_type_id
LEFT JOIN dim_supply_type supply ON f.supply_type_id = supply.supply_type_id;
