/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { layoutZoom } from '../../engine/layout-zoom.svelte';
import { resetTabCache, setGroups } from '../../engine/tab-groups.svelte';
import type { SlotId } from '../../engine/types';

const clients = vi.hoisted(() => ({ made: [] as Array<{ id: string; _tabHidden?: boolean }> }));
vi.mock('../terminal-live/client', () => ({
  startLiveTerminal: (_el: unknown, instance: string) => {
    // A class instance, like the real client: Svelte never proxies one.
    const client = new (class FakeClient { constructor(public id: string) {} })(instance);
    clients.made.push(client);
    return { client, dispose() {} };
  },
}));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const row = (id: string, label: string) => ({
    session: { id }, label, agent_family: 'shell', tmux_session: `cloude_${id}`,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
  });
  return {
    ...actual,
    sessions: {
      data: [row('ses_a', 'alpha'), row('ses_c', 'gamma')],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_a' as SlotId;
const C = 'terminal:ses_c' as SlotId;
let apps: ReturnType<typeof mount>[] = [];
const tabHidden: Array<[string, boolean]> = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  terminalLayout.add('terminal', 'ses_a');
  terminalLayout.add('terminal', 'ses_c');
  setGroups(terminalLayout, { [A]: { tabs: [A] }, [C]: { tabs: [C] } });
  tabHidden.length = 0;
  clients.made.length = 0;
  const w = globalThis as Record<string, unknown>;
  w.CloudeWeb = { launchpad: { loadRunningSessions: async () => {} } };
  w.Themes = {
    getSessionManifest: () => ({ id: 'global', cssVars: { '--color-accent': '#ff8800' } }),
    onXtermThemeChange: () => () => {},
  };
  w.TerminalSizeVote = {
    setTabHidden: (client: { id: string; _tabHidden?: boolean }, hidden: boolean) => {
      if (!!client._tabHidden === hidden) return;
      client._tabHidden = hidden;
      tabHidden.push([client.id, hidden]);
    },
  };
});

afterEach(async () => {
  for (const app of apps) await unmount(app);
  apps = [];
  layoutZoom.restore();
  terminalLayout.remove(A);
  terminalLayout.remove(C);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
  for (const key of ['CloudeWeb', 'Themes', 'TerminalSizeVote']) {
    delete (globalThis as Record<string, unknown>)[key];
  }
});

function draw(slot: SlotId): void {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(TabbedFrame, { target, props: { slot } }));
  flushSync();
}

test('zooming component A withdraws component C\'s size vote; restoring rejoins it', () => {
  draw(A);
  draw(C);
  const clientA = clients.made.find((c) => c.id === A);
  const clientC = clients.made.find((c) => c.id === C);
  expect(clientA?._tabHidden ?? false).toBe(false);
  expect(clientC?._tabHidden ?? false).toBe(false);

  layoutZoom.toggle(A);
  flushSync();
  expect(clientA?._tabHidden ?? false).toBe(false);
  expect(clientC?._tabHidden).toBe(true);
  expect(tabHidden).toContainEqual([C, true]);

  layoutZoom.restore();
  flushSync();
  expect(clientC?._tabHidden).toBe(false);
});

test('zooming component C instead withdraws A\'s vote, never its own', () => {
  draw(A);
  draw(C);
  layoutZoom.toggle(C);
  flushSync();
  const clientA = clients.made.find((c) => c.id === A);
  const clientC = clients.made.find((c) => c.id === C);
  expect(clientA?._tabHidden).toBe(true);
  expect(clientC?._tabHidden ?? false).toBe(false);
});
