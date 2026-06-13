-- ============================================================
-- 資料表名稱：trec_direct_transaction_clean
-- 中文名稱：T-REC 直轉供憑證成交紀錄清理資料表
-- 資料來源：trec_direct_transaction_raw
-- 用途：儲存已完成基本型態轉換的直轉供憑證成交資料。
-- 主鍵：clean_id：使用 MySQL AUTO_INCREMENT 流水號
-- 來源追蹤：raw_id：對應 trec_direct_transaction_raw.raw_id
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS trec_direct_transaction_clean (
    clean_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'MySQL 自動流水號，每筆 clean 資料唯一識別碼',
    raw_id INT NOT NULL COMMENT '來源 raw table 的 raw_id',
    seller VARCHAR(32) COMMENT '出售單位',
    facility_name VARCHAR(65) COMMENT '發電設備',
    buyer VARCHAR(33) COMMENT '購買者',
    energy_type VARCHAR(8) COMMENT '能源類型',
    supply_type VARCHAR(8) COMMENT '供電種類',
    total_transfer_mwh DECIMAL(12,3) COMMENT '總移轉量(MWh)',
    transaction_date DATE COMMENT '成交日期',
    transaction_transfer_mwh DECIMAL(12,3) COMMENT '成交移轉量(MWh)',
    transaction_record_text VARCHAR(80) COMMENT '成交記錄原文',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    CONSTRAINT fk_direct_clean_raw
        FOREIGN KEY (raw_id)
        REFERENCES trec_direct_transaction_raw(raw_id)
) COMMENT='T-REC 直轉供憑證成交紀錄清理資料表';
