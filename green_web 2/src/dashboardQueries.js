import { getDatasetTableName } from "./config.js";
import { runQuery } from "./bigqueryClient.js";

// BigQuery 回傳的 NUMERIC / INTEGER 有時會是字串或 null，
// 這裡統一轉成前端圖表可以直接使用的 Number。
const numberValue = (value) => (value == null ? 0 : Number(value));

// BigQuery DATE / TIMESTAMP 在 Node.js SDK 可能回傳字串，
// 也可能回傳 { value: "YYYY-MM-DD" } 這種物件，這裡統一轉成字串。
const dateValue = (value) => {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object" && "value" in value) return String(value.value);
  return String(value);
};

// 網頁所有 dashboard 資料都以這張 BigQuery 明細 view 為主要來源。
// 這樣篩選條件可以套用在 KPI、圖表、排行、明細列表等所有區塊。
const detailView = () => getDatasetTableName("vw_transaction_detail");

// 依照前端傳進來的 query string 組出 BigQuery WHERE 條件。
// 使用 @year / @energy 這種參數化查詢，避免直接把使用者輸入拼進 SQL。
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

// /api/dashboard 會呼叫這個 function。
// 它會一次查 BigQuery 多個統計結果，最後整理成前端 App.vue 需要的 JSON 格式。
export async function fetchDashboard(query = {}) {
  const detailFilter = buildDetailFilters(query);

  // 明細列表分頁設定：預設每頁 50 筆，最多 100 筆，避免一次拉太多資料。
  const recordPageSize = Math.min(Math.max(Number(query.recordPageSize || 50), 1), 100);
  const recordPage = Math.max(Number(query.recordPage || 1), 1);
  const recordOffset = (recordPage - 1) * recordPageSize;

  // 這些查詢彼此沒有相依性，所以用 Promise.all 平行查 BigQuery，
  // 可以讓 dashboard 載入速度比一個一個查更快。
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
    // KPI：總交易筆數、買賣方數、案場數、總成交量、資料期間。
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
    // 月統計：折線圖 / 趨勢圖使用，並拆出直轉供與自發自用兩種來源。
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
    // 日統計：較細的時間序列資料，同樣拆出不同交易來源。
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
    // 能源類型分布：例如太陽能、風力能、生質能等。
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
    // 資料來源分布：例如直轉供憑證成交、自用發電設備憑證成交。
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
    // 供給類型分布：沒有供給類型時統一顯示為「未分類」。
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
    // 賣方排行：依照成交 MWh 排名前 10 名。
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
    // 買方排行：依照成交 MWh 排名前 10 名。
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
    // 年度 KPI：前端年度表格 / 年度趨勢使用。
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
    // 買賣方流向圖：先找出交易量最高的買方與賣方，再統計彼此之間的流量。
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
    // 案場流向：賣方 -> 案場 -> 買方，用於前端 Sankey 或流向表。
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
    // 明細資料總筆數：用來計算分頁總頁數。
    runQuery(
      `
        SELECT COUNT(*) AS record_count
        FROM ${detailView()}
        WHERE ${detailFilter.where}
      `,
      detailFilter.params
    ),
    // 明細列表：依日期與交易量排序，只取目前頁面需要的資料。
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
    // 篩選選項：年份、能源類型、供給類型、資料來源。
    // 這裡不套用目前篩選條件，讓下拉選單永遠保留完整可選項目。
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

  // 將 BigQuery 的 snake_case 欄位整理成前端使用的 camelCase 欄位。
  // 前端 App.vue 只需要吃這個 JSON，不需要知道 BigQuery 原始欄位名稱。
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
