import type { ChartConfig } from './types';

export function configKey(chart: ChartConfig): string {
  const { id: _id, revision: _revision, ...config } = chart;
  return JSON.stringify(config, (_key, value: unknown) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : 1)))
      : value,
  );
}

export function staleChartIds(charts: readonly ChartConfig[], referenced: ReadonlySet<string>): string[] {
  const kept = new Set<string>();
  for (const chart of charts) if (referenced.has(`analytics:${chart.id}`)) kept.add(configKey(chart));
  const stale: string[] = [];
  for (const chart of charts) {
    if (referenced.has(`analytics:${chart.id}`)) continue;
    const key = configKey(chart);
    if (kept.has(key)) stale.push(chart.id);
    else kept.add(key);
  }
  return stale;
}

export const PRUNE_DONE_KEY = 'cloudecode.opscenter.charts-pruned.v1';

export function pruneAlreadyDone(): boolean {
  try {
    return localStorage.getItem(PRUNE_DONE_KEY) === 'done';
  } catch {
    return false;
  }
}

export function markPruneDone(): void {
  try {
    localStorage.setItem(PRUNE_DONE_KEY, 'done');
  } catch {
  }
}
