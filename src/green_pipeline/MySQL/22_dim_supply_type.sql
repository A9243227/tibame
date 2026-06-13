-- ============================================================
-- 資料表名稱：dim_supply_type
-- 中文名稱：供電種類維度表
-- 資料來源：trec_direct_transaction_clean 中的 supply_type
-- 用途：集中管理供電種類，供後續 fact tables 關聯使用。
-- 主鍵：supply_type_id：使用 MySQL AUTO_INCREMENT 流水號
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS dim_supply_type (
    supply_type_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '供電種類維度主鍵',
    supply_type_name VARCHAR(20) NOT NULL COMMENT '供電種類名稱',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    UNIQUE KEY uk_dim_supply_type_name (supply_type_name)
) COMMENT='供電種類維度表';
