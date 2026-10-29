import type { ChartColumns } from '../../lib/run-chart';
import type { RecentRun, RunOutcome } from '../../../lib/pipeline-status/api';
import { pluginNameKey } from '../../../lib/pipeline-status/model';

export interface ChartRow extends Record<string, unknown> {
  id: string;
  name: string;
  area: string | null;
  runMs: number | null;
  agoSeconds: number;
  runs: number | null;
  detail: string | null;
  outcome: RunOutcome;
  error: string | null;
}

export const OUTCOME_KEYS: Readonly<Record<RunOutcome, string>> = {
  ok: 'pipeline.chart.outcome.ok',
  failed: 'pipeline.chart.outcome.failed',
  parked: 'pipeline.chart.outcome.parked',
};

export type DetailOf = (detail: { conversations: number; size_bytes: number }) => string;

export type NameOf = (plugin: string, rebuild: boolean) => string;

export function pluginAreaKey(plugin: string): string {
  return `pipeline.plugin_area.${plugin}`;
}

export function pluginWords(t: (key: string, params?: Record<string, string | number>) => string, plugin: string, rebuild: boolean): string {
  const name = t(pluginNameKey(plugin));
  return rebuild ? t('pipeline.chart.rebuild_of', { plugin: name }) : name;
}

export function chartRows(recent: readonly RecentRun[], nowS: number, nameOf: NameOf, pluginArea: (plugin: string) => string = pluginAreaKey, detailOf: DetailOf = () => ''): ChartRow[] {
  return recent.map((run) => ({
    id: `${run.scope}:${run.session_uuid ?? run.project_id ?? ''}:${run.plugin}:${run.kind}`,
    name: nameOf(run.plugin, run.kind === 'rebuild'),
    area: run.scope === 'plugin' ? pluginArea(run.plugin) : areaOf(run),
    runMs: run.duration_ms ?? null,
    agoSeconds: Math.max(0, nowS - run.finished_at),
    runs: run.runs,
    detail: run.detail ? detailOf(run.detail) || null : null,
    outcome: run.outcome,
    error: run.error,
  }));
}

export function areaOf(run: Pick<RecentRun, 'scope' | 'session' | 'project'>): string | null {
  if (run.scope === 'machine') return null;
  return run.session || run.project || null;
}

export const PIPELINE_COLUMNS: ChartColumns = {
  all: [
    { key: 'name', headKey: 'opscenter.column.name', minPx: 48, weight: 1.4, insetPx: 12 },
    { key: 'area', headKey: 'opscenter.column.area', minPx: 48, weight: 1.6 },
    { key: 'runTime', headKey: 'opscenter.column.run_time', minPx: 40, weight: 0.01, align: 'end', fit: 'runTime' },
    { key: 'ago', headKey: 'opscenter.column.ago', minPx: 40, weight: 0.01, align: 'end', fit: 'ago' },
    { key: 'runs', headKey: 'opscenter.column.runs', minPx: 32, weight: 0.01, align: 'end', insetPx: 12, fit: 'count' },
  ],
  narrow: ['name', 'area', 'runTime', 'ago'],
  wideAt: 380,
  tight: ['name', 'runTime', 'ago'],
  tightAt: 260,
  phone: [
    { key: 'name', headKey: '', minPx: 0, weight: 1, line: 1 },
    { key: 'ago', headKey: '', minPx: 0, weight: 0, align: 'end', line: 1 },
    { key: 'area', headKey: '', minPx: 0, weight: 1, line: 2 },
    { key: 'runTime', headKey: '', minPx: 0, weight: 0, align: 'end', line: 2 },
  ],
};

export function sizeWords(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}
