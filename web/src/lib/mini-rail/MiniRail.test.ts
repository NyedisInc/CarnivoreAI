/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import MiniRail from './MiniRail.svelte';
import SidebarRail from '../sidebar-widgets/SidebarRail.svelte';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import '../dynamic-tabs/builtin';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

const mounted: Record<string, unknown>[] = [];
let target: HTMLElement;
const open = vi.fn();

beforeEach(() => {
  installPopoverPolyfill();
  registerCoreSidebarWidgets();
  (globalThis as unknown as { SessionSidebar: unknown }).SessionSidebar = { open };
  open.mockClear();
  target = document.createElement('div');
  document.body.append(target);
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.className = '';
  document.body.replaceChildren();
});

const keys = (): string[] => [...target.querySelectorAll<HTMLElement>('[data-rail-key]')].map((el) => el.dataset.railKey ?? '');

test('the closed rail draws the same keys in the same order as the open drawer rail, plus the meters (the open rail has none), and its pin place reopens the drawer', async () => {
  mounted.push(mount(SidebarRail, { target }));
  flushSync();
  const openKeys = keys();
  expect(openKeys.length).toBeGreaterThan(3);
  expect(target.querySelector('.mr-usage')).toBeNull();
  expect(target.querySelector('.mr-footer')).toBeNull();
  for (const c of mounted.splice(0)) await unmount(c);
  target.replaceChildren();

  document.body.classList.add('session-sidebar-railed');
  mounted.push(mount(MiniRail, { target }));
  flushSync();
  expect(keys()).toEqual(openKeys);
  expect(target.querySelector('.mr-usage')).not.toBeNull();
  expect(target.querySelector('.mr-footer')).not.toBeNull();
  target.querySelector<HTMLButtonElement>('[data-rail="open"]')!.click();
  expect(open).toHaveBeenCalledTimes(1);
});
