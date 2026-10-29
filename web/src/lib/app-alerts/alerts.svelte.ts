
import { authFetch } from '../../opscenter/api/auth.svelte';
import { subscribe } from '../../opscenter/api/events.svelte';
import type { EventFrame } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { ALERT_FRAMES, shouldToast, type AlertCounts, type AlertFrame, type AlertAction, type AlertSourceEntry, type AppAlert } from './alerts-model';

export const ALERTS_PATH = '/alerts?state=all&limit=200';

const COALESCE_MS = 250;

export const TOAST_KIND = 'AppAlert';

export const alertCenter = $state<{
  alerts: AppAlert[];
  counts: AlertCounts;
  sources: AlertSourceEntry[];
  status: 'idle' | 'ok' | 'error';
}>({ alerts: [], counts: { error: 0, warn: 0, info: 0 }, sources: [], status: 'idle' });

let toastOpener: (() => void) | null = null;

export function setAlertToastOpener(open: (() => void) | null): void {
  toastOpener = open;
}

let started = false;
let pending: ReturnType<typeof setTimeout> | null = null;
const toasted = new Set<number>();

export async function refreshAlerts(): Promise<void> {
  try {
    const body = await authFetch<{ alerts: AppAlert[]; counts: AlertCounts; sources?: AlertSourceEntry[] }>(ALERTS_PATH);
    alertCenter.alerts = body.alerts ?? [];
    alertCenter.counts = body.counts ?? { error: 0, warn: 0, info: 0 };
    alertCenter.sources = body.sources ?? [];
    alertCenter.status = 'ok';
    armSnoozeWake(alertCenter.alerts);
  } catch {
    alertCenter.status = 'error';
  }
}

let snoozeWake: ReturnType<typeof setTimeout> | null = null;

export function armSnoozeWake(alerts: AppAlert[]): void {
  if (snoozeWake) clearTimeout(snoozeWake);
  snoozeWake = null;
  const due = alerts
    .filter((alert) => alert.state === 'snoozed' && alert.snoozed_until)
    .map((alert) => Date.parse(alert.snoozed_until as string))
    .filter((at) => Number.isFinite(at));
  if (due.length === 0) return;
  const wait = Math.min(Math.max(0, Math.min(...due) - Date.now()) + 1000, 2_147_000_000);
  snoozeWake = setTimeout(() => { snoozeWake = null; scheduleRefresh(); }, wait);
}

function scheduleRefresh(): void {
  if (pending) return;
  pending = setTimeout(() => {
    pending = null;
    void refreshAlerts();
  }, COALESCE_MS);
}

interface ToastSurface {
  add(toast: Record<string, unknown>): void;
}

export function toastFor(alert: AppAlert, open: (() => void) | null = null, now: number = Date.now()): Record<string, unknown> {
  return {
    id: `app-alert:${alert.id}:${now}`,
    session_id: null,
    kind: TOAST_KIND,
    title: t(alert.title_key, alert.params),
    body: alert.detail_key ? t(alert.detail_key, alert.params) : '',
    session_label: t('app_alert.toast.surface'),
    alert_severity: alert.severity,
    on_open: open,
    local: true,
  };
}

export async function onFrame(frame: EventFrame): Promise<void> {
  const alertFrame = frame as unknown as AlertFrame;
  if (shouldToast(alertFrame, toasted)) {
    await refreshAlerts();
    const alert = alertCenter.alerts.find((a) => a.id === alertFrame.id);
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    const hidden = alert !== undefined && (globalThis as { NotifyScreen?: { shows(t: { notify_type?: unknown }): boolean } }).NotifyScreen?.shows(alert) === false;
    if (alert && surface && typeof surface.add === 'function' && !hidden) surface.add(toastFor(alert, toastOpener));
    return;
  }
  scheduleRefresh();
}

export function startAlertCenter(): void {
  if (started) return;
  started = true;
  for (const kind of ALERT_FRAMES) subscribe(kind, (frame) => void onFrame(frame));
  subscribe('events.hello', () => scheduleRefresh());
  void refreshAlerts();
}

export async function dismissAlert(id: number): Promise<void> {
  await authFetch(`/alerts/${id}/dismiss`, { method: 'POST' });
  await refreshAlerts();
}

export async function snoozeAlert(id: number, minutes: number): Promise<void> {
  await authFetch(`/alerts/${id}/snooze`, { method: 'POST', body: JSON.stringify({ minutes }) });
  await refreshAlerts();
}

export async function dismissResolvedAlerts(): Promise<void> {
  await authFetch('/alerts/dismiss-resolved', { method: 'POST' });
  await refreshAlerts();
}

export async function runAlertAction(action: AlertAction): Promise<void> {
  const init: RequestInit = { method: (action.method ?? 'GET').toUpperCase() };
  if (action.body !== undefined) init.body = JSON.stringify(action.body);
  await authFetch(`/api/v1${action.route}`, init);
}
