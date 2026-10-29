/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import './builtin';
import WidgetAreaBar from './WidgetAreaBar.svelte';
import { sidebarTabs } from './tab-store.svelte';
import { WIDGET_AREA_STORAGE_KEY, widgetArea } from './widget-area.svelte';
import { GLANCE_ROW_HEIGHT_PX } from '../drawer-zone/glance';

let barHost: HTMLElement;
let area: HTMLElement;
let instance: unknown;
let areaHeight = 0;

const bar = (): HTMLElement => barHost.querySelector<HTMLElement>('[data-area-bar]')!;
const pointer = (type: string, clientY: number, target: EventTarget = bar()): void => {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientY }));
  flushSync();
};

beforeEach(() => {
  localStorage.clear();
  widgetArea.overrides = {};
  sidebarTabs.select('menu');
  area = document.createElement('div');
  area.id = 'session-sidebar-ledger';
  area.className = 'session-sidebar-ledger';
  area.getBoundingClientRect = () => ({ height: areaHeight }) as DOMRect;
  barHost = document.createElement('div');
  document.body.append(barHost, area);
  instance = mount(WidgetAreaBar, { target: barHost });
  flushSync();
});

afterEach(() => {
  unmount(instance as never);
  barHost.remove();
  area.remove();
});

describe('the separator', () => {
  test('is a thin handle: no label, no buttons, the short centre line outside closed', () => {
    expect(widgetArea.stateFor('menu')).toBe('glance');
    expect(bar().textContent?.trim()).toBe('');
    expect(bar().querySelectorAll('button')).toHaveLength(0);
    expect(bar().querySelector('[data-area-handle]')).not.toBeNull();
    expect(bar().querySelector('[data-area-chevron]')).toBeNull();
    expect(area.dataset['areaState']).toBe('glance');
  });

  test('closed shows the pull-up chevron, and a click opens FULL, not glance', () => {
    widgetArea.set('menu', 'closed');
    flushSync();
    expect(bar().querySelector('[data-area-chevron]')).not.toBeNull();
    expect(bar().querySelector('[data-area-handle]')).toBeNull();
    bar().click();
    flushSync();
    expect(widgetArea.stateFor('menu')).toBe('full');
    expect(area.dataset['areaState']).toBe('full');
    expect(JSON.parse(localStorage.getItem(WIDGET_AREA_STORAGE_KEY) ?? '{}')).toEqual({ menu: 'full' });
  });

  test('PHONE TAP TARGET: closed draws the "tap to enlarge" hint, shown and 44px tall only below 1024px', () => {
    expect(bar().querySelector('[data-area-hint]')).toBeNull();
    widgetArea.set('menu', 'closed');
    flushSync();
    const hint = bar().querySelector('[data-area-hint]')!;
    expect(hint.textContent).toBe('tap to enlarge');
    const source = fs.readFileSync(path.join(process.cwd(), 'src', 'lib', 'dynamic-tabs', 'WidgetAreaBar.svelte'), 'utf8');
    const css = source.slice(source.indexOf('<style>')).replace(/\/\*[\s\S]*?\*\//g, '');
    expect(css).toMatch(/\.wab-hint\s*\{\s*display:\s*none;/);
    const phone = css.slice(css.indexOf('@media (max-width: 1023px)'));
    expect(phone).toMatch(/\.wab\[data-area-state='closed'\]\s*\{[^}]*min-height:\s*var\(--oc-tap, 44px\)/);
    expect(phone).toMatch(/\.wab-hint\s*\{[^}]*display:\s*inline/);
    expect(css).toMatch(/\.wab\s*\{[^}]*height:\s*10px/);
    bar().click();
    flushSync();
    expect(bar().querySelector('[data-area-hint]')).toBeNull();
  });

  test('a click outside closed changes nothing', () => {
    bar().click();
    flushSync();
    expect(widgetArea.stateFor('menu')).toBe('glance');
  });

  test('a drag up from closed snaps through glance to full, and back down to closed', () => {
    widgetArea.set('menu', 'closed');
    flushSync();
    areaHeight = 0;
    pointer('pointerdown', 500);
    pointer('pointermove', 500 - GLANCE_ROW_HEIGHT_PX);
    expect(widgetArea.stateFor('menu'), 'about one glance row up').toBe('glance');
    pointer('pointermove', 500 - 400);
    expect(widgetArea.stateFor('menu'), 'well past glance').toBe('full');
    pointer('pointermove', 500 - 5);
    expect(widgetArea.stateFor('menu'), 'back near zero').toBe('closed');
    pointer('pointerup', 495);
    bar().click();
    flushSync();
    expect(widgetArea.stateFor('menu'), 'the click ending a drag does not also open it').toBe('closed');
  });

  test('a drag down from full snaps to the nearest state using full\'s measured height', () => {
    widgetArea.set('menu', 'full');
    flushSync();
    areaHeight = 300;
    pointer('pointerdown', 100);
    pointer('pointermove', 100 + 100);
    expect(widgetArea.stateFor('menu'), '200 of 300 is still nearest full').toBe('full');
    pointer('pointermove', 100 + 200);
    expect(widgetArea.stateFor('menu'), '100 is nearest glance').toBe('glance');
    pointer('pointermove', 100 + 290);
    expect(widgetArea.stateFor('menu')).toBe('closed');
    pointer('pointerup', 390);
  });

  test('the keys step through the states and Enter opens and closes full', () => {
    const key = (k: string): void => {
      bar().dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
      flushSync();
    };
    key('ArrowUp');
    expect(widgetArea.stateFor('menu')).toBe('full');
    key('ArrowDown');
    key('ArrowDown');
    expect(widgetArea.stateFor('menu')).toBe('closed');
    key('Enter');
    expect(widgetArea.stateFor('menu')).toBe('full');
    key('Enter');
    expect(widgetArea.stateFor('menu')).toBe('closed');
  });

  test('FULL FOLLOWS ITS CONTENT: no height is ever written onto the area, and none is stored', () => {
    area.style.height = '420px';
    area.style.maxHeight = 'none';
    widgetArea.set('menu', 'full');
    flushSync();
    expect(area.style.height, 'an older inline height is cleared').toBe('');
    expect(area.style.maxHeight).toBe('');
    areaHeight = 300;
    pointer('pointerdown', 100);
    pointer('pointermove', 50);
    pointer('pointerup', 50);
    expect(area.style.height).toBe('');
    expect(Object.values(JSON.parse(localStorage.getItem(WIDGET_AREA_STORAGE_KEY) ?? '{}'))).toEqual(['full']);
  });

  test('per tab: another tab keeps its own state and default', () => {
    widgetArea.set('menu', 'closed');
    sidebarTabs.select('agents');
    flushSync();
    expect(area.dataset['areaState'], 'agents defaults to full').toBe('full');
    sidebarTabs.select('menu');
    flushSync();
    expect(area.dataset['areaState']).toBe('closed');
  });
});
