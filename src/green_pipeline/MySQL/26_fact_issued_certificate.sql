-- ============================================================
-- 資料表名稱：fact_issued_certificate
-- 中文名稱：已發放憑證事實表
-- 資料來源：trec_issued_certificate_clean
-- 用途：集中管理已發放憑證、移轉量與剩餘量資訊，並關聯各維度表。
-- 主鍵：issued_certificate_id：使用 MySQL AUTO_INCREMENT 流水號
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS fact_issued_certificate (
    issued_certificate_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '已發放憑證事實表主鍵',
    source_raw_id INT NOT NULL COMMENT '來源 raw_id',
    unit_company_id INT NOT NULL COMMENT '單位名稱公司維度主鍵',
    facility_id INT NOT NULL COMMENT '發電設備維度主鍵',
    energy_type_id INT NOT NULL COMMENT '能源類型維度主鍵',
    certificate_year YEAR COMMENT '憑證年份',
    transferred_mwh DECIMAL(12,3) COMMENT '已移轉量(MWh)',
    remaining_mwh DECIMAL(12,3) COMMENT '剩餘量(MWh)',
    certificate_number VARCHAR(35) COMMENT '憑證編號',
    trec_last_issue_date DATE COMMENT 'T-REC最後憑證發放日期',
    generation_start_date DATE COMMENT '發電區間開始日期',
    generation_end_date DATE COMMENT '發電區間結束日期',
    equipment_audit_report VARCHAR(13) COMMENT '再生能源設備查核報告',
    power_generation_verification_report VARCHAR(13) COMMENT '再生能源發電量查證報告',
    detail_transferred_mwh DECIMAL(12,3) COMMENT '詳情_已移轉量(MWh)',
    detail_remaining_mwh DECIMAL(12,3) COMMENT '詳情_剩餘量(MWh)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    UNIQUE KEY uk_fact_issued_certificate_source (source_raw_id),
    CONSTRAINT fk_fact_issued_certificate_unit_company FOREIGN KEY (unit_company_id) REFERENCES dim_company (company_id),
    CONSTRAINT fk_fact_issued_certificate_facility FOREIGN KEY (facility_id) REFERENCES dim_facility (facility_id),
    CONSTRAINT fk_fact_issued_certificate_energy_type FOREIGN KEY (energy_type_id) REFERENCES dim_energy_type (energy_type_id)
) COMMENT='已發放憑證事實表';
