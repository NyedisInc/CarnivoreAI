import { PRESETS, presetConfig } from '../../viz/presets';
import { fixtureChartId } from './ids';
import type { QueryBody, QueryResult } from '../../cells/analytics/types';
import { ago, DAY, epochAgo, FROZEN_NOW, HOUR, MIN } from './clock';
import { ledgerFixtures } from './core.ledger';
import { sessionList } from './made-up';
import type { RouteTable, WidgetFixtures } from './types';

const POINTS = 24;

const GROUPS: Readonly<Record<string, readonly string[]>> = {
  account_id: ['studio account', 'harbor team account', 'lab'],
  project: ['atlas', 'harbor', 'meridian', 'billing-api', 'docs-site', 'mobile-app', 'infra-tools', 'release-notes'],
  model: ['opus 5.5', 'sonnet 5.5', 'haiku 4.5', 'gpt 5.2', 'opus 4.5', 'sonnet 4.5'],
  provider: ['claude', 'codex', 'gemini'],
  agent_kind: ['session', 'subagent'],
  subagent_type: ['builder', 'explore', 'verifier'],
  window: ['five_hour', 'seven_day', 'seven_day_opus'],
  conversation_id: ['billing retries', 'docs search', 'push tokens'],
};

const KEYS_BY_METRIC: Readonly<Record<string, readonly string[]>> = {
  stop_reasons: ['tool_use', 'end_turn', 'max_tokens', 'pause_turn', 'stop_sequence', 'refusal'],
  tool_calls: ['Bash', 'Read', 'Edit', 'Grep', 'Write', 'Glob', 'Task', 'WebFetch', 'TodoWrite', 'NotebookEdit'],
};

const ACCOUNT_KEYS: Readonly<Record<string, string>> = { 'studio account': 'acct-studio', 'harbor team account': 'acct-home', lab: 'acct-lab' };

function seedOf(text: string): number {
  let hash = 7;
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) % 9973;
  return hash;
}

function unitOf(metric: string): string {
  if (metric.includes('cost')) return 'nano_usd';
  if (metric.includes('seconds')) return 'seconds';
  if (metric.includes('utilization')) return 'percent';
  if (metric.includes('tokens')) return 'tokens';
  if (metric === 'usage_count') return 'observations';
  if (metric.startsWith('average_')) return 'agents';
  return 'events';
}

const POINT_BASE: Readonly<Record<string, number>> = { percent: 40, nano_usd: 12e9, agents: 3, events: 120 };

function valueAt(metric: string, group: number, i: number): number {
  const seed = seedOf(metric) + group * 101;
  const base = POINT_BASE[unitOf(metric)] ?? 1200;
  return Math.round(base * (1 + 0.6 * Math.sin((i + seed) / 3.5)) * (1 - group * 0.22));
}

function labelsOf(body: QueryBody): readonly string[] {
  if (!body.group_by) return ['total'];
  const values = body.group_by === 'key' ? KEYS_BY_METRIC[body.metric] : GROUPS[body.group_by];
  return (values ?? ['first group', 'second group', 'third group']).slice(0, body.top_n ?? 3);
}

function effectiveRange(body: QueryBody): QueryResult['effective_range'] {
  return body.from !== undefined && body.to !== undefined ? { from: body.from, to: body.to } : undefined;
}

function seriesFor(body: QueryBody, shift: number): QueryResult['series'] {
  const from = Date.parse(body.from ?? '') || FROZEN_NOW - 24 * HOUR * 1000;
  const to = Date.parse(body.to ?? '') || FROZEN_NOW;
  const step = Math.max(60_000, Math.floor((to - from) / POINTS));
  return labelsOf(body).map((label, group) => ({
    key: (body.group_by === 'account_id' ? ACCOUNT_KEYS[label] : undefined) ?? label.replace(/\s+/g, '-'),
    label,
    points: Array.from({ length: POINTS }, (_, i) => ({
      time: new Date(from + i * step).toISOString(),
      value: valueAt(body.metric, group, i + shift),
      samples: 4,
    })),
  }));
}

