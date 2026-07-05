CREATE SCHEMA IF NOT EXISTS `tibametopics.trec_data`
OPTIONS(location = "asia-east1");

CREATE TABLE IF NOT EXISTS `tibametopics.trec_data.trec_issued_certificate_raw` (
  raw_id INTEGER,
  unit_name STRING,
  facility_name STRING,
  energy_type STRING,
  facility_address STRING,
  installed_capacity STRING,
  shared_company STRING,
  certificate_number STRING,
  trec_last_issue_date STRING,
  generation_period STRING,
  equipment_audit_report STRING,
  power_generation_verification_report STRING,
  transferred_mwh STRING,
  remaining_mwh STRING,
  created_at TIMESTAMP
);
