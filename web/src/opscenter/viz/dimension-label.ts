import { t } from '../../lib/i18n/index.svelte';
import type { QueryBody, QueryResult } from '../cells/analytics/types';

const NAMED_GROUPS = new Set(['agent_kind', 'key', 'window']);

export function dimensionLabel(metric: string, groupBy: string | undefined, value: string | null | undefined, label: string): string {
  if (!groupBy || !NAMED_GROUPS.has(groupBy) || !value) return label;
  const key = `viz.dim.${groupBy === 'key' ? metric : groupBy}.${value}`;
  const named = t(key);
  return named !== key ? named : label.replaceAll('_', ' ');
}

export function windowLabel(value: string): string {
  return dimensionLabel('', 'window', value, value);
}

export function labelResult(body: QueryBody, result: QueryResult): QueryResult {
  if (!body.group_by || !NAMED_GROUPS.has(body.group_by)) return result;
  const name = <T extends { key: string; label: string; filter_value?: string | null }>(row: T): T =>
    ({ ...row, label: dimensionLabel(body.metric, body.group_by, row.filter_value ?? row.key, row.label) });
  return {
    ...result,
    series: result.series.map(name),
    ranking: result.ranking?.map(name) ?? result.ranking,
    comparison: result.comparison ? { ...result.comparison, series: result.comparison.series.map(name), ranking: result.comparison.ranking?.map(name) ?? result.comparison.ranking } : result.comparison,
  };
}
