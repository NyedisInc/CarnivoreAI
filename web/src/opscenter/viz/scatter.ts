import type { ChartConfig } from '../cells/analytics/types';
import { allowedFilters, effectiveRange, mergeFilters, type PlanContext } from './plan';

export const SCATTER_CAP = 500;

export interface ConversationRow {
  conversation_id: string;
  project: string;
  model: string;
  model_label?: string | null;
  tokens: number;
  cost_nano_usd: number | null;
  first_minute: number;
  last_minute: number;
  duration_seconds: number;
}
export interface ConversationsPayload { items: ConversationRow[]; total: number; truncated: boolean }

export interface ScatterPoint {
  id: string;
  minutes: number;
  usd: number;
  tokens: number;
  size: number;
  project: string;
  model: string;
}

export function scatterPath(config: ChartConfig, ctx: PlanContext): string {
  const range = effectiveRange(config, { ...ctx, marker: null });
  const filters = allowedFilters('estimated_cost_nano_usd', mergeFilters(ctx.filters, config.filters));
  const params = new URLSearchParams({ from: range.from, to: range.to, limit: String(SCATTER_CAP) });
  for (const key of ['provider', 'project', 'model'] as const) if (filters[key]) params.set(key, filters[key] as string);
  return `/stats/conversations?${params.toString()}`;
}

export function scatterPoints(rows: readonly ConversationRow[], min = 5, max = 26): { points: ScatterPoint[]; unpriced: number } {
  const priced = rows.filter((row) => row.cost_nano_usd !== null && row.cost_nano_usd > 0);
  const peak = Math.max(1, ...priced.map((row) => row.tokens));
  return {
    unpriced: rows.length - priced.length,
    points: priced.map((row) => ({
      id: row.conversation_id, minutes: Math.max(1, row.duration_seconds / 60), usd: (row.cost_nano_usd as number) / 1e9, tokens: row.tokens,
      size: min + (max - min) * Math.sqrt(row.tokens / peak), project: row.project, model: row.model_label || row.model,
    })),
  };
}
