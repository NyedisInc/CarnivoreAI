/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import CascadeMenu from './CascadeMenu.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { claimOpenMenu, closeOpenMenu } from './open-menu';
import type { MenuNode } from './add-component-menu';

installPopoverPolyfill();
setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  closeOpenMenu();
});

function render(root: MenuNode[], extra: Record<string, unknown> = {}): ReturnType<typeof vi.fn> {
  const onClose = vi.fn();
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(CascadeMenu, { target, props: { root, anchor: null, label: 'menu', onClose, ...extra } }));
  flushSync();
  return onClose;
}

const ONE: MenuNode[] = [{ id: 'a', label: 'a', run: () => {} }];

test('opening a second menu closes the first; the second stays open', () => {
  const first = render(ONE);
  expect(first).not.toHaveBeenCalled();
  const second = render(ONE);
  expect(first).toHaveBeenCalled();
  expect(second).not.toHaveBeenCalled();
});

test('a nested flyout never claims the handle: the host keeps it, so the handle closes the host and not the flyout', () => {
  const host = render(ONE);
  const flyout = render(ONE, { nestedIn: document.querySelector<HTMLElement>('.acm-menu') });
  host.mockClear();
  flyout.mockClear();
  closeOpenMenu();
  expect(host).toHaveBeenCalledTimes(1);
  expect(flyout).not.toHaveBeenCalled();
});

test('another engine (the terminal kebab) uses the same handle: claiming closes the open menu, and a closed menu releases it', () => {
  const menu = render(ONE);
  const release = claimOpenMenu(() => {});
  expect(menu).toHaveBeenCalledTimes(1);
  release();
  closeOpenMenu();
});

test('a press on a surface that stops the event still closes the menu (capture phase)', () => {
  const onClose = render(ONE);
  const terminal = document.createElement('div');
  terminal.className = 'xterm';
  terminal.addEventListener('pointerdown', (event) => event.stopPropagation());
  document.body.append(terminal);
  terminal.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('a press inside an iframe (the window blurs onto it) closes the menu', async () => {
  const onClose = render(ONE);
  const frame = document.createElement('iframe');
  document.body.append(frame);
  frame.focus();
  window.dispatchEvent(new Event('blur'));
  await new Promise((resolve) => setTimeout(resolve, 5));
  expect(onClose).toHaveBeenCalled();
});

test('a press inside the menu does not close it', () => {
  const onClose = render(ONE);
  document.querySelector('.acm-item')!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(onClose).not.toHaveBeenCalled();
});

test('a destructive item wears the danger class, and a menu with any icon gives every row the 14px slot so labels line up', () => {
  render([
    { id: 'plain', label: 'plain', run: () => {} },
    { id: 'close-widget', label: 'close widget', icon: 'close', danger: true, run: () => {} },
  ]);
  expect(document.querySelector('[data-node="close-widget"]')!.classList.contains('acm-item--danger')).toBe(true);
  expect(document.querySelector('[data-node="plain"]')!.classList.contains('acm-item--danger')).toBe(false);
  expect(document.querySelector('[data-node="plain"] .acm-icon')).not.toBeNull();
});

test('a menu with no icon draws no icon slot', () => {
  render(ONE);
  expect(document.querySelector('.acm-icon')).toBeNull();
});
