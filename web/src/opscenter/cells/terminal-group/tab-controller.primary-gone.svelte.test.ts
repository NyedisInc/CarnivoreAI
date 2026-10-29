/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { createTabController, PRIMARY_SESSION_GONE_EVENT } from './tab-controller.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups } from '../../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../../engine/model';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const row = (id: string, tmux: string, label: string) => ({
    session: { id }, label, agent_family: 'claude', tmux_session: tmux,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
  });
  return {
    ...actual,
    sessions: {
      data: [row('ses_page', 'cloude_page', 'page'), row('ses_b', 'cloude_b', 'beta')],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

interface AppStub { App?: unknown; CloudeWeb?: unknown; TerminalController?: unknown }

const B = 'terminal:ses_b' as SlotId;
type Controller = ReturnType<typeof createTabController>;
let stops: Array<() => void> = [];
let showLaunchpad: ReturnType<typeof vi.fn>;
let openRunningSession: ReturnType<typeof vi.fn>;

function mountStrip(): Controller {
  let controller!: Controller;
  stops.push($effect.root(() => {
    controller = createTabController(() => PRIMARY_SLOT, () => {});
  }));
  flushSync();
  return controller;
}

beforeEach(() => {
  const stub = globalThis as unknown as AppStub;
  stub.TerminalController = { _sessionId: () => 'ses_page' };
  showLaunchpad = vi.fn();
  openRunningSession = vi.fn();
  stub.App = { showLaunchpad };
  stub.CloudeWeb = { launchpad: { openRunningSession } };
  terminalLayout.bindSession('cloude_page', 1);
});

afterEach(() => {
  for (const stop of stops) stop();
  stops = [];
  inputFocus.forget(PRIMARY_SLOT);
  terminalLayout.bindSession('');
  resetTabCache();
  localStorage.clear();
  const stub = globalThis as unknown as AppStub;
  delete stub.TerminalController;
  delete stub.App;
  delete stub.CloudeWeb;
});

test('own session gone with another tab open: lands on that tab, never goes home', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  mountStrip();

  window.dispatchEvent(new CustomEvent(PRIMARY_SESSION_GONE_EVENT));
  flushSync();

  expect(openRunningSession).toHaveBeenCalledWith('ses_b', 'cloude_b');
  expect(showLaunchpad).not.toHaveBeenCalled();
});

test('own session gone as the only tab: goes home', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] } });
  mountStrip();

  window.dispatchEvent(new CustomEvent(PRIMARY_SESSION_GONE_EVENT));
  flushSync();

  expect(showLaunchpad).toHaveBeenCalledTimes(1);
  expect(openRunningSession).not.toHaveBeenCalled();
});

test('a strip not holding the primary tabs (a secondary component) ignores the event', () => {
  const C = 'terminal:ses_c' as SlotId;
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [C]: { tabs: [C] } });
  let secondary!: Controller;
  stops.push($effect.root(() => {
    secondary = createTabController(() => C, () => {});
  }));
  flushSync();
  void secondary;

  window.dispatchEvent(new CustomEvent(PRIMARY_SESSION_GONE_EVENT));
  flushSync();

  expect(showLaunchpad).not.toHaveBeenCalled();
});
