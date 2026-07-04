<script setup>
import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  DoughnutController,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip
} from 'chart.js';
import { Flow, SankeyController } from 'chartjs-chart-sankey';
import {
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Factory,
  FileText,
  Gauge,
  Leaf,
  LineChart,
  Network,
  RefreshCw,
  ShieldCheck,
  Users,
  Zap
} from '@lucide/vue';
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';

Chart.register(
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  DoughnutController,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Flow,
  SankeyController,
  Tooltip
);

const ChartCanvas = defineComponent({
  props: {
    config: {
      type: Object,
      required: true
    }
  },
  setup(props) {
    const canvas = ref(null);
    let chart;

    const render = () => {
      if (!canvas.value) return;
      chart?.destroy();
      chart = new Chart(canvas.value, props.config);
    };

    onMounted(render);
    watch(() => props.config, render, { deep: true });
    onBeforeUnmount(() => chart?.destroy());

    return () => h('canvas', { ref: canvas });
  }
});

const loading = ref(true);
const error = ref('');
const dashboard = ref(null);
const activeFilter = ref('');
const activeView = ref('overview');
const recordPage = ref(1);
const recordPageSize = 50;
const filters = reactive({
  year: '全部',
  granularity: '月',
  energy: '全部',
  supply: '全部',
  role: '出售單位',
  source: '全部'
});

const blue = '#0b63d8';
const green = '#2f9d27';
const yellow = '#f7b731';
const cyan = '#20b8ce';
const gridColor = 'rgba(165, 190, 205, 0.17)';
const textColor = '#dbe7ee';
const mutedColor = '#9db0bd';
const energyPalette = [yellow, blue, green, cyan, '#9066d9'];
const viewTabs = [
  { key: 'overview', label: '總覽圖表', icon: LineChart },
  { key: 'records', label: '交易列表', icon: FileText },
  { key: 'flow', label: '能源流向圖', icon: Network }
];
const sankeyPalette = [
  '#4aa3ee',
  '#7bc84a',
  '#69a13b',
  '#9162c7',
  '#ff7d7d',
  '#f05252',
  '#b28bd8',
  '#ffd54a',
  '#8bd3d4',
  '#ffad68',
  '#2d95df',
  '#f7b731',
  '#8178bd',
  '#5bc0be',
  '#ff934f',
  '#1b998b',
  '#d95d39',
  '#6a4c93',
  '#1982c4',
  '#8ac926'
];

