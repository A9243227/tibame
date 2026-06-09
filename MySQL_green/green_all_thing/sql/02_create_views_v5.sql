-- =========================================================
-- Taiwan Green Power Project V5 Final - Column Fixed Views
-- =========================================================

USE Tibame_G3;

CREATE OR REPLACE VIEW vw_transaction_detail AS
SELECT
    tf.transaction_id,
    tf.raw_id,
    seller.company_name AS seller,
    buyer.company_name AS buyer,
    f.facility_name,
    et.energy_type_name,
    st.supply_type_name,
    tf.transfer_mwh,
    tf.transaction_date,
    tf.source_table
FROM transaction_fact tf
LEFT JOIN company seller ON tf.seller_company_id = seller.company_id
LEFT JOIN company buyer ON tf.buyer_company_id = buyer.company_id
LEFT JOIN facility f ON tf.facility_id = f.facility_id
LEFT JOIN energy_type et ON tf.energy_type_id = et.energy_type_id
LEFT JOIN supply_type st ON tf.supply_type_id = st.supply_type_id;

CREATE OR REPLACE VIEW vw_top_buyers AS
SELECT buyer, SUM(transfer_mwh) AS total_mwh
FROM vw_transaction_detail
WHERE buyer IS NOT NULL
GROUP BY buyer
ORDER BY total_mwh DESC;

CREATE OR REPLACE VIEW vw_top_sellers AS
SELECT seller, SUM(transfer_mwh) AS total_mwh
FROM vw_transaction_detail
WHERE seller IS NOT NULL
GROUP BY seller
ORDER BY total_mwh DESC;

CREATE OR REPLACE VIEW vw_sankey_data AS
SELECT
    seller AS source,
    buyer AS target,
    SUM(transfer_mwh) AS value
FROM vw_transaction_detail
WHERE seller IS NOT NULL
  AND buyer IS NOT NULL
  AND transfer_mwh IS NOT NULL
GROUP BY seller, buyer
HAVING value > 0
ORDER BY value DESC;

CREATE OR REPLACE VIEW vw_energy_analysis AS
SELECT
    energy_type_name,
    SUM(transfer_mwh) AS total_mwh
FROM vw_transaction_detail
WHERE energy_type_name IS NOT NULL
GROUP BY energy_type_name
ORDER BY total_mwh DESC;

CREATE OR REPLACE VIEW vw_certificate_detail AS
SELECT
    cf.certificate_fact_id,
    cf.raw_id,
    seller.company_name AS seller,
    co_owner.company_name AS co_owner,
    f.facility_name,
    f.facility_location,
    f.capacity,
    et.energy_type_name,
    cf.certificate_no,
    cf.vintage_year,
    cf.transferred_mwh,
    cf.balance_mwh,
    cf.trec_last_issue_date,
    cf.generation_period,
    cf.inspection_report,
    cf.verification_report
FROM certificate_fact cf
LEFT JOIN company seller ON cf.seller_company_id = seller.company_id
LEFT JOIN company co_owner ON cf.co_owner_company_id = co_owner.company_id
LEFT JOIN facility f ON cf.facility_id = f.facility_id
LEFT JOIN energy_type et ON cf.energy_type_id = et.energy_type_id;

CREATE OR REPLACE VIEW vw_certificate_energy_summary AS
SELECT
    energy_type_name,
    SUM(transferred_mwh) AS total_transferred_mwh,
    SUM(balance_mwh) AS total_balance_mwh,
    COUNT(*) AS certificate_count
FROM vw_certificate_detail
WHERE energy_type_name IS NOT NULL
GROUP BY energy_type_name
ORDER BY total_balance_mwh DESC;

CREATE OR REPLACE VIEW vw_certificate_company_summary AS
SELECT
    seller,
    SUM(transferred_mwh) AS total_transferred_mwh,
    SUM(balance_mwh) AS total_balance_mwh,
    COUNT(*) AS certificate_count
FROM vw_certificate_detail
WHERE seller IS NOT NULL
GROUP BY seller
ORDER BY total_balance_mwh DESC;
