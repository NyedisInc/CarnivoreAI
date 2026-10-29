/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import DockBar from './DockBar.svelte';
import { createKeyMenuBridge, toFramePoint } from './key-menu-bridge';
import { KEY_MENU_MESSAGE, readKeyMenuMessage } from '../sdk/widget-lab';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');
let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('a key outside the frame hangs its menu at the frame edge, inside the frame window', () => {
  expect(toFramePoint({ left: 410, top: 10, width: 36, height: 36 }, { left: 0, top: 0, width: 400, height: 440 })).toEqual({ x: 399, y: 28 });
  expect(toFramePoint({ left: 100, top: 460, width: 36, height: 36 }, { left: 0, top: 0, width: 400, height: 440 })).toEqual({ x: 118, y: 439 });
});

test('a frame drawn at a scale maps the key to the frame\'s own pixels', () => {
  expect(toFramePoint({ left: 100, top: 50, width: 20, height: 20 }, { left: 0, top: 0, width: 200, height: 220 }, 0.5)).toEqual({ x: 220, y: 120 });
  expect(toFramePoint({ left: 400, top: 50, width: 20, height: 20 }, { left: 0, top: 0, width: 200, height: 220 }, 0.5)).toEqual({ x: 399, y: 120 });
});

test('the bridge reaches every listener until it is stopped, and the reader refuses a malformed message', () => {
  const bridge = createKeyMenuBridge();
  const heard = vi.fn();
  const stop = bridge.subscribe(heard);
  bridge.request({ left: 1, top: 2, width: 3, height: 4 });
  stop();
  bridge.request({ left: 1, top: 2, width: 3, height: 4 });
  expect(heard).toHaveBeenCalledTimes(1);
  expect(readKeyMenuMessage({ type: KEY_MENU_MESSAGE, x: 3, y: 4 })).toEqual({ type: KEY_MENU_MESSAGE, x: 3, y: 4 });
  expect(readKeyMenuMessage({ type: 'other', x: 3, y: 4 })).toBeNull();
  expect(readKeyMenuMessage({ type: KEY_MENU_MESSAGE, x: 'a', y: 4 })).toBeNull();
});

test('only the lit key of the mock bar asks for the menu, on a right-click', () => {
  const asked = vi.fn();
  app = mount(DockBar, { target: document.body, props: { edge: 'side', keys: ['files'], lit: 'grid', litLabel: 'notes', onlitmenu: asked } });
  flushSync();
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  document.querySelector('[data-key-open]')!.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(asked).toHaveBeenCalledTimes(1);
  expect(document.querySelectorAll('.dwl-chrome-key[inert]').length).toBe(1);
});
