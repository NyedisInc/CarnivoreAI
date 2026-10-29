
import { metaFor } from '../../engine/meta';
import { normalizeStatus, sessions, statusHue, type SessionInfo } from '../../api';
import { hostOffline, usageLimitLabel } from '../../../lib/led';
import { atLeast } from '../../lib/states';
import type { ColumnSpec, PhoneMark, PhoneSummary } from '../../engine/types';
import { t } from '../../../lib/i18n/index.svelte';

export const meta = metaFor('running-sessions');

export function taskFor(row: SessionInfo): string {
  return row.label ?? row.tmux_session ?? row.session.id;
}

export function columnsFor(widthState: string): ColumnSpec[] {
  const steps = meta.widthStates;
  const hasAgent = atLeast(steps, widthState, 'agent-icon');
  const agentNamed = atLeast(steps, widthState, 'agent-name');
  const hasProject = atLeast(steps, widthState, 'project');
  const hasElapsed = atLeast(steps, widthState, 'elapsed');
  const statusLabelled = atLeast(steps, widthState, 'status-label');

  const columns: ColumnSpec[] = [
    { key: 'id', headKey: 'opscenter.column.index', minPx: 42, weight: 0, insetPx: 14 },
    { key: 'task', headKey: 'opscenter.column.name_task', minPx: 110, weight: 2.13, insetPx: 9 },
  ];
  if (hasAgent) {
    columns.push({ key: 'agent', headKey: 'opscenter.column.agent', minPx: agentNamed ? 90 : 34, weight: 1.19, ...(agentNamed ? { insetPx: 18 } : {}) });
  }
  if (hasProject) columns.push({ key: 'project', headKey: 'opscenter.column.project', minPx: 145, weight: 1.49, insetPx: 11, headInsetPx: 10 });
  if (hasElapsed) columns.push({ key: 'elapsed', headKey: 'opscenter.column.elapsed', minPx: 70, weight: 0.99, insetPx: 12 });
  columns.push({ key: 'status', headKey: 'opscenter.column.status', minPx: statusLabelled ? 100 : 30, weight: 2.2, ...(statusLabelled ? { insetPx: 20 } : {}) });
  return columns;
}

export function titleCount(): number | null {
  return sessions.status === 'ok' ? (sessions.data?.length ?? null) : null;
}

export function phoneTotal(): number | null {
  return titleCount();
}

const GROUPS: readonly { key: string; tone: string; shape: 'solid' | 'hollow'; wordKey: string }[] = [
  { key: 'yellow', tone: 'oc-yellow-bright', shape: 'solid', wordKey: 'opscenter.session.mark.waiting' },
  { key: 'green', tone: 'oc-green-bright', shape: 'solid', wordKey: 'opscenter.session.mark.working' },
  { key: 'green-hollow', tone: 'oc-green-bright', shape: 'hollow', wordKey: 'opscenter.session.mark.finished_unread' },
  { key: 'blue', tone: 'oc-cyan', shape: 'solid', wordKey: 'opscenter.session.mark.notice' },
  { key: 'red', tone: 'oc-coral', shape: 'solid', wordKey: 'opscenter.session.mark.dead' },
  { key: 'grey', tone: 'oc-text-dim', shape: 'solid', wordKey: 'opscenter.session.mark.idle' },
  { key: 'grey-hollow', tone: 'oc-text-dim', shape: 'hollow', wordKey: 'opscenter.session.mark.not_measured' },
];

/* could not be read */
export function phoneSummary(): PhoneSummary | null {
  if (sessions.status !== 'ok') return null;
  const rows = sessions.data ?? [];
  const counts = new Map<string, number>();
  for (const row of rows) {
    const hue = statusHue(row.activity_status, row.startup_gate, row.unread, hostOffline(row), usageLimitLabel(row));
    const key = normalizeStatus(row.activity_status);
    const unread = row.unread === true && (key === 'idle' || key === 'unknown');
    const hollow = row.startup_gate === 'awaiting_startup_prompt' ? false : unread || key === 'unknown';
    const group = hollow && (hue === 'green' || hue === 'grey') ? `${hue}-hollow` : hue;
    counts.set(group, (counts.get(group) ?? 0) + 1);
  }
  const marks: PhoneMark[] = [];
  for (const group of GROUPS) {
    const n = counts.get(group.key) ?? 0;
    if (n === 0) continue;
    marks.push({
      tone: group.tone,
      shape: group.shape,
      count: n,
      label: t('opscenter.session.mark', { count: n, state: t(group.wordKey) }),
    });
  }
  return { marks };
}

export function phoneColumns(): ColumnSpec[] {
  return [
    { key: 'status', headKey: 'opscenter.column.status', minPx: 0, weight: 0, line: 1 },
    { key: 'task', headKey: 'opscenter.column.name_task', minPx: 0, weight: 1, line: 1 },
    { key: 'elapsed', headKey: 'opscenter.column.elapsed', minPx: 0, weight: 0, align: 'end', line: 1 },
    { key: 'project', headKey: 'opscenter.column.project', minPx: 0, weight: 1, line: 2 },
  ];
}

/* could not be read */
export function phoneElapsed(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return t('opscenter.value.undetermined');
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return t('opscenter.time.short_seconds', { count: whole });
  if (whole < 3600) return t('opscenter.time.short_minutes', { count: Math.floor(whole / 60) });
  if (whole < 86400) return t('opscenter.time.short_hours', { count: Math.floor(whole / 3600) });
  return t('opscenter.time.short_days', { count: Math.floor(whole / 86400) });
}
