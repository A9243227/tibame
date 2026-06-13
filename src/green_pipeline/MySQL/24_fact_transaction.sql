-- ============================================================
-- 資料表名稱：fact_transaction
-- 中文名稱：交易事實表
-- 資料來源：trec_direct_transaction_clean、trec_self_generation_transaction_clean
-- 用途：集中管理憑證交易與移轉數值，並關聯各維度表。
-- 主鍵：transaction_id：使用 MySQL AUTO_INCREMENT 流水號
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS fact_transaction (
    transaction_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '交易事實表主鍵',
    source_table VARCHAR(64) NOT NULL COMMENT '來源 clean table 名稱',
    source_raw_id INT NOT NULL COMMENT '來源 raw_id',
    transaction_source_type VARCHAR(32) NOT NULL COMMENT '交易來源類型',
    seller_company_id INT NOT NULL COMMENT '出售單位公司維度主鍵',
    buyer_company_id INT NOT NULL COMMENT '購買者公司維度主鍵',
    facility_id INT NOT NULL COMMENT '發電設備維度主鍵',
    energy_type_id INT NOT NULL COMMENT '能源類型維度主鍵',
    supply_type_id INT COMMENT '供電種類維度主鍵',
    certificate_year YEAR COMMENT '憑證年份',
    transaction_date DATE NOT NULL COMMENT '交易或移轉日期',
    transaction_mwh DECIMAL(12,3) NOT NULL COMMENT '交易或移轉量(MWh)',
    total_transfer_mwh DECIMAL(12,3) COMMENT '總移轉量(MWh)',
    transaction_record_text VARCHAR(80) COMMENT '成交記錄原文',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    UNIQUE KEY uk_fact_transaction_source (source_table, source_raw_id),
    CONSTRAINT fk_fact_transaction_seller_company FOREIGN KEY (seller_company_id) REFERENCES dim_company (company_id),
    CONSTRAINT fk_fact_transaction_buyer_company FOREIGN KEY (buyer_company_id) REFERENCES dim_company (company_id),
    CONSTRAINT fk_fact_transaction_facility FOREIGN KEY (facility_id) REFERENCES dim_facility (facility_id),
    CONSTRAINT fk_fact_transaction_energy_type FOREIGN KEY (energy_type_id) REFERENCES dim_energy_type (energy_type_id),
    CONSTRAINT fk_fact_transaction_supply_type FOREIGN KEY (supply_type_id) REFERENCES dim_supply_type (supply_type_id)
) COMMENT='交易事實表';
