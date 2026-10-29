/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { resetTabCache, setGroups, tabsFor } from '../../engine/tab-groups.svelte';
import { pageTabId } from '../../engine/page-tabs';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));

const PAGE_ID = '0123456789abcdef';
const FILE_ID = 'fedcba9876543210';
const NEW_ID = '1111111111111111';

const held = vi.hoisted(() => ({
  pages: [] as unknown[], files: [] as unknown[], browsers: [] as unknown[], status: 'ok' as string, created: [] as string[],
}));

vi.mock('../../../lib/browser/pages.svelte', () => ({
  openPages: {
    get status() { return held.status; }, get data() { return held.pages; },
    refresh: async () => undefined,
  },
  pageById: (id: string) => (held.pages as { id: string }[]).find((p) => p.id === id) ?? null,
}));
vi.mock('../../../lib/open-files/api.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/open-files/api.svelte')>()),
  openFiles: {
    get status() { return held.status; }, get data() { return held.files; },
    refresh: async () => undefined,
  },
  fileById: (id: string) => (held.files as { id: string }[]).find((f) => f.id === id) ?? null,
}));
vi.mock('../../../lib/browser/api.svelte', () => ({
  browsers: {
    get status() { return held.status; }, get data() { return held.browsers; },
    refresh: async () => undefined,
  },
  browserById: (id: string) => (held.browsers as { id: string }[]).find((b) => b.id === id) ?? null,
  createBrowser: async () => {
    held.created.push(NEW_ID);
    held.browsers.push({ id: NEW_ID, label: 'new browser', url: '', state: 'live', viewers: 0 });
    return { id: NEW_ID };
  },
}));
vi.mock('../../../lib/browser/PageFrame.svelte', async () => ({ default: (await import('./fixtures/StubFrame.svelte')).default }));
vi.mock('../../../lib/browser/BrowserView.svelte', async () => ({ default: (await import('./fixtures/StubFrame.svelte')).default }));
vi.mock('../../../lib/open-files/FileScreen.svelte', async () => ({ default: (await import('./fixtures/StubFrame.svelte')).default }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: { data: [], status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {} },
  };
});

const A = 'terminal:ses_a' as SlotId;
const PAGE_TAB = pageTabId(PAGE_ID);
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  terminalLayout.add('terminal', 'ses_a');
  held.pages = [{ id: PAGE_ID, key: 'k', frame: 'sandboxed', title: 'review board', opened_at: 1, src: '/api/v1/x' }];
  held.files = [{ id: FILE_ID, kind: 'file', root: 'user', path: 'a.md', session_uuid: '', title: 'a.md', opened_at: 1, seq: 1 }];
  held.browsers = [];
  held.status = 'ok';
  held.created.length = 0;
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  inputFocus.forget(A);
  terminalLayout.remove(A);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
});

function draw(): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A } });
  flushSync();
  return target;
}

function item(id: string): HTMLButtonElement {
  return document.querySelector(`[role="menuitem"][data-node="${id}"]`) as HTMLButtonElement;
}

function openBrowserBranch(root: HTMLElement): void {
  (root.querySelector('.oc-tab-new') as HTMLButtonElement).click();
  flushSync();
  item('browser').click();
  flushSync();
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) await Promise.resolve();
  flushSync();
}

test('a page tab draws its frame in the pane and reads the page title with no status light', async () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, PAGE_TAB] } });
  const root = draw();
  await settle();
  const pane = root.querySelector(`[data-tab-pane="${PAGE_TAB}"]`) as HTMLElement;
  expect(pane.querySelector(`[data-page-tab="${PAGE_ID}"]`)).not.toBeNull();
  expect(pane.querySelector('[data-stub-frame]')).not.toBeNull();
  const tab = root.querySelector(`[data-tab="${PAGE_TAB}"]`) as HTMLElement;
  expect(tab.textContent).toContain('review board');
  expect(tab.querySelector('.status-led, [data-status-led]')).toBeNull();
});

