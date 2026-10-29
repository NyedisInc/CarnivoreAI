/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import CascadeMenu from './CascadeMenu.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import type { MenuNode } from './add-component-menu';

installPopoverPolyfill();
setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

function render(root: MenuNode[]): void {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(CascadeMenu, { target, props: { root, anchor: null, label: 'menu', onClose: () => {} } }));
  flushSync();
}

test('a locked item draws the star and "sign in", is not aria-disabled, and a click runs it', () => {
  const run = vi.fn();
  render([
    { id: 'plain', label: 'plain', run: () => {} },
    { id: 'share', label: 'share read only', locked: 'share_link', run },
  ]);
  const item = document.querySelector<HTMLElement>('[data-node="share"]')!;
  expect(item.classList.contains('acm-locked')).toBe(true);
  expect(item.querySelector('.acm-lock-star svg'), 'star').not.toBeNull();
  expect(item.querySelector('.acm-lock')?.textContent).toContain('sign in');
  expect(item.hasAttribute('aria-disabled')).toBe(false);
  item.click();
  expect(run).toHaveBeenCalledTimes(1);
  const plain = document.querySelector<HTMLElement>('[data-node="plain"]')!;
  expect(plain.querySelector('.acm-lock')).toBeNull();
});

test('an on/off item draws a check box, filled only when checked, and a blocked one is aria-disabled so it reads dimmed', () => {
  render([
    { id: 'on', label: 'on one', toggle: true, checked: true, run: () => {} },
    { id: 'off', label: 'off one', toggle: true, checked: false, run: () => {} },
    { id: 'frozen', label: 'frozen one', toggle: true, checked: true, blocked: 'frozen one', run: () => {} },
    { id: 'radio', label: 'radio one', checked: true, run: () => {} },
  ]);
  const at = (id: string) => document.querySelector<HTMLElement>(`[data-node="${id}"]`)!;
  expect(at('on').getAttribute('role')).toBe('menuitemcheckbox');
  expect(at('on').querySelector('.acm-box.acm-box--on')).not.toBeNull();
  expect(at('off').querySelector('.acm-box')).not.toBeNull();
  expect(at('off').querySelector('.acm-box--on')).toBeNull();
  expect(at('frozen').getAttribute('aria-disabled')).toBe('true');
  expect(at('frozen').querySelector('.acm-box--on')).not.toBeNull();
  expect(at('radio').querySelector('.acm-box')).toBeNull();
});
