-- ============================================================
-- 資料表名稱：trec_issued_certificate_clean
-- 中文名稱：T-REC 已發放憑證清理資料表
-- 資料來源：trec_issued_certificate_raw
-- 用途：儲存已完成基本型態轉換的已發放憑證資料。
-- 主鍵：clean_id：使用 MySQL AUTO_INCREMENT 流水號
-- 來源追蹤：raw_id：對應 trec_issued_certificate_raw.raw_id
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS trec_issued_certificate_clean (
    clean_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'MySQL 自動流水號，每筆 clean 資料唯一識別碼',
    raw_id INT NOT NULL COMMENT '來源 raw table 的 raw_id',
    unit_name VARCHAR(32) COMMENT '單位名稱',
    facility_name VARCHAR(65) COMMENT '發電設備',
    energy_type VARCHAR(8) COMMENT '能源類型',
    certificate_year YEAR COMMENT '憑證發放年份',
    transferred_mwh DECIMAL(12,3) COMMENT '已移轉量(MWh)',
    remaining_mwh DECIMAL(12,3) COMMENT '剩餘量(MWh)',
    facility_address TEXT COMMENT '發電設備地址',
    installed_capacity_kw DECIMAL(12,3) COMMENT '裝置總容量(kW)',
    shared_company VARCHAR(100) COMMENT '發電設備共用單位',
    certificate_number VARCHAR(35) COMMENT '證書編號',
    trec_last_issue_date DATE COMMENT 'T-REC最後憑證發放日期',
    generation_start_date DATE COMMENT '發電區間開始日期',
    generation_end_date DATE COMMENT '發電區間結束日期',
    equipment_audit_report VARCHAR(13) COMMENT '再生能源設備查核報告',
    power_generation_verification_report VARCHAR(13) COMMENT '再生能源發電量查證報告',
    detail_transferred_mwh DECIMAL(12,3) COMMENT '詳情_已移轉量(MWh)',
    detail_remaining_mwh DECIMAL(12,3) COMMENT '詳情_剩餘量(MWh)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    CONSTRAINT fk_issued_certificate_clean_raw
        FOREIGN KEY (raw_id)
        REFERENCES trec_issued_certificate_raw(raw_id)
) COMMENT='T-REC 已發放憑證清理資料表';
