
import { metaFor } from '../../engine/meta';
import { recent, outcome, elapsedSeconds, type SessionRecord } from '../../api';
import { atLeast } from '../../lib/states';
import type { ColumnSpec, PhoneSummary } from '../../engine/types';
import { t } from '../../../lib/i18n/index.svelte';

export const meta = metaFor('closed-sessions');

export function taskFor(row: SessionRecord): string {
  return row.title ?? row.tmux_name ?? row.session_uuid;
}

export function closedSeconds(row: SessionRecord, now: number): number | null {
  return elapsedSeconds(row.closed_at, now);
}

export function columnsFor(widthState: string): ColumnSpec[] {
  const steps = meta.widthStates;
  const hasAgent = atLeast(steps, widthState, 'agent-icon');
  const agentNamed = atLeast(steps, widthState, 'agent-name');
  const hasStarted = atLeast(steps, widthState, 'ended');
  const statusLabelled = atLeast(steps, widthState, 'status-label');

  const columns: ColumnSpec[] = [
    { key: 'id', headKey: 'opscenter.column.index', minPx: 53, weight: 0, insetPx: 12 },
    { key: 'task', headKey: 'opscenter.column.name_task', minPx: 110, weight: 1.4, insetPx: 11 },
  ];
  // running sessions
  if (hasAgent) {
    columns.push({ key: 'agent', headKey: 'opscenter.column.agent', minPx: agentNamed ? 90 : 48, weight: agentNamed ? 0.8 : 0, ...(agentNamed ? { insetPx: 17 } : {}) });
  }
  if (hasStarted) columns.push({ key: 'closed', headKey: 'opscenter.column.closed', minPx: 56, weight: 0.68, insetPx: 14 });
  columns.push({ key: 'status', headKey: 'opscenter.column.status', minPx: statusLabelled ? 112 : 34, weight: statusLabelled ? 2.2 : 1.22, ...(statusLabelled ? { insetPx: 15 } : {}) });
  return columns;
}

/* could not */
export function titleCount(): number | null {
  if (recent.status !== 'ok' || !recent.data) return null;
  return outcome(recent.data) === 'could-not-determine' ? null : recent.data.sessions.length;
}

export function phoneTotal(): number | null {
  return titleCount();
}

export function phoneColumns(): ColumnSpec[] {
  return [
    { key: 'status', headKey: 'opscenter.column.status', minPx: 0, weight: 0, line: 1 },
    { key: 'task', headKey: 'opscenter.column.name_task', minPx: 0, weight: 1, line: 1 },
    { key: 'closed', headKey: 'opscenter.column.closed', minPx: 0, weight: 0, align: 'end', line: 1 },
  ];
}

export function lifecycleIcon(lifecycle: string, archived: boolean): string {
  if (archived) return 'archive';
  if (lifecycle === 'running') return 'play';
  if (lifecycle === 'stopped') return 'check-circle';
  return 'clock';
}

/* could not be read */
export function phoneSummary(nowMs: number = Date.now()): PhoneSummary | null {
  if (recent.status !== 'ok' || !recent.data) return null;
  if (outcome(recent.data) === 'could-not-determine') return null;
  const rows = recent.data.sessions;
  const ages = rows
    .map((row) => closedSeconds(row, nowMs))
    .filter((value): value is number => value !== null);
  const newest = ages.length ? Math.min(...ages) : null;
  return {
    marks: [
      {
        tone: 'oc-text-dim',
        shape: 'solid',
        count: rows.length,
        label: t('opscenter.closed.count', { count: rows.length }),
      },
    ],
    note:
      newest === null
        ? t('opscenter.closed.newest_unknown')
        : t('opscenter.closed.newest', { age: phoneStarted(newest) }),
  };
}

/* could not be read */
export function phoneStarted(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return t('opscenter.value.undetermined');
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return t('opscenter.time.short_seconds', { count: whole });
  if (whole < 3600) return t('opscenter.time.short_minutes', { count: Math.floor(whole / 60) });
  if (whole < 86400) return t('opscenter.time.short_hours', { count: Math.floor(whole / 3600) });
  return t('opscenter.time.short_days', { count: Math.floor(whole / 86400) });
}
