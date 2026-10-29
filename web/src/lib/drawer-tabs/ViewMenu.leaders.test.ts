/** @vitest-environment jsdom */
import * as Density from '../drawer/density';
import { leadersShown, setLeadersShown } from '../drawer/leader-visibility';
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

/** The drawer's <aside>, exactly as shipped. */
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
  win.SessionSidebarDensity = {
    init: Density.init, apply: Density.apply, setMode: Density.setMode, currentMode: Density.currentMode,
  };
});

afterEach(async () => {
  cplugEnablement.enabled = {};
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete win.SessionSidebarDensity;
  vi.restoreAllMocks();
});

/** Mount the bar and open the view menu. */
function openMenu(): HTMLElement {
  // The view menu as the sidebar draws it: the top bar's controls (issue #1774), not the retired tab strip.
  const target = document.createElement('div');
  document.getElementById('session-sidebar-panel')!.append(target);
  mounted.push(mount(SidebarControls, { target }));
  flushSync();
  target.querySelector<HTMLButtonElement>('[data-action="density"]')!.click();
  flushSync();
  return target;
}

const item = () =>
  [...document.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"]')].find(
    (el) => el.textContent?.includes(t('drawer.density.show_leaders')),
  );

test('the view menu carries the leaders toggle and the standalone key is gone', () => {
  const row = openMenu();
  expect(item()).toBeTruthy();
  expect(item()!.getAttribute('aria-checked')).toBe('true');
  expect(row.querySelector('[data-leaders]')).toBeNull();
  expect(row.querySelectorAll('[role="toolbar"] button[data-action="density"]').length).toBe(1);
});

test('choosing it flips the same stored preference', () => {
  openMenu();
  expect(leadersShown()).toBe(true);
  item()!.click();
  flushSync();
  expect(leadersShown()).toBe(false);
  setLeadersShown(true);
});