function answer(body: QueryBody): QueryResult {
  const series = seriesFor(body, 0);
  const total = series.reduce((sum, one) => sum + one.points.reduce((s, p) => s + (p.value ?? 0), 0), 0);
  return {
    metric: body.metric,
    operation: body.operation,
    unit: unitOf(body.metric),
    resolution: body.resolution,
    effective_range: effectiveRange(body),
    series,
    summary: { value: total, samples: POINTS * series.length, contributing_conversations: 12 },
    ranking: series.map((one, i) => ({ key: one.key, label: one.label, filter_value: one.label, value: total / (i + 2), samples: 6 })),
    comparison: body.comparison
      ? { range: body.comparison, series: seriesFor(body, 5), summary: { value: Math.round(total * 0.8), samples: POINTS } }
      : null,
    coverage: { observed_minutes: 1440, range_minutes: 1440, partial: false },
  };
}

function emptyAnswer(body: QueryBody): QueryResult {
  return { metric: body.metric, operation: body.operation, unit: unitOf(body.metric), resolution: body.resolution,
    effective_range: effectiveRange(body), series: [], summary: { value: null, samples: 0 }, ranking: [], comparison: null };
}

function batch(answerOne: (body: QueryBody) => QueryResult): (url: URL, init?: RequestInit) => unknown {
  return (_url, init) => {
    const items = (JSON.parse(String(init?.body ?? '{}')) as { items?: QueryBody[] }).items ?? [];
    return { results: items.map((body) => ({ ok: true, result: answerOne(body) })) };
  };
}

function charts(): unknown[] {
  return PRESETS.map((preset) => ({ ...presetConfig(preset), id: fixtureChartId(preset.id), revision: 1 }));
}

function shared(): RouteTable {
  const metrics = [...new Set(PRESETS.flatMap((p) => p.series.map((s) => s.metric)))];
  return {
    'GET /stats/charts': charts(),
    'GET /stats/catalog': metrics.map((id) => ({ id, label: id.replace(/_/g, ' '), unit: unitOf(id), operations: ['sum', 'avg', 'max'], group_by: Object.keys(GROUPS) })),
    'GET /stats/settings': { enabled: true, revision: 1 },
    'GET /stats/tripwires': [],
    'GET /stats/events*': { items: [] },
    'GET /stats/annotations*': { items: [] },
  };
}

const MARKER = { id: 'mark-retry-rule', revision: 1, occurred_at: epochAgo(2 * DAY), kind: 'rule', label: 'retry rule tightened', reference: null };

function live(): unknown {
  const burn = (tokens: number, usd: number, minutes: number) => ({ window_minutes: minutes, tokens_per_minute: tokens, estimated_usd_per_hour: usd });
  const top = (id: string, project: string, model: string, label: string, tokens: number, usd: number) => ({
    conversation_id: id, provider: model.startsWith('gpt') ? 'codex' : 'claude', project, model, model_label: label, tokens, estimated_cost_usd: usd,
  });
  return {
    state: 'ok', as_of: ago(20), metrics: { working: 3, waiting: 1, sessions: 7 },
    burn: { '5m': burn(2140, 5.8, 5), '15m': burn(1860, 4.9, 15), '60m': burn(1520, 4.1, 60) },
    cache_hit_ratio_15m: 0.62,
    top_conversations_15m: [
      top('conv-billing-retries', 'billing-api', 'opus-5.5', 'Opus 5.5', 48200, 1.92),
      top('conv-docs-search', 'docs-site', 'sonnet-5.5', 'Sonnet 5.5', 31400, 0.61),
      top('conv-push-tokens', 'mobile-app', 'sonnet-5.5', 'Sonnet 5.5', 18900, 0.37),
      top('conv-infra-sweep', 'infra-tools', 'gpt-5.2', 'GPT 5.2', 9600, 0.22),
    ],
  };
}

function eventLog(): unknown {
  const event = (id: number, secondsAgo: number, kind: string, subject: string) => ({ id, occurred_at: epochAgo(secondsAgo), kind, subject, label: subject });
  return {
    items: [
      event(9, 2 * MIN, 'session_created', 'billing webhooks'),
      event(8, 9 * MIN, 'tripwire_fired', 'spend over 5 usd an hour'),
      event(7, 26 * MIN, 'session_finished', 'docs search'),
      event(6, 48 * MIN, 'account_switched', 'studio to home'),
      event(5, 2 * HOUR, 'model_first_seen', 'sonnet 5.5'),
      event(4, 3 * HOUR, 'tripwire_resolved', 'spend over 5 usd an hour'),
      event(3, 5 * HOUR, 'session_created', 'mobile-app'),
    ],
  };
}

