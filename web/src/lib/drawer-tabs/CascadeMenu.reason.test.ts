/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import CascadeMenu from './CascadeMenu.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { tooltipTargetFor } from '../tooltip/tooltip';

installPopoverPolyfill();
setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

test('a blocked item is grayed with its reason in the tooltip, no printed line, and does nothing', () => {
  const reason = 'cannot rename: this agent has no live backend to send the change to';
  const blockedRun = vi.fn();
  const okRun = vi.fn();
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(CascadeMenu, { target, props: { root: [{ id: 'rename', label: 'rename', blocked: reason, run: blockedRun }, { id: 'ok', label: 'ok', run: okRun }], anchor: null, label: 'menu', onClose: () => {} } }));
  flushSync();
  const blocked = document.querySelector<HTMLElement>('[data-node="rename"]')!;
  const ok = document.querySelector<HTMLElement>('[data-node="ok"]')!;
  expect(blocked.getAttribute('aria-disabled')).toBe('true');
  expect(blocked.getAttribute('data-tooltip')).toBe(reason);
  expect(blocked.hasAttribute('title')).toBe(false);
  expect(blocked.hasAttribute('disabled')).toBe(false);
  expect(document.querySelector('.acm-why')).toBeNull();
  expect(blocked.textContent).not.toContain(reason);
  expect(tooltipTargetFor(blocked)).toBe(blocked);
  blocked.click();
  blocked.dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true }));
  expect(blockedRun).not.toHaveBeenCalled();
  expect(blocked.hasAttribute('data-menu-key')).toBe(false);
  expect(ok.hasAttribute('aria-disabled')).toBe(false);
  expect(ok.hasAttribute('data-tooltip')).toBe(false);
  ok.click();
  expect(okRun).toHaveBeenCalledTimes(1);
});
