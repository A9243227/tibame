CREATE OR REPLACE VIEW `tibametopics.trec_data.trec_issued_certificate_clean_v` AS
SELECT
  raw_id,
  unit_name,
  facility_name,
  energy_type,
  facility_address,
  SAFE_CAST(
    NULLIF(REGEXP_REPLACE(installed_capacity, r'[^0-9.-]', ''), '')
    AS FLOAT64
  ) AS installed_capacity_kw,
  installed_capacity AS installed_capacity_raw,
  shared_company,
  certificate_number,
  SAFE_CAST(trec_last_issue_date AS DATE) AS trec_last_issue_date,
  generation_period,
  SAFE_CAST(SPLIT(generation_period, '~')[SAFE_OFFSET(0)] AS DATE) AS generation_start_date,
  SAFE_CAST(SPLIT(generation_period, '~')[SAFE_OFFSET(1)] AS DATE) AS generation_end_date,
  equipment_audit_report,
  power_generation_verification_report,
  SAFE_CAST(
    NULLIF(REGEXP_REPLACE(transferred_mwh, r'[^0-9.-]', ''), '')
    AS FLOAT64
  ) AS transferred_mwh,
  transferred_mwh AS transferred_mwh_raw,
  SAFE_CAST(
    NULLIF(REGEXP_REPLACE(remaining_mwh, r'[^0-9.-]', ''), '')
    AS FLOAT64
  ) AS remaining_mwh,
  remaining_mwh AS remaining_mwh_raw,
  created_at
FROM `tibametopics.trec_data.trec_issued_certificate_raw`;

CREATE OR REPLACE VIEW `tibametopics.trec_data.trec_dashboard_daily_v` AS
SELECT
  COALESCE(trec_last_issue_date, DATE(created_at)) AS report_date,
  COUNT(*) AS certificate_count,
  SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
  SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
  COUNT(DISTINCT facility_name) AS facility_count,
  COUNT(DISTINCT shared_company) AS company_count
FROM `tibametopics.trec_data.trec_issued_certificate_clean_v`
GROUP BY report_date;

CREATE OR REPLACE VIEW `tibametopics.trec_data.trec_dashboard_energy_type_v` AS
SELECT
  COALESCE(energy_type, '未分類') AS energy_type,
  COUNT(*) AS certificate_count,
  SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
  SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
  COUNT(DISTINCT facility_name) AS facility_count,
  COUNT(DISTINCT shared_company) AS company_count
FROM `tibametopics.trec_data.trec_issued_certificate_clean_v`
GROUP BY energy_type;

CREATE OR REPLACE VIEW `tibametopics.trec_data.trec_dashboard_facility_v` AS
SELECT
  COALESCE(facility_name, '未命名案場') AS facility_name,
  COALESCE(energy_type, '未分類') AS energy_type,
  COUNT(*) AS certificate_count,
  SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
  SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
  COUNT(DISTINCT shared_company) AS company_count,
  MAX(trec_last_issue_date) AS latest_issue_date
FROM `tibametopics.trec_data.trec_issued_certificate_clean_v`
GROUP BY facility_name, energy_type;

CREATE OR REPLACE VIEW `tibametopics.trec_data.trec_dashboard_company_v` AS
SELECT
  COALESCE(shared_company, '未填寫公司') AS shared_company,
  COUNT(*) AS certificate_count,
  SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
  SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
  COUNT(DISTINCT facility_name) AS facility_count,
  MAX(trec_last_issue_date) AS latest_issue_date
FROM `tibametopics.trec_data.trec_issued_certificate_clean_v`
GROUP BY shared_company;
