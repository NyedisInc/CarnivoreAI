/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

let approvalsReply: { items: unknown[] } = { items: [] };
let aggregateReply: { groups: unknown[] } = { groups: [] };
let alertsReply: { alerts: unknown[]; counts: unknown; sources: unknown[] } = { alerts: [], counts: { error: 0, warn: 0, info: 0 }, sources: [] };
const calls: string[] = [];

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${path}`);
    if (path === '/approvals') return approvalsReply;
    if (path === '/cplugs/huddle/aggregate?live_only=1') return aggregateReply;
    if (path === '/cplugs/huddle/lists') return { lists: [] };
    if (path.startsWith('/alerts')) return alertsReply;
    return null;
  },
}));

const openApprovalFor = vi.fn(async (_: string) => 'opened');
vi.mock('../../../lib/approvals/mount-approvals.svelte', () => ({ openApprovalFor: (id: string) => openApprovalFor(id), jumpToApproval: () => {} }));

const openAppAlerts = vi.fn();
vi.mock('../../../lib/app-alerts/alert-panel.svelte', () => ({ openAppAlerts: () => openAppAlerts(), alertPanel: { open: false }, toggleAppAlerts: () => {} }));

import Cell from './Cell.svelte';
import { alertCountSource } from '../../../lib/session-rail/alert-counts';
import '../../../lib/session-rail/alert-count-sources.svelte';
import { titleCount } from './meta';
import { META } from '../../engine/meta';
import { approvals, refreshApprovals } from '../../../lib/approvals/approvals.svelte';
import { huddle, refreshTaskManager } from '../../../cplugs/huddle/huddle.svelte';
import { alertCenter, refreshAlerts } from '../../../lib/app-alerts/alerts.svelte';
import { setLocale, t } from '../../../lib/i18n/index.svelte';
import { sidebarTabs } from '../../../lib/dynamic-tabs/tab-store.svelte';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  approvalsReply = { items: [] };
  aggregateReply = { groups: [] };
  alertsReply = { alerts: [], counts: { error: 0, warn: 0, info: 0 }, sources: [] };
  calls.length = 0;
  openAppAlerts.mockClear();
  alertCenter.alerts = [];
  alertCenter.sources = [];
  alertCenter.status = 'idle';
  approvals.items = [];
  approvals.status = 'idle';
  huddle.groups = null;
  huddle.status = 'idle';
});

function draw(options?: Record<string, boolean>, instance = 'questions'): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(Cell, { target, props: { width: 300, height: 300, meta: META.questions, instance, page: 'home', options } as never }));
  flushSync();
  return target;
}

async function settle(): Promise<void> {
  await refreshApprovals();
  await refreshTaskManager();
  await refreshAlerts();
  await tick();
}

describe('the questions cell', () => {
  test('nothing waiting reads lowercase and plain, and the title count is 0', async () => {
    const host = draw();
    await settle();
    expect(host.querySelector('[data-questions-empty] .oc-state__title')?.textContent).toBe('nothing waiting on you');
    expect(host.querySelector('[data-question-row]')).toBeNull();
    expect(titleCount()).toBe(0);
  });

  test('an approval and a huddle question land in one list, oldest first, and a push replaces them', async () => {
    approvalsReply = { items: [{ id: 'a1', source: 'dialog', session_id: 'ses_1', session_name: 'carnivore api', question: 'run npm test?', created_at: 2_000 }] };
    aggregateReply = { groups: [{ list: '7', name: 'billing', project_id: 7, revision: 1, items: [{ id: 9, text: 'ship it?', needs_you: true, deleted: false, thread: [{ kind: 'question', answered: false, created_at: 1_000 }] }] }] };
    const host = draw();
    await settle();
    const rows = [...host.querySelectorAll('[data-question-row]')];
    expect(rows.map((r) => r.getAttribute('data-question-row'))).toEqual(['huddle:7:9', 'approval:a1']);
    expect(rows[1]?.textContent).toContain('carnivore api');
    expect(rows[1]?.textContent).toContain('run npm test?');
    expect(rows[0]?.textContent).toContain('billing');
    expect(titleCount()).toBe(2);
    approvalsReply = { items: [] };
    aggregateReply = { groups: [] };
    await settle();
    expect(host.querySelector('[data-question-row]')).toBeNull();
    expect(host.querySelector('[data-questions-empty]')).not.toBeNull();
  });

  test('a click opens the approval inbox on the session, or the huddle item through its documented focus route', async () => {
    approvalsReply = { items: [{ id: 'a1', source: 'dialog', session_id: 'ses_1', session_name: 'api', question: 'q?', created_at: 5_000 }] };
    aggregateReply = { groups: [{ list: '7', name: 'billing', project_id: 7, revision: 1, items: [{ id: 9, text: 'ship it?', needs_you: true, deleted: false, thread: [] }] }] };
    const host = draw();
    await settle();
    host.querySelector<HTMLElement>('[data-question-row="approval:a1"]')!.click();
    await tick();
    expect(openApprovalFor).toHaveBeenCalledWith('ses_1');
    host.querySelector<HTMLElement>('[data-question-row="huddle:7:9"]')!.click();
    await settle();
    expect(calls).not.toContain('POST /cplugs/huddle/focus');
    expect(host.querySelector('[data-questions-failed] .oc-state__title')?.textContent).toBe(t('opscenter.cell.task_list.no_tm'));
    expect(sidebarTabs.active()).not.toBe('huddle');
    const taskManager = document.body.appendChild(document.createElement('div'));
    taskManager.setAttribute('data-task-manager-all-cell', '');
    host.querySelector<HTMLElement>('[data-question-row="huddle:7:9"]')!.click();
    await settle();
    expect(calls).toContain('POST /cplugs/huddle/focus');
    expect(sidebarTabs.active()).not.toBe('huddle');
    taskManager.remove();
  });
});

const ALERT = {
  id: 31, key: 'backup_health.usb_stale', source: 'backup_health', severity: 'warn', title_key: 'app_alert.backup_health.usb_stale.title', params: {}, detail_key: null,
  state: 'active', sticky: false, auto_resolve: false, first_seen: '2026-10-11T10:00:00Z', last_seen: '2026-10-11T10:00:00Z', count: 1,
  resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [], source_label_key: 'app_alert.source.backup_health', source_icon: 'database', source_name: null,
};
const SENDERS = [{ id: 'backup_health', label_key: 'app_alert.source.backup_health', icon: 'database' }];

function everythingWaiting(): void {
  approvalsReply = { items: [{ id: 'a1', source: 'dialog', session_id: 'ses_1', session_name: 'api', question: 'run it?', created_at: 2_000 }] };
  aggregateReply = { groups: [{ list: '7', name: 'billing', project_id: 7, revision: 1, items: [{ id: 9, text: 'ship it?', needs_you: true, deleted: false, thread: [{ kind: 'question', answered: false, created_at: 1_000 }] }] }] };
  alertsReply = { alerts: [ALERT], counts: { error: 0, warn: 1, info: 0 }, sources: SENDERS };
}

describe('the bell\'s alerts in the list', () => {
  test('an open alert joins the list as its own row, and a click opens the bell panel', async () => {
    everythingWaiting();
    const host = draw();
    await settle();
    const rows = [...host.querySelectorAll('[data-question-row]')];
    expect(rows.map((r) => r.getAttribute('data-question-row'))).toEqual(['huddle:7:9', 'approval:a1', 'alert:31']);
    expect(rows[2]?.getAttribute('data-question-source')).toBe('alert');
    expect(rows[2]?.textContent).toContain('backup health add-on');
    host.querySelector<HTMLElement>('[data-question-row="alert:31"]')!.click();
    await tick();
    expect(openAppAlerts).toHaveBeenCalledTimes(1);
  });
});

describe('a click on a row of a copy with its own checks still opens it', () => {
  test('approvals-only copy: the row opens the approval inbox; huddle-only copy: the focus route', async () => {
    everythingWaiting();
    const approvalsOnly = draw({ kind_all: false, kind_huddle: false, kind_automations: false }, 'drawer-zone:core.questions');
    const taskManagerOnly = draw({ kind_all: false, kind_approvals: false, kind_automations: false }, 'drawer-zone:core.questions#i2');
    await settle();
    openApprovalFor.mockClear();
    approvalsOnly.querySelector<HTMLElement>('[data-question-row="approval:a1"]')!.click();
    await tick();
    expect(openApprovalFor).toHaveBeenCalledWith('ses_1');
    const taskManager = document.body.appendChild(document.createElement('div'));
    taskManager.setAttribute('data-task-manager-all-cell', '');
    taskManagerOnly.querySelector<HTMLElement>('[data-question-row="huddle:7:9"]')!.click();
    await settle();
    expect(calls).toContain('POST /cplugs/huddle/focus');
    taskManager.remove();
  });
});

describe('copies of the widget are independent (Joe (ccsliinc), 2026-10-11: "multiple instances")', () => {
  test('two copies draw different rows from the same pushed data', async () => {
    everythingWaiting();
    const approvalsOnly = draw({ kind_all: false, kind_huddle: false, kind_automations: false }, 'drawer-zone:core.questions');
    const nothingChecked = draw({ kind_all: false, kind_approvals: false, kind_huddle: false, kind_automations: false }, 'drawer-zone:core.questions#i2');
    const everything = draw(undefined, 'questions');
    await settle();
    const keys = (host: HTMLElement) => [...host.querySelectorAll('[data-question-row]')].map((r) => r.getAttribute('data-question-row'));
    expect(keys(approvalsOnly)).toEqual(['approval:a1']);
    expect(keys(nothingChecked)).toEqual([]);
    expect(keys(everything)).toEqual(['huddle:7:9', 'approval:a1', 'alert:31']);
  });

  test('with all off, the checked kinds are listed and the bell\'s alerts are not', async () => {
    everythingWaiting();
    const host = draw({ kind_all: false, kind_approvals: false });
    await settle();
    expect([...host.querySelectorAll('[data-question-row]')].map((r) => r.getAttribute('data-question-source'))).toEqual(['huddle']);
  });

  test('a copy with everything switched off says nothing is waiting', async () => {
    everythingWaiting();
    const host = draw({ kind_all: false, kind_approvals: false, kind_huddle: false, kind_automations: false });
    await settle();
    expect(host.querySelector('[data-question-row]')).toBeNull();
    expect(host.querySelector('[data-questions-empty] .oc-state__title')?.textContent).toBe('nothing waiting on you');
  });

  test('the in-widget count and the published rail count follow the copy\'s own checks', async () => {
    everythingWaiting();
    const all = draw(undefined, 'drawer-zone:core.questions');
    const two = draw({ kind_all: false, kind_automations: false }, 'drawer-zone:core.questions#i2');
    await settle();
    expect(all.querySelector('[data-questions-count]')?.textContent).toBe('3 waiting on you');
    expect(two.querySelector('[data-questions-count]')?.textContent).toBe('2 waiting on you');
    expect(alertCountSource('core.questions')?.read(null, undefined)).toBe(3);
    expect(alertCountSource('core.questions')?.read(null, { kind_all: false, kind_huddle: false, kind_automations: false })).toBe(1);
    expect(alertCountSource('core.questions')?.read(null, { counts: false })).toBe(3);
  });
});
