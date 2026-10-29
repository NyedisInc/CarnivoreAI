export type Resolution = 'auto' | 'minute' | '5minute' | 'hour' | 'day' | 'week' | 'month' | 'year';
export type RangePreset = '1h' | '6h' | '24h' | '7d' | '30d' | '90d';
export type Operation = 'timeline' | 'summary' | 'ranking' | 'comparison';
export type Viz = 'timeline' | 'kpi' | 'leaderboard' | 'treemap' | 'heat' | 'vitals' | 'hot' | 'events' | 'fleet' | 'runway' | 'swimlanes' | 'flow' | 'scatter' | 'impact' | 'health' | 'pack' | 'agents';
export type ChartType = 'line' | 'area' | 'bar';
export interface GroupDetail { count: number; folders: string[]; unnamed: number }
export interface StatsFilters {
  provider?: string;
  host?: string;
  project?: string;
  model?: string;
  agent_kind?: string;
  conversation_id?: string;
  account_id?: string;
  window?: string;
}
export interface ChartSeries {
  metric: string;
  operation?: Operation;
  group_by?: string;
  label?: string;
  filters?: StatsFilters;
  transform?: 'total' | 'rate' | 'cumulative' | 'per_conversation';
  visible?: boolean;
}
export interface ChartConfig {
  id: string;
  revision: number;
  title: string;
  enabled: boolean;
  viz?: Viz;
  options?: Record<string, unknown>;
  series: ChartSeries[];
  filters: StatsFilters;
  resolution?: Resolution;
  range: { mode: 'global' | 'pinned'; from?: string; to?: string; preset?: RangePreset | null; zoom?: { from: string; to: string } | null };
  display: { type: ChartType; stacked?: boolean; axes?: Record<string, 'left' | 'right'>; indexed?: boolean; legend?: boolean; hidden_series?: string[] };
}
export interface QueryBody {
  metric: string;
  operation: Operation;
  from?: string;
  to?: string;
  rolling?: RangePreset;
  timezone: string;
  resolution: Resolution;
  filters: StatsFilters;
  group_by?: string;
  top_n?: number;
  transform?: 'total' | 'rate' | 'cumulative' | 'per_conversation';
  comparison?: { from: string; to: string };
  scope?: 'pack';
}
export interface AnswerMeta {
  as_of: string;
  stale: boolean;
  reason: null | 'refreshing' | 'compute_failed' | 'rebuilding' | 'catching_up';
}
export interface QueryResult {
  metric: string;
  operation: Operation;
  scope?: 'local' | 'pack';
  pack?: { offline: { id: string; label: string; through: string }[] };
  unit: string;
  resolution: Resolution;
  effective_range?: { from: string; to: string };
  series: { key: string; label: string; filter_value?: string | null; points: { time: string; value: number | null; samples?: number; coverage?: unknown }[] }[];
  summary?: Record<string, unknown>;
  ranking?: { key: string; label: string; filter_value?: string | null; value: number | null; samples?: number; detail?: GroupDetail }[] | null;
  comparison?: { range: { from: string; to: string }; series: QueryResult['series']; summary?: { value: number | null; samples: number; contributing_conversations?: number }; ranking?: QueryResult['ranking'] } | null;
  coverage?: { observed_minutes?: number; range_minutes?: number; unknown_value_rows?: number; partial?: boolean; minute_rows?: number;
    priced_usage_count?: number; unpriced_usage_count?: number; priced_token_total?: number; unpriced_token_total?: number;
    mixed_price_token_total?: number; quality_rows?: number; known_agent_seconds?: number; unknown_agent_seconds?: number };
  price_basis?: unknown;
}
export interface MetricCatalogEntry {
  id: string;
  label?: string;
  unit?: string;
  operations?: Operation[];
  group_by?: string[];
}
export interface DimensionItem { key: string; label: string; filter_value: string | null; minute_rows?: number; through?: string | null }
export interface Annotation {
  id: string;
  revision: number;
  occurred_at: number;
  kind: 'rule' | 'manual';
  label: string;
  rule_hash?: string | null;
  reference?: string | null;
  basis?: string | null;
  scope?: StatsFilters;
}
export interface DetailsView {
  readonly id: string;
  readonly title: string;
  readonly period: string;
  readonly config: ChartConfig;
  readonly results: QueryResult[];
  readonly markers: Annotation[];
  readonly activeSeries: ChartSeries[];
  readonly units: string[];
  readonly thresholds: number[];
  readonly range: { from: string; to: string };
  readonly baseRange: { from: string; to: string };
  readonly quotaWindow: string | undefined;
  readonly selectedMarker: Annotation | null;
  readonly comparisonHours: number;
  readonly open: boolean;
  selectMarker(marker: Annotation | null): void;
  setComparisonHours(hours: number): void;
  setMarkers(next: Annotation[]): void;
}
