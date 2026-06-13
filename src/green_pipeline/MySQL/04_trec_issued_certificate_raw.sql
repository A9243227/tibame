-- ============================================================
-- 資料表名稱：trec_issued_certificate_raw
-- 中文名稱：T-REC 已發放憑證原始資料表
-- 資料來源：T-REC 官網 - 已發放憑證
-- 用途：儲存從 T-REC 網站抓取之已發放憑證原始資料，保留資料原始樣貌，
-- 作為後續資料清洗、正規化與分析使用。
-- 主鍵：raw_id：使用 MySQL AUTO_INCREMENT 流水號
-- 建立日期：2026-06-11
-- ============================================================

CREATE TABLE trec_issued_certificate_raw (
    raw_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'MySQL 自動流水號，每筆原始資料唯一識別碼',
    -- ============================================================
    unit_name VARCHAR(32) COMMENT '單位名稱',
    facility_name VARCHAR(65) COMMENT '發電設備',
    energy_type VARCHAR(8) COMMENT '能源類型',
    certificate_year VARCHAR(8) COMMENT '憑證發放年份',
    transferred_mwh VARCHAR(20) COMMENT '已移轉量(MWh)',
    remaining_mwh VARCHAR(20) COMMENT '剩餘量(MWh)',
    facility_address TEXT COMMENT '發電設備地址',
    installed_capacity VARCHAR(22) COMMENT '裝置總容量',
    shared_company VARCHAR(100) COMMENT '發電設備共用單位',
    certificate_number VARCHAR(35) COMMENT '證書編號',
    trec_last_issue_date VARCHAR(16) COMMENT 'T-REC最後憑證發放日期',
    generation_period VARCHAR(31) COMMENT '發電區間',
    equipment_audit_report VARCHAR(13) COMMENT '再生能源設備查核報告',
    power_generation_verification_report VARCHAR(13) COMMENT '再生能源發電量查證報告',
    detail_transferred_mwh VARCHAR(24) COMMENT '詳情_已移轉量',
    detail_remaining_mwh VARCHAR(24) COMMENT '詳情_剩餘量',
    -- ============================================================
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間'
) COMMENT='T-REC 已發放憑證原始資料表';
