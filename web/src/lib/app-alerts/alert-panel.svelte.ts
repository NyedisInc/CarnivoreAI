import { mountPanel, unmountPanel } from '../mount';
import { hostDocument } from '../sessions/env';
import AlertPanel from './AlertPanel.svelte';

export const ALERTS_PANEL_ID = 'app-alerts-panel';

export const alertPanel = $state<{ open: boolean }>({ open: false });

function closePanel(): void {
  unmountPanel(ALERTS_PANEL_ID);
  hostDocument()?.getElementById?.(ALERTS_PANEL_ID)?.remove?.();
  alertPanel.open = false;
}

export function openAppAlerts(): void {
  if (alertPanel.open) return;
  const doc = hostDocument();
  if (!doc?.body) return;
  let host = doc.getElementById(ALERTS_PANEL_ID);
  if (!host) {
    host = doc.createElement('div');
    host.id = ALERTS_PANEL_ID;
    doc.body.appendChild(host);
  }
  alertPanel.open = mountPanel(ALERTS_PANEL_ID, AlertPanel as never, { onClose: () => closePanel() } as never) !== null;
}

export function toggleAppAlerts(): void {
  if (alertPanel.open) closePanel();
  else openAppAlerts();
}
