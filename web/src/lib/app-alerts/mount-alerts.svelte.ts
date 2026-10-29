/* display: none */
import { mountPanel } from '../mount';
import { openAppAlerts } from './alert-panel.svelte';
import { hostDocument } from '../sessions/env';
import AlertBell from './AlertBell.svelte';
import AlertDot from './AlertDot.svelte';
import { setAlertToastOpener, startAlertCenter } from './alerts.svelte';

export const ALERTS_BELL_HOST_ID = 'session-sidebar-alerts';
export const ALERTS_DOT_HOST_ID = 'headerAlertDot';

let mounted = false;

export function mountAppAlerts(): boolean {
  const doc = hostDocument();
  if (!doc) return false;
  setAlertToastOpener(() => openAppAlerts());
  startAlertCenter();
  if (mounted) return true;
  const bell = doc.getElementById?.(ALERTS_BELL_HOST_ID);
  if (!bell) return false;
  mounted = mountPanel(ALERTS_BELL_HOST_ID, AlertBell as never, { place: 'drawer' } as never) !== null;
  if (doc.getElementById?.(ALERTS_DOT_HOST_ID)) mountPanel(ALERTS_DOT_HOST_ID, AlertDot as never, {} as never);
  return mounted;
}
