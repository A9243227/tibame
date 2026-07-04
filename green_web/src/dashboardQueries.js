import { getDatasetTableName } from "./config.js";
import { runQuery } from "./bigqueryClient.js";

const numberValue = (value) => (value == null ? 0 : Number(value));
const dateValue = (value) => {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object" && "value" in value) return String(value.value);
  return String(value);
};

const detailView = () => getDatasetTableName("vw_transaction_detail");

function buildDetailFilters(query = {}, dateColumn = "transaction_date") {
  const whereParts = ["1 = 1"];
  const params = {};

  if (query.year && query.year !== "全部") {
    whereParts.push(`EXTRACT(YEAR FROM ${dateColumn}) = @year`);
    params.year = Number(query.year);
  }

  if (query.energy && query.energy !== "全部") {
    whereParts.push("energy_type_name = @energy");
    params.energy = String(query.energy);
  }

  if (query.supply && query.supply !== "全部") {
    whereParts.push("COALESCE(supply_type_name, '未分類') = @supply");
    params.supply = String(query.supply);
  }

  if (query.sourceType && query.sourceType !== "全部") {
    whereParts.push("transaction_source_type = @sourceType");
    params.sourceType = String(query.sourceType);
  }

  return {
    params,
    where: whereParts.join(" AND ")
  };
}

