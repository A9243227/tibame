-- ============================================================
-- 資料表名稱：trec_direct_transaction_raw
-- 中文名稱：T-REC 直轉供憑證成交紀錄原始資料表
-- 資料來源：T-REC 官網 - 直轉供憑證成交紀錄
-- 用途：儲存從 T-REC 網站抓取之直轉供憑證成交原始資料，保留資料原始樣貌，
-- 作為後續資料清洗、正規化與分析使用。
-- 主鍵：raw_id：使用 MySQL AUTO_INCREMENT 流水號
-- 建立日期：2026-06-11
-- ============================================================

CREATE TABLE trec_direct_transaction_raw (
    raw_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'MySQL 自動流水號，每筆原始資料唯一識別碼',
-- ======================================================================
    seller VARCHAR(32) COMMENT '出售單位',
    facility_name VARCHAR(65) COMMENT '發電設備',
    buyer VARCHAR(33) COMMENT '購買者',
    energy_type VARCHAR(8) COMMENT '能源類型',
    supply_type VARCHAR(8) COMMENT '供電種類',

    total_transfer_mwh VARCHAR(20) COMMENT '總移轉量(MWh)',
    transaction_date VARCHAR(16) COMMENT '成交日期',
    transaction_transfer_mwh VARCHAR(20) COMMENT '成交移轉量(MWh)',
    transaction_record_text VARCHAR(80) COMMENT '成交記錄原文',
-- ======================================================================
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間'
) COMMENT='T-REC 直轉供憑證成交紀錄原始資料表';
