/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AlertPanel from './AlertPanel.svelte';
import { refreshAlerts } from './alerts.svelte';
import { recorded, reframed, snapshot } from '../dialog-frame/goldens';

const FRAME = { addClasses: ['oc-anchored'] };

let app: ReturnType<typeof mount> | null = null;
afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

test('the panel renders its recorded markup', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ alerts: [], counts: { error: 0, warn: 0, info: 0 } }), { status: 200 })));
  document.body.innerHTML = '<div id="host"></div>';
  await refreshAlerts();
  app = mount(AlertPanel, { target: document.getElementById('host')!, props: { onClose: () => {} } });
  flushSync();
  const now = snapshot(document.querySelector('[data-app-alert-panel]')!);
  expect(now).toBe(reframed(recorded('alert-panel', now), FRAME));
});
