/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { createTabController } from './tab-controller.svelte';
import TabStrip from '../../shell/TabStrip.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache } from '../../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../../engine/model';
import { listing } from './fixtures/fake-listing.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SessionInfo } from '../../api/types';
import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';

const fakeProjects = vi.hoisted(() => ({ data: [] as Array<Record<string, unknown>> }));

vi.mock('../../api/projects.svelte', () => ({ projects: fakeProjects }));
vi.mock('../../../lib/companies', () => ({ companyList: () => [{ id: 3, name: 'acme', hue: 145 }] }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  const { listing: fake } = await import('./fixtures/fake-listing.svelte');
  const resource = (read: () => unknown) => ({
    get data() { return read(); },
    get status() { return read() ? 'ok' : 'loading'; },
    refresh: vi.fn(async () => {}), fetchedAt: 1, error: null, stop() {},
  });
  return { ...actual, sessions: resource(() => fake.sessions), asleep: resource(() => fake.asleep), projects: fakeProjects };
});

function live(id: string, rowId: number, tmux: string, projectId: number | null): SessionInfo {
  return {
    session: { id }, session_row_id: rowId, tmux_session: tmux, label: tmux, agent_family: 'claude', project_id: projectId,
    activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null, status_source: 'registry',
  } as unknown as SessionInfo;
}

let stop: (() => void) | null = null;
let view: Record<string, unknown> | null = null;

function openAndRender(): { wrap: HTMLElement; bar: string | null | undefined; ctl: ReturnType<typeof createTabController>; tab: string } {
  let ctl!: ReturnType<typeof createTabController>;
  stop = $effect.root(() => { ctl = createTabController(() => PRIMARY_SLOT, () => {}); });
  flushSync();
  ctl.newAnchor = document.createElement('button');
  flushSync();
  const find = (nodes: MenuNode[]): MenuNode | null => {
    for (const n of nodes) { if (n.id.endsWith('/ses_a')) return n; const k = find(n.children ?? []); if (k) return k; }
    return null;
  };
  find(ctl.menu)!.run!();
  flushSync();
  const tab = ctl.tabs.find((one) => one !== PRIMARY_SLOT)!;
  inputFocus.claim(tab);
  flushSync();
  const host = document.createElement('div');
  document.body.append(host);
  view = mount(TabStrip, { target: host, props: { items: ctl.items, active: tab, holdsInput: ctl.holdsInput, onSelect: () => {}, group: 'g' } as never });
  flushSync();
  const wrap = host.querySelector('.oc-tabwrap-active') as HTMLElement;
  return { wrap, bar: ctl.items.find((one) => one.id === tab)?.bar, ctl, tab };
}

beforeEach(() => {
  (globalThis as { TerminalController?: unknown }).TerminalController = { _sessionId: () => 'ses_page' };
  terminalLayout.bindSession('cloude_page', 1);
});

afterEach(() => {
  if (view) unmount(view);
  view = null;
  stop?.();
  stop = null;
  document.body.innerHTML = '';
  inputFocus.forget('terminal:row:99');
  resetTabCache();
  localStorage.clear();
  delete (globalThis as { TerminalController?: unknown }).TerminalController;
});

test('a session in a project with a color: the active tab bar is that project color', () => {
  fakeProjects.data = [{ id: 9, color: '#966356', company_id: 3 }];
  listing.sessions = [live('ses_page', 1, 'cloude_page', null), live('ses_a', 7, 'cloude_a', 9)];
  const { wrap, bar } = openAndRender();
  expect(bar).toBe('#966356');
  expect(wrap.style.getPropertyValue('--oc-tab-bar')).toBe('#966356');
});

test('a project with no color but a company hue: the bar is the company hue', () => {
  fakeProjects.data = [{ id: 9, color: null, company_id: 3 }];
  listing.sessions = [live('ses_page', 1, 'cloude_page', null), live('ses_a', 7, 'cloude_a', 9)];
  expect(openAndRender().bar).toBe('oklch(0.74 0.09 145)');
});

test('an unfiled session: the bar is the theme accent, never orange', () => {
  fakeProjects.data = [];
  listing.sessions = [live('ses_page', 1, 'cloude_page', null), live('ses_a', 7, 'cloude_a', null)];
  const { wrap, bar } = openAndRender();
  expect(bar ?? null).toBe(wrap.style.getPropertyValue('--oc-tab-bar') || null);
  expect(wrap.style.getPropertyValue('--oc-tab-bar')).not.toMatch(/orange/);
});

function strip(ctl: ReturnType<typeof createTabController>, tab: string): HTMLElement {
  if (view) unmount(view);
  document.body.innerHTML = '';
  const host = document.createElement('div');
  document.body.append(host);
  view = mount(TabStrip, { target: host, props: { items: ctl.items, active: tab, holdsInput: ctl.holdsInput, onSelect: () => {}, group: 'g' } as never });
  flushSync();
  return host.querySelector('.oc-tabwrap-active') as HTMLElement;
}

test('two panes in a layout: only the pane that holds input shows the bar on its active tab', () => {
  fakeProjects.data = [{ id: 9, color: '#966356', company_id: 3 }];
  listing.sessions = [live('ses_page', 1, 'cloude_page', null), live('ses_a', 7, 'cloude_a', 9)];
  const { ctl, tab } = openAndRender();
  inputFocus.claim('terminal:row:99');
  flushSync();
  expect(ctl.holdsInput).toBe(false);
  expect(strip(ctl, tab).style.getPropertyValue('--oc-tab-bar')).toBe('');
  inputFocus.claim(tab);
  flushSync();
  expect(ctl.holdsInput).toBe(true);
  expect(strip(ctl, tab).style.getPropertyValue('--oc-tab-bar')).toBe('#966356');
  inputFocus.release(tab);
  flushSync();
  expect(ctl.holdsInput).toBe(true);
});
