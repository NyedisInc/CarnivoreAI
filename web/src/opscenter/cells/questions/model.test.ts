import { describe, expect, test } from 'vitest';
import { filterRows, mergeQuestions } from './model';
import { alertRows, taskManagerRows, taskManagerWaitingSince } from '../../../lib/attention-kinds/rows';
import type { AppAlert } from '../../../lib/app-alerts/alerts-model';
import type { ApprovalItem } from '../../../lib/approvals/approvals-model';
import type { TaskManagerGroup } from '../../../cplugs/huddle/huddle-model';

const approval = (id: string, createdAt: number | null, extra: Partial<ApprovalItem> = {}): ApprovalItem =>
  ({ id, source: 'dialog', session_id: `ses_${id}`, session_name: `session ${id}`, question: `question ${id}?`, created_at: createdAt, ...extra }) as ApprovalItem;

const groups = (items: Record<string, unknown>[]): TaskManagerGroup[] =>
  [{ list: '7', name: 'billing-api', project_id: 7, revision: 1, items: items as never }];

const waiting = (id: number, at: number, extra: Record<string, unknown> = {}) =>
  ({ id, text: `item ${id}`, needs_you: true, deleted: false, thread: [{ kind: 'question', answered: false, created_at: at }], ...extra });

describe('mergeQuestions', () => {
  test('nothing from either source is an empty list', () => {
    expect(mergeQuestions([], null)).toEqual([]);
    expect(mergeQuestions([], groups([]))).toEqual([]);
  });

  test('approvals and huddle questions interleave oldest first', () => {
    const rows = mergeQuestions([approval('a', 1_700_000_100), approval('c', 1_700_000_300)], groups([waiting(2, 1_700_000_200)]));
    expect(rows.map((r) => r.key)).toEqual(['approval:a', 'huddle:7:2', 'approval:c']);
    expect(rows[1]).toMatchObject({ source: 'huddle', where: 'billing-api', what: 'item 2', atMs: 1_700_000_200_000, target: { source: 'huddle', list: '7', itemId: 2 } });
    expect(rows[0]).toMatchObject({ source: 'approval', where: 'session a', what: 'question a?', target: { source: 'approval', sessionId: 'ses_a' } });
  });

  test('rows with no time come after the dated ones, approvals first', () => {
    const rows = mergeQuestions([approval('undated', null)], groups([waiting(4, 9), { id: 5, text: 'no thread', needs_you: true, deleted: false, thread: [] }]));
    expect(rows.map((r) => r.key)).toEqual(['huddle:7:4', 'approval:undated', 'huddle:7:5']);
  });
});

describe('taskManagerRows', () => {
  test('only live needs-you items qualify', () => {
    const rows = taskManagerRows(groups([waiting(1, 1), waiting(2, 2, { needs_you: false }), waiting(3, 3, { deleted: true }), waiting(4, 4, { title: ' shown title ' })]));
    expect(rows.map((r) => r.key)).toEqual(['huddle:7:1', 'huddle:7:4']);
    expect(rows[1]?.what).toBe('shown title');
  });

  test('the shared list has no project name', () => {
    expect(taskManagerRows([{ list: 'all', name: null, project_id: null, revision: 1, items: [waiting(1, 1)] as never }])[0]?.where).toBe('');
  });
});

describe('taskManagerWaitingSince', () => {
  test('the newest unanswered question wins, else the newest post', () => {
    expect(taskManagerWaitingSince({ thread: [{ kind: 'question', answered: true, created_at: 50 }, { kind: 'question', answered: false, created_at: 10 }, { kind: 'question', answered: false, created_at: 20 }] as never })).toBe(20_000);
    expect(taskManagerWaitingSince({ thread: [{ kind: 'reply', answered: false, created_at: 5 }] as never })).toBe(5_000);
    expect(taskManagerWaitingSince({ thread: [] })).toBeNull();
  });
});

const alert = (id: number, extra: Partial<AppAlert> = {}): AppAlert =>
  ({
    id, key: `k${id}`, source: 'backup_health', severity: 'warn', title_key: `app_alert.t${id}.title`, params: {}, detail_key: null,
    state: 'active', sticky: false, auto_resolve: false, first_seen: '2026-10-11T10:00:00Z', last_seen: '2026-10-11T10:00:00Z', count: 1,
    resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [], source_label_key: 'app_alert.source.backup_health', ...extra,
  }) as AppAlert;

const say = (key: string): string => `<${key}>`;

describe('alertRows', () => {
  test('only the alerts raised and still open become rows, each tagged with its sender and sending the person to the bell', () => {
    const rows = alertRows([alert(1), alert(2, { state: 'snoozed' }), alert(3, { state: 'resolved' }), alert(4, { state: 'dismissed' })], say);
    expect(rows.map((r) => r.key)).toEqual(['alert:1']);
    expect(rows[0]).toMatchObject({ source: 'alert', kindId: 'alert_backup_health', what: '<app_alert.t1.title>', target: { source: 'alert', alertId: 1 }, atMs: Date.parse('2026-10-11T10:00:00Z') });
  });

  test('an alert from a server older than the sender fields falls to the fallback sender', () => {
    expect(alertRows([alert(1, { source_label_key: undefined })], say)[0]?.kindId).toBe('alert_other');
  });
});

describe('one copy lists only the kinds it checked', () => {
  const approvals = [approval('a', 1_700_000_100)];
  const taskManagerGroups = groups([waiting(2, 1_700_000_200)]);
  const alerts = [alert(5, { first_seen: '2023-11-14T22:17:30Z' })];

  test('with no options every source is listed, oldest first', () => {
    expect(mergeQuestions(approvals, taskManagerGroups, alerts, say).map((r) => r.kindId)).toEqual(['approvals', 'huddle', 'alert_backup_health']);
  });

  test('while all is on the kind checks change nothing; with all off each kind is listed on its own and an alert never is', () => {
    const keys = (options: Record<string, boolean>) => mergeQuestions(approvals, taskManagerGroups, alerts, say, options).map((r) => r.kindId);
    expect(keys({ kind_approvals: false })).toEqual(['approvals', 'huddle', 'alert_backup_health']);
    expect(keys({ kind_all: false, kind_approvals: false })).toEqual(['huddle']);
    expect(keys({ kind_all: false, kind_huddle: false })).toEqual(['approvals']);
    expect(keys({ kind_all: false, kind_approvals: false, kind_huddle: false, kind_automations: false })).toEqual([]);
  });

  test('keys of the earlier build are ignored', () => {
    expect(mergeQuestions(approvals, taskManagerGroups, alerts, say, { s_approvals: false, s_alert_backup_health: false }).map((r) => r.kindId)).toEqual(['approvals', 'huddle', 'alert_backup_health']);
  });

  test('two copies with different options list different things from the same data', () => {
    const rows = mergeQuestions(approvals, taskManagerGroups, alerts, say);
    const onlyApprovals = filterRows(rows, { kind_all: false, kind_huddle: false, kind_automations: false });
    const everything = filterRows(rows, undefined);
    expect(onlyApprovals.map((r) => r.key)).toEqual(['approval:a']);
    expect(everything.map((r) => r.key)).toEqual(rows.map((r) => r.key));
  });
});
