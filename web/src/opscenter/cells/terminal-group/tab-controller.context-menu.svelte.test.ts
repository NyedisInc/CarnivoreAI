/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { createTabController } from './tab-controller.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups, tabsFor } from '../../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../../engine/model';
import { pageTabId } from '../../engine/page-tabs';
import { inputFocus } from '../../lib/input-focus.svelte';
import { listing } from './fixtures/fake-listing.svelte';
import type { SessionInfo, SessionRecord } from '../../api/types';
import type { SlotId } from '../../engine/types';

const held = vi.hoisted(() => ({ pages: [] as unknown[], files: [] as unknown[], browsers: [] as unknown[] }));
const menus = vi.hoisted(() => ({
  openRowMenu: vi.fn(() => true),
  openBrowserItemMenu: vi.fn(() => true),
}));

vi.mock('../terminal-live/row-menu', () => ({ ...menus, uuidOfTmuxName: () => 'uuid-live' }));
vi.mock('../../../lib/browser/pages.svelte', () => ({
  openPages: { status: 'ok', get data() { return held.pages; }, refresh: async () => undefined },
  pageById: (id: string) => (held.pages as { id: string }[]).find((p) => p.id === id) ?? null,
}));
vi.mock('../../../lib/open-files/api.svelte', () => ({
  openFiles: { status: 'ok', get data() { return held.files; }, refresh: async () => undefined },
  fileById: (id: string) => (held.files as { id: string }[]).find((f) => f.id === id) ?? null,
}));
vi.mock('../../../lib/browser/api.svelte', () => ({
  browsers: { status: 'ok', get data() { return held.browsers; }, refresh: async () => undefined },
  browserById: (id: string) => (held.browsers as { id: string }[]).find((b) => b.id === id) ?? null,
  createBrowser: async () => ({ id: '' }),
}));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const { listing: fake } = await import('./fixtures/fake-listing.svelte');
  const resource = (read: () => unknown) => ({
    get data() { return read(); }, get status() { return read() ? 'ok' : 'loading'; },
    refresh: vi.fn(async () => {}), fetchedAt: 1, error: null, stop() {},
  });
  return { ...actual, sessions: resource(() => fake.sessions), asleep: resource(() => fake.asleep) };
});

const PAGE_ID = '0123456789abcdef';
const FILE_ID = 'fedcba9876543210';
const BROWSER_ID = 'aaaaaaaaaaaaaaaa';
const GONE_ID = 'bbbbbbbbbbbbbbbb';

const live = (id: string, rowId: number, tmux: string, family: string): SessionInfo => ({
  session: { id }, session_row_id: rowId, tmux_session: tmux, label: tmux, agent_family: family,
  activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: 'alien', status_source: 'registry',
}) as unknown as SessionInfo;

let stop: (() => void) | null = null;
type Controller = ReturnType<typeof createTabController>;

function strip(tabs: string[]): Controller {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, ...tabs] } });
  let ctl!: Controller;
  stop = $effect.root(() => { ctl = createTabController(() => PRIMARY_SLOT, () => {}); });
  flushSync();
  return ctl;
}

const anchor = (): HTMLElement => document.body.appendChild(document.createElement('button'));
const POINT = { x: 30, y: 12 };

beforeEach(() => {
  (globalThis as { TerminalController?: unknown }).TerminalController = { _sessionId: () => 'ses_page' };
  terminalLayout.bindSession('cloude_page', 1);
  listing.sessions = [
    live('ses_page', 1, 'cloude_page', 'claude'), live('ses_a', 7, 'cloude_a', 'claude'), live('ses_sh', 8, 'cloude_sh', 'shell'),
  ];
  listing.asleep = [{
    id: 9, session_uuid: 'uuid-9', tmux_name: 'cloude_z', title: 'zed', asleep: true, agent_family: 'claude', pinned_theme: 'matrix',
  } as unknown as SessionRecord];
  held.pages = [{ id: PAGE_ID, title: 'review board' }];
  held.files = [{ id: FILE_ID, kind: 'file', title: 'a.md' }];
  held.browsers = [{ id: BROWSER_ID, label: 'docs' }];
  menus.openRowMenu.mockClear();
  menus.openBrowserItemMenu.mockClear();
});

