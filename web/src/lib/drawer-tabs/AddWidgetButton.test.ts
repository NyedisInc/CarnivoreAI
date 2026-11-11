/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const host = vi.hoisted(() => ({ open: vi.fn(), close: vi.fn(), isOpen: vi.fn(() => false) }));
vi.mock('../../opscenter/terminal-surface-host', () => ({
  openTerminalComponents: host.open,
  closeTerminalComponents: host.close,
  terminalComponentsOpen: host.isOpen,
}));

import MiniRail from '../mini-rail/MiniRail.svelte';
import AddWidgetButton from './AddWidgetButton.svelte';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import '../dynamic-tabs/builtin';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

const mounted: Record<string, unknown>[] = [];
let target: HTMLElement;

beforeEach(() => {
  installPopoverPolyfill();
  registerCoreSidebarWidgets();
  (globalThis as unknown as { SessionSidebar: unknown }).SessionSidebar = { open: vi.fn() };
  host.open.mockClear();
  host.close.mockClear();
  host.isOpen.mockReturnValue(false);
  target = document.createElement('div');
  document.body.append(target);
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.className = '';
  document.body.replaceChildren();
});

test('the railed terminal page draws one add-widget key in the rail, and it opens the list anchored to itself', () => {
  document.body.classList.add('session-sidebar-railed', 'ps-terminal-active', 'ps-grid-surface');
  mounted.push(mount(MiniRail, { target }));
  flushSync();
  const keys = target.querySelectorAll<HTMLButtonElement>('[data-add-widget]');
  expect(keys).toHaveLength(1);
  expect(keys[0]!.dataset.addWidget).toBe('rail');
  expect(keys[0]!.getAttribute('aria-label')).toBe('add widget');
  keys[0]!.click();
  expect(host.open).toHaveBeenCalledWith(keys[0], 'below');
});

test('a second press closes the list', () => {
  mounted.push(mount(AddWidgetButton, { target, props: { place: 'drawer' } }));
  flushSync();
  host.isOpen.mockReturnValue(true);
  target.querySelector<HTMLButtonElement>('[data-add-widget]')!.click();
  expect(host.close).toHaveBeenCalledTimes(1);
  expect(host.open).not.toHaveBeenCalled();
});
