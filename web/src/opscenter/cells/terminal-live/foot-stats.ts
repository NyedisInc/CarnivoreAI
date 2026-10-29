import type { SessionTokenUsage, UsageContextView, UsagePanelModel, UsageRow, UsageWindowView } from '../../api';
import { t } from '../../../lib/i18n/index.svelte';
import { clockText } from '../../lib/clock';

const DAY_MS = 86_400_000;

export type StatsCell =
  | { kind: 'context'; key: 'context'; label: string; view: UsageContextView }
  | { kind: 'window'; key: string; label: string; view: UsageWindowView; resetAt: string | null }
  | { kind: 'model'; key: 'model'; label: string; row: UsageRow; effort: string | null }
  | { kind: 'text'; key: string; label: string; row: UsageRow };

export function resetClock(resetsAt: string | null | undefined, nowMs: number): string | null {
  const at = resetsAt ? Date.parse(resetsAt) : NaN;
  if (!Number.isFinite(at) || at <= nowMs || at - nowMs >= DAY_MS) return null;
  return t('usage.window.reset_at', { time: clockText(at) });
}

export function statsGroups(model: UsagePanelModel, payload: SessionTokenUsage | null, nowMs: number): StatsCell[][] {
  if (model.state !== 'ok') return [];
  const rows: Record<string, UsageRow> = Object.fromEntries(model.rows.map((r) => [r.key, r]));
  const text = (key: string): StatsCell[] => (rows[key] ? [{ kind: 'text', key, label: rows[key].label, row: rows[key] }] : []);

  const first: StatsCell[] = [{ kind: 'context', key: 'context', label: model.context.title, view: model.context }];
  const modelRow = rows.model;
  if (modelRow?.spans?.[0]?.text) {
    const hasEffort = typeof payload?.effort === 'string' && payload.effort.trim() !== '' && modelRow.spans.length > 2;
    first.push({ kind: 'model', key: 'model', label: modelRow.label, row: modelRow,
      effort: hasEffort ? (modelRow.spans[2]?.text ?? null) : null });
  }
  first.push(...text('tokens'));

  const raw = payload?.account?.windows ?? [];
  const windows: StatsCell[] = model.windows.map((view) => ({
    kind: 'window', key: view.key, label: view.label, view,
    resetAt: resetClock(raw.find((w) => `window:${w.kind}` === view.key)?.resets_at, nowMs),
  }));

  const last: StatsCell[] = [...text('cost')];
  if (payload?.account) last.push(...text('account'));
  last.push(...text('login'), ...text('limits'));

  return [first, windows, last].filter((group) => group.length > 0);
}
