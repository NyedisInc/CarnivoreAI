/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { startDrawerTabEffects } from '../drawer-tabs/drawer-tab-effects.svelte';
import './builtin';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import DynamicTabBody from './DynamicTabBody.svelte';
import { sidebarTabs } from './tab-store.svelte';
import { homeLayout } from '../../opscenter/engine/layout.svelte';
import {
  editorSeams,
  enterLayoutEditor,
  finishLayoutEditor,
  layoutEditor,
} from '../../opscenter/layout-editor/editor.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const REPO = path.resolve(process.cwd(), '..');
const real = { ...editorSeams };
const mounted: ReturnType<typeof mount>[] = [];

function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  return source.slice(start, end + '</aside>'.length);
}

let stopEffects: (() => void) | null = null;

function render(): void {
  stopEffects = startDrawerTabEffects();
  mounted.push(mount(DynamicTabBody, { target: document.getElementById('session-sidebar-tabbody')! }));
  flushSync();
}

const present = (id: string): boolean => sidebarTabs.present().some((def) => def.id === id);
const tabbody = () => document.getElementById('session-sidebar-tabbody')!;
const list = () => document.getElementById('session-sidebar-list')!;
const opened = vi.fn();

beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  registerCoreSidebarWidgets();
  localStorage.clear();
  sidebarTabs.select('agents');
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  homeLayout.resetAll();
  opened.mockReset();
  (globalThis as Record<string, unknown>).SessionSidebar = { isOpen: false, open: opened };
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(async () => {
  void finishLayoutEditor();
  flushSync();
  for (const c of mounted.splice(0)) await unmount(c);
  stopEffects?.();
  stopEffects = null;
  Object.assign(editorSeams, real);
  delete (globalThis as Record<string, unknown>).SessionSidebar;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test('entering edit layout opens the tab, shows it, opens a closed drawer, and docks the widget drawer in the sidebar', () => {
  render();
  expect(present('edit-layout'), 'no tab while the mode is off').toBe(false);
  expect(enterLayoutEditor()).toBe(true);
  flushSync();
  expect(sidebarTabs.active()).toBe('edit-layout');
  expect(opened).toHaveBeenCalledWith({ persist: false });
  expect(tabbody().hidden).toBe(false);
  expect(list().hidden).toBe(true);
  expect(tabbody().querySelector('.le-drawer.le-drawer--docked')).not.toBeNull();
  sidebarTabs.select('agents');
  flushSync();
  expect(layoutEditor.active).toBe(true);
  expect(list().hidden).toBe(false);
  expect(tabbody().hidden).toBe(true);
  expect(present('edit-layout')).toBe(true);
});

test('closing the tab exits edit layout and lands on the stored place', () => {
  render();
  sidebarTabs.select('menu');
  enterLayoutEditor();
  flushSync();
  sidebarTabs.close('edit-layout');
  flushSync();
  expect(layoutEditor.active).toBe(false);
  expect(present('edit-layout')).toBe(false);
  expect(sidebarTabs.active()).toBe('menu');
  expect(tabbody().querySelector('.le-drawer')).toBeNull();
  expect(tabbody().querySelector('nav.oc-sidebar')).toBeNull();
});

test('opening the tab enters edit layout; leaving the mode any other way (Escape) closes the tab', () => {
  render();
  expect(sidebarTabs.open('edit-layout')).toBe(true);
  flushSync();
  expect(layoutEditor.active).toBe(true);
  expect(sidebarTabs.active()).toBe('edit-layout');
  finishLayoutEditor();
  flushSync();
  expect(present('edit-layout')).toBe(false);
  expect(sidebarTabs.active()).toBe('agents');
});

test('the tab is refused where edit layout is (below 1024): nothing opens', () => {
  render();
  editorSeams.wide = () => false;
  expect(sidebarTabs.open('edit-layout')).toBe(false);
  flushSync();
  expect(present('edit-layout')).toBe(false);
});
