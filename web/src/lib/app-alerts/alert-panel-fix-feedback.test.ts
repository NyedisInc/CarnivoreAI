/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AlertPanel from './AlertPanel.svelte';
import { refreshAlerts } from './alerts.svelte';
import type { AppAlert } from './alerts-model';

const CLEAR = { id: 'clear_freeze', label_key: 'app_alert.action.clear_freeze', done_key: 'app_alert.action.clear_freeze.done', method: 'POST', route: '/cplugs/save/mass-gone/clear' };
const RECHECK = { id: 'recheck', label_key: 'app_alert.action.recheck', method: 'POST', route: '/alerts/7/recheck' };

function frozen(): AppAlert {
  return {
    id: 7, key: 'backup_health.vault_frozen', source: 'backup_health', severity: 'warn', title_key: 'app_alert.backup_health.vault_frozen.title',
    params: { count: 12 }, detail_key: null, state: 'active', sticky: false, auto_resolve: true,
    first_seen: '2026-11-23T07:00:00+00:00', last_seen: '2026-11-23T07:00:00+00:00', count: 1,
    resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [CLEAR, RECHECK],
    source_label_key: 'app_alert.source.backup_health', source_icon: 'database', source_name: null, kind: 'needs_you',
  } as AppAlert;
}

let server: AppAlert[] = [];
let failClear = false;
let calls: string[] = [];
let mounted: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  document.body.innerHTML = '<div id="host"></div>';
  calls = [];
  failClear = false;
  server = [frozen()];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === 'POST') {
      calls.push(path);
      if (path.endsWith('/mass-gone/clear')) return failClear ? new Response('{}', { status: 500 }) : new Response('{"cleared":true}', { status: 200 });
      if (path.endsWith('/recheck')) server = [];
      return new Response('{}', { status: 200 });
    }
    return new Response(JSON.stringify({ alerts: server, counts: { error: 0, warn: server.length, info: 0 }, sources: [] }), { status: 200 });
  }));
});

afterEach(() => {
  if (mounted) unmount(mounted);
  mounted = null;
  vi.unstubAllGlobals();
});

async function pressClear(): Promise<void> {
  await refreshAlerts();
  mounted = mount(AlertPanel, { target: document.getElementById('host')!, props: { onClose: () => {} } });
  flushSync();
  (document.querySelector('[data-app-alert-action="clear_freeze"]') as HTMLButtonElement).click();
  await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0));
  await new Promise((r) => setTimeout(r, 30));
  flushSync();
}

test('a successful clear shows the success line, re-checks the alert, and the list is re-read without it', async () => {
  await pressClear();
  expect(calls).toEqual(['/api/v1/cplugs/save/mass-gone/clear', '/api/v1/alerts/7/recheck']);
  expect(document.querySelector('[data-app-alert-row="7"]')).toBeNull();
});

test('the success line stays on a row that is still listed after the re-check', async () => {
  server = [{ ...frozen(), key: 'backup_health.vault_mass_gone', sticky: true }];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { calls.push(String(url)); return new Response('{}', { status: 200 }); }
    return new Response(JSON.stringify({ alerts: server, counts: { error: 0, warn: 1, info: 0 }, sources: [] }), { status: 200 });
  }));
  await pressClear();
  expect(document.querySelector('[data-app-alert-row="7"]')?.textContent).toContain('freeze cleared, pruning resumes');
});

test('a refused clear shows no success line and runs no re-check', async () => {
  failClear = true;
  await pressClear();
  expect(calls).toEqual(['/api/v1/cplugs/save/mass-gone/clear']);
  expect(document.querySelector('[data-app-alert-row="7"]')?.textContent).not.toContain('freeze cleared');
});
