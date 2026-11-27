import type {
  AllocationData,
  HoldingLine,
  OverviewData,
  Report,
  ReturnsData,
  ValueChartData,
} from "../api/types";

export const CLASS_NAMES = { hisse: "Hisse", altin: "Altın", nakit: "Nakit" };

export function holding(overrides: Partial<HoldingLine> = {}): HoldingLine {
  return {
    instrument: "XHT",
    asset_class: "hisse",
    allocation: true,
    units: "100",
    cost: "1000",
    value: "1283.827",
    price: "12.83827",
    price_date: "2026-11-24",
    source: "tefas",
    simple_return: "0.283827",
    real_return: "0.1",
    ...overrides,
  };
}

export function report(overrides: Partial<Report> = {}): Report {
  return {
    schema_version: "1.0",
    profile: "real",
    kind: "weekly",
    logical_date: "2026-11-25",
    summary: {
      values: { in_allocation: "90000", out_of_allocation: "0", total: "90000" },
      change_since: "2026-11-18",
      previous_total: "88000",
      change: "0.0227",
      simple_return: "0.125",
      realized_pnl: "0",
      real_same_as_nominal: false,
    },
    holdings: [],
    allocation: [],
    quiet_period: false,
    rebalance: null,
    alerts: [],
    data_issues: [],
    provenance: { price_dates: {}, cpi_period: null, generated_at: "2026-11-25T06:30:00Z" },
    health: { last_price_sync: null, last_cpi_sync: null, failed_jobs_7d: 0 },
    ...overrides,
  };
}

export function chart(overrides: Partial<ValueChartData> = {}): ValueChartData {
  return {
    points: [
      {
        day: "2026-11-11",
        value: "80000",
        invested: "79000",
        adjusted: "79500",
        cpi_period: "2026-10",
        estimated: false,
      },
      {
        day: "2026-11-18",
        value: null,
        invested: "85000",
        adjusted: "85600",
        cpi_period: "2026-10",
        estimated: true,
      },
      {
        day: "2026-11-25",
        value: "90000",
        invested: "85000",
        adjusted: null,
        cpi_period: null,
        estimated: false,
      },
    ],
    real_gap: "4400",
    estimated_period: "2026-10",
    ...overrides,
  };
}

export function overview(overrides: Partial<OverviewData> = {}): OverviewData {
  return {
    report: report(),
    stale: {},
    stale_all: [],
    class_names: CLASS_NAMES,
    refresh: {
      allowed: true,
      reason: null,
      earliest: null,
      last_sync: "2026-11-25T06:30:00Z",
    },
    chart: chart(),
    ...overrides,
  };
}

export function allocationPage(overrides: Partial<AllocationData> = {}): AllocationData {
  return { report: report(), stale: {}, stale_all: [], class_names: CLASS_NAMES, ...overrides };
}

export function returnsPage(overrides: Partial<ReturnsData> = {}): ReturnsData {
  return {
    report: report(),
    stale: {},
    stale_all: [],
    class_names: CLASS_NAMES,
    chart: chart(),
    contributions: [],
    ...overrides,
  };
}
