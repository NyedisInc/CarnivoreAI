/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AlertPanel from './AlertPanel.svelte';
import { refreshAlerts } from './alerts.svelte';
import type { AppAlert } from './alerts-model';

function alertRow(over: Partial<AppAlert> = {}): AppAlert {
  return {
    id: 7, key: 'k', source: 'backup_health', severity: 'warn', title_key: 'app_alert.backup_health.usb_stale.title',
    params: {}, detail_key: null, state: 'active', sticky: false, auto_resolve: true,
    first_seen: '2026-10-11T16:00:15+00:00', last_seen: '2026-10-11T16:00:15+00:00', count: 1,
    resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [],
    source_label_key: 'app_alert.source.backup_health', source_icon: 'database', source_name: null, kind: 'needs_you',
    ...over,
  } as AppAlert;
}

let server: AppAlert[] = [];
let failPosts = false;
let mounted: ReturnType<typeof mount> | null = null;
const onClose = vi.fn();

beforeEach(() => {
  document.body.innerHTML = '<div id="host"></div>';
  onClose.mockClear();
  failPosts = false;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      if (failPosts) return new Response('{}', { status: 500 });
      if (String(url).endsWith('/dismiss')) server = server.filter((a) => a.id !== Number(/alerts\/(\d+)\/dismiss/.exec(String(url))![1]));
      if (String(url).endsWith('/dismiss-resolved')) server = server.filter((a) => a.state !== 'resolved');
      if (String(url).endsWith('/snooze')) server = server.map((a) => ({ ...a, state: 'snoozed' }) as AppAlert);
    }
    return new Response(JSON.stringify({ alerts: server, counts: { error: 0, warn: server.length, info: 0 } }), { status: 200 });
  }));
});

afterEach(async () => {
  if (mounted) await unmount(mounted);
  mounted = null;
  vi.unstubAllGlobals();
});

async function open(list: AppAlert[]): Promise<void> {
  server = list;
  await refreshAlerts();
  mounted = mount(AlertPanel, { target: document.getElementById('host')!, props: { onClose } });
  flushSync();
}

async function press(label: string): Promise<void> {
  const button = [...document.querySelectorAll<HTMLElement>('[data-btn]')].find((b) => b.textContent?.trim() === label)!;
  button.click();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 100));
  flushSync();
}

test('dismissing the last alert closes the panel', async () => {
  await open([alertRow()]);
  await press('dismiss');
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('dismissing one of two alerts leaves the panel open', async () => {
  await open([alertRow(), alertRow({ id: 8 })]);
  await press('dismiss');
  expect(onClose).not.toHaveBeenCalled();
});

test('dismiss resolved that leaves nothing closes the panel', async () => {
  const resolved = alertRow({ state: 'resolved', resolved_at: new Date().toISOString() });
  await open([resolved]);
  await press('clear resolved');
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('a failed dismiss keeps the panel open', async () => {
  await open([alertRow()]);
  failPosts = true;
  await press('dismiss');
  expect(onClose).not.toHaveBeenCalled();
});

test('snoozing the only alert keeps it listed, so the panel stays open', async () => {
  await open([alertRow()]);
  await press('snooze 1h');
  expect(onClose).not.toHaveBeenCalled();
});

test('opening on an empty list shows the empty line and does not close', async () => {
  await open([]);
  expect(document.querySelector('.aa-empty')).not.toBeNull();
  expect(onClose).not.toHaveBeenCalled();
});
