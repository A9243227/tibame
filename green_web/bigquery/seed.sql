INSERT INTO `tibametopics.trec_data.trec_issued_certificate_raw`
  (
    raw_id,
    unit_name,
    facility_name,
    energy_type,
    facility_address,
    installed_capacity,
    shared_company,
    certificate_number,
    trec_last_issue_date,
    generation_period,
    equipment_audit_report,
    power_generation_verification_report,
    transferred_mwh,
    remaining_mwh,
    created_at
  )
VALUES
  (
    1,
    "再生能源發電業者A",
    "台南太陽光電案場",
    "太陽光電",
    "台南市",
    "1,200 kW",
    "科技公司A",
    "TREC-2026-0001",
    "2026-01-03",
    "2025/12",
    "-",
    "-",
    "120.5",
    "20.1",
    TIMESTAMP "2026-01-03 02:15:00+00"
  ),
  (
    2,
    "再生能源發電業者B",
    "彰化離岸風電案場",
    "風力",
    "彰化縣",
    "3,600 kW",
    "製造公司B",
    "TREC-2026-0002",
    "2026-01-04",
    "2025/12",
    "-",
    "-",
    "360.2",
    "84.7",
    TIMESTAMP "2026-01-04 02:20:00+00"
  );
