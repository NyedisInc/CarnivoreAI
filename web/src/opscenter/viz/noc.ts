import type { Annotation } from '../cells/analytics/types';
import { chartBars, tokensIn, type ChartBar } from '../../lib/stats-feed/rate';
import type { FeedBody } from '../../lib/stats-feed/types';

export interface BurnWindow { window_minutes?: number; tokens_per_minute: number | null; estimated_usd_per_hour: number | null }
export interface TopConversation {
  conversation_id: string;
  provider: string;
  project: string | null;
  model: string | null;
  model_label?: string | null;
  tokens: number;
  estimated_cost_usd: number | null;
}
export interface LivePayload {
  state?: string;
  as_of?: string;
  metrics?: Record<string, number | null>;
  subagents_coverage?: unknown;
  burn?: Record<string, BurnWindow | undefined>;
  cache_hit_ratio_15m?: number | null;
  top_conversations_15m?: TopConversation[];
  agents_5m?: { conversation_id: string; name: string; tokens: number; tokens_per_minute: number }[];
}
export interface VitalsRow {
  activity_status?: string | null;
  startup_gate?: string | null;
  subagents_state?: string | null;
  subagents_running?: number | null;
  session?: { id?: string };
}

export type Trend = 'rising' | 'steady' | 'falling' | 'unknown';
export interface VitalsModel {
  sessions: { live: number; working: number; waiting: number; idle: number } | null;
  subagents: number | null;
  tokensPerMinute: number | null;
  usdPerHour: number | null;
  trend: Trend;
  cacheHit: number | null;
}

export function bucket(row: Pick<VitalsRow, 'activity_status' | 'startup_gate'>): 'working' | 'waiting' | 'idle' | null {
  if (row.startup_gate === 'awaiting_startup_prompt') return 'waiting';
  switch (row.activity_status) {
    case 'working': case 'working_subagent': return 'working';
    case 'question': case 'notice': return 'waiting';
    case 'idle': case 'finished_unread': return 'idle';
    default: return null;
  }
}

export function trendOf(short: number | null | undefined, long: number | null | undefined): Trend {
  if (typeof short !== 'number' || typeof long !== 'number' || long <= 0) return 'unknown';
  const ratio = short / long;
  return ratio > 1.25 ? 'rising' : ratio < 0.8 ? 'falling' : 'steady';
}

export function feedTokens(feed: FeedBody | null): { perMinute: number | null; recent: number | null; hour: number | null } {
  const none = { perMinute: null, recent: null, hour: null };
  if (!feed?.rate) return none;
  const mean = (bars: ChartBar[]): number | null => {
    const seen = bars.map((bar) => bar.total).filter((total): total is number => total !== null);
    return seen.length ? seen.reduce((sum, total) => sum + total, 0) / seen.length : null;
  };
  const bars = chartBars(feed).slice(0, -1);
  return { perMinute: ((tokensIn(feed.rate) ?? 0) + feed.rate.out) * 60, recent: mean(bars.slice(-5)), hour: mean(bars) };
}

export function vitalsModel(live: LivePayload | null, rows: readonly VitalsRow[] | null, feed: FeedBody | null = null): VitalsModel {
  const counts = { live: 0, working: 0, waiting: 0, idle: 0 };
  let subagents: number | null = null;
  const seen = new Set<string>();
  for (const row of rows ?? []) {
    const kind = bucket(row);
    if (kind) { counts[kind]++; counts.live++; }
    const id = row.session?.id;
    if (row.subagents_state === 'ok' && typeof row.subagents_running === 'number' && !(id && seen.has(id))) {
      if (id) seen.add(id);
      subagents = (subagents ?? 0) + row.subagents_running;
    }
  }
  const burn = live?.burn?.['15m'];
  const measured = feedTokens(feed);
  return {
    sessions: rows ? counts : null,
    subagents,
    tokensPerMinute: measured.perMinute,
    usdPerHour: burn?.estimated_usd_per_hour ?? null,
    trend: trendOf(measured.recent, measured.hour),
    cacheHit: live?.cache_hit_ratio_15m ?? null,
  };
}

export interface HotRow {
  key: string;
  conversationId: string;
  project: string | null;
  model: string | null;
  provider: string;
  tokens: number;
  costUsd: number | null;
  share: number;
}

export function hotRows(live: LivePayload | null): HotRow[] {
  const list = [...(live?.top_conversations_15m ?? [])].sort((a, b) => b.tokens - a.tokens);
  const top = list[0]?.tokens ?? 0;
  return list.map((row) => ({
    key: `${row.provider}:${row.conversation_id}`, conversationId: row.conversation_id, project: row.project, model: row.model_label || row.model, provider: row.provider,
    tokens: row.tokens, costUsd: row.estimated_cost_usd, share: top > 0 ? row.tokens / top : 0,
  }));
}

export function hotTag(row: HotRow, rows: readonly HotRow[], title: string | null | undefined): string {
  if (rows.filter((other) => other.project === row.project).length < 2) return '';
  return title?.trim() || row.conversationId.slice(0, 6);
}

export function liveSessionFor<T extends { activity_status?: string | null; claude_session_uuid?: string | null }>(
  conversationId: string | null, sessions: readonly T[] | null,
): T | null {
  if (!conversationId || !sessions) return null;
  const matches = sessions.filter((row) => row.activity_status !== 'dead' && row.claude_session_uuid === conversationId);
  return matches.length === 1 ? matches[0]! : null;
}

export interface LogEvent { id: number; occurred_at: number; kind: string; subject: string; label?: string; data?: Record<string, unknown> }
export interface TickerRow {
  key: string;
  at: number;
  kindKey: string;
  subject: string;
}

export const TICKER_LIMIT = 50;

export function mergeEvents(log: readonly LogEvent[], marks: readonly Annotation[], limit: number = TICKER_LIMIT): TickerRow[] {
  const rows: TickerRow[] = [
    ...log.map((event) => ({ key: `e${event.id}`, at: event.occurred_at, kindKey: `events.kind.${event.kind}`, subject: event.label || event.subject })),
    ...marks.map((mark) => ({ key: `a${mark.id}`, at: mark.occurred_at, kindKey: `events.kind.mark_${mark.kind}`, subject: mark.label })),
  ];
  rows.sort((a, b) => b.at - a.at || (a.key < b.key ? -1 : 1));
  return rows.slice(0, Math.max(0, limit));
}
