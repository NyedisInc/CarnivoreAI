/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AlertPanel from './AlertPanel.svelte';
import { refreshAlerts } from './alerts.svelte';
import { kindOf, primaryAction, senderText, type AppAlert } from './alerts-model';
import { t } from '../i18n/index.svelte';

const USB_ACTIONS = [
  { id: 'recheck', label_key: 'app_alert.action.recheck', method: 'POST', route: '/alerts/7/recheck' },
  { id: 'open_backups', label_key: 'app_alert.action.open_backups', href: '#plugins/save/settings' },
];

function usbAlert(over: Partial<AppAlert> = {}): AppAlert {
  return {
    id: 7, key: 'backup_health.usb_backup', source: 'backup_health', severity: 'warn',
    title_key: 'app_alert.backup_health.usb_stale.title', params: { days: 20, max_days: 14, path: '/Volumes/Backup' },
    detail_key: 'app_alert.backup_health.usb_stale.detail', state: 'active', sticky: false, auto_resolve: true,
    first_seen: '2026-10-11T16:00:15+00:00', last_seen: '2026-10-11T16:00:15+00:00', count: 1,
    resolved_at: null, dismissed_at: null, snoozed_until: null, actions: USB_ACTIONS as AppAlert['actions'],
    source_label_key: 'app_alert.source.backup_health', source_icon: 'database', source_name: null, kind: 'needs_you',
    ...over,
  };
}

let alerts: AppAlert[] = [];
const calls: Array<{ url: string; method: string }> = [];
let mounted: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  document.body.innerHTML = '<div id="host"></div>';
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? 'GET' });
    return new Response(JSON.stringify({ alerts, counts: { error: 0, warn: alerts.length, info: 0 } }), { status: 200 });
  }));
});

afterEach(async () => {
  if (mounted) await unmount(mounted);
  mounted = null;
  vi.unstubAllGlobals();
});

async function open(list: AppAlert[]): Promise<HTMLElement> {
  alerts = list;
  await refreshAlerts();
  mounted = mount(AlertPanel, { target: document.getElementById('host')!, props: { onClose: () => {} } });
  flushSync();
  return document.querySelector<HTMLElement>('[data-app-alert-row]')!;
}

test('a row names its sender, shows a kind chip, and the first fix is the main button before snooze and dismiss', async () => {
  const row = await open([usbAlert()]);
  expect(row.querySelector('[data-app-alert-source]')?.textContent?.trim()).toBe('backup health add-on');
  const chip = row.querySelector('[data-app-alert-kind]')!;
  expect(chip.getAttribute('data-app-alert-kind')).toBe('needs_you');
  expect(chip.textContent).toBe('needs you');

  const buttons = [...row.querySelectorAll('.aa-actions [data-btn]')];
  expect(buttons.map((b) => b.textContent?.trim())).toEqual(['re-check now', 'open backups', 'snooze 1h', 'dismiss']);
  expect(buttons[0]!.getAttribute('data-btn')).toBe('confirm');
  expect(buttons.slice(1).every((b) => b.getAttribute('data-btn') !== 'confirm')).toBe(true);
});

test('an fyi alert gets the quiet chip, a named agent shows after the sender, and an older server falls back to severity', async () => {
  const fyi = usbAlert({ id: 8, kind: 'fyi', severity: 'info', actions: [], source_name: 'Cv-Misc UI', source: 'automations', source_label_key: 'app_alert.source.automations' });
  const row = await open([fyi]);
  expect(row.querySelector('[data-app-alert-kind]')?.textContent).toBe('fyi');
  expect(row.querySelector('[data-app-alert-source]')?.textContent).toContain('automations · Cv-Misc UI');

  expect(kindOf({ severity: 'info' })).toBe('fyi');
  expect(kindOf({ severity: 'error' })).toBe('needs_you');
  expect(primaryAction({ actions: [] })).toBeNull();
  expect(senderText({ source: 'some_new_source', source_label_key: null, source_name: null }, t)).toBe('some new source');
});
