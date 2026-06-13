-- ============================================================
-- 資料表名稱：dim_facility
-- 中文名稱：發電設備維度表
-- 資料來源：clean tables 中的 facility_name、energy_type、facility_address、installed_capacity_kw
-- 用途：集中管理發電設備，供後續 fact tables 關聯使用。
-- 主鍵：facility_id：使用 MySQL AUTO_INCREMENT 流水號
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS dim_facility (
    facility_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '發電設備維度主鍵',
    facility_match_key VARCHAR(255) NOT NULL COMMENT '發電設備判斷鍵',
    facility_name VARCHAR(100) NOT NULL COMMENT '發電設備名稱',
    facility_address TEXT COMMENT '發電設備地址',
    installed_capacity_kw DECIMAL(12,3) COMMENT '裝置容量(kW)',
    energy_type_id INT NOT NULL COMMENT '能源類型維度主鍵',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    UNIQUE KEY uk_dim_facility_match_key (facility_match_key),
    CONSTRAINT fk_dim_facility_energy_type FOREIGN KEY (energy_type_id) REFERENCES dim_energy_type (energy_type_id)
) COMMENT='發電設備維度表';