test('a file and a proxy browser tab draw their own renderers', async () => {
  held.browsers = [{ id: NEW_ID, label: 'search', url: '', state: 'live', viewers: 0 }];
  setGroups(terminalLayout, { [A]: { tabs: [A, pageTabId(FILE_ID), pageTabId(NEW_ID)] } });
  const root = draw();
  await settle();
  expect((root.querySelector(`[data-tab="${pageTabId(FILE_ID)}"]`) as HTMLElement).textContent).toContain('a.md');
  expect((root.querySelector(`[data-tab="${pageTabId(NEW_ID)}"]`) as HTMLElement).textContent).toContain('search');
  expect(root.querySelectorAll('[data-stub-frame]').length).toBe(2);
});

test('a tab whose page is gone shows the closed placeholder, and its x still removes it', () => {
  held.pages = [];
  setGroups(terminalLayout, { [A]: { tabs: [A, PAGE_TAB] } });
  const root = draw();
  const pane = root.querySelector(`[data-tab-pane="${PAGE_TAB}"]`) as HTMLElement;
  expect(pane.textContent).toContain('this page was closed');
  expect(pane.querySelector('[data-stub-frame]')).toBeNull();
  expect((root.querySelector(`[data-tab="${PAGE_TAB}"]`) as HTMLElement).textContent).toContain('closed page');
  (root.querySelector(`[data-tab-close="${PAGE_TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(tabsFor(terminalLayout, A)).toEqual([A]);
});

test('lists that have not arrived read as loading, never closed', () => {
  held.pages = [];
  held.status = 'loading';
  setGroups(terminalLayout, { [A]: { tabs: [A, PAGE_TAB] } });
  const root = draw();
  const pane = root.querySelector(`[data-tab-pane="${PAGE_TAB}"]`) as HTMLElement;
  expect(pane.textContent).not.toContain('was closed');
});

test('the browser root lists the open pages and files; picking one opens it as a tab here', () => {
  const root = draw();
  openBrowserBranch(root);
  expect(item('browser/new')).not.toBeNull();
  expect(item(`browser/${FILE_ID}`)).not.toBeNull();
  item(`browser/${PAGE_ID}`).click();
  flushSync();
  expect(tabsFor(terminalLayout, A)).toEqual([A, PAGE_TAB]);
  expect(root.querySelector(`[data-tab="${PAGE_TAB}"]`)?.getAttribute('aria-selected')).toBe('true');
});

test('a page already a tab here is left out of the menu', () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, PAGE_TAB] } });
  const root = draw();
  openBrowserBranch(root);
  expect(item(`browser/${PAGE_ID}`)).toBeNull();
  expect(item(`browser/${FILE_ID}`)).not.toBeNull();
});

test('new proxy browser creates one and lands it as a tab here', async () => {
  const root = draw();
  openBrowserBranch(root);
  item('browser/new').click();
  await Promise.resolve();
  await Promise.resolve();
  flushSync();
  expect(held.created).toEqual([NEW_ID]);
  expect(tabsFor(terminalLayout, A)).toEqual([A, pageTabId(NEW_ID)]);
});

test('the frame title row names the showing page, never "terminal", and fenmont on a session tab', async () => {
  setGroups(terminalLayout, { [A]: { tabs: [A, PAGE_TAB] } });
  const root = draw();
  await settle();
  const names = (): string[] =>
    [...root.querySelectorAll('.oc-frame-name, .oc-frame-nametext')].map((el) => (el.textContent ?? '').trim().toLowerCase());
  (root.querySelector(`[data-tab="${PAGE_TAB}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(names().length).toBeGreaterThan(0);
  expect(names()).toContain('review board');
  expect(names()).not.toContain('terminal');
  (root.querySelector(`[data-tab="${A}"]`) as HTMLButtonElement).click();
  flushSync();
  expect(names()).not.toContain('review board');
});
