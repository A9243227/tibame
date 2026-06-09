-- =========================================================
-- Taiwan Green Power Project V5 Final - Column Fixed
-- 專題：台灣綠電交易資料分析
--
-- 修正版重點：
-- 1. Raw Table 欄位完整對應目前三份 CSV。
-- 2. 欄位名稱使用英文。
-- 3. 中文欄位說明放在 COMMENT。
-- 4. 保留原始資料重要欄位，不再過度精簡。
-- =========================================================

DROP DATABASE IF EXISTS Tibame_G3;
CREATE DATABASE Tibame_G3
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE Tibame_G3;

-- =========================================================
-- Raw Table 1：直轉供憑證成交紀錄原始資料
-- 對應 CSV 欄位：
-- 出售單位、發電設備、購買者、能源類型、供電種類、總移轉量(MWh)、成交日期、成交移轉量(MWh)、成交記錄原文
-- =========================================================
CREATE TABLE trec_all_raw (
    raw_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '原始資料流水號',

    seller VARCHAR(255) COMMENT '出售單位',
    facility_name VARCHAR(500) COMMENT '發電設備',
    buyer VARCHAR(255) COMMENT '購買者',
    energy_type VARCHAR(100) COMMENT '能源類型',
    supply_type VARCHAR(100) COMMENT '供電種類',

    total_transfer_mwh DECIMAL(18,4) NULL COMMENT '總移轉量(MWh)',
    transaction_date DATE NULL COMMENT '成交日期',
    transaction_transfer_mwh DECIMAL(18,4) NULL COMMENT '成交移轉量(MWh)',
    transaction_detail_raw TEXT COMMENT '成交記錄原文',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間'
) COMMENT='直轉供憑證成交紀錄原始資料表';

-- =========================================================
-- Raw Table 2：自用發電設備憑證成交紀錄原始資料
-- 對應 CSV 欄位：
-- 出售單位、發電設備、購買者、能源類型、移轉量(MWh)、憑證發放年份、移轉日期
-- =========================================================
CREATE TABLE trec_direct_supply_raw (
    raw_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '原始資料流水號',

    seller VARCHAR(255) COMMENT '出售單位',
    facility_name VARCHAR(500) COMMENT '發電設備',
    buyer VARCHAR(255) COMMENT '購買者',
    energy_type VARCHAR(100) COMMENT '能源類型',

    transfer_mwh DECIMAL(18,4) NULL COMMENT '移轉量(MWh)',
    certificate_year INT NULL COMMENT '憑證發放年份',
    transfer_date DATE NULL COMMENT '移轉日期',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間'
) COMMENT='自用發電設備憑證成交紀錄原始資料表';

-- =========================================================
-- Raw Table 3：憑證原始資料
-- 對應 CSV 欄位：
-- 出售單位、發電設備、能源類型、憑證發放年份、已移轉量(MWh)、剩餘量(MWh)、
-- 發電設備地址、裝置總容量、發電設備共用單位、證書編號、T-REC最後憑證發放日期、
-- 發電區間、再生能源設備查核報告、再生能源發電量查證報告、詳情_已移轉量、詳情_剩餘量
-- =========================================================
CREATE TABLE trec_certificate_raw (
    raw_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '原始資料流水號',

    seller VARCHAR(255) COMMENT '出售單位',
    facility_name VARCHAR(500) COMMENT '發電設備',
    energy_type VARCHAR(100) COMMENT '能源類型',

    vintage_year INT NULL COMMENT '憑證發放年份',
    transferred_mwh DECIMAL(18,4) NULL COMMENT '已移轉量(MWh)',
    balance_mwh DECIMAL(18,4) NULL COMMENT '剩餘量(MWh)',

    facility_location TEXT COMMENT '發電設備地址',
    capacity VARCHAR(100) COMMENT '裝置總容量',
    co_owner VARCHAR(255) COMMENT '發電設備共用單位',
    certificate_no VARCHAR(255) COMMENT '證書編號',

    trec_last_issue_date DATE NULL COMMENT 'T-REC最後憑證發放日期',
    generation_period VARCHAR(100) COMMENT '發電區間',
    inspection_report VARCHAR(255) COMMENT '再生能源設備查核報告',
    verification_report VARCHAR(255) COMMENT '再生能源發電量查證報告',

    detail_transferred_mwh DECIMAL(18,4) NULL COMMENT '詳情_已移轉量',
    detail_available_mwh DECIMAL(18,4) NULL COMMENT '詳情_剩餘量',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間'
) COMMENT='憑證持有與發放原始資料表';

-- =========================================================
-- Dimension Table：公司別名
-- =========================================================
CREATE TABLE company_alias (
    alias_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '公司別名流水號',
    alias_name VARCHAR(255) NOT NULL COMMENT '公司別名或原始公司名稱',
    standard_company_name VARCHAR(255) NOT NULL COMMENT '標準公司名稱',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',
    UNIQUE KEY uk_alias_name (alias_name)
) COMMENT='公司名稱別名對照表';

