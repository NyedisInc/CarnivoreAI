/** @vitest-environment jsdom */
import * as Density from '../drawer/density';
import { emptySectionsHidden, setEmptySectionsHidden } from '../drawer/empty-sections.svelte';
import { init as initSections, sectionShown, setSectionShown } from '../drawer/section-visibility.svelte';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import SidebarControls from '../sidebar-widgets/SidebarControls.svelte';
import { drawerSurface } from './drawer-surface.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { t } from '../i18n/index.svelte';

installPopoverPolyfill();

const REPO = path.resolve(process.cwd(), '..');
const win = globalThis as unknown as Record<string, unknown>;
const mounted: ReturnType<typeof mount>[] = [];

function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  return source.slice(start, source.indexOf('</aside>', start) + '</aside>'.length);
}

beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  localStorage.clear();
  drawerSurface.page = 'home';
  cplugEnablement.enabled = { huddle: false };
  vi.spyOn(console, 'log').mockImplementation(() => {});
  Density.init();
  initSections();
  win.SessionSidebarDensity = { init: Density.init, apply: Density.apply, setMode: Density.setMode, currentMode: Density.currentMode };
});

afterEach(async () => {
  cplugEnablement.enabled = {};
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete win.SessionSidebarDensity;
  setSectionShown('open', false);
  setSectionShown('sleeping', false);
  setEmptySectionsHidden(false);
  vi.restoreAllMocks();
});

function openMenu(): void {
  const target = document.createElement('div');
  document.getElementById('session-sidebar-panel')!.append(target);
  mounted.push(mount(SidebarControls, { target }));
  flushSync();
  target.querySelector<HTMLButtonElement>('[data-action="density"]')!.click();
  flushSync();
}

const checkboxes = () => [...document.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"]')];
const item = (key: string) => checkboxes().find((el) => el.textContent?.includes(t(key)))!;

test('both items are checkboxes, drawn with the square check box, checked by default', () => {
  openMenu();
  for (const key of ['drawer.density.show_open', 'drawer.density.show_sleeping']) {
    expect(item(key).getAttribute('aria-checked'), key).toBe('true');
    expect(item(key).querySelector('.acm-box'), key).not.toBeNull();
  }
  expect(checkboxes().length).toBe(7);
  expect(document.querySelectorAll('[role="menuitemradio"]').length).toBe(3);
});

test('choosing each flips only its own section, and the menu then shows it checked', () => {
  openMenu();
  item('drawer.density.show_open').click();
  flushSync();
  expect(sectionShown('open')).toBe(false);
  expect(sectionShown('sleeping')).toBe(true);
  expect(item('drawer.density.show_open').getAttribute('aria-checked')).toBe('false');
  item('drawer.density.show_sleeping').click();
  flushSync();
  expect(sectionShown('sleeping')).toBe(false);
});

const menuOpen = () => document.querySelector('[role="menu"]') !== null;

test('ticking and unticking keeps the menu open, flips the setting, and focus stays on the item', () => {
  openMenu();
  const open = item('drawer.density.show_open');
  open.focus();
  open.click();
  flushSync();
  expect(menuOpen()).toBe(true);
  expect(sectionShown('open')).toBe(false);
  expect(item('drawer.density.show_open').getAttribute('aria-checked')).toBe('false');
  expect(document.activeElement).toBe(item('drawer.density.show_open'));
  item('drawer.density.show_open').click();
  flushSync();
  expect(menuOpen()).toBe(true);
  expect(sectionShown('open')).toBe(true);
});

test('every other tick and the density radios keep the menu open too', () => {
  openMenu();
  for (const key of ['drawer.density.show_leaders', 'drawer.density.show_archived', 'drawer.density.show_stats']) {
    item(key).click();
    flushSync();
    expect(menuOpen(), key).toBe(true);
  }
  document.querySelector<HTMLElement>('[role="menuitemradio"]')!.click();
  flushSync();
  expect(menuOpen()).toBe(true);
});

test('Escape and an outside press still close the menu', () => {
  openMenu();
  item('drawer.density.show_open').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(menuOpen()).toBe(false);
  document.querySelector<HTMLButtonElement>('[data-action="density"]')!.click();
  flushSync();
  expect(menuOpen()).toBe(true);
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  flushSync();
  expect(menuOpen()).toBe(false);
});

test('an outside press closes the menu even when the page under it swallows the pointerdown (#1766)', () => {
  openMenu();
  const swallower = document.createElement('div');
  swallower.addEventListener('pointerdown', (event) => event.stopPropagation());
  document.body.append(swallower);
  swallower.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  flushSync();
  expect(menuOpen()).toBe(false);
});

test('a press inside the menu keeps it open', () => {
  openMenu();
  item('drawer.density.show_open').dispatchEvent(new Event('pointerdown', { bubbles: true }));
  flushSync();
  expect(menuOpen()).toBe(true);
});

test('the window blurring to an iframe closes the menu, a blur to the page does not (#1766)', async () => {
  openMenu();
  const frame = document.createElement('iframe');
  document.body.append(frame);
  frame.focus();
  window.dispatchEvent(new Event('blur'));
  await new Promise((resolve) => setTimeout(resolve, 5));
  flushSync();
  expect(menuOpen()).toBe(false);
  document.querySelector<HTMLButtonElement>('[data-action="density"]')!.click();
  flushSync();
  expect(menuOpen()).toBe(true);
  (document.activeElement as HTMLElement | null)?.blur();
  window.dispatchEvent(new Event('blur'));
  await new Promise((resolve) => setTimeout(resolve, 5));
  flushSync();
  expect(menuOpen()).toBe(true);
});

test('focus moving outside the menu closes it, focus inside it does not (#1766)', () => {
  openMenu();
  item('drawer.density.show_open').focus();
  flushSync();
  expect(menuOpen()).toBe(true);
  const field = document.createElement('input');
  document.body.append(field);
  field.focus();
  flushSync();
  expect(menuOpen()).toBe(false);
});

test('hide empty sections is a tick, checked by default, that flips the setting and keeps the menu open', () => {
  openMenu();
  const key = 'drawer.density.hide_empty_sections';
  expect(item(key).getAttribute('aria-checked')).toBe('false');
  item(key).click();
  flushSync();
  expect(emptySectionsHidden()).toBe(true);
  expect(menuOpen()).toBe(true);
  expect(item(key).getAttribute('aria-checked')).toBe('true');
});