export async function fetchDashboard(query = {}) {
  const detailFilter = buildDetailFilters(query);
  const recordPageSize = Math.min(Math.max(Number(query.recordPageSize || 50), 1), 100);
  const recordPage = Math.max(Number(query.recordPage || 1), 1);
  const recordOffset = (recordPage - 1) * recordPageSize;

  const [
    kpiRows,
    monthlyRows,
    dailyRows,
    energyRows,
    sourceRows,
    supplyRows,
    sellerRows,
    buyerRows,
    yearlyRows,
    flowRows,
    facilityFlowRows,
    recordCountRows,
    recordRows,
    filterRows
  ] = await Promise.all([
    runQuery(
      `
        SELECT
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT seller_company_name) AS seller_company_count,
          COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh,
          MIN(transaction_date) AS first_transaction_date,
          MAX(transaction_date) AS last_transaction_date
        FROM ${detailView()}
        WHERE ${detailFilter.where}
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          FORMAT_DATE('%Y-%m-01', DATE_TRUNC(transaction_date, MONTH)) AS transaction_month,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh,
          SUM(IF(transaction_source_type = 'direct_transaction', transaction_mwh, 0)) AS direct_transaction_mwh,
          SUM(IF(transaction_source_type = 'self_generation_transaction', transaction_mwh, 0)) AS self_generation_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY transaction_month
        ORDER BY transaction_month
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          FORMAT_DATE('%Y-%m-%d', transaction_date) AS transaction_day,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh,
          SUM(IF(transaction_source_type = 'direct_transaction', transaction_mwh, 0)) AS direct_transaction_mwh,
          SUM(IF(transaction_source_type = 'self_generation_transaction', transaction_mwh, 0)) AS self_generation_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY transaction_day
        ORDER BY transaction_day
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          energy_type_name,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY energy_type_name
        ORDER BY total_transaction_mwh DESC
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          transaction_source_type,
          transaction_source_name_zh,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY transaction_source_type, transaction_source_name_zh
        ORDER BY total_transaction_mwh DESC
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          COALESCE(supply_type_name, '未分類') AS supply_type_name,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY supply_type_name
        ORDER BY total_transaction_mwh DESC
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          seller_company_name,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY seller_company_name
        ORDER BY total_transaction_mwh DESC
        LIMIT 10
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          buyer_company_name,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT seller_company_name) AS seller_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY buyer_company_name
        ORDER BY total_transaction_mwh DESC
        LIMIT 10
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          EXTRACT(YEAR FROM transaction_date) AS transaction_year,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT seller_company_name) AS seller_company_count,
          COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY transaction_year
        ORDER BY transaction_year
      `,
      detailFilter.params
    ),
    runQuery(
      `
        WITH filtered AS (
          SELECT *
          FROM ${detailView()}
          WHERE ${detailFilter.where}
        ),
        top_buyers AS (
          SELECT buyer_company_name
          FROM filtered
          GROUP BY buyer_company_name
          ORDER BY SUM(transaction_mwh) DESC
          LIMIT 10
        ),
        top_sellers AS (
          SELECT seller_company_name
          FROM filtered
          GROUP BY seller_company_name
          ORDER BY SUM(transaction_mwh) DESC
          LIMIT 10
        )
        SELECT
          v.seller_company_name,
          v.buyer_company_name,
          v.transaction_source_type,
          v.energy_type_name,
          COUNT(*) AS transaction_count,
          SUM(v.transaction_mwh) AS total_transaction_mwh
        FROM filtered v
        JOIN top_sellers s ON s.seller_company_name = v.seller_company_name
        JOIN top_buyers b ON b.buyer_company_name = v.buyer_company_name
        GROUP BY v.seller_company_name, v.buyer_company_name, v.transaction_source_type, v.energy_type_name
        ORDER BY total_transaction_mwh DESC
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          seller_company_name,
          facility_name,
          buyer_company_name,
          energy_type_name,
          COALESCE(supply_type_name, '未分類') AS supply_type_name,
          transaction_source_type,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        GROUP BY seller_company_name, facility_name, buyer_company_name, energy_type_name, supply_type_name, transaction_source_type
        ORDER BY total_transaction_mwh DESC
        LIMIT 30
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT COUNT(*) AS record_count
        FROM ${detailView()}
        WHERE ${detailFilter.where}
      `,
      detailFilter.params
    ),
    runQuery(
      `
        SELECT
          transaction_date,
          seller_company_name,
          facility_name,
          buyer_company_name,
          energy_type_name,
          COALESCE(supply_type_name, '未分類') AS supply_type_name,
          transaction_source_type,
          transaction_mwh
        FROM ${detailView()}
        WHERE ${detailFilter.where}
        ORDER BY transaction_date DESC, transaction_mwh DESC
        LIMIT @recordPageSize OFFSET @recordOffset
      `,
      { ...detailFilter.params, recordPageSize, recordOffset }
    ),
    runQuery(
      `
        SELECT DISTINCT
          'year' AS option_type,
          CAST(EXTRACT(YEAR FROM transaction_date) AS STRING) AS option_value,
          CAST(EXTRACT(YEAR FROM transaction_date) AS STRING) AS option_label,
          CAST(NULL AS STRING) AS option_extra
        FROM ${detailView()}
        UNION ALL
        SELECT DISTINCT 'energy', energy_type_name, energy_type_name, CAST(NULL AS STRING)
        FROM ${detailView()}
        UNION ALL
        SELECT DISTINCT 'supply', COALESCE(supply_type_name, '未分類'), COALESCE(supply_type_name, '未分類'), CAST(NULL AS STRING)
        FROM ${detailView()}
        UNION ALL
        SELECT DISTINCT
          'source',
          transaction_source_type,
          transaction_source_name_zh,
          transaction_source_type
        FROM ${detailView()}
        ORDER BY option_type, option_label
      `
    )
  ]);

  const kpi = kpiRows[0] || {};
  const recordTotal = numberValue(recordCountRows[0]?.record_count);

  return {
    kpi: {
      transactionCount: numberValue(kpi.transaction_count),
      sellerCompanyCount: numberValue(kpi.seller_company_count),
      buyerCompanyCount: numberValue(kpi.buyer_company_count),
      facilityCount: numberValue(kpi.facility_count),
      totalTransactionMwh: numberValue(kpi.total_transaction_mwh),
      firstTransactionDate: dateValue(kpi.first_transaction_date),
      lastTransactionDate: dateValue(kpi.last_transaction_date)
    },
    monthly: monthlyRows.map((row) => ({
      month: row.transaction_month,
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh),
      directTransactionMwh: numberValue(row.direct_transaction_mwh),
      selfGenerationTransactionMwh: numberValue(row.self_generation_transaction_mwh)
    })),
    daily: dailyRows.map((row) => ({
      day: row.transaction_day,
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh),
      directTransactionMwh: numberValue(row.direct_transaction_mwh),
      selfGenerationTransactionMwh: numberValue(row.self_generation_transaction_mwh)
    })),
    energyTypes: energyRows.map((row) => ({
      name: row.energy_type_name || "未分類",
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    sources: sourceRows.map((row) => ({
      type: row.transaction_source_type,
      name: row.transaction_source_name_zh || row.transaction_source_type,
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    supplies: supplyRows.map((row) => ({
      name: row.supply_type_name,
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    topSellers: sellerRows.map((row) => ({
      name: row.seller_company_name || "未填寫",
      transactionCount: numberValue(row.transaction_count),
      buyerCompanyCount: numberValue(row.buyer_company_count),
      facilityCount: numberValue(row.facility_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    topBuyers: buyerRows.map((row) => ({
      name: row.buyer_company_name || "未填寫",
      transactionCount: numberValue(row.transaction_count),
      sellerCompanyCount: numberValue(row.seller_company_count),
      facilityCount: numberValue(row.facility_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    kpiByYear: yearlyRows.map((row) => ({
      year: String(row.transaction_year),
      transactionCount: numberValue(row.transaction_count),
      sellerCompanyCount: numberValue(row.seller_company_count),
      buyerCompanyCount: numberValue(row.buyer_company_count),
      facilityCount: numberValue(row.facility_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    filterOptions: {
      years: filterRows.filter((row) => row.option_type === "year").map((row) => row.option_label),
      energyTypes: filterRows.filter((row) => row.option_type === "energy").map((row) => row.option_label),
      supplyTypes: filterRows.filter((row) => row.option_type === "supply").map((row) => row.option_label),
      sources: filterRows
        .filter((row) => row.option_type === "source")
        .map((row) => ({ label: row.option_label, type: row.option_extra || row.option_value }))
    },
    flows: flowRows.map((row) => ({
      seller: row.seller_company_name,
      buyer: row.buyer_company_name,
      sourceType: row.transaction_source_type,
      energyType: row.energy_type_name,
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    facilityFlows: facilityFlowRows.map((row) => ({
      seller: row.seller_company_name,
      facility: row.facility_name,
      buyer: row.buyer_company_name,
      energyType: row.energy_type_name,
      supplyType: row.supply_type_name,
      sourceType: row.transaction_source_type,
      transactionCount: numberValue(row.transaction_count),
      totalTransactionMwh: numberValue(row.total_transaction_mwh)
    })),
    records: recordRows.map((row) => ({
      date: dateValue(row.transaction_date),
      seller: row.seller_company_name,
      facility: row.facility_name,
      buyer: row.buyer_company_name,
      energyType: row.energy_type_name,
      supplyType: row.supply_type_name,
      sourceType: row.transaction_source_type,
      transactionMwh: numberValue(row.transaction_mwh)
    })),
    recordPage,
    recordPageSize,
    recordTotal,
    recordTotalPages: Math.max(Math.ceil(recordTotal / recordPageSize), 1)
  };
}
