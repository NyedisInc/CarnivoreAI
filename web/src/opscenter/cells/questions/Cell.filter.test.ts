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
import { setLocale } from '../../../lib/i18n/index.svelte';

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


const ALERT = {
  id: 31, key: 'backup_health.usb_stale', source: 'backup_health', severity: 'warn', title_key: 'app_alert.backup_health.usb_stale.title', params: {}, detail_key: null,
  state: 'active', sticky: false, auto_resolve: false, first_seen: '2026-10-11T10:00:00Z', last_seen: '2026-10-11T10:00:00Z', count: 1,
  resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [], source_label_key: 'app_alert.source.backup_health', source_icon: 'database', source_name: null,
};

function everythingWaiting(): void {
  approvalsReply = { items: [{ id: 'a1', source: 'dialog', session_id: 'ses_1', session_name: 'api', question: 'run it?', created_at: 2_000 }] };
  aggregateReply = { groups: [{ list: '7', name: 'billing', project_id: 7, revision: 1, items: [{ id: 9, text: 'ship it?', needs_you: true, deleted: false, thread: [{ kind: 'question', answered: false, created_at: 1_000 }] }] }] };
  alertsReply = { alerts: [ALERT], counts: { error: 0, warn: 1, info: 0 }, sources: [{ id: 'backup_health', label_key: 'app_alert.source.backup_health', icon: 'database' }] };
}

const keys = (host: HTMLElement): string[] => [...host.querySelectorAll('[data-question-row]')].map((r) => r.getAttribute('data-question-row') ?? '');

describe('the waiting-on-you widget, one copy at a time', () => {
  test('the body draws no filter at all, even when nothing is waiting', async () => {
    const host = draw();
    await settle();
    expect(host.querySelector('[data-questions-empty]')).not.toBeNull();
    expect(host.querySelector('[data-kind-filter]')).toBeNull();
    expect(host.querySelector('[data-kind-filter-all]')).toBeNull();
  });

  test('a new copy (no options) is on all: every row, the bell\'s alerts included, and the full count', async () => {
    everythingWaiting();
    const host = draw();
    await settle();
    expect(keys(host)).toEqual(['huddle:7:9', 'approval:a1', 'alert:31']);
    expect(titleCount()).toBe(3);
  });

  test('two copies keep their own checks: each lists, counts and publishes only what it checks', async () => {
    everythingWaiting();
    const huddleOnly = draw({ kind_all: false, kind_approvals: false, kind_automations: false }, 'drawer-zone:core.questions');
    const noTaskManager = draw({ kind_all: false, kind_huddle: false }, 'drawer-zone:core.questions#i2');
    await settle();
    expect(keys(huddleOnly)).toEqual(['huddle:7:9']);
    expect(keys(noTaskManager)).toEqual(['approval:a1']);
    expect(huddleOnly.querySelector('[data-questions-count]')?.textContent).toBe('1 waiting on you');
    const count = alertCountSource('core.questions')!;
    expect(count.read(null, { kind_all: false, kind_approvals: false, kind_automations: false })).toBe(1);
    expect(count.read(null, { kind_all: false, kind_huddle: false })).toBe(1);
    expect(count.read(null, undefined)).toBe(3);
  });

  test('all on lists everything whatever the kind checks remembered; all off honors them without losing the alerts rule', async () => {
    everythingWaiting();
    const allOn = draw({ kind_all: true, kind_huddle: false });
    const allOff = draw({ kind_all: false, kind_huddle: false }, 'drawer-zone:core.questions#i3');
    await settle();
    expect(keys(allOn)).toEqual(['huddle:7:9', 'approval:a1', 'alert:31']);
    expect(keys(allOff)).toEqual(['approval:a1']);
  });

  test('keys written by the earlier build are ignored, so a stale copy lists everything', async () => {
    everythingWaiting();
    const host = draw({ s_huddle: false, s_alert_backup_health: false, counts: false });
    await settle();
    expect(keys(host)).toEqual(['huddle:7:9', 'approval:a1', 'alert:31']);
    expect(host.querySelector('[data-questions-count]')?.textContent).toBe('3 waiting on you');
  });
});
