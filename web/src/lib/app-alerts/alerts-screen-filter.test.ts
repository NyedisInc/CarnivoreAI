import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { alertCenter, onFrame } from './alerts.svelte';
import type { EventFrame } from '../../opscenter/api/types';

const row = (id: number, notifyType?: string): Record<string, unknown> => ({
  id, key: `k${id}`, source: 's', severity: 'warn', title_key: 'app_alert.panel.title', params: {}, detail_key: null,
  state: 'active', sticky: false, auto_resolve: true, first_seen: '2026-09-30T10:00:00+00:00', last_seen: '2026-09-30T10:00:00+00:00',
  count: 1, resolved_at: null, dismissed_at: null, snoozed_until: null, actions: [], ...(notifyType ? { notify_type: notifyType } : {}),
});

let alerts: Record<string, unknown>[] = [];
const toasts: Record<string, unknown>[] = [];
const raise = (id: number) => onFrame({ type: 'app_alert.raised', id, severity: 'warn' } as unknown as EventFrame);

beforeEach(() => {
  toasts.length = 0;
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ alerts, counts: { error: 0, warn: alerts.length, info: 0 } }), { status: 200 })));
  vi.stubGlobal('ToastManager', { add: (t: Record<string, unknown>) => toasts.push(t) });
});
afterEach(() => vi.unstubAllGlobals());

test('an unticked type draws no card but the bell list keeps the alert', async () => {
  vi.stubGlobal('NotifyScreen', { shows: (t: { notify_type?: string }) => t.notify_type !== 'alert.self_check' });
  alerts = [row(9101, 'alert.self_check'), row(9102, 'alert.account')];
  await raise(9101);
  await raise(9102);
  expect(toasts.length).toBe(1);
  expect(alertCenter.alerts.map((a) => a.id)).toEqual(expect.arrayContaining([9101, 9102]));
});

test('with no NotifyScreen, or an alert with no notify_type, the card is drawn', async () => {
  alerts = [row(9103, 'alert.self_check'), row(9104)];
  await raise(9103);
  vi.stubGlobal('NotifyScreen', { shows: (t: { notify_type?: string }) => !t.notify_type ? true : false });
  await raise(9104);
  expect(toasts.length).toBe(2);
});
