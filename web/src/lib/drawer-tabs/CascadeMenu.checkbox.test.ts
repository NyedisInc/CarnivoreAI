/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import CascadeMenu from './CascadeMenu.svelte';
import { closing } from '../widget-menu/model';
import type { MenuNode } from './add-component-menu';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();
setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

function open(extra: Partial<MenuNode> = {}): { onClose: ReturnType<typeof vi.fn>; state: { on: boolean; ran: number } } {
  const state = { on: false, ran: 0 };
  const onClose = vi.fn();
  const root: MenuNode[] = closing([
    { id: 'check', label: 'check', toggle: true, checked: false, run: () => { state.on = !state.on; }, ...extra },
    { id: 'plain', label: 'plain', run: () => { state.ran += 1; } },
    { id: 'radio', label: 'radio', checked: false, run: () => { state.ran += 1; } },
  ], onClose);
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(CascadeMenu, { target, props: { root, anchor: null, label: 'menu', onClose } }));
  flushSync();
  return { onClose, state };
}

const row = (id: string): HTMLElement => document.querySelector<HTMLElement>(`[data-node="${id}"]`)!;

test('a checkbox row flips both ways and the menu stays open', () => {
  const { onClose, state } = open();
  row('check').click();
  flushSync();
  expect(state.on).toBe(true);
  row('check').click();
  flushSync();
  expect(state.on).toBe(false);
  expect(onClose).not.toHaveBeenCalled();
});

test('a plain action row and a radio choice still close the menu', () => {
  const { onClose, state } = open();
  row('plain').click();
  expect(state.ran).toBe(1);
  expect(onClose).toHaveBeenCalledTimes(1);
  row('radio').click();
  expect(onClose).toHaveBeenCalledTimes(2);
});

test('keepOpen false makes one checkbox close the menu', () => {
  const { onClose } = open({ keepOpen: false });
  row('check').click();
  expect(onClose).toHaveBeenCalledTimes(1);
});
