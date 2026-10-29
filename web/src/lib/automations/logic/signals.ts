import { t } from '../../i18n/index.svelte';
import type { ListSignals, RecentRun } from './types';
import { isLive, tileLabel } from './words';

export const ATTENTION_RULES = ['waiting_on_you', 'last_run_failed', 'skipped_lately', 'newest_output_empty', 'switched_off'] as const;
export type AttentionRule = (typeof ATTENTION_RULES)[number];

export function attentionWords(rule: AttentionRule): string {
  return t(`automations.page.attention.${rule}`);
}

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

export interface AutomationSignals {
  last: RecentRun | null;
  strip: RecentRun[];
  rate: { n: number; ok: number; v: number };
  median: number | null;
  empty: boolean;
  attention: AttentionRule | null;
  attentionRank: number;
}

export function signalsOf(row: Pick<ListSignals, 'recent' | 'median_took_s' | 'newest_output_empty'>, enabled: boolean): AutomationSignals {
  const runs = row.recent;
  const last = runs[0] ?? null;
  const strip = runs.slice(0, 12).reverse();
  const ok = strip.filter((r) => r.status === 'succeeded').length;
  const empty = row.newest_output_empty;
  const tests: Record<AttentionRule, boolean> = {
    waiting_on_you: !!last && last.status === 'waiting_on_you',
    last_run_failed: !!last && last.status === 'failed',
    skipped_lately: !!last && last.status === 'skipped',
    newest_output_empty: !!last && last.status === 'succeeded' && empty,
    switched_off: !enabled,
  };
  const attention = ATTENTION_RULES.find((r) => tests[r]) ?? null;
  return {
    last,
    strip,
    rate: { n: strip.length, ok, v: strip.length ? ok / strip.length : -1 },
    median: row.median_took_s,
    empty,
    attention,
    attentionRank: attention ? ATTENTION_RULES.indexOf(attention) : ATTENTION_RULES.length,
  };
}

export function rateWords(rate: { n: number; ok: number }): string {
  return rate.n ? t('automations.page.rate', { ok: rate.ok, n: rate.n }) : t('automations.page.rate_none');
}

const UNIT = /_(usd|pct|bytes|s|ms)$/;
const ID_KEY = /(^|_)(id|uuid)$/i;

export interface FirstMetric {
  key: string;
  label: string;
  value: number;
  unit: string | null;
  path: string;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

export function firstMetric(report: unknown): FirstMetric | null {
  if (!isRecord(report)) return null;
  const metrics = report.metrics;
  if (Array.isArray(metrics) && metrics.length && isRecord(metrics[0]) && typeof metrics[0].value === 'number') {
    const m = metrics[0] as { key?: string; label?: string; value: number; unit?: string };
    const key = m.key || m.label || '';
    return { key, label: m.label || tileLabel(m.key ?? ''), value: m.value, unit: m.unit || null, path: 'metrics[0]' };
  }
  let level: { o: Record<string, unknown>; p: string }[] = [{ o: report, p: '' }];
  for (let depth = 0; depth <= 2 && level.length; depth++) {
    const found: FirstMetric[] = [];
    const next: { o: Record<string, unknown>; p: string }[] = [];
    for (const n of level) {
      for (const k of Object.keys(n.o)) {
        const v = n.o[k];
        const p = n.p ? `${n.p}.${k}` : k;
        if (typeof v === 'number' && Number.isFinite(v) && k !== 'exit_code' && k !== 'duration_s' && !ID_KEY.test(k)) {
          found.push({ key: k, label: tileLabel(k), value: v, unit: null, path: p });
        } else if (isRecord(v)) next.push({ o: v, p });
      }
    }
    if (found.length) return found.find((f) => UNIT.test(f.key)) ?? found[0]!;
    level = next;
  }
  return null;
}

export function metricIn(report: unknown, m: FirstMetric): number | null {
  if (!isRecord(report)) return null;
  if (m.path === 'metrics[0]') {
    const list = Array.isArray(report.metrics) ? (report.metrics as { key?: string; label?: string; value?: unknown }[]) : [];
    const f = list.find((x) => (x.key || x.label) === m.key);
    return f && typeof f.value === 'number' ? f.value : null;
  }
  let cur: unknown = report;
  for (const seg of m.path.split('.')) {
    if (!isRecord(cur)) return null;
    cur = cur[seg];
  }
  return typeof cur === 'number' ? cur : null;
}

export function newestIsLive(sig: AutomationSignals): boolean {
  return !!sig.last && isLive(sig.last.status);
}
