const fromInput = document.querySelector("#fromInput");
const toInput = document.querySelector("#toInput");
const siteInput = document.querySelector("#siteInput");
const refreshButton = document.querySelector("#refreshButton");
const sourceBadge = document.querySelector("#sourceBadge");
const transferredKpi = document.querySelector("#transferredKpi");
const remainingKpi = document.querySelector("#remainingKpi");
const certificateKpi = document.querySelector("#certificateKpi");
const dailyChart = document.querySelector("#dailyChart");
const categoryList = document.querySelector("#categoryList");

const numberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1
});

async function init() {
  const today = new Date().toISOString().slice(0, 10);
  fromInput.value = "2026-01-01";
  toInput.value = today;
  await loadSites();
  await loadSummary();
}

async function loadSites() {
  const response = await fetch("/api/sites");
  const data = await response.json();

  for (const site of data.sites || []) {
    const option = document.createElement("option");
    option.value = site;
    option.textContent = site;
    siteInput.append(option);
  }
}

async function loadSummary() {
  refreshButton.disabled = true;

  try {
    const params = new URLSearchParams({
      from: fromInput.value,
      to: toInput.value
    });

    if (siteInput.value) {
      params.set("site", siteInput.value);
    }

    const response = await fetch(`/api/summary?${params}`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || "Unable to load summary.");
    }

    renderSummary(data);
  } catch (error) {
    dailyChart.innerHTML = `<p class="empty">${error.message}</p>`;
  } finally {
    refreshButton.disabled = false;
  }
}

function renderSummary(data) {
  sourceBadge.textContent = data.source === "bigquery" ? "BigQuery" : "Mock Data";
  transferredKpi.textContent = numberFormat.format(data.totals.transferred_mwh || 0);
  remainingKpi.textContent = numberFormat.format(data.totals.remaining_mwh || 0);
  certificateKpi.textContent = numberFormat.format(data.totals.certificate_count || 0);

  renderDailyChart(data.daily || []);
  renderCategoryList(data.categories || []);
}

function renderDailyChart(rows) {
  const max = Math.max(...rows.map((row) => row.transferred_mwh), 1);
  dailyChart.replaceChildren();

  if (!rows.length) {
    dailyChart.textContent = "這個篩選條件沒有資料。";
    return;
  }

  for (const row of rows) {
    const width = `${Math.max((row.transferred_mwh / max) * 100, 2)}%`;
    const item = document.createElement("div");
    item.className = "barRow";
    item.innerHTML = `
      <strong>${row.event_date}</strong>
      <div class="barTrack"><div class="barFill" style="width: ${width}"></div></div>
      <span class="barValue">${numberFormat.format(row.transferred_mwh)} MWh</span>
    `;
    dailyChart.append(item);
  }
}

function renderCategoryList(rows) {
  const max = Math.max(...rows.map((row) => row.transferred_mwh), 1);
  categoryList.replaceChildren();

  if (!rows.length) {
    categoryList.textContent = "這個篩選條件沒有資料。";
    return;
  }

  for (const row of rows) {
    const width = `${Math.max((row.transferred_mwh / max) * 100, 2)}%`;
    const item = document.createElement("div");
    item.className = "categoryItem";
    item.innerHTML = `
      <div class="categoryMeta">
        <strong>${row.category}</strong>
        <span>${numberFormat.format(row.transferred_mwh)} MWh / ${numberFormat.format(row.certificate_count)} 筆</span>
      </div>
      <div class="miniTrack"><div class="miniFill" style="width: ${width}"></div></div>
    `;
    categoryList.append(item);
  }
}

refreshButton.addEventListener("click", loadSummary);
siteInput.addEventListener("change", loadSummary);

init();
