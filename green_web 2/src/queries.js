import { getDatasetTableName } from "./config.js";
import { runQuery } from "./bigqueryClient.js";

export async function fetchSites() {
  const query = `
    SELECT DISTINCT f.facility_name AS site
    FROM ${getDatasetTableName("fact_issued_certificate")} cert
    JOIN ${getDatasetTableName("dim_facility")} f
      ON cert.facility_id = f.facility_id
    WHERE f.facility_name IS NOT NULL
    ORDER BY site
  `;

  const rows = await runQuery(query);
  return rows.map((row) => row.site);
}

export async function fetchSummary({ from, to, site }) {
  const siteFilter = site ? "AND f.facility_name = @site" : "";

  const query = `
    WITH filtered AS (
      SELECT
        cert.issued_certificate_id,
        unit_company.company_name AS unit_name,
        f.facility_name,
        e.energy_type,
        shared_company.company_name AS shared_company,
        cert.certificate_number,
        cert.trec_last_issue_date,
        cert.generation_start_date,
        cert.generation_end_date,
        CAST(cert.transferred_mwh AS FLOAT64) AS transferred_mwh,
        CAST(cert.remaining_mwh AS FLOAT64) AS remaining_mwh,
        cert.created_at
      FROM ${getDatasetTableName("fact_issued_certificate")} cert
      LEFT JOIN ${getDatasetTableName("dim_facility")} f
        ON cert.facility_id = f.facility_id
      LEFT JOIN ${getDatasetTableName("dim_energy_type")} e
        ON cert.energy_type_id = e.energy_type_id
      LEFT JOIN ${getDatasetTableName("dim_company")} unit_company
        ON cert.unit_company_id = unit_company.company_id
      LEFT JOIN ${getDatasetTableName("dim_company")} shared_company
        ON cert.shared_company_id = shared_company.company_id
      WHERE cert.trec_last_issue_date BETWEEN @from AND @to
      ${siteFilter}
    ),
    daily AS (
      SELECT
        trec_last_issue_date AS event_date,
        SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
        SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
        COUNT(*) AS certificate_count
      FROM filtered
      GROUP BY event_date
    ),
    by_energy_type AS (
      SELECT
        COALESCE(energy_type, '未分類') AS category,
        SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
        COUNT(*) AS certificate_count
      FROM filtered
      GROUP BY category
    ),
    by_facility AS (
      SELECT
        COALESCE(facility_name, '未命名案場') AS facility_name,
        COALESCE(energy_type, '未分類') AS energy_type,
        SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
        SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
        COUNT(*) AS certificate_count
      FROM filtered
      GROUP BY facility_name, energy_type
    ),
    by_company AS (
      SELECT
        COALESCE(shared_company, '未填寫公司') AS shared_company,
        SUM(COALESCE(transferred_mwh, 0)) AS transferred_mwh,
        SUM(COALESCE(remaining_mwh, 0)) AS remaining_mwh,
        COUNT(*) AS certificate_count
      FROM filtered
      GROUP BY shared_company
    )
    SELECT
      (
        SELECT AS STRUCT
          COUNT(*) AS certificate_count,
          COALESCE(SUM(transferred_mwh), 0) AS transferred_mwh,
          COALESCE(SUM(remaining_mwh), 0) AS remaining_mwh,
          COUNT(DISTINCT facility_name) AS facility_count,
          COUNT(DISTINCT shared_company) AS company_count,
          COUNT(DISTINCT energy_type) AS energy_type_count
        FROM filtered
      ) AS totals,
      ARRAY(
        SELECT AS STRUCT
          CAST(event_date AS STRING) AS event_date,
          transferred_mwh,
          remaining_mwh,
          certificate_count
        FROM daily
        ORDER BY event_date
      ) AS daily,
      ARRAY(
        SELECT AS STRUCT
          category,
          transferred_mwh,
          certificate_count
        FROM by_energy_type
        ORDER BY transferred_mwh DESC
      ) AS categories
      ,
      ARRAY(
        SELECT AS STRUCT
          facility_name,
          energy_type,
          transferred_mwh,
          remaining_mwh,
          certificate_count
        FROM by_facility
        ORDER BY transferred_mwh DESC, certificate_count DESC
        LIMIT 10
      ) AS facilities,
      ARRAY(
        SELECT AS STRUCT
          shared_company,
          transferred_mwh,
          remaining_mwh,
          certificate_count
        FROM by_company
        ORDER BY transferred_mwh DESC, certificate_count DESC
        LIMIT 10
      ) AS companies,
      ARRAY(
        SELECT AS STRUCT
          CAST(issued_certificate_id AS STRING) AS raw_id,
          unit_name,
          facility_name,
          energy_type,
          shared_company,
          certificate_number,
          CAST(trec_last_issue_date AS STRING) AS trec_last_issue_date,
          CONCAT(CAST(generation_start_date AS STRING), '~', CAST(generation_end_date AS STRING)) AS generation_period,
          transferred_mwh,
          remaining_mwh
        FROM filtered
        ORDER BY trec_last_issue_date DESC, issued_certificate_id DESC
        LIMIT 12
      ) AS recent
  `;

  const [row] = await runQuery(query, { from, to, ...(site ? { site } : {}) });

  return {
    totals: normalizeRecord(row?.totals),
    daily: normalizeRepeated(row?.daily),
    categories: normalizeRepeated(row?.categories),
    facilities: normalizeRepeated(row?.facilities),
    companies: normalizeRepeated(row?.companies),
    recent: normalizeRepeated(row?.recent)
  };
}

function normalizeRepeated(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(normalizeRecord);
  return value.map((item) => normalizeRecord(item));
}

function normalizeRecord(value = {}) {
  const record = value.value || value;

  return Object.fromEntries(
    Object.entries(record).map(([key, fieldValue]) => [key, normalizeBigQueryValue(fieldValue)])
  );
}

function normalizeBigQueryValue(value) {
  if (value && typeof value === "object" && "value" in value) {
    return value.value;
  }

  return value;
}