const formatNumber = (value, digits = 0) =>
  new Intl.NumberFormat('zh-TW', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(value || 0);

const formatCompact = (value) => {
  if (!value) return '0';
  if (value >= 1_000_000) return `${formatNumber(value / 1_000_000, 1)}M`;
  if (value >= 1_000) return `${formatNumber(value / 1_000, 0)}K`;
  return formatNumber(value);
};

const shortName = (value, length = 12) => {
  const text = value || '';
  return text.length > length ? `${text.slice(0, length)}...` : text;
};

const sourceName = (value) => {
  if (value === 'direct_transaction') return '直轉供';
  if (value === 'self_generation_transaction') return '自用發電';
  return value || '未分類';
};

const selectFilter = (key, value) => {
  filters[key] = value;
  activeFilter.value = '';
  recordPage.value = 1;
  loadData();
};

async function loadData() {
  loading.value = true;
  error.value = '';

  try {
    const params = new URLSearchParams();
    if (filters.year !== '全部') params.set('year', filters.year);
    if (filters.energy !== '全部') params.set('energy', filters.energy);
    if (filters.supply !== '全部') params.set('supply', filters.supply);
    if (filters.source !== '全部') {
      const sourceType = dashboard.value?.filterOptions?.sources?.find(
        (source) => source.label === filters.source
      )?.type;
      if (sourceType) params.set('sourceType', sourceType);
    }
    params.set('recordPage', String(recordPage.value));
    params.set('recordPageSize', String(recordPageSize));

    const query = params.toString();
    const response = await fetch(`/api/dashboard${query ? `?${query}` : ''}`);
    if (!response.ok) throw new Error('API 回傳失敗，請確認後端與 MySQL 連線。');
    dashboard.value = await response.json();
  } catch (caught) {
    error.value = caught.message || '讀取資料失敗';
  } finally {
    loading.value = false;
  }
}

onMounted(loadData);

const goRecordPage = (page) => {
  const totalPages = dashboard.value?.recordTotalPages || 1;
  recordPage.value = Math.min(Math.max(page, 1), totalPages);
  loadData();
};

const selectedKpi = computed(() => {
  return dashboard.value?.kpi || null;
});

const previousYearKpi = computed(() => {
  if (!dashboard.value || filters.year === '全部') return null;
  return dashboard.value.kpiByYear?.find((row) => row.year === String(Number(filters.year) - 1)) || null;
});

const selectedKpiGrowth = computed(() => {
  const hasSecondaryFilters =
    filters.energy !== '全部' || filters.supply !== '全部' || filters.source !== '全部';
  if (hasSecondaryFilters) return null;
  const current = selectedKpi.value?.totalTransactionMwh || 0;
  const previous = previousYearKpi.value?.totalTransactionMwh || 0;
  if (!previous) return null;
  return ((current / previous - 1) * 100);
});

const kpiPeriodLabel = computed(() => {
  if (filters.year === '全部') return '資料期間';
  if (selectedKpiGrowth.value == null) return '目前篩選';
  return `較 ${Number(filters.year) - 1} 年`;
});

const kpiGrowthLabel = computed(() => {
  if (selectedKpiGrowth.value != null) return `↑ ${formatNumber(selectedKpiGrowth.value, 1)}%`;
  if (filters.year !== '全部') return '依條件更新';
  const startYear = dashboard.value?.kpi?.firstTransactionDate?.slice(0, 4) || '';
  const endYear = dashboard.value?.kpi?.lastTransactionDate?.slice(0, 4) || '';
  return startYear && endYear ? `${startYear}-${endYear}` : '依條件更新';
});

const kpiCards = computed(() => {
  const kpi = selectedKpi.value;
  if (!kpi) return [];

  return [
    {
      label: '總交易量 (MWh)',
      value: formatNumber(kpi.totalTransactionMwh),
      icon: Zap,
      tone: 'blue',
      growth: kpiGrowthLabel.value
    },
    {
      label: '總交易筆數',
      value: formatNumber(kpi.transactionCount),
      icon: FileText,
      tone: 'green',
      growth: kpiGrowthLabel.value
    },
    {
      label: '出售單位數',
      value: formatNumber(kpi.sellerCompanyCount),
      icon: Building2,
      tone: 'green',
      growth: kpiGrowthLabel.value
    },
    {
      label: '購買者數',
      value: formatNumber(kpi.buyerCompanyCount),
      icon: Users,
      tone: 'blue',
      growth: kpiGrowthLabel.value
    },
    {
      label: '發電設備數',
      value: formatNumber(kpi.facilityCount),
      icon: Factory,
      tone: 'green',
      growth: kpiGrowthLabel.value
    }
  ];
});

const availableYears = computed(() => {
  return ['全部', ...(dashboard.value?.filterOptions?.years || [])];
});

const allYearlyRows = computed(() => {
  const rows = dashboard.value?.monthly || [];
  const grouped = rows.reduce((acc, row) => {
    const year = String(row.month).slice(0, 4);
    acc[year] ||= { year, transactionCount: 0, totalTransactionMwh: 0 };
    acc[year].transactionCount += row.transactionCount;
    acc[year].totalTransactionMwh += row.totalTransactionMwh;
    return acc;
  }, {});

  return Object.values(grouped).sort((a, b) => a.year.localeCompare(b.year)).slice(-6);
});

const yearlyRows = computed(() => {
  if (filters.year === '全部') return allYearlyRows.value;
  return allYearlyRows.value.filter((row) => row.year === filters.year);
});

const latestYearMonthly = computed(() => {
  const rows = dashboard.value?.monthly || [];
  const latestYear = filters.year === '全部' ? rows.at(-1)?.month?.slice(0, 4) : filters.year;
  return rows
    .filter((row) => row.month?.slice(0, 4) === latestYear)
    .map((row) => ({
      month: `${Number(row.month.slice(5, 7))}月`,
      direct: row.directTransactionMwh,
      self: row.selfGenerationTransactionMwh
    }));
});

const latestYearDaily = computed(() => {
  const rows = dashboard.value?.daily || [];
  const latestYear = filters.year === '全部' ? rows.at(-1)?.day?.slice(0, 4) : filters.year;
  return rows
    .filter((row) => row.day?.slice(0, 4) === latestYear)
    .map((row) => ({
      label: `${Number(row.day.slice(5, 7))}/${Number(row.day.slice(8, 10))}`,
      direct: row.directTransactionMwh,
      self: row.selfGenerationTransactionMwh
    }));
});

const trendRows = computed(() =>
  filters.granularity === '日' ? latestYearDaily.value : latestYearMonthly.value
);

const trendTitle = computed(() =>
  filters.granularity === '日' ? '每日交易量趨勢' : '每月交易量趨勢'
);

const allEnergyRows = computed(() => dashboard.value?.energyTypes || []);
const energyOptions = computed(() => ['全部', ...(dashboard.value?.filterOptions?.energyTypes || [])]);
const energyRows = computed(() =>
  filters.energy === '全部'
    ? allEnergyRows.value
    : allEnergyRows.value.filter((row) => row.name === filters.energy)
);

const allSourceRows = computed(() => dashboard.value?.sources || []);
const sourceOptions = computed(() => [
  '全部',
  ...((dashboard.value?.filterOptions?.sources || []).map((source) => source.label))
]);
const supplyOptions = computed(() => ['全部', ...(dashboard.value?.filterOptions?.supplyTypes || [])]);
const sellerRows = computed(() => dashboard.value?.topSellers || []);
const buyerRows = computed(() => dashboard.value?.topBuyers || []);
const recordRows = computed(() => dashboard.value?.records || []);
const recordTotal = computed(() => dashboard.value?.recordTotal || 0);
const recordTotalPages = computed(() => dashboard.value?.recordTotalPages || 1);
const recordStart = computed(() => (recordRows.value.length ? (recordPage.value - 1) * recordPageSize + 1 : 0));
const recordEnd = computed(() => Math.min(recordPage.value * recordPageSize, recordTotal.value));
const recordPageNumbers = computed(() => {
  const total = recordTotalPages.value;
  const current = recordPage.value;
  const start = Math.max(1, Math.min(current - 2, total - 4));
  const end = Math.min(total, start + 4);
  return Array.from({ length: end - start + 1 }, (_, index) => start + index);
});
const recordTitle = computed(() =>
  filters.source === '全部' ? '憑證成交紀錄' : `${filters.source.replace('憑證成交', '')}成交紀錄`
);
const facilityFlowRows = computed(() => dashboard.value?.facilityFlows || []);
const summaryRows = computed(() =>
  filters.role === '購買者'
    ? dashboard.value?.topBuyers || []
    : dashboard.value?.topSellers || []
);
const roleMetricLabel = computed(() => (filters.role === '購買者' ? '賣方數' : '買方數'));
const totalEnergy = computed(() => energyRows.value.reduce((sum, row) => sum + row.totalTransactionMwh, 0));

const sourceTypeByName = computed(() =>
  allSourceRows.value.reduce((acc, row) => {
    acc[row.name] = row.type;
    return acc;
  }, {})
);

const sankeyFilteredRows = computed(() => {
  const selectedSourceType = sourceTypeByName.value[filters.source] || sourceTypeByName.value[filters.supply];

  return (dashboard.value?.flows || [])
    .filter((row) => filters.energy === '全部' || row.energyType === filters.energy)
    .filter((row) => !selectedSourceType || row.sourceType === selectedSourceType)
});

const sankeyRows = computed(() => {
  const grouped = sankeyFilteredRows.value.reduce((acc, row) => {
    const key = `${row.seller}|||${row.buyer}`;
    if (!acc[key]) {
      acc[key] = {
        seller: row.seller,
        buyer: row.buyer,
        transactionCount: 0,
        totalTransactionMwh: 0
      };
    }
    acc[key].transactionCount += row.transactionCount;
    acc[key].totalTransactionMwh += row.totalTransactionMwh;
    return acc;
  }, {});

  return Object.values(grouped).sort((a, b) => b.totalTransactionMwh - a.totalTransactionMwh);
});

const sankeyUniqueBuyerCount = computed(() => new Set(sankeyRows.value.map((row) => row.buyer)).size);
const sankeyUniqueSellerCount = computed(() => new Set(sankeyRows.value.map((row) => row.seller)).size);

const facilityFlowLinkRows = computed(() => {
  const links = {};
  const addLink = (from, to, flow) => {
    const key = `${from}|||${to}`;
    links[key] ||= { from, to, flow: 0 };
    links[key].flow += flow;
  };

  facilityFlowRows.value.forEach((row) => {
    const sellerKey = `seller:${row.seller}`;
    const facilityKey = `facility:${row.facility}`;
    const buyerKey = `buyer:${row.buyer}`;
    addLink(facilityKey, sellerKey, row.totalTransactionMwh);
    addLink(sellerKey, buyerKey, row.totalTransactionMwh);
  });

  return Object.values(links).sort((a, b) => b.flow - a.flow);
});

const facilityFlowMeta = computed(() => {
  const labels = {};
  const colors = {};
  const priority = {};
  const column = {};
  const totals = {};
  let colorIndex = 0;

  facilityFlowLinkRows.value.forEach((row) => {
    totals[row.from] = (totals[row.from] || 0) + row.flow;
    totals[row.to] = (totals[row.to] || 0) + row.flow;
  });

  const orderedKeys = Object.entries(totals)
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => key);

  const nodeColumn = (key) => {
    if (key.startsWith('facility:')) return 0;
    if (key.startsWith('seller:')) return 1;
    return 2;
  };

  facilityFlowLinkRows.value.forEach((row) => {
    [row.from, row.to].forEach((key) => {
      if (!colors[key]) {
        colors[key] = sankeyPalette[colorIndex % sankeyPalette.length];
        colorIndex += 1;
      }
      labels[key] = key.replace(/^(seller|facility|buyer):/, '');
      priority[key] = orderedKeys.indexOf(key);
      column[key] = nodeColumn(key);
    });
  });

  return { labels, colors, priority, column };
});

