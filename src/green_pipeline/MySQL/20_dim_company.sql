-- ============================================================
-- 資料表名稱：dim_company
-- 中文名稱：公司維度表
-- 資料來源：clean tables 中的 seller、buyer、unit_name
-- 用途：集中管理公司與單位名稱，供後續 fact tables 關聯使用。
-- 主鍵：company_id：使用 MySQL AUTO_INCREMENT 流水號
-- ============================================================

USE green_energy_exchange_db;

CREATE TABLE IF NOT EXISTS dim_company (
    company_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '公司維度主鍵',
    company_name VARCHAR(100) NOT NULL COMMENT '公司或單位名稱',
    is_seller TINYINT(1) DEFAULT 0 COMMENT '是否出現在出售單位欄位',
    is_buyer TINYINT(1) DEFAULT 0 COMMENT '是否出現在購買者欄位',
    is_unit_name TINYINT(1) DEFAULT 0 COMMENT '是否出現在已發放憑證的單位名稱欄位',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '資料建立時間',
    UNIQUE KEY uk_dim_company_name (company_name)
) COMMENT='公司維度表';
