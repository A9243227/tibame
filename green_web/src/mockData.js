const rows = [
  [1, "再生能源發電業者A", "台南太陽光電案場", "太陽光電", "科技公司A", "TREC-2026-0001", "2026-01-03", "2025/12", 120.5, 20.1, "2026-01-03T02:15:00.000Z"],
  [2, "再生能源發電業者B", "彰化離岸風電案場", "風力", "製造公司B", "TREC-2026-0002", "2026-01-04", "2025/12", 360.2, 84.7, "2026-01-04T02:20:00.000Z"],
  [3, "再生能源發電業者A", "台南太陽光電案場", "太陽光電", "半導體公司C", "TREC-2026-0003", "2026-01-05", "2025/12", 88.3, 12.4, "2026-01-05T02:22:00.000Z"],
  [4, "再生能源發電業者C", "屏東生質能案場", "生質能", "食品公司D", "TREC-2026-0004", "2026-01-05", "2025/12", 42.0, 5.5, "2026-01-05T03:00:00.000Z"],
  [5, "再生能源發電業者B", "彰化離岸風電案場", "風力", "科技公司A", "TREC-2026-0005", "2026-01-06", "2025/12", 215.8, 44.0, "2026-01-06T02:32:00.000Z"]
].map(([
  raw_id,
  unit_name,
  facility_name,
  energy_type,
  shared_company,
  certificate_number,
  trec_last_issue_date,
  generation_period,
  transferred_mwh,
  remaining_mwh,
  created_at
]) => ({
  raw_id,
  unit_name,
  facility_name,
  energy_type,
  shared_company,
  certificate_number,
  trec_last_issue_date,
  generation_period,
  transferred_mwh,
  remaining_mwh,
  created_at
}));

export function getMockSites() {
  return [...new Set(rows.map((row) => row.facility_name))].sort();
}

export function getMockSummary({ from, to, site }) {
  const filtered = rows.filter((row) => {
    const eventDate = row.trec_last_issue_date;
    const inDateRange = eventDate >= from && eventDate <= to;
    const inSite = site ? row.facility_name === site : true;
    return inDateRange && inSite;
  });

  const totals = filtered.reduce(
    (acc, row) => {
      acc.certificate_count += 1;
      acc.transferred_mwh += row.transferred_mwh;
      acc.remaining_mwh += row.remaining_mwh;
      acc.facilities.add(row.facility_name);
      acc.companies.add(row.shared_company);
      acc.energyTypes.add(row.energy_type);
      return acc;
    },
    {
      certificate_count: 0,
      transferred_mwh: 0,
      remaining_mwh: 0,
      facilities: new Set(),
      companies: new Set(),
      energyTypes: new Set()
    }
  );

  totals.facility_count = totals.facilities.size;
  totals.company_count = totals.companies.size;
  totals.energy_type_count = totals.energyTypes.size;
  delete totals.facilities;
  delete totals.companies;
  delete totals.energyTypes;

  const dailyMap = new Map();
  const categoryMap = new Map();
  const facilityMap = new Map();
  const companyMap = new Map();

  for (const row of filtered) {
    const eventDate = row.trec_last_issue_date;
    const daily = dailyMap.get(eventDate) || {
      event_date: eventDate,
      transferred_mwh: 0,
      remaining_mwh: 0,
      certificate_count: 0
    };

    daily.transferred_mwh += row.transferred_mwh;
    daily.remaining_mwh += row.remaining_mwh;
    daily.certificate_count += 1;
    dailyMap.set(eventDate, daily);

    const category = row.energy_type || "未分類";
    const categoryValue = categoryMap.get(category) || {
      category,
      transferred_mwh: 0,
      certificate_count: 0
    };
    categoryValue.transferred_mwh += row.transferred_mwh;
    categoryValue.certificate_count += 1;
    categoryMap.set(category, categoryValue);

    const facilityValue = facilityMap.get(row.facility_name) || {
      facility_name: row.facility_name,
      energy_type: row.energy_type,
      transferred_mwh: 0,
      remaining_mwh: 0,
      certificate_count: 0
    };
    facilityValue.transferred_mwh += row.transferred_mwh;
    facilityValue.remaining_mwh += row.remaining_mwh;
    facilityValue.certificate_count += 1;
    facilityMap.set(row.facility_name, facilityValue);

    const companyValue = companyMap.get(row.shared_company) || {
      shared_company: row.shared_company,
      transferred_mwh: 0,
      remaining_mwh: 0,
      certificate_count: 0
    };
    companyValue.transferred_mwh += row.transferred_mwh;
    companyValue.remaining_mwh += row.remaining_mwh;
    companyValue.certificate_count += 1;
    companyMap.set(row.shared_company, companyValue);
  }

  return {
    totals,
    daily: [...dailyMap.values()].sort((a, b) => a.event_date.localeCompare(b.event_date)),
    categories: [...categoryMap.values()].sort((a, b) => b.transferred_mwh - a.transferred_mwh),
    facilities: [...facilityMap.values()]
      .sort((a, b) => b.transferred_mwh - a.transferred_mwh)
      .slice(0, 10),
    companies: [...companyMap.values()]
      .sort((a, b) => b.transferred_mwh - a.transferred_mwh)
      .slice(0, 10),
    recent: [...filtered]
      .sort((a, b) => b.trec_last_issue_date.localeCompare(a.trec_last_issue_date))
      .slice(0, 12)
  };
}