const sankeyNodeMeta = computed(() => {
  const labels = {};
  const colors = {};
  const priority = {};
  const column = {};
  const totals = {};
  let colorIndex = 0;

  sankeyRows.value.forEach((row) => {
    totals[`seller:${row.seller}`] = (totals[`seller:${row.seller}`] || 0) + row.totalTransactionMwh;
    totals[`buyer:${row.buyer}`] = (totals[`buyer:${row.buyer}`] || 0) + row.totalTransactionMwh;
  });

  const orderedKeys = Object.entries(totals)
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => key);

  const assignNode = (key, label, nodeColumn) => {
    if (!colors[key]) {
      colors[key] = sankeyPalette[colorIndex % sankeyPalette.length];
      colorIndex += 1;
    }
    labels[key] = label;
    priority[key] = orderedKeys.indexOf(key);
    column[key] = nodeColumn;
  };

  sankeyRows.value.forEach((row) => {
    const sellerKey = `seller:${row.seller}`;
    const buyerKey = `buyer:${row.buyer}`;
    assignNode(sellerKey, row.seller, 0);
    assignNode(buyerKey, row.buyer, 2);
  });

  return { labels, colors, priority, column };
});

const filterControls = computed(() => [
  { key: 'year', label: '年度', value: filters.year, icon: CalendarDays, options: availableYears.value },
  { key: 'granularity', label: '分析粒度', value: filters.granularity, icon: LineChart, options: ['月', '日'] },
  { key: 'energy', label: '能源類型', value: filters.energy, icon: Leaf, options: energyOptions.value },
  { key: 'supply', label: '供電種類', value: filters.supply, icon: Zap, options: supplyOptions.value },
  { key: 'role', label: '公司角色', value: filters.role, icon: Users, options: ['出售單位', '購買者'] },
  { key: 'source', label: '交易來源', value: filters.source, icon: Building2, options: sourceOptions.value }
]);

