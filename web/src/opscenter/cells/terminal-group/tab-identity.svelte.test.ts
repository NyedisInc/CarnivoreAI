/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { createTabController } from './tab-controller.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache } from '../../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../../engine/model';
import { flushSave } from '../../engine/persist';
import { inputFocus } from '../../lib/input-focus.svelte';
import { listing } from './fixtures/fake-listing.svelte';
import type { SessionInfo, SessionRecord } from '../../api/types';
import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const { listing: fake } = await import('./fixtures/fake-listing.svelte');
  const resource = (read: () => unknown) => ({
    get data() {
      return read();
    },
    get status() {
      return read() ? 'ok' : 'loading';
    },
    refresh: vi.fn(async () => {}),
    fetchedAt: 1,
    error: null,
    stop() {},
  });
  return { ...actual, sessions: resource(() => fake.sessions), asleep: resource(() => fake.asleep) };
});

function live(id: string, rowId: number, tmux: string, label: string, status = 'idle'): SessionInfo {
  return {
    session: { id }, session_row_id: rowId, tmux_session: tmux, label, agent_family: 'claude',
    activity_status: status, startup_gate: null, unread: false, pinned_theme: null, status_source: 'registry',
  } as unknown as SessionInfo;
}

function sleeping(rowId: number, tmux: string, title: string): SessionRecord {
  return {
    id: rowId, session_uuid: `uuid-${rowId}`, tmux_name: tmux, title, asleep: true, agent_family: 'claude',
  } as unknown as SessionRecord;
}

type Controller = ReturnType<typeof createTabController>;
let stops: Array<() => void> = [];

function mountStrip(): Controller {
  let controller!: Controller;
  stops.push($effect.root(() => {
    controller = createTabController(() => PRIMARY_SLOT, () => {});
  }));
  flushSync();
  return controller;
}

function openFromMenu(controller: Controller, sessionId: string): string {
  controller.newAnchor = document.createElement('button');
  flushSync();
  const find = (nodes: MenuNode[]): MenuNode | null => {
    for (const node of nodes) {
      if (node.id.endsWith(`/${sessionId}`)) return node;
      const inner = find(node.children ?? []);
      if (inner) return inner;
    }
    return null;
  };
  const node = find(controller.menu);
  expect(node, `the menu offers ${sessionId}`).not.toBeNull();
  node!.run!();
  flushSync();
  const tab = controller.tabs.find((one) => one !== PRIMARY_SLOT);
  expect(tab).toBeDefined();
  return tab!;
}

function drawn(controller: Controller, tab: string) {
  flushSync();
  const item = controller.items.find((one) => one.id === tab);
  return { name: item?.name, status: item?.face?.status ?? null, session: controller.sessionOf(tab) };
}

function reload(): Controller {
  for (const stop of stops) stop();
  stops = [];
  flushSave();
  resetTabCache();
  return mountStrip();
}

beforeEach(() => {
  (globalThis as { TerminalController?: unknown }).TerminalController = { _sessionId: () => 'ses_page' };
  terminalLayout.bindSession('cloude_page', 1);
  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page'), live('ses_a', 7, 'cloude_p', 'alpha')];
  listing.asleep = [];
});

afterEach(() => {
  for (const stop of stops) stop();
  stops = [];
  inputFocus.forget(PRIMARY_SLOT);
  terminalLayout.bindSession('');
  resetTabCache();
  flushSave();
  localStorage.clear();
  delete (globalThis as { TerminalController?: unknown }).TerminalController;
});

test('wake: the tab follows its session to the new app id, with its name and light', () => {
  const strip = mountStrip();
  const tab = openFromMenu(strip, 'ses_a');
  expect(drawn(strip, tab)).toEqual({ name: 'alpha', status: 'idle', session: 'ses_a' });

  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page')];
  listing.asleep = [sleeping(7, 'cloude_p', 'alpha')];
  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page'), live('ses_a_woke', 7, 'cloude_p', 'alpha', 'working')];
  listing.asleep = [];

  expect(drawn(strip, tab)).toEqual({ name: 'alpha', status: 'working', session: 'ses_a_woke' });
});

test('recreate: a session whose tmux died comes back on its row under a new id, and its tab follows', () => {
  const strip = mountStrip();
  const tab = openFromMenu(strip, 'ses_a');
  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page'), live('ses_a_recreated', 7, 'cloude_p', 'alpha', 'question')];

  expect(drawn(strip, tab)).toEqual({ name: 'alpha', status: 'question', session: 'ses_a_recreated' });
});

test('reboot reopen: a new app id AND a new tmux name on the same row, and the tab still follows', () => {
  const strip = mountStrip();
  const tab = openFromMenu(strip, 'ses_a');
  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page'), live('ses_a_reopened', 7, 'carnivore_p', 'alpha')];

  const shown = reload();
  expect(drawn(shown, tab)).toEqual({ name: 'alpha', status: 'idle', session: 'ses_a_reopened' });
});

test('sleep plus reload: the sleeping tab keeps its name and its moon', () => {
  const strip = mountStrip();
  const tab = openFromMenu(strip, 'ses_a');
  expect(drawn(strip, tab).name).toBe('alpha');
  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page')];
  listing.asleep = [sleeping(7, 'cloude_p', 'task A')];
  expect(drawn(strip, tab)).toMatchObject({ name: 'task A', status: 'asleep' });

  const shown = reload();
  expect(drawn(shown, tab)).toMatchObject({ name: 'task A', status: 'asleep' });
});

test('a reused tmux name never lends another sleeping session its title', () => {
  const strip = mountStrip();
  const tab = openFromMenu(strip, 'ses_a');
  expect(drawn(strip, tab).name).toBe('alpha');

  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page'), live('ses_b', 9, 'cloude_p', 'beta')];
  listing.asleep = [sleeping(7, 'cloude_p', 'task A')];
  expect(drawn(strip, tab)).toMatchObject({ name: 'task A', status: 'asleep' });
  listing.sessions = [live('ses_page', 1, 'cloude_page', 'page')];
  listing.asleep = [sleeping(9, 'cloude_p', 'task B'), sleeping(7, 'cloude_p', 'task A')];

  expect(drawn(strip, tab)).toMatchObject({ name: 'task A', status: 'asleep' });
});

test("the page's own tab shows its session's name when the page holds an app id the listing does not carry", () => {
  (globalThis as { TerminalController?: unknown }).TerminalController = {
    _sessionId: () => 'ses_3c0ed73d',
    _currentTmuxName: () => 'cloude_misc',
  };
  listing.sessions = [live('ses_other', 9, 'cloude_misc', 'bot-Misc UI', 'working')];
  const strip = mountStrip();
  expect(drawn(strip, PRIMARY_SLOT)).toEqual({ name: 'bot-Misc UI', status: 'working', session: 'ses_other' });

  (globalThis as { SessionLabel?: unknown }).SessionLabel = {
    resolve: (row: { label: string | null; name: string | null }) => row.label || (row.name ?? '').replace(/^cloude_/, '') || null,
  };
  listing.sessions = [];
  expect(drawn(strip, PRIMARY_SLOT).name).toBe('misc');
  delete (globalThis as { SessionLabel?: unknown }).SessionLabel;
});
