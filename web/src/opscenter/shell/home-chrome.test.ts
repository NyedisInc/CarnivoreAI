/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import App from '../App.svelte';
import AccountMenu from '../../lib/drawer-hud/AccountMenu.svelte';
import * as Bar from '../../lib/drawer/bar';
import { viewport } from '../engine/viewport.svelte';
import { homeBoards } from '../engine/home-sync.svelte';
import { approvals } from '../../lib/approvals/approvals.svelte';
import { closeAccountMenu } from '../../lib/drawer-hud/account-menu.svelte';
import { POPOUT_PATH } from '../../popout/popout';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';

installPopoverPolyfill();

(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

const SRC = path.join(process.cwd(), 'src/opscenter');
const read = (rel: string): string => fs.readFileSync(path.join(SRC, rel), 'utf8');
const ruleBody = (css: string, selector: string): string => {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const at = clean.search(new RegExp(`(^|\\n)\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{`));
  if (at < 0) return '';
  const open = clean.indexOf('{', at);
  return clean.slice(open + 1, clean.indexOf('}', open));
};

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  viewport.wide = true;
  viewport.phone = false;
  approvals.items = [];
  homeBoards.list = [{ id: 'home', name: 'home' }];
  homeBoards.active = 'home';
  homeBoards.ready = false;
  delete cplugEnablement.enabled['huddle'];
  closeAccountMenu();
  Bar.reset();
  delete (globalThis as { App?: unknown }).App;
  vi.restoreAllMocks();
});

/* the home screen */
function home(phone: boolean): HTMLElement {
  viewport.wide = !phone;
  viewport.phone = phone;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(App, { target }));
  flushSync();
  return target;
}

test('desktop: no header bar, and the one pop-out control takes no layout space', () => {
  const root = home(false);
  const shell = root.querySelector('.oc-app')!;
  expect(root.querySelector('.oc-topbar'), 'the header bar is still drawn on a desktop').toBeNull();
  expect(shell.classList.contains('oc-app-bare')).toBe(true);
  const btn = root.querySelector<HTMLButtonElement>('[data-home-open]');
  expect(btn, 'the pop-out control is missing').not.toBeNull();
  expect(btn!.getAttribute('aria-label')).toBe('open in a new window');
  const inFlow = [...shell.children].filter((el) => !el.classList.contains('oc-open-float'));
  expect(inFlow.map((el) => el.className.split(' ')[0])).toEqual(['oc-content']);
  expect(ruleBody(read('app.css'), '.oc-app-bare')).toMatch(/grid-template-rows:\s*minmax\(0, 1fr\)/);
  const menuSrc = read('shell/HomeOpenMenu.svelte');
  const float = ruleBody(menuSrc, '.oc-open-float');
  expect(float).toMatch(/position:\s*absolute/);
  expect(float).toMatch(/pointer-events:\s*none/);
  expect(btn!.dataset).toMatchObject({ btn: 'quiet', size: 'icon', tone: 'float' });
  expect(ruleBody(menuSrc, '.oc-open-float :global([data-home-open])')).toMatch(/pointer-events:\s*auto/);
  expect(ruleBody(read('../lib/base/icon-button.css'), ":where([data-btn][data-size='icon'][data-tone='float'])"), 'faint at rest').toMatch(/opacity:\s*0\.\d/);
});

test('NEGATIVE: a phone still draws its strip and no floating control', () => {
  const root = home(true);
  expect(root.querySelector('.oc-topbar')).not.toBeNull();
  expect(root.querySelector('[data-home-open]')).toBeNull();
  expect(root.querySelector('.oc-app')!.classList.contains('oc-app-bare')).toBe(false);
});

test('the pop-out menu lists the home screen, its wallboard, every other dashboard and every tab that pops out (Joe, 2026-10-04)', () => {
  homeBoards.list = [{ id: 'home', name: 'main' }, { id: 'b-1a2b', name: 'wall' }];
  homeBoards.active = 'home';
  homeBoards.ready = true;
  cplugEnablement.enabled['huddle'] = true;
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  const root = home(false);
  const btn = root.querySelector<HTMLButtonElement>('[data-home-open]')!;
  btn.click();
  flushSync();
  const items = () => [...document.querySelectorAll<HTMLElement>('[role="menu"] [role="menuitem"]')];
  expect(items().map((i) => i.dataset.node)).toEqual(['home', 'wallboard', 'dashboard:b-1a2b', 'tab:huddle']);
  expect(items().map((i) => i.querySelector('.acm-label')?.textContent?.trim())).toEqual(['home screen: main', 'home wallboard', 'wall', 'swarm']);
  expect(items().some((i) => i.dataset.node?.startsWith('board:'))).toBe(false);
  items()[2]!.click();
  flushSync();
  expect(open).toHaveBeenLastCalledWith('/static/popout.html?board=b-1a2b&edit=1', 'carnivore-dashboard-b-1a2b', expect.any(String));
  expect(document.querySelector('[role="menu"]'), 'choosing closes the menu').toBeNull();
  btn.click();
  flushSync();
  items()[0]!.click();
  expect(open).toHaveBeenLastCalledWith('/static/popout.html?board=home&edit=1', 'carnivore-dashboard-home', expect.stringContaining('popup=yes'));
  btn.click();
  flushSync();
  items()[1]!.click();
  expect(open).toHaveBeenLastCalledWith('/static/popout.html?view=wallboard', 'carnivore-wallboard', expect.any(String));
  btn.click();
  flushSync();
  items()[3]!.click();
  expect(open).toHaveBeenLastCalledWith(expect.stringContaining('/static/popout.html?tab=huddle'), expect.stringMatching(/^carnivore-tab-huddle-\w+$/), expect.any(String));
});

test('before the dashboards are known the home screen pops out as the plain home pop-out', () => {
  homeBoards.ready = false;
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  const root = home(false);
  root.querySelector<HTMLButtonElement>('[data-home-open]')!.click();
  flushSync();
  document.querySelector<HTMLElement>('[role="menu"] [data-node="home"]')!.click();
  expect(open).toHaveBeenLastCalledWith(POPOUT_PATH, 'carnivore-stats', expect.stringContaining('popup=yes'));
});

test('log out is the account menu item, and the bar has no standalone logout', () => {
  const logout = vi.fn();
  (globalThis as { App?: unknown }).App = { logout };
  document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div><div id="acct"></div>';
  Bar.paint();
  const slot = document.getElementById('session-sidebar-bar-slot')!;
  expect(slot.querySelector('[data-bar-action="logout"]'), 'standalone logout still drawn').toBeNull();
  expect(slot.querySelector('.session-sidebar-bar__conn'), 'the status light is gone').toBeNull();
  mounted.push(mount(AccountMenu, { target: document.getElementById('acct')! }));
  slot.querySelector<HTMLElement>('[data-bar-action="account"]')!.click();
  flushSync();
  const items = [...document.querySelectorAll<HTMLElement>('[role="menu"] [role="menuitem"]')];
  const byId = (id: string) => items.find((i) => i.dataset.node === id)!;
  expect(items.at(-1)?.dataset.node).toBe('logout');
  expect(items.find((i) => i.dataset.node === 'help'), 'help row is gone').toBeUndefined();
  expect(items.find((i) => i.dataset.node === 'profile'), 'no placeholder item').toBeUndefined();
  byId('logout').click();
  flushSync();
  expect(logout).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});
