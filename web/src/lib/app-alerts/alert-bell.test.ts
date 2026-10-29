/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/session-usage.svelte', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../opscenter/api/session-usage.svelte')>();
  return { ...actual, sessionUsage: () => ({ status: 'idle', data: null, error: null }), releaseSessionUsage: () => {} };
});

import MiniRail from '../mini-rail/MiniRail.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { mountAppAlerts } from './mount-alerts.svelte';
import { alertPanel, toggleAppAlerts } from './alert-panel.svelte';
import { onFrame, refreshAlerts } from './alerts.svelte';
import type { EventFrame } from '../../opscenter/api/types';

installPopoverPolyfill();

function row(id: number, severity: 'error' | 'warn' | 'info', count = 1): Record<string, unknown> {
  return {
    id, key: `k${id}`, source: 's', severity, title_key: 'app_alert.panel.title', params: {}, detail_key: null,
    state: 'active', sticky: false, auto_resolve: true, first_seen: '2026-09-30T10:00:00+00:00',
    last_seen: '2026-09-30T10:00:00+00:00', count, resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [],
  };
}

let alerts: Record<string, unknown>[] = [];
const toasts: Record<string, unknown>[] = [];
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  document.body.innerHTML = `
    <aside id="session-sidebar-panel"><div class="session-sidebar-header"><div class="session-sidebar-heading">
      <button id="session-sidebar-brand"></button><div id="session-sidebar-alerts"></div>
    </div></div></aside>
    <div id="session-sidebar-list"></div><div id="rail"></div>`;
  alerts = [row(1, 'error')];
  toasts.length = 0;
  vi.stubGlobal('fetch', vi.fn(async () => {
    const counts = { error: 0, warn: 0, info: 0 } as Record<string, number>;
    for (const a of alerts) counts[a.severity as string] = (counts[a.severity as string] ?? 0) + 1;
    return new Response(JSON.stringify({ alerts, counts }), { status: 200 });
  }));
  vi.stubGlobal('ToastManager', { add: (t: Record<string, unknown>) => toasts.push(t) });
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(async () => {
  if (alertPanel.open) toggleAppAlerts();
  for (const c of mounted.splice(0)) await unmount(c);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('the bell sits in the drawer header (wide) and under the rail claw (narrow), badged, and opens the panel', async () => {
  alerts = [];
  expect(mountAppAlerts()).toBe(true);
  await refreshAlerts();
  flushSync();
  expect(document.querySelector('[data-app-alert-bell]')).toBeNull();
  alerts = [row(1, 'error')];
  await refreshAlerts();
  flushSync();

  const heading = document.querySelector('.session-sidebar-heading')!;
  const wide = heading.querySelector<HTMLButtonElement>('[data-app-alert-bell="drawer"]');
  expect(wide).not.toBeNull();
  expect(wide!.querySelector('[data-app-alert-badge="error"]')?.textContent).toBe('1');

  wide!.click();
  flushSync();
  expect(document.querySelector('[data-app-alert-panel]')).not.toBeNull();
  expect(wide!.getAttribute('aria-expanded')).toBe('true');
  wide!.click();
  flushSync();
  expect(document.querySelector('[data-app-alert-panel]')).toBeNull();

  // the drawer closed
  mounted.push(mount(MiniRail, { target: document.getElementById('rail')! }));
  document.body.classList.add('session-sidebar-railed');
  flushSync();
  const narrow = document.querySelector<HTMLButtonElement>('[data-app-alert-bell="rail"]');
  expect(narrow).not.toBeNull();
  expect(narrow!.querySelector('[data-app-alert-badge="error"]')?.textContent).toBe('1');
  narrow!.click();
  flushSync();
  expect(document.querySelector('[data-app-alert-panel]')).not.toBeNull();
  toggleAppAlerts();
  alerts = [];
  await refreshAlerts();
  flushSync();
  expect(document.querySelector('[data-app-alert-bell]')).toBeNull();
});

test('every newly raised alert toasts by severity once, a bump does not, and the toast opens the panel', async () => {
  mountAppAlerts();
  alerts = [row(11, 'warn'), row(12, 'info')];
  await onFrame({ type: 'app_alert.raised', id: 11, severity: 'warn' } as unknown as EventFrame);
  await onFrame({ type: 'app_alert.raised', id: 12, severity: 'info' } as unknown as EventFrame);
  alerts = [row(11, 'warn', 2), row(12, 'info')];
  await onFrame({ type: 'app_alert.updated', id: 11, severity: 'warn', count: 2 } as unknown as EventFrame);
  await onFrame({ type: 'app_alert.raised', id: 11, severity: 'warn' } as unknown as EventFrame);

  expect(toasts.map((t) => t.alert_severity)).toEqual(['warn', 'info']);
  expect(alertPanel.open).toBe(false);
  (toasts[0]?.on_open as () => void)();
  flushSync();
  expect(alertPanel.open).toBe(true);
  expect(document.querySelector('[data-app-alert-panel]')).not.toBeNull();
});