-- =========================================================
-- Dimension Table：公司
-- =========================================================
CREATE TABLE company (
    company_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '公司資料流水號',
    company_name VARCHAR(255) NOT NULL COMMENT '公司名稱',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',
    UNIQUE KEY uk_company_name (company_name)
) COMMENT='公司資料表';

-- =========================================================
-- Dimension Table：發電設備
-- =========================================================
CREATE TABLE facility (
    facility_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '發電設備資料流水號',
    facility_name VARCHAR(500) NOT NULL COMMENT '發電設備',
    facility_location TEXT COMMENT '發電設備地址',
    capacity VARCHAR(100) COMMENT '裝置總容量',
    owner_company_id BIGINT NULL COMMENT '設備所有者公司ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',
    UNIQUE KEY uk_facility_name (facility_name),
    CONSTRAINT fk_facility_owner_company
        FOREIGN KEY (owner_company_id) REFERENCES company(company_id)
) COMMENT='發電設備資料表';

-- =========================================================
-- Dimension Table：能源類型
-- =========================================================
CREATE TABLE energy_type (
    energy_type_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '能源類型資料流水號',
    energy_type_name VARCHAR(100) NOT NULL COMMENT '能源類型',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',
    UNIQUE KEY uk_energy_type_name (energy_type_name)
) COMMENT='能源類型資料表';

-- =========================================================
-- Dimension Table：供電種類
-- =========================================================
CREATE TABLE supply_type (
    supply_type_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '供電種類資料流水號',
    supply_type_name VARCHAR(100) NOT NULL COMMENT '供電種類',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',
    UNIQUE KEY uk_supply_type_name (supply_type_name)
) COMMENT='供電種類資料表';

-- =========================================================
-- Fact Table：交易交易事實表
-- =========================================================
CREATE TABLE transaction_fact (
    transaction_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '交易事實流水號',

    seller_company_id BIGINT NULL COMMENT '出售單位公司ID',
    buyer_company_id BIGINT NULL COMMENT '購買者公司ID',
    facility_id BIGINT NULL COMMENT '發電設備ID',
    energy_type_id BIGINT NULL COMMENT '能源類型ID',
    supply_type_id BIGINT NULL COMMENT '供電種類ID',

    transfer_mwh DECIMAL(18,4) NULL COMMENT '移轉量(MWh)',
    transaction_date DATE NULL COMMENT '交易日期',
    source_table VARCHAR(100) COMMENT '來源資料表',
    raw_id BIGINT NULL COMMENT '來源 Raw Table 的 raw_id',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',

    CONSTRAINT fk_tf_seller_company FOREIGN KEY (seller_company_id) REFERENCES company(company_id),
    CONSTRAINT fk_tf_buyer_company FOREIGN KEY (buyer_company_id) REFERENCES company(company_id),
    CONSTRAINT fk_tf_facility FOREIGN KEY (facility_id) REFERENCES facility(facility_id),
    CONSTRAINT fk_tf_energy_type FOREIGN KEY (energy_type_id) REFERENCES energy_type(energy_type_id),
    CONSTRAINT fk_tf_supply_type FOREIGN KEY (supply_type_id) REFERENCES supply_type(supply_type_id)
) COMMENT='綠電交易交易事實表';

-- =========================================================
-- Fact Table：憑證交易事實表
-- =========================================================
CREATE TABLE certificate_fact (
    certificate_fact_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '憑證事實流水號',

    seller_company_id BIGINT NULL COMMENT '出售單位公司ID',
    co_owner_company_id BIGINT NULL COMMENT '發電設備共用單位公司ID',
    facility_id BIGINT NULL COMMENT '發電設備ID',
    energy_type_id BIGINT NULL COMMENT '能源類型ID',

    certificate_no VARCHAR(255) COMMENT '證書編號',
    vintage_year INT NULL COMMENT '憑證發放年份',
    transferred_mwh DECIMAL(18,4) NULL COMMENT '已移轉量(MWh)',
    balance_mwh DECIMAL(18,4) NULL COMMENT '剩餘量(MWh)',
    trec_last_issue_date DATE NULL COMMENT 'T-REC最後憑證發放日期',
    generation_period VARCHAR(100) COMMENT '發電區間',
    inspection_report VARCHAR(255) COMMENT '再生能源設備查核報告',
    verification_report VARCHAR(255) COMMENT '再生能源發電量查證報告',
    raw_id BIGINT NULL COMMENT '來源 trec_certificate_raw.raw_id',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '建立時間',

    CONSTRAINT fk_cf_seller_company FOREIGN KEY (seller_company_id) REFERENCES company(company_id),
    CONSTRAINT fk_cf_co_owner_company FOREIGN KEY (co_owner_company_id) REFERENCES company(company_id),
    CONSTRAINT fk_cf_facility FOREIGN KEY (facility_id) REFERENCES facility(facility_id),
    CONSTRAINT fk_cf_energy_type FOREIGN KEY (energy_type_id) REFERENCES energy_type(energy_type_id)
) COMMENT='憑證持有與發放交易事實表';
