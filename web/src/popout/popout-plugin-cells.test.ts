/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

/* the Task Manager */
const server = vi.hoisted(() => ({ huddleOn: true }));

vi.mock('../opscenter/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../opscenter/api')>()),
  isDemo: () => false,
  auth: { state: 'signed-in' },
  initAuth: () => {},
  startEvents: () => {},
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));
vi.mock('../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../opscenter/api/auth.svelte')>()),
  authFetch: async (path: string) => (path === '/cplugs' ? { cplugs: [{ id: 'huddle', enabled: server.huddleOn }] } : {}),
}));

import { installPopoverPolyfill } from '../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

let teardown: (() => void) | null = null;
let target: HTMLElement;

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  target = document.body.appendChild(document.createElement('div'));
});

afterEach(() => {
  teardown?.();
  teardown = null;
  document.body.innerHTML = '';
  localStorage.clear();
  vi.unstubAllGlobals();
});

async function bootAndMount(huddleOn: boolean): Promise<void> {
  const { flushSync, mount, tick, unmount } = await import('svelte');
  const { bootPluginCells } = await import('../plugins/host/cell-boot');
  const { startPopoutCplugs } = await import('../plugins/host/popout-start');
  const { cplugEnablement } = await import('../plugins/host/enablement.svelte');
  const { default: SingleWidget } = await import('./SingleWidget.svelte');
  cplugEnablement.enabled = { taskmanager: huddleOn };
  bootPluginCells();
  startPopoutCplugs();
  await vi.waitFor(() => expect(cplugEnablement.read).toBe(true));
  const app = mount(SingleWidget, { target, props: { widget: 'core.task-manager-mk2' } });
  teardown = () => unmount(app, { outro: false });
  flushSync();
  await tick();
}

for (const huddleOn of [true, false]) {
  test(`a Mark II pop-out draws the cell, never unavailable, with the Task Manager switched ${huddleOn ? 'on' : 'off'}`, async () => {
    server.huddleOn = huddleOn;
    await bootAndMount(huddleOn);
    await vi.waitFor(() => expect(target.querySelector('[data-widget-loading]')).toBeNull());
    expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
    expect(target.querySelector('.oc-cell-unavailable')).toBeNull();
    const { t } = await import('../lib/i18n/index.svelte');
    expect(target.querySelector('.oc-wshell[data-widget="core.task-manager-mk2"]')?.textContent?.trim()).toBe(t('opscenter.cell.task_manager_mk2.no_session'));
  }, 30_000);
}
