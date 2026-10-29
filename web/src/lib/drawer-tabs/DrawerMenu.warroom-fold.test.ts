/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const gate = vi.hoisted(() => ({ wide: true }));
const openWarroomScreen = vi.hoisted(() => vi.fn());
vi.mock('../warroom/phone.svelte', () => ({ warroomAvailable: () => gate.wide }));
vi.mock('../warroom/screen-host', () => ({ openWarroomScreen }));

import DrawerMenu from './DrawerMenu.svelte';
import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import { menuDashboardsFold } from './menu-dashboards.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  gate.wide = true;
  homeBoards.list = [{ id: 'home', name: 'home' }, { id: 'b-2', name: 'ops' }];
  homeBoards.active = 'home';
  homeBoards.ready = true;
  menuDashboardsFold.open = true;
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  menuDashboardsFold.open = false;
  homeBoards.list = [{ id: 'home', name: 'home' }];
  homeBoards.ready = false;
  openWarroomScreen.mockClear();
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(DrawerMenu, { target }));
  flushSync();
  return target;
}

test('wide, fold open: the first line under dashboards is war room, the main rows have none, and c still opens it', () => {
  const root = render();
  const mainIds = [...root.querySelectorAll<HTMLElement>('li.oc-nav-line:not(.oc-nav-sub)[data-menu-row]')].map((l) => l.dataset.menuRow);
  expect(mainIds).not.toContain('warroom');
  const subs = [...root.querySelectorAll<HTMLElement>('li.oc-nav-sub')];
  expect(subs[0]?.querySelector('[data-rail-item="warroom"]')?.textContent).toContain('war room');
  expect(subs[1]?.querySelector('[data-menu-dashboard]')).not.toBeNull();
  const key = new KeyboardEvent('keydown', { key: 'c', bubbles: true, cancelable: true });
  root.querySelector('[data-rail-item="dashboards"]')!.dispatchEvent(key);
  expect(openWarroomScreen).toHaveBeenCalledTimes(1);
});

test('at 700 px and narrower the fold shows no war room line', () => {
  gate.wide = false;
  const root = render();
  expect(root.querySelector('[data-rail-item="warroom"]')).toBeNull();
  expect(root.querySelector('li.oc-nav-sub [data-menu-dashboard]')).not.toBeNull();
});