function impact(): unknown {
  const at = MARKER.occurred_at;
  return {
    annotation: { id: MARKER.id, label: MARKER.label, kind: MARKER.kind, reference: null, occurred_at: at },
    metric: 'estimated_cost_nano_usd', unit: 'nano_usd', days: 7,
    before: { from: at - 7 * DAY, to: at, n: 64, conversations: 64, median: 410_000_000 },
    after: { from: at, to: epochAgo(0), n: 22, conversations: 22, median: 520_000_000, partial: true },
    delta: { absolute: 110_000_000, percent: 0.268 },
    interval: { low: 40_000_000, high: 180_000_000, level: 0.95, iterations: 1000, seed: 7 },
    mix: { distance: 0.08, shifted: false, models: [
      { model: 'opus-5.5', model_label: 'Opus 5.5', before: 0.42, after: 0.46 },
      { model: 'sonnet-5.5', model_label: 'Sonnet 5.5', before: 0.48, after: 0.45 },
      { model: 'haiku-4.5', model_label: 'Haiku 4.5', before: 0.1, after: 0.09 },
    ] },
    verdict: 'higher', subsampled: false,
  };
}

function conversations(): unknown {
  const projects = GROUPS.project!;
  const models = [['opus-5.5', 'Opus 5.5'], ['sonnet-5.5', 'Sonnet 5.5'], ['haiku-4.5', 'Haiku 4.5'], ['gpt-5.2', 'GPT 5.2']] as const;
  const items = Array.from({ length: 30 }, (_, i) => {
    const minutes = 3 + ((i * 37) % 180);
    const model = models[i % models.length]!;
    const last = Math.round(FROZEN_NOW / 60_000) - i * 190;
    return {
      conversation_id: `conv-${i + 1}`, project: projects[i % projects.length]!, model: model[0], model_label: model[1],
      tokens: 4000 + ((i * 7919) % 90_000), cost_nano_usd: (20 + ((i * 131) % 900)) * 10_000_000,
      first_minute: last - minutes, last_minute: last, duration_seconds: minutes * 60,
    };
  });
  return { items, total: items.length, truncated: false };
}

function coverage(): unknown {
  return {
    state: 'ok', from: ago(30 * DAY), to: ago(0), latest: ago(40), freshness_seconds: 40,
    minute_rows: 182_400, quality_rows: 181_950, unknown_cost_rows: 450, disabled_spans: [],
    sources: [{ status: 'ok', quality: 'exact', count: 214 }, { status: 'ok', quality: 'estimated', count: 12 }, { status: 'pending', quality: 'exact', count: 2 }],
    backfill: { done: 226, pending: 2 }, db_bytes: 412_000_000,
    collector: { state: 'ok', last_success: epochAgo(12), backfill_running: false,
      collector: { known_sources: 228, pending_sources: 2, initial_pending_sources: 0, backfill_complete: true } },
  };
}

function data(): RouteTable {
  return {
    ...shared(),
    'POST /stats/query-batch': batch(answer),
    'GET /stats/live': live(),
    'GET /stats/coverage': coverage(),
    'GET /stats/dimensions*': (url: URL) => ({
      items: (GROUPS[url.searchParams.get('dimension') ?? url.searchParams.get('name') ?? ''] ?? []).map((label) => ({ key: label, label, filter_value: label })),
    }),
    'GET /stats/event-log*': eventLog(),
    'GET /stats/events*': { items: [MARKER] },
    'GET /stats/impact*': impact(),
    'GET /stats/conversations*': conversations(),
    'GET /stats/contributions*': { items: [] },
    'GET /sessions/list': sessionList(),
    'GET /provider-ledger': ledgerFixtures.data['GET /provider-ledger'],
  };
}

function empty(): RouteTable {
  return {
    ...shared(),
    'POST /stats/query-batch': batch(emptyAnswer),
    'GET /stats/live': { state: 'ok', as_of: ago(20), metrics: {} },
    'GET /stats/coverage': { state: 'empty' },
    'GET /stats/dimensions*': { items: [] },
    'GET /stats/event-log*': { items: [] },
    'GET /stats/contributions*': { items: [] },
    'GET /stats/conversations*': { items: [], total: 0, truncated: false },
    'GET /sessions/list': [],
    'GET /provider-ledger': ledgerFixtures.empty['GET /provider-ledger'],
  };
}

export function analyticsFixtures(presetId: string): WidgetFixtures | undefined {
  if (!PRESETS.some((preset) => preset.id === presetId)) return undefined;
  return { data: data(), empty: empty() };
}
