/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerSearch from './DrawerSearch.svelte';
import * as Search from '../drawer/search';
import { applyDrawerTab, DRAWER_SEARCH_ID } from './drawer-tabs';
import { BUILTIN_TABS } from '../dynamic-tabs/builtin';

const REPO = path.resolve(process.cwd(), '..');
const html = (): string => fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');

function drawerMarkup(): string {
  const source = html();
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  if (start < 0 || end < 0) throw new Error('the drawer markup is missing from client/index.html');
  return source.slice(start, end + '</aside>'.length);
}

function installSearch(): void {
  delete win.SessionSidebar;
  Search.setQuery('');
  win.SessionSidebarSearch = {
    getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow,
    matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize,
  };
}

const mounted: ReturnType<typeof mount>[] = [];
type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;

beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  localStorage.clear();
  vi.spyOn(console, 'log').mockImplementation(() => {});
  installSearch();
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  for (const key of ['SessionSidebarSearch', 'SessionSidebar', 'SessionSidebarReorder', 'SessionLabel']) {
    delete win[key];
  }
  vi.restoreAllMocks();
});

function render(): { row: HTMLElement; input: HTMLInputElement } {
  const target = document.getElementById(DRAWER_SEARCH_ID);
  if (!target) throw new Error(`no #${DRAWER_SEARCH_ID} in the drawer markup`);
  mounted.push(mount(DrawerSearch, { target }));
  flushSync();
  const input = target.querySelector<HTMLInputElement>('.oc-search > input');
  if (!input) throw new Error('no input rendered');
  return { row: target, input };
}

test('renders a labeled text box, placeholder and aria-label from the catalog, no clear button while empty', () => {
  const { row, input } = render();
  expect(input.value).toBe('');
  expect(input.placeholder).toBeTruthy();
  expect(input.getAttribute('aria-label')).toBeTruthy();
  expect(row.querySelector('.oc-search__clear')).toBeNull();
});

test('typing sets window.SessionSidebarSearch\'s query and shows the clear button', () => {
  const { row, input } = render();
  input.value = 'orchard';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  expect((win.SessionSidebarSearch as { getQuery: () => string }).getQuery()).toBe('orchard');
  expect(row.querySelector<HTMLButtonElement>('.oc-search__clear')).not.toBeNull();
});

test('the clear button empties the box, clears the query, and returns focus to the input', () => {
  const { row, input } = render();
  input.value = 'orchard';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  row.querySelector<HTMLButtonElement>('.oc-search__clear')!.click();
  flushSync();
  expect(input.value).toBe('');
  expect((win.SessionSidebarSearch as { getQuery: () => string }).getQuery()).toBe('');
  expect(document.activeElement).toBe(input);
  expect(row.querySelector('.oc-search__clear')).toBeNull();
});

test('Escape on a non-empty box clears it and stops the keystroke reaching a document-level listener (the drawer\'s own Escape-to-close)', () => {
  const { input } = render();
  const outer = vi.fn();
  document.addEventListener('keydown', outer);
  input.value = 'orchard';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  flushSync();
  expect(input.value).toBe('');
  expect(outer, 'the drawer\'s document-level Escape handler must not also fire on this keystroke').not.toHaveBeenCalled();
  document.removeEventListener('keydown', outer);
});

test('Escape on an EMPTY box does nothing here and reaches the document, so a second press still closes the drawer as usual', () => {
  const { input } = render();
  const outer = vi.fn();
  document.addEventListener('keydown', outer);
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  flushSync();
  expect(outer, 'an empty box must not swallow Escape').toHaveBeenCalledTimes(1);
  document.removeEventListener('keydown', outer);
});

test('ArrowDown moves focus onto the first row via SessionSidebarReorder, not some ad-hoc lookup', () => {
  const { input } = render();
  const rowEl = { dataset: { name: 'cloude_alpha', band: 'pinned' } } as unknown as HTMLElement;
  const setFocusRow = vi.fn();
  win.SessionSidebarReorder = { rowEls: () => [rowEl], setFocusRow };
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  flushSync();
  expect(setFocusRow).toHaveBeenCalledWith('cloude_alpha', 'pinned', true);
});

test('ArrowDown with no rows on screen is a no-op, not a throw', () => {
  const { input } = render();
  win.SessionSidebarReorder = { rowEls: () => [], setFocusRow: vi.fn() };
  expect(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))).not.toThrow();
});

test('"/" focuses the box while the drawer has focus and no other field is being typed into', () => {
  const { row, input } = render();
  const panel = document.getElementById('session-sidebar-panel')!;
  const decoy = document.createElement('button');
  panel.appendChild(decoy);
  decoy.focus();
  expect(document.activeElement).toBe(decoy);
  document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true }));
  flushSync();
  expect(document.activeElement).toBe(input);
  expect(row.contains(input)).toBe(true);
});

test('"/" typed while ALREADY inside the search box is an ordinary character, not re-triggered focus', () => {
  const { input } = render();
  input.focus();
  const evt = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });
  const prevented = !document.dispatchEvent(evt);
  expect(prevented, 'typing "/" while already in the box must not be intercepted').toBe(false);
});

test('"/" from anywhere outside the drawer focuses the box (a global shortcut)', () => {
  const { input } = render();
  (document.activeElement as HTMLElement | null)?.blur?.();
  document.body.focus();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true }));
  flushSync();
  expect(document.activeElement).toBe(input);
});

test('"/" typed into a field or the terminal elsewhere stays a "/"', () => {
  const { input } = render();
  const term = document.createElement('textarea');
  document.body.appendChild(term);
  term.focus();
  const evt = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });
  const prevented = !term.dispatchEvent(evt);
  flushSync();
  expect(prevented).toBe(false);
  expect(document.activeElement).toBe(term);
  expect(document.activeElement).not.toBe(input);
  term.remove();
});

test('"/" is ignored on the menu tab, where the search container is hidden', () => {
  const { input } = render();
  applyDrawerTab('menu', BUILTIN_TABS);
  const panel = document.getElementById('session-sidebar-panel')!;
  const decoy = document.createElement('button');
  panel.appendChild(decoy);
  decoy.focus();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }));
  flushSync();
  expect(document.activeElement).not.toBe(input);
  applyDrawerTab('agents', BUILTIN_TABS);
});

test('Ctrl/Cmd+F is NOT bound here - it is the terminal search panel\'s own chord and must reach it untouched', () => {
  const { input } = render();
  const panel = document.getElementById('session-sidebar-panel')!;
  const decoy = document.createElement('button');
  panel.appendChild(decoy);
  decoy.focus();
  const meta = new KeyboardEvent('keydown', { key: 'f', metaKey: true, bubbles: true, cancelable: true });
  const ctrl = new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true, cancelable: true });
  const metaPrevented = !document.dispatchEvent(meta);
  const ctrlPrevented = !document.dispatchEvent(ctrl);
  flushSync();
  expect(metaPrevented).toBe(false);
  expect(ctrlPrevented).toBe(false);
  expect(document.activeElement).not.toBe(input);
});

test('applyDrawerTab hides and shows the search container the same way it does the list', () => {
  render();
  const container = document.getElementById(DRAWER_SEARCH_ID)!;
  expect(container.hidden, 'agents is the default tab').toBe(false);
  applyDrawerTab('menu', BUILTIN_TABS);
  expect(container.hidden).toBe(true);
  applyDrawerTab('agents', BUILTIN_TABS);
  expect(container.hidden).toBe(false);
});
