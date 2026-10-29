import { createdMs, targetNameFor, type ApprovalItem } from '../approvals/approvals-model';
import { headline } from '../approvals/approval-display';
import type { TaskManagerGroup, HuddleItem } from '../../cplugs/huddle/huddle-model';
import { senderText, type AppAlert, type Severity } from '../app-alerts/alerts-model';
import type { RunRow } from '../../opscenter/cells/developer/model';
import { resultOf } from '../../opscenter/cells/developer/model';
import { APPROVALS_KIND, AUTOMATIONS_KIND, TASK_MANAGER_KIND, alertKindId, type KindOrigin } from './kinds';

export type Translate = (key: string, params?: Record<string, unknown> | null) => string;

export type AttentionTarget =
  | { source: 'approval'; sessionId: string }
  | { source: 'huddle'; list: string; itemId: number }
  | { source: 'alert'; alertId: number }
  | { source: 'automation'; automationId: string };

export interface AttentionRow {
  key: string;
  source: KindOrigin;
  kindId: string;
  severity: Severity;
  sender: string;
  what: string;
  where: string;
  atMs: number | null;
  target: AttentionTarget;
}

export function approvalWhat(item: ApprovalItem): string {
  if (item.display) return headline(item.display);
  return (item.question || item.summary || item.action || item.kind || '').trim();
}

export function taskManagerWaitingSince(item: Pick<HuddleItem, 'thread'>): number | null {
  const posts = (item.thread ?? []).filter((m) => Number.isFinite(m.created_at) && m.created_at > 0);
  const open = posts.filter((m) => m.kind === 'question' && !m.answered);
  const pick = (open.length ? open : posts).reduce<number | null>((best, m) => (best === null || m.created_at > best ? m.created_at : best), null);
  return pick === null ? null : pick * 1000;
}

export function taskManagerRows(groups: readonly TaskManagerGroup[] | null): AttentionRow[] {
  const rows: AttentionRow[] = [];
  for (const group of groups ?? []) {
    for (const item of group.items ?? []) {
      if (!item.needs_you || item.deleted) continue;
      rows.push({
        key: `huddle:${group.list}:${item.id}`,
        source: 'huddle',
        kindId: TASK_MANAGER_KIND,
        severity: 'warn',
        sender: '',
        what: (item.title || item.text || '').trim(),
        where: group.name ?? '',
        atMs: taskManagerWaitingSince(item),
        target: { source: 'huddle', list: group.list, itemId: item.id },
      });
    }
  }
  return rows;
}

export function approvalRows(items: readonly ApprovalItem[]): AttentionRow[] {
  return items.map((item) => ({
    key: `approval:${item.id}`,
    source: 'approval' as const,
    kindId: APPROVALS_KIND,
    severity: 'warn' as const,
    sender: '',
    what: approvalWhat(item),
    where: (targetNameFor(item, null) ?? item.project ?? '').trim(),
    atMs: createdMs(item),
    target: { source: 'approval' as const, sessionId: item.session_id ?? item.tmux_session ?? '' },
  }));
}

export function alertRows(alerts: readonly AppAlert[], translate: Translate): AttentionRow[] {
  return alerts
    .filter((alert) => alert.state === 'active')
    .map((alert) => {
      const at = Date.parse(alert.first_seen);
      return {
        key: `alert:${alert.id}`,
        source: 'alert' as const,
        kindId: alertKindId(alert.source_label_key),
        severity: alert.severity,
        sender: senderText(alert, translate as never),
        what: translate(alert.title_key, alert.params),
        where: alert.source_name ?? '',
        atMs: Number.isFinite(at) ? at : null,
        target: { source: 'alert' as const, alertId: alert.id },
      };
    });
}

const NO_RESULT = new Set(['claimed', 'running', 'waiting_on_you', 'skipped', 'cancelled']);

export function failedAutomationRows(runs: readonly RunRow[]): AttentionRow[] {
  const latest = new Map<string, RunRow>();
  for (const run of runs) {
    if (NO_RESULT.has(run.status)) continue;
    const seen = latest.get(run.automation_id);
    if (!seen || stamp(run) > stamp(seen)) latest.set(run.automation_id, run);
  }
  const rows: AttentionRow[] = [];
  for (const run of latest.values()) {
    if (resultOf(run.status) !== 'error') continue;
    const at = run.ended_at ?? run.started_at;
    rows.push({
      key: `automation:${run.automation_id}`,
      source: 'automation',
      kindId: AUTOMATIONS_KIND,
      severity: 'error',
      sender: '',
      what: run.automation_name,
      where: '',
      atMs: at === null ? null : at * 1000,
      target: { source: 'automation', automationId: run.automation_id },
    });
  }
  return rows;
}

function stamp(run: RunRow): number {
  return run.ended_at ?? run.started_at ?? run.slot_at ?? 0;
}
