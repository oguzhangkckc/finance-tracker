import type { components } from "./schema";

type Schemas = components["schemas"];

export type Report = Schemas["Report"];
export type Summary = Schemas["Summary"];
export type HoldingLine = Schemas["HoldingLine"];
export type AllocationLine = Schemas["AllocationLine"];
export type AlertLine = Schemas["AlertLine"];
export type ReturnFigure = Schemas["ReturnFigure"];
export type RefreshInfo = Schemas["RefreshInfo"];
export type ValueChartData = Schemas["ValueChartData"];
export type ValuePoint = Schemas["ValuePointItem"];
export type ContributionItem = Schemas["ContributionItem"];
export type OverviewData = Schemas["OverviewPage"];
export type AllocationData = Schemas["ReportPage"];
export type ReturnsData = Schemas["ReturnsPage"];
export type ReportText = Schemas["ReportText"];
