/** @vitest-environment jsdom */
import * as Density from '../drawer/density';
import { init as initStats, setStatsShown } from '../drawer/stats-visibility.svelte';
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
  initStats();
  win.SessionSidebarDensity = {
    init: Density.init, apply: Density.apply, setMode: Density.setMode, currentMode: Density.currentMode,
  };
});

afterEach(async () => {
  cplugEnablement.enabled = {};
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete win.SessionSidebarDensity;
  setStatsShown(false);
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

const items = () => [...document.querySelectorAll<HTMLElement>('.acm-item')];

test('the menu is exactly four groups, a rule before the second, third and fourth', () => {
  openMenu();
  const ids = items().map((el) => el.dataset.node);
  expect(ids).toEqual([
    'density-compact', 'density-cozy', 'density-detailed',
    'show-stats',
    'show-leaders', 'show-archived', 'show-closed',
    'show-open', 'show-sleeping', 'hide-empty-sections',
  ]);
  const starts = items().filter((el) => el.classList.contains('acm-sep')).map((el) => el.dataset.node);
  expect(starts).toEqual(['show-stats', 'show-leaders', 'show-open']);
});

function setClipped(el: HTMLElement, cut: boolean): void {
  Object.defineProperty(el, 'clientWidth', { configurable: true, value: 100 });
  Object.defineProperty(el, 'scrollWidth', { configurable: true, value: cut ? 180 : 100 });
}

test('a label shows its full text on hover only when it is cut off', () => {
  openMenu();
  const labels = items().map((el) => el.querySelector<HTMLElement>('.acm-label')!);
  expect(labels.length).toBeGreaterThan(0);
  for (const label of labels) expect(label.hasAttribute('title')).toBe(false);
  const cut = labels[0]!;
  const fits = labels[1]!;
  setClipped(cut, true);
  setClipped(fits, false);
  cut.dispatchEvent(new Event('pointerover', { bubbles: true }));
  fits.dispatchEvent(new Event('pointerover', { bubbles: true }));
  expect(cut.getAttribute('data-tooltip')).toBe(cut.textContent);
  expect(fits.hasAttribute('data-tooltip')).toBe(false);
  setClipped(cut, false);
  cut.dispatchEvent(new Event('pointerover', { bubbles: true }));
  expect(cut.hasAttribute('data-tooltip')).toBe(false);
});
