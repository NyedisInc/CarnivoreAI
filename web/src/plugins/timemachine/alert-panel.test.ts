/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AlertPanel from '../../lib/app-alerts/AlertPanel.svelte';
import { refreshAlerts } from '../../lib/app-alerts/alerts.svelte';
import type { AppAlert } from '../../lib/app-alerts/alerts-model';

const RECHECK = { id: 'recheck', label_key: 'app_alert.action.recheck', method: 'POST', route: '/cplugs/timemachine/check' };
const ACTIONS = [
  {
    id: 'check_access', label_key: 'cplug.timemachine.action.check_access',
    explain_key: 'cplug.timemachine.alert.unknown.explain.access',
    actions: [
      { id: 'open_privacy', label_key: 'app_alert.action.open_privacy', method: 'POST', route: '/alerts/open-system-settings', body: { pane: 'full_disk_access' } },
      RECHECK,
    ],
  },
  RECHECK,
];

function alert(): AppAlert {
  return {
    id: 7, key: 'cplug.timemachine.time_machine', source: 'cplug.timemachine', severity: 'warn',
    title_key: 'cplug.timemachine.alert.unknown.title', params: { reason: 'access' },
    detail_key: 'cplug.timemachine.alert.unknown.detail.access', state: 'active', sticky: false, auto_resolve: true,
    first_seen: '2026-10-26T16:00:15+00:00', last_seen: '2026-10-26T16:00:15+00:00', count: 1,
    resolved_at: null, dismissed_at: null, snoozed_until: null, actions: ACTIONS as AppAlert['actions'],
    source_label_key: 'app_alert.source.other', source_icon: 'plug', source_name: null, kind: 'needs_you',
  };
}

const calls: Array<{ url: string; method: string }> = [];
let mounted: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  document.body.innerHTML = '<div id="host"></div>';
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? 'GET' });
    return new Response(JSON.stringify({ alerts: [alert()], counts: { error: 0, warn: 1, info: 0 } }), { status: 200 });
  }));
});

afterEach(async () => {
  if (mounted) await unmount(mounted);
  mounted = null;
  vi.unstubAllGlobals();
});

test('the check access button opens the plugin explainer, and re-check now posts to the plugin route', async () => {
  await refreshAlerts();
  mounted = mount(AlertPanel, { target: document.getElementById('host')!, props: { onClose: () => {} } });
  flushSync();
  const row = document.querySelector<HTMLElement>('[data-app-alert-row]')!;
  expect(row.querySelector('[data-app-alert-explain]')).toBeNull();
  row.querySelector<HTMLButtonElement>('[data-app-alert-action="check_access"]')!.click();
  flushSync();
  const explain = row.querySelector('[data-app-alert-explain]')!;
  expect(explain.textContent).toContain('full disk access');
  const inner = [...explain.querySelectorAll('[data-app-alert-action]')].map((b) => b.getAttribute('data-app-alert-action'));
  expect(inner).toEqual(['open_privacy', 'recheck']);

  explain.querySelector<HTMLButtonElement>('[data-app-alert-action="recheck"]')!.click();
  await vi.waitFor(() => expect(calls.some((c) => c.url === '/api/v1/cplugs/timemachine/check' && c.method === 'POST')).toBe(true));
});