afterEach(() => {
  stop?.();
  stop = null;
  inputFocus.forget(PRIMARY_SLOT);
  terminalLayout.bindSession('');
  resetTabCache();
  localStorage.clear();
  delete (globalThis as { TerminalController?: unknown }).TerminalController;
});

test('a live agent tab opens the session row menu at the pointer', () => {
  const ctl = strip(['terminal:row:7']);
  const a = anchor();
  expect(ctl.openTabMenu('terminal:row:7', a, POINT)).toBe(true);
  const [row, uuid, el, opts] = menus.openRowMenu.mock.calls[0] as unknown as [SessionInfo, string, HTMLElement, Record<string, unknown>];
  expect(row.tmux_session).toBe('cloude_a');
  expect([uuid, el]).toEqual(['uuid-live', a]);
  expect(opts).toEqual({ point: POINT });
});

test('a shell tab opens the same session row menu', () => {
  const ctl = strip(['terminal:row:8']);
  ctl.openTabMenu('terminal:row:8', anchor(), POINT);
  const row = (menus.openRowMenu.mock.calls[0] as unknown as [SessionInfo])[0];
  expect(row.agent_family).toBe('shell');
});

test('a sleeping session\'s tab opens the ASLEEP row menu (the asleep row, its durable uuid)', () => {
  const ctl = strip(['terminal:row:9']);
  expect(ctl.openTabMenu('terminal:row:9', anchor(), POINT)).toBe(true);
  const [row, uuid] = menus.openRowMenu.mock.calls[0] as unknown as [Record<string, unknown>, string];
  expect(row).toMatchObject({ asleep: true, tmux_session: 'cloude_z', pinned_theme: 'matrix' });
  expect(uuid).toBe('uuid-9');
  expect(ctl.tabMenuAnchor).toBeNull();
});

test('a file tab opens the browser-kind row menu as a file', () => {
  const ctl = strip([pageTabId(FILE_ID)]);
  const a = anchor();
  expect(ctl.openTabMenu(pageTabId(FILE_ID), a, POINT)).toBe(true);
  expect(menus.openBrowserItemMenu).toHaveBeenCalledWith('file', FILE_ID, 'a.md', a, { point: POINT });
});

test('a review board tab (an opened page) opens the browser-kind row menu as a page', () => {
  const ctl = strip([pageTabId(PAGE_ID)]);
  ctl.openTabMenu(pageTabId(PAGE_ID), anchor(), null);
  expect(menus.openBrowserItemMenu.mock.calls[0]!.slice(0, 3)).toEqual(['page', PAGE_ID, 'review board']);
});

test('a proxy browser tab opens the browser-kind row menu as a browser', () => {
  const ctl = strip([pageTabId(BROWSER_ID)]);
  ctl.openTabMenu(pageTabId(BROWSER_ID), anchor(), POINT);
  expect(menus.openBrowserItemMenu.mock.calls[0]!.slice(0, 3)).toEqual(['browser', BROWSER_ID, 'docs']);
});

test('a closed page\'s tab opens the smallest menu: close tab, which removes the tab', () => {
  const tab = pageTabId(GONE_ID);
  const ctl = strip([tab]);
  const a = anchor();
  expect(ctl.openTabMenu(tab, a, POINT)).toBe(true);
  expect(menus.openBrowserItemMenu).not.toHaveBeenCalled();
  expect(ctl.tabMenuAnchor).toBe(a);
  expect(ctl.tabMenuNodes.map((n) => n.id)).toEqual(['close']);
  ctl.tabMenuNodes[0]!.run!();
  flushSync();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).not.toContain(tab);
  expect(ctl.tabMenuAnchor).toBeNull();
});

test('a session tab that is neither live nor asleep (a closed session) opens the smallest menu too', () => {
  const tab = 'terminal:row:42' as SlotId;
  const ctl = strip([tab]);
  expect(ctl.openTabMenu(tab, anchor(), POINT)).toBe(true);
  expect(menus.openRowMenu).not.toHaveBeenCalled();
  expect(ctl.tabMenuNodes.map((n) => n.id)).toEqual(['close']);
});
