/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerMenu from './DrawerMenu.svelte';
import { menuDashboardsFold } from './menu-dashboards.svelte';
import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import { resetLayout } from '../../opscenter/engine/model';
import { META } from '../../opscenter/engine/meta';
import { setLocale } from '../i18n/index.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();
setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  cplugEnablement.enabled = { huddle: true };
  homeBoards.list = [
    { id: 'home', name: 'main' },
    { id: 'b-2', name: 'Ops wall' },
    { id: 'b-3', name: 'alpha' },
  ];
  homeBoards.active = 'home';
  homeBoards.layouts = { 'b-2': resetLayout(META, 'home') };
  homeBoards.ready = true;
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  homeBoards.list = [{ id: 'home', name: 'home' }];
  homeBoards.ready = false;
  homeBoards.layouts = {};
  menuDashboardsFold.open = false;
  vi.restoreAllMocks();
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(DrawerMenu, { target }));
  flushSync();
  return target;
}

const caret = (root: HTMLElement) => root.querySelector<HTMLButtonElement>('[data-menu-dashboards-caret]')!;

test('no home row; dashboards row first with a caret, no key and no preview; the caret folds out the list: default and others A to Z, star on the default, keys on list items only, edit last', () => {
  const showLaunchpad = vi.fn();
  (window as unknown as { App: unknown }).App = { showLaunchpad };
  const root = render();
  expect(root.querySelector('[data-rail-item="home"]')).toBeNull();
  const first = root.querySelector<HTMLElement>('[data-rail-item]')!;
  expect(first.dataset['railItem']).toBe('dashboards');
  expect(caret(root).getAttribute('aria-expanded')).toBe('false');
  expect(root.querySelector('[data-menu-dashboard]')).toBeNull();
  expect(first.querySelector('.oc-nav-hint')).toBeNull();
  expect(root.querySelector('[data-menu-popout]')).toBeNull();
  first.dispatchEvent(new PointerEvent('pointerenter'));
  flushSync();
  expect(document.querySelector('[data-menu-preview]')).toBeNull();

  caret(root).click();
  flushSync();
  expect(caret(root).getAttribute('aria-expanded')).toBe('true');
  const items = [...root.querySelectorAll<HTMLElement>('[data-menu-dashboard]')];
  expect(items.map((item) => item.dataset['menuDashboard'])).toEqual(['b-3', 'home', 'b-2']);
  expect(root.querySelectorAll('[role="img"][aria-label="default"]').length).toBe(1);
  expect(items[1]!.querySelector('[role="img"][aria-label="default"]')).not.toBeNull();
  const keys = [...root.querySelectorAll<HTMLElement>('[data-menu-popout]')].map((key) => key.dataset['menuPopout']);
  expect(keys).toEqual(['dashboard:b-3', 'dashboard:home', 'dashboard:b-2']);
  const last = root.querySelector('[data-menu-dashboards-edit]')!;
  expect(last.closest('li')!.nextElementSibling!.querySelector('[data-rail-item="sessions"]')).not.toBeNull();
  expect(items[2]!.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  first.click();
  expect(showLaunchpad).toHaveBeenCalledTimes(1);
  caret(root).click();
  flushSync();
  expect(root.querySelector('[data-menu-dashboard]')).toBeNull();
});

test('each key opens the right window: the default as its dashboard, another dashboard as its own', () => {
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  const root = render();
  caret(root).click();
  flushSync();
  const press = (id: string) => root.querySelector<HTMLElement>(`[data-menu-popout="${id}"]`)!.click();
  press('dashboard:home');
  expect(open).toHaveBeenLastCalledWith('/static/popout.html?board=home&edit=1', 'carnivore-dashboard-home', expect.any(String));
  press('dashboard:b-2');
  expect(open).toHaveBeenLastCalledWith('/static/popout.html?board=b-2&edit=1', 'carnivore-dashboard-b-2', expect.any(String));
});

test('hovering or focusing a dashboard in the list shows its layout preview beside it; leaving takes it down', () => {
  const root = render();
  caret(root).click();
  flushSync();
  const rowEl = root.querySelector<HTMLElement>('[data-menu-dashboard="b-2"]')!;
  expect(document.querySelector('[data-menu-preview]')).toBeNull();
  rowEl.dispatchEvent(new PointerEvent('pointerenter'));
  flushSync();
  const preview = document.querySelector<HTMLElement>('[data-menu-preview]')!;
  expect(preview.dataset['menuPreview']).toBe('Ops wall');
  expect(preview.querySelectorAll('.dash-preview__box').length).toBeGreaterThan(0);
  rowEl.dispatchEvent(new PointerEvent('pointerleave'));
  flushSync();
  expect(document.querySelector('[data-menu-preview]')).toBeNull();
  rowEl.dispatchEvent(new FocusEvent('focus'));
  flushSync();
  expect(document.querySelector('[data-menu-preview]')).not.toBeNull();
});
