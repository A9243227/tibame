-- ============================================================
-- 檢視表名稱：vw_issued_certificate_detail
-- 中文名稱：已發放憑證明細檢視表
-- 用途：將已發放憑證 fact table 的維度 ID 轉回名稱，方便閱讀與查詢。
-- 輸出欄位：
-- issued_certificate_id：已發放憑證事實表主鍵
-- source_raw_id：來源 raw_id
-- unit_company_name：單位名稱
-- facility_name：發電設備名稱
-- facility_address：發電設備地址
-- installed_capacity_kw：裝置容量(kW)
-- energy_type_name：能源類型名稱
-- certificate_year：憑證年份
-- transferred_mwh：已移轉量(MWh)
-- remaining_mwh：剩餘量(MWh)
-- certificate_number：憑證編號
-- trec_last_issue_date：T-REC最後憑證發放日期
-- generation_start_date：發電區間開始日期
-- generation_end_date：發電區間結束日期
-- equipment_audit_report：再生能源設備查核報告
-- power_generation_verification_report：再生能源發電量查證報告
-- detail_transferred_mwh：詳情_已移轉量(MWh)
-- detail_remaining_mwh：詳情_剩餘量(MWh)
-- created_at：資料建立時間
-- ============================================================

USE green_energy_exchange_db;

CREATE OR REPLACE VIEW vw_issued_certificate_detail AS
SELECT
    f.issued_certificate_id AS issued_certificate_id,
    f.source_raw_id AS source_raw_id,
    company.company_name AS unit_company_name,
    facility.facility_name AS facility_name,
    facility.facility_address AS facility_address,
    facility.installed_capacity_kw AS installed_capacity_kw,
    energy.energy_type_name AS energy_type_name,
    f.certificate_year AS certificate_year,
    f.transferred_mwh AS transferred_mwh,
    f.remaining_mwh AS remaining_mwh,
    f.certificate_number AS certificate_number,
    f.trec_last_issue_date AS trec_last_issue_date,
    f.generation_start_date AS generation_start_date,
    f.generation_end_date AS generation_end_date,
    f.equipment_audit_report AS equipment_audit_report,
    f.power_generation_verification_report AS power_generation_verification_report,
    f.detail_transferred_mwh AS detail_transferred_mwh,
    f.detail_remaining_mwh AS detail_remaining_mwh,
    f.created_at AS created_at
FROM fact_issued_certificate f
JOIN dim_company company ON f.unit_company_id = company.company_id
JOIN dim_facility facility ON f.facility_id = facility.facility_id
JOIN dim_energy_type energy ON f.energy_type_id = energy.energy_type_id;
