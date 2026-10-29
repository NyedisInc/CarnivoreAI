/** @vitest-environment jsdom */
import * as Density from '../drawer/density';
import { init as initStats, setStatsShown, statsShown } from '../drawer/stats-visibility.svelte';
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

const checkboxes = () => [...document.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"]')];

test('the item starts unchecked', () => {
  openMenu();
  const item = checkboxes().find((el) => el.textContent?.includes(t('drawer.density.show_stats')))!;
  expect(item.getAttribute('aria-checked')).toBe('false');
});

test('choosing it shows the stats and choosing it again hides them', () => {
  openMenu();
  const pick = (): void => {
    checkboxes().find((el) => el.textContent?.includes(t('drawer.density.show_stats')))!.click();
    flushSync();
  };
  expect(statsShown()).toBe(false);
  pick();
  expect(statsShown()).toBe(true);
  pick();
  expect(statsShown()).toBe(false);
});