const monthlyTrendChart = computed(() => ({
  type: 'line',
  data: {
    labels: trendRows.value.map((row) => row.label || row.month),
    datasets: [
      {
        label: '直轉供',
        data: trendRows.value.map((row) => row.direct),
        borderColor: blue,
        backgroundColor: 'rgba(11, 99, 216, 0.12)',
        pointBackgroundColor: blue,
        pointRadius: filters.granularity === '日' ? 0 : 3,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.35
      },
      {
        label: '自用發電',
        data: trendRows.value.map((row) => row.self),
        borderColor: green,
        backgroundColor: 'rgba(47, 157, 39, 0.12)',
        pointBackgroundColor: green,
        pointRadius: filters.granularity === '日' ? 0 : 3,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.35
      }
    ]
  },
  options: lineOptions()
}));

const energyDoughnutChart = computed(() => ({
  type: 'doughnut',
  data: {
    labels: energyRows.value.map((row) => row.name),
    datasets: [
      {
        data: energyRows.value.map((row) => row.totalTransactionMwh),
        backgroundColor: energyRows.value.map((_, index) => energyPalette[index % energyPalette.length]),
        borderColor: '#071923',
        borderWidth: 3
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '58%',
    plugins: {
      legend: { display: false },
      tooltip: tooltipOptions('MWh')
    }
  }
}));

const yearlyBarChart = computed(() => ({
  type: 'line',
  data: {
    labels: yearlyRows.value.map((row, index) =>
      index === yearlyRows.value.length - 1 ? `${row.year} YTD` : row.year
    ),
    datasets: [
      {
        label: '交易量',
        data: yearlyRows.value.map((row) => row.totalTransactionMwh),
        borderColor: blue,
        backgroundColor: blue,
        pointBackgroundColor: blue,
        pointRadius: 4,
        pointHoverRadius: 6,
        fill: true,
        tension: 0.32
      }
    ]
  },
  options: lineOptions()
}));

const sellerRankingChart = computed(() => ({
  type: 'bar',
  data: {
    labels: sellerRows.value.map((row) => shortName(row.name, 14)),
    datasets: [
      {
        label: '總交易量',
        data: sellerRows.value.map((row) => row.totalTransactionMwh),
        backgroundColor: green,
        borderRadius: 0,
        barThickness: 16
      }
    ]
  },
  options: {
    ...horizontalOptions(),
    scales: {
      ...horizontalOptions().scales,
      y: {
        ...horizontalOptions().scales.y,
        ticks: {
          ...horizontalOptions().scales.y.ticks,
          font: { size: 11, weight: 700 }
        }
      }
    }
  }
}));

const buyerRankingChart = computed(() => ({
  type: 'bar',
  data: {
    labels: buyerRows.value.map((row) => shortName(row.name, 14)),
    datasets: [
      {
        label: '總交易量',
        data: buyerRows.value.map((row) => row.totalTransactionMwh),
        backgroundColor: blue,
        borderRadius: 0,
        barThickness: 16
      }
    ]
  },
  options: {
    ...horizontalOptions(),
    scales: {
      ...horizontalOptions().scales,
      y: {
        ...horizontalOptions().scales.y,
        ticks: {
          ...horizontalOptions().scales.y.ticks,
          font: { size: 11, weight: 700 }
        }
      }
    }
  }
}));

const sankeyChart = computed(() => ({
  type: 'sankey',
  data: {
    datasets: [
      {
        label: '交易流量 MWh',
        data: sankeyRows.value.map((row) => ({
          from: `seller:${row.seller}`,
          to: `buyer:${row.buyer}`,
          flow: row.totalTransactionMwh
        })),
        colorFrom: (context) => sankeyNodeMeta.value.colors[context.dataset.data[context.dataIndex].from],
        colorTo: (context) => sankeyNodeMeta.value.colors[context.dataset.data[context.dataIndex].to],
        hoverColorFrom: (context) => sankeyNodeMeta.value.colors[context.dataset.data[context.dataIndex].from],
        hoverColorTo: (context) => sankeyNodeMeta.value.colors[context.dataset.data[context.dataIndex].to],
        colorMode: 'gradient',
        alpha: 0.82,
        borderWidth: 0,
        color: '#dbe7ee',
        font: {
          size: 12,
          weight: 800
        },
        labels: sankeyNodeMeta.value.labels,
        priority: sankeyNodeMeta.value.priority,
        column: sankeyNodeMeta.value.column,
        nodePadding: 7,
        nodeWidth: 18,
        size: 'max',
        modeX: 'edge'
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(15, 30, 42, 0.94)',
        borderColor: 'rgba(141, 169, 184, 0.35)',
        borderWidth: 1,
        bodyColor: '#dbe7ee',
        bodyFont: {
          size: 12,
          weight: 800
        },
        displayColors: true,
        padding: 12,
        titleColor: '#ffffff',
        callbacks: {
          title() {
            return '交易流向';
          },
          label(context) {
            const raw = context.raw || {};
            const from = sankeyNodeMeta.value.labels[raw.from] || raw.from || '';
            const to = sankeyNodeMeta.value.labels[raw.to] || raw.to || '';
            return `${from} → ${to}: ${formatNumber(raw.flow, 2)} MWh`;
          }
        }
      }
    }
  }
}));

const facilitySankeyChart = computed(() => ({
  type: 'sankey',
  data: {
    datasets: [
      {
        label: '移轉量 MWh',
        data: facilityFlowLinkRows.value.map((row) => ({
          from: row.from,
          to: row.to,
          flow: row.flow
        })),
        colorFrom: (context) => facilityFlowMeta.value.colors[context.dataset.data[context.dataIndex].from],
        colorTo: (context) => facilityFlowMeta.value.colors[context.dataset.data[context.dataIndex].to],
        hoverColorFrom: (context) => facilityFlowMeta.value.colors[context.dataset.data[context.dataIndex].from],
        hoverColorTo: (context) => facilityFlowMeta.value.colors[context.dataset.data[context.dataIndex].to],
        colorMode: 'gradient',
        alpha: 0.82,
        borderWidth: 0,
        color: '#dbe7ee',
        font: {
          size: 11,
          weight: 800
        },
        labels: facilityFlowMeta.value.labels,
        priority: facilityFlowMeta.value.priority,
        column: facilityFlowMeta.value.column,
        nodePadding: 18,
        nodeWidth: 22,
        size: 'max',
        modeX: 'edge'
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(15, 30, 42, 0.94)',
        borderColor: 'rgba(141, 169, 184, 0.35)',
        borderWidth: 1,
        bodyColor: '#dbe7ee',
        bodyFont: {
          size: 12,
          weight: 800
        },
        displayColors: true,
        padding: 12,
        titleColor: '#ffffff',
        callbacks: {
          title() {
            return '能源流向';
          },
          label(context) {
            const raw = context.raw || {};
            const from = facilityFlowMeta.value.labels[raw.from] || raw.from || '';
            const to = facilityFlowMeta.value.labels[raw.to] || raw.to || '';
            return `${from} → ${to}: ${formatNumber(raw.flow, 2)} MWh`;
          }
        }
      }
    }
  }
}));

function tooltipOptions(unit, valueAxis = 'y') {
  return {
    callbacks: {
      label(context) {
        const value =
          valueAxis === 'x'
            ? context.parsed.x ?? context.parsed.y ?? context.parsed
            : context.parsed.y ?? context.parsed.x ?? context.parsed;
        return `${context.dataset.label || context.label}: ${formatNumber(value)} ${unit}`;
      }
    }
  };
}

function commonPlugins(showLegend = true) {
  return {
    legend: {
      display: showLegend,
      position: 'top',
      labels: {
        boxHeight: 8,
        boxWidth: 22,
        color: textColor,
        font: { size: 12, weight: 700 },
        usePointStyle: true
      }
    },
    tooltip: tooltipOptions('MWh')
  };
}

function lineOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: commonPlugins(true),
    scales: axisScales({ denseX: filters.granularity === '日' })
  };
}

function horizontalOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {
      ...commonPlugins(false),
      tooltip: tooltipOptions('MWh', 'x')
    },
    scales: {
      x: {
        beginAtZero: true,
        border: { color: 'rgba(178, 205, 220, 0.35)' },
        grid: { color: gridColor },
        ticks: {
          color: textColor,
          callback: (value) => formatCompact(value)
        }
      },
      y: {
        border: { display: false },
        grid: { display: false },
        ticks: { color: textColor, font: { size: 12, weight: 700 } }
      }
    }
  };
}

function axisScales({ denseX = false } = {}) {
  return {
    x: {
      border: { color: 'rgba(178, 205, 220, 0.35)' },
      grid: { display: false },
      ticks: {
        autoSkip: denseX,
        maxTicksLimit: denseX ? 12 : undefined,
        color: textColor,
        font: { size: denseX ? 10 : 12, weight: 700 }
      }
    },
    y: {
      beginAtZero: true,
      border: { color: 'rgba(178, 205, 220, 0.35)' },
      grid: { color: gridColor, borderDash: [4, 4] },
      ticks: {
        color: textColor,
        callback: (value) => formatCompact(value)
      }
    }
  };
}
</script>

<template>
  <main class="trec-page">
    <header class="trec-header">
      <div class="brand-mark" aria-hidden="true">
        <Leaf :size="58" />
        <Zap :size="28" />
      </div>
      <div class="title-block">
        <h1>
          <span class="title-line">T-REC <em>綠電交易資料平台</em></span>
          <span class="title-line">Dashboard：整體市場總覽</span>
        </h1>
      </div>
      <div class="header-action">
        <button class="demo-badge" type="button"><ShieldCheck :size="18" />面試作品集展示版</button>
        <span><RefreshCw :size="15" />資料更新時間：2026-07-03 16:30</span>
      </div>
    </header>

    <section class="filter-row" aria-label="篩選條件">
      <div v-for="control in filterControls" :key="control.key" class="filter-menu">
        <button
          :class="['filter-pill', { active: activeFilter === control.key }]"
          type="button"
          @click="activeFilter = activeFilter === control.key ? '' : control.key"
        >
          <component :is="control.icon" :size="22" />
          {{ control.label }}
          <span>{{ control.value }}</span>
          <ChevronDown :size="16" />
        </button>
        <div v-if="activeFilter === control.key" class="filter-options">
          <button
            v-for="option in control.options"
            :key="option"
            :class="{ selected: option === control.value }"
            type="button"
            @click="selectFilter(control.key, option)"
          >
            {{ option }}
          </button>
        </div>
      </div>
    </section>

    <section v-if="loading" class="state-card">讀取 MySQL 資料中...</section>
    <section v-else-if="error" class="state-card error">
      <strong>讀取失敗</strong>
      <span>{{ error }}</span>
    </section>

    <template v-else-if="dashboard">
      <section class="kpi-row">
        <article v-for="card in kpiCards" :key="card.label" class="kpi-card">
          <div :class="['kpi-icon', card.tone]">
            <component :is="card.icon" :size="38" />
          </div>
          <div class="kpi-copy">
            <h2>{{ card.label }}</h2>
            <strong>{{ card.value }}</strong>
            <p>{{ kpiPeriodLabel }} <span>{{ card.growth }}</span></p>
          </div>
        </article>
      </section>

      <nav class="view-tabs" aria-label="頁面切換">
        <button
          v-for="tabItem in viewTabs"
          :key="tabItem.key"
          :class="{ active: activeView === tabItem.key }"
          type="button"
          @click="activeView = tabItem.key"
        >
          <component :is="tabItem.icon" :size="18" />
          {{ tabItem.label }}
        </button>
      </nav>

      <section v-if="activeView === 'overview'" class="dashboard-grid">
        <article class="panel panel-wide">
          <div class="panel-title"><LineChart :size="21" /><h2>{{ trendTitle }}</h2><span>單位：MWh</span></div>
          <div class="chart-frame tall">
            <ChartCanvas :config="monthlyTrendChart" />
          </div>
        </article>

        <article class="panel panel-wide">
          <div class="panel-title"><Leaf :size="21" /><h2>能源類型占比</h2></div>
          <div class="donut-layout">
            <div class="donut-frame">
              <ChartCanvas :config="energyDoughnutChart" />
            </div>
            <ul class="legend-list">
              <li v-for="(row, index) in energyRows" :key="row.name">
                <span :style="{ backgroundColor: energyPalette[index % energyPalette.length] }"></span>
                <b>{{ row.name }}</b>
                <em>{{ formatNumber((row.totalTransactionMwh / totalEnergy) * 100, 1) }}%</em>
              </li>
            </ul>
          </div>
        </article>

        <article class="panel panel-half">
          <div class="panel-title"><LineChart :size="21" /><h2>年度交易量趨勢</h2><span>單位：MWh</span></div>
          <div class="chart-frame">
            <ChartCanvas :config="yearlyBarChart" />
          </div>
        </article>

        <article class="panel insights-panel panel-half">
          <div class="panel-title green"><Gauge :size="21" /><h2>重點洞察</h2></div>
          <ol class="insight-list">
            <li>總交易量達 {{ formatNumber(dashboard.kpi.totalTransactionMwh) }} MWh，市場持續擴大。</li>
            <li>直轉供為主要供電模式，企業綠電採購需求明顯。</li>
            <li>太陽能與風力能為主要能源類型，占整體交易量最高。</li>
            <li>購買者數達 {{ formatNumber(dashboard.kpi.buyerCompanyCount) }}，顯示需求端參與增加。</li>
          </ol>
        </article>

        <article class="panel panel-wide">
          <div class="panel-title green"><Building2 :size="21" /><h2>Top 10 出售單位排行</h2><span>單位：MWh</span></div>
          <div class="chart-frame ranking">
            <ChartCanvas :config="sellerRankingChart" />
          </div>
        </article>

        <article class="panel panel-wide">
          <div class="panel-title"><Users :size="21" /><h2>Top 10 購買者排行</h2><span>單位：MWh</span></div>
          <div class="chart-frame ranking">
            <ChartCanvas :config="buyerRankingChart" />
          </div>
        </article>

        <article class="panel panel-half">
          <div class="panel-title"><FileText :size="21" /><h2>年度摘要</h2></div>
          <table>
            <thead>
              <tr>
                <th>年度</th>
                <th>交易量(MWh)</th>
                <th>交易筆數</th>
                <th>年增率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in yearlyRows" :key="row.year">
                <td>{{ index === yearlyRows.length - 1 ? `${row.year} YTD` : row.year }}</td>
                <td>{{ formatNumber(row.totalTransactionMwh) }}</td>
                <td>{{ formatNumber(row.transactionCount) }}</td>
                <td :class="index === 0 ? '' : 'positive'">{{ index === 0 ? '–' : `${formatNumber(((row.totalTransactionMwh / yearlyRows[index - 1].totalTransactionMwh) - 1) * 100, 2)}%` }}</td>
              </tr>
            </tbody>
          </table>
        </article>

        <article class="panel table-panel">
          <div class="panel-title green"><FileText :size="21" /><h2>重點公司摘要</h2></div>
          <table>
            <thead>
              <tr>
                <th>公司名稱</th>
                <th>交易量(MWh)</th>
                <th>交易筆數</th>
                <th>{{ roleMetricLabel }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in summaryRows.slice(0, 6)" :key="row.name">
                <td>{{ row.name }}</td>
                <td>{{ formatNumber(row.totalTransactionMwh) }}</td>
                <td>{{ formatNumber(row.transactionCount) }}</td>
                <td>{{ formatNumber(row.buyerCompanyCount ?? row.sellerCompanyCount) }}</td>
              </tr>
            </tbody>
          </table>
        </article>
      </section>

      <section v-else-if="activeView === 'records'" class="record-section">
        <article class="panel record-panel">
          <div class="panel-title">
            <FileText :size="21" />
            <h2>{{ recordTitle }}</h2>
            <span>第 {{ recordStart }}-{{ recordEnd }} 筆 / 共 {{ formatNumber(recordTotal) }} 筆</span>
          </div>
          <div class="record-list">
            <article v-for="(row, index) in recordRows" :key="`${row.date}-${row.seller}-${row.buyer}-${index}`" class="record-card">
              <div class="record-index">{{ recordStart + index }}</div>
              <div class="record-main">
                <div class="record-tags">
                  <span :class="['source-tag', row.sourceType === 'self_generation_transaction' ? 'green' : 'blue']">{{ sourceName(row.sourceType) }}</span>
                  <span>{{ row.energyType }}</span>
                  <span>{{ row.supplyType }}</span>
                  <span>{{ row.date }}</span>
                </div>
                <strong>{{ row.seller }}</strong>
                <p>{{ row.facility }}</p>
                <em>購買者：{{ row.buyer }}</em>
              </div>
              <div class="record-value">
                <strong>{{ formatNumber(row.transactionMwh, 3) }}</strong>
                <span>MWh</span>
              </div>
            </article>
          </div>
          <div class="record-actions">
            <button type="button" :disabled="recordPage <= 1" @click="goRecordPage(recordPage - 1)">上一頁</button>
            <button
              v-for="page in recordPageNumbers"
              :key="page"
              :class="{ active: page === recordPage }"
              type="button"
              @click="goRecordPage(page)"
            >
              {{ page }}
            </button>
            <button type="button" :disabled="recordPage >= recordTotalPages" @click="goRecordPage(recordPage + 1)">下一頁</button>
            <span>第 {{ recordPage }} / {{ recordTotalPages }} 頁，每頁 {{ recordPageSize }} 筆</span>
          </div>
        </article>
      </section>

      <section v-else class="sankey-top sankey-bottom">
        <article class="panel flow-summary">
          <div>
            <span>供應商</span>
            <strong>{{ new Set(facilityFlowRows.map((row) => row.seller)).size }}</strong>
          </div>
          <div>
            <span>案場</span>
            <strong>{{ new Set(facilityFlowRows.map((row) => row.facility)).size }}</strong>
          </div>
          <div>
            <span>買方</span>
            <strong>{{ new Set(facilityFlowRows.map((row) => row.buyer)).size }}</strong>
          </div>
          <div>
            <span>流向連線</span>
            <strong>{{ facilityFlowLinkRows.length }}</strong>
          </div>
        </article>

        <article class="panel sankey-hero">
          <div class="panel-title"><Network :size="21" /><h2>案場 → 供應商 → 買方 能源流向圖</h2><span>單位：MWh</span></div>
          <div v-if="facilityFlowLinkRows.length" class="chart-frame sankey-frame">
            <ChartCanvas :config="facilitySankeyChart" />
          </div>
          <div v-else class="chart-empty sankey-frame">
            <strong>目前篩選條件沒有能源流向資料</strong>
            <span>請切回「全部」或選擇其他能源類型 / 交易來源。</span>
          </div>
          <div class="sankey-status">
            <span>視覺化</span>
            <span>案場 → 供應商 → 買方</span>
            <span>取交易量前 30 組明細彙總</span>
          </div>
        </article>
      </section>
    </template>

    <footer class="trec-footer">
      <div class="source-line">
        <Cloud :size="30" />
        <span>Data Source: T-REC API</span>
        <b>/</b>
        <span>Data Lake: GCS</span>
        <b>/</b>
        <span>Warehouse: BigQuery</span>
        <b>/</b>
        <span>Orchestration: Airflow</span>
        <b>/</b>
        <span>Dashboard: Looker Studio</span>
      </div>
      <div class="landscape" aria-hidden="true">
        <span class="hill one"></span>
        <span class="hill two"></span>
        <span class="wind a"></span>
        <span class="wind b"></span>
        <span class="solar"></span>
      </div>
    </footer>
  </main>
</template>
