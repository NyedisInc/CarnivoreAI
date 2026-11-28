import { t } from '../../lib/i18n/index.svelte';
import type { ChartConfig, QueryBody, QueryResult, RangePreset } from '../cells/analytics/types';
import { liveSessionFor, type LivePayload } from './noc';
import { baseRange, seriesBody, type PlanContext } from './plan';

export const AGENT_LINES = 8;
export const AGENT_WINDOWS: readonly RangePreset[] = ['1h', '24h', '7d'];
export const AGENT_DEFAULT_WINDOW: RangePreset = '24h';
export const OTHER_KEY = 'other';
export const OTHER_COLOR = '--oc-text-dim';

export function agentWindow(config: Pick<ChartConfig, 'range'>): RangePreset {
  const saved = config.range.preset;
  return saved && AGENT_WINDOWS.includes(saved) ? saved : AGENT_DEFAULT_WINDOW;
}

/* tokens per agent */
export function agentsPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const series = { metric: 'total_tokens', operation: 'timeline' as const, group_by: 'conversation_id' };
  const own: ChartConfig = { ...config, range: { mode: 'global', preset: agentWindow(config), zoom: null } };
  const plan = { ...ctx, marker: null, rolling: true };
  return [{ ...seriesBody(own, series, baseRange(own, ctx.now), plan), top_n: AGENT_LINES }];
}

function seedOf(text: string): number {
  let hash = 0x811c9dc5;
  for (let at = 0; at < text.length; at++) hash = Math.imul(hash ^ text.charCodeAt(at), 0x01000193);
  return (hash >>> 1) || 1;
}

export const AGENT_SERIES_TOKENS: readonly string[] = Array.from(
  { length: AGENT_LINES },
  (_, index) => `var(--oc-series-${index + 1})`,
);

const COLOR_PROBE_STRIDE = 3;

/* gives the same */
export function agentColor(conversationId: string): string {
  const seed = seedOf(conversationId);
  return AGENT_SERIES_TOKENS[seed % AGENT_SERIES_TOKENS.length]!;
}

export function assignAgentColors(conversationIds: readonly string[]): Map<string, string> {
  const count = AGENT_SERIES_TOKENS.length;
  const used = new Set<number>();
  const colors = new Map<string, string>();
  for (const id of conversationIds) {
    if (colors.has(id)) continue;
    const start = seedOf(id) % count;
    let chosen = start;
    for (let step = 0; step < count; step += 1) {
      const candidate = (start + step * COLOR_PROBE_STRIDE) % count;
      if (!used.has(candidate)) {
        chosen = candidate;
        used.add(candidate);
        break;
      }
    }
    colors.set(id, AGENT_SERIES_TOKENS[chosen]!);
  }
  return colors;
}

export interface AgentLine { key: string; name: string; color: string; other: boolean }

function withoutEmptyNewest(series: QueryResult['series']): QueryResult['series'] {
  const newest = series.reduce((latest, item) => { const time = item.points[item.points.length - 1]?.time ?? ''; return time > latest ? time : latest; }, '');
  return series.map((item) => {
    const last = item.points[item.points.length - 1];
    return last && last.time === newest && !last.value ? { ...item, points: item.points.slice(0, -1) } : item;
  });
}

export function agentChart(result: QueryResult | null): { result: QueryResult | null; lines: AgentLine[]; colors: Map<string, string> } {
  if (!result) return { result: null, lines: [], colors: new Map() };
  const series = withoutEmptyNewest(result.series.map((item) => (item.key === OTHER_KEY ? { ...item, label: t('agents.other') } : item)));
  const namedIds = series.filter((item) => item.key !== OTHER_KEY).map((item) => item.filter_value ?? item.key);
  const colors = assignAgentColors(namedIds);
  const lines = series.map((item) => {
    const id = item.filter_value ?? item.key;
    return {
      key: item.key, name: item.label, other: item.key === OTHER_KEY,
      color: item.key === OTHER_KEY ? OTHER_COLOR : (colors.get(id) ?? agentColor(id)),
    };
  });
  return { result: { ...result, series }, lines, colors };
}

const BUCKET_MINUTES: Partial<Record<QueryResult['resolution'], number>> = { minute: 1, '5minute': 5, hour: 60, day: 1440, week: 10080 };

function bucketMinutes(result: QueryResult): number {
  const fixed = BUCKET_MINUTES[result.resolution];
  if (fixed) return fixed;
  let gap = Infinity;
  for (const item of result.series) {
    for (let at = 1; at < item.points.length; at++) {
      const step = Date.parse(item.points[at]!.time) - Date.parse(item.points[at - 1]!.time);
      if (step > 0 && step < gap) gap = step;
    }
  }
  return Number.isFinite(gap) ? gap / 60000 : 0;
}

export function agentP95(result: QueryResult | null): number {
  if (!result) return 0;
  const minutes = bucketMinutes(result);
  if (!(minutes > 0)) return 0;
  const rates: number[] = [];
  for (const item of result.series) {
    if (item.key === OTHER_KEY) continue;
    for (const point of item.points) if (point.value && point.value > 0) rates.push(point.value / minutes);
  }
  if (!rates.length) return 0;
  rates.sort((a, b) => a - b);
  return rates[Math.ceil(0.95 * rates.length) - 1]!;
}

export interface LiveAgent { key: string; name: string; color: string; perMinute: number; share: number }

export function liveAgents<T extends { activity_status?: string | null; claude_session_uuid?: string | null }>(
  live: LivePayload | null,
  sessions: readonly T[] | null,
  reference = 0,
  colors?: ReadonlyMap<string, string>,
): LiveAgent[] {
  const rows = (live?.agents_5m ?? [])
    .filter((row) => row.tokens_per_minute > 0 && liveSessionFor(row.conversation_id, sessions))
    .sort((a, b) => b.tokens_per_minute - a.tokens_per_minute || a.name.localeCompare(b.name));
  const top = reference > 0 ? reference : rows[0]?.tokens_per_minute ?? 0;
  return rows.map((row) => ({
    key: row.conversation_id,
    name: row.name,
    color: colors?.get(row.conversation_id) ?? agentColor(row.conversation_id),
    perMinute: row.tokens_per_minute,
    share: top > 0 ? Math.min(1, row.tokens_per_minute / top) : 0,
  }));
}
