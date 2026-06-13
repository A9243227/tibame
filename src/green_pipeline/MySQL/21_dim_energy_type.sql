-- ============================================================
-- 資料表名稱：dim_energy_type
-- 中文名稱：能源類型維度表
-- 資料來源：clean tables 中的 energy_type
-- 用途：集中管理能源類型，供後續 fact tables 關聯使用。
-- 主鍵：energy_type_id：使用 MySQL AUTO_INCREMENT 流水號
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS dim_energy_type (
    energy_type_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '能源類型維度主鍵',
    energy_type_name VARCHAR(20) NOT NULL COMMENT '能源類型名稱',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    UNIQUE KEY uk_dim_energy_type_name (energy_type_name)
) COMMENT='能源類型維度表';
