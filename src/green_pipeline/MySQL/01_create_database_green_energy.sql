-- ============================================================
-- 資料庫名稱：green_energy_exchange_db
-- 中文名稱：台灣綠電交易資料庫
-- 用途：儲存 T-REC 綠電憑證交易與已發放憑證原始資料，
-- 作為後續資料清洗、正規化與分析使用。
-- 建立日期：2026-06-11
-- ============================================================

CREATE DATABASE IF NOT EXISTS green_energy_exchange_db
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE green_energy_exchange_db;