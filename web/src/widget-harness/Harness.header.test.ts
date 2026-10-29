/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import Harness from './Harness.svelte';
import { harnessWidget } from './catalog';
import { drawerZone } from '../lib/drawer-zone/zone-store.svelte';
import { zoneItemKey } from '../lib/drawer-zone/zone-model';
import { railStores } from '../lib/session-rail/rail-store.svelte';
import { HEADER_OPTION } from '../opscenter/shell/widget-head';
import { setLocale } from '../lib/i18n/index.svelte';
import { installPopoverPolyfill } from '../lib/popover-jsdom-polyfill';

setLocale('en');
installPopoverPolyfill();
(globalThis as Record<string, unknown>)['ResizeObserver'] ??= class { observe(): void {} unobserve(): void {} disconnect(): void {} };
let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('the drawer placement is in the drawer store, and its show header option hides then shows the header', async () => {
  const widget = harnessWidget('core.notes')!;
  app = mount(Harness, { target: document.body, props: { widget, zone: 'drawer', size: { name: 'm', w: 300, h: null } as never } });
  flushSync();
  await tick();
  const key = zoneItemKey(drawerZone.items[0]!);
  expect(drawerZone.items).toHaveLength(1);
  expect(drawerZone.items[0]!.widget).toBe('core.notes');
  expect(document.querySelector('[data-widget-head]')).not.toBeNull();
  drawerZone.setOption(key, HEADER_OPTION, false);
  await tick();
  flushSync();
  expect(document.querySelector('[data-widget-head]')).toBeNull();
  drawerZone.setOption(key, HEADER_OPTION, true);
  await tick();
  flushSync();
  expect(document.querySelector('[data-widget-head]')).not.toBeNull();
});

test.each(['side', 'bottom'] as const)('the %s slide-out card is in its bar store: no header until ticked, then show header and hide header work', async (dock) => {
  const widget = harnessWidget('core.notes')!;
  app = mount(Harness, { target: document.body, props: { widget, zone: 'drawer', size: { name: 'm', w: 300, h: null } as never, dock } });
  flushSync();
  await tick();
  const store = railStores[dock];
  expect(store.items).toHaveLength(1);
  expect(store.items[0]!.widget).toBe('core.notes');
  const key = zoneItemKey(store.items[0]!);
  expect(document.querySelector('[data-widget-head]')).toBeNull();
  expect(store.setOption(key, HEADER_OPTION, true)).toBe(true);
  await tick();
  flushSync();
  expect(document.querySelector('[data-widget-head]')).not.toBeNull();
  store.setOption(key, HEADER_OPTION, false);
  await tick();
  flushSync();
  expect(document.querySelector('[data-widget-head]')).toBeNull();
});

test('a right-click on a slide-out card opens the bar key menu, and its show header tick draws the header', async () => {
  const widget = harnessWidget('core.notes')!;
  app = mount(Harness, { target: document.body, props: { widget, zone: 'drawer', size: { name: 'm', w: 300, h: null } as never, dock: 'side' } });
  flushSync();
  await tick();
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 20, clientY: 20 });
  document.querySelector('.wh-rail-body')!.dispatchEvent(event);
  for (let i = 0; i < 4; i += 1) { await tick(); flushSync(); }
  expect(event.defaultPrevented).toBe(true);
  const tick_ = [...document.querySelectorAll<HTMLElement>('[role^="menuitem"]')].find((one) => /show header/.test(one.textContent ?? ''));
  expect(tick_).toBeDefined();
  tick_!.click();
  for (let i = 0; i < 4; i += 1) { await tick(); flushSync(); }
  expect(document.querySelector('[data-widget-head]')).not.toBeNull();
});
