/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, ledger: { status: 'ok', data: null, fetchedAt: null, error: null }, primarySessionId: () => '' };
});
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  const { default: HeadBarProbe } = await import('../../opscenter/shell/fixtures/HeadBarProbe.svelte');
  return { ...real, entryFor: () => ({ component: HeadBarProbe }) };
});

import DrawerZone from './DrawerZone.svelte';
import { drawerZone } from './zone-store.svelte';
import { ZONE_FIELD } from './zone-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { configureSheet } from '../../opscenter/widgets/chrome/configure.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
installPopoverPolyfill();

let host: HTMLElement | null = null;
let instance: unknown = null;
let written: { items: { widget: string; options?: Record<string, unknown> }[] }[] = [];

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  written = [];
  layoutEditor.active = false;
  configureSheet.slot = null;
  const stored = { v: 1, items: [{ widget: 'core.activity-log' }, { widget: 'core.notes', options: { show_header: false } }] };
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => stored,
    write: async (field: string, value: unknown) => {
      expect(field).toBe(ZONE_FIELD);
      written.push(value as never);
      return { status: 'committed' };
    },
    follow: () => () => {},
  };
  drawerZone.reload();
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(DrawerZone, { target: host });
  flushSync();
});

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  document.body.replaceChildren();
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

const card = (widget: string): HTMLElement => host!.querySelector<HTMLElement>(`[data-zone-cell="${widget}"]`)!;

function partsOf(head: Element): string[] {
  const named: [string, string][] = [
    ['[data-corner]', 'icon'],
    ['.oc-frame-name', 'name'],
    ['[data-probe-bar]', 'bar'],
    ['.oc-head-sep', 'sep'],
    ['[data-zone-settings]', 'gear'],
    ['[data-zone-popout]', 'pop out'],
    ['[data-head-close]', 'close'],
  ];
  return [...head.querySelectorAll(named.map(([sel]) => sel).join(','))].map((el) => named.find(([sel]) => el.matches(sel))![1]);
}

function menuItem(widget: string, action: string): HTMLElement {
  const icon = card(widget).querySelector<HTMLButtonElement>('[data-corner]');
  if (icon) icon.click();
  else card(widget).querySelector<HTMLElement>('.dzc-body')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 8, clientY: 8 }));
  flushSync();
  const item = document.querySelector<HTMLElement>(`.acm-menu [data-node="${action}"]`);
  if (!item) throw new Error(`no ${action} item`);
  return item;
}

describe('a drawer card wears the widget header', () => {
  test('icon, name, the cell bar, then the close x: no gear and no pop out key on the row, one hairline before the x', () => {
    const head = card('core.activity-log').querySelector('[data-widget-head]')!;
    expect(head).not.toBeNull();
    expect(partsOf(head)).toEqual(['icon', 'name', 'bar', 'sep', 'close']);
    expect(head.querySelector('.oc-frame-name')?.textContent).toBe('activity log');
    expect(card('core.activity-log').querySelector('.dzc-body [data-probe-bar]')).toBeNull();
    expect(card('core.activity-log').querySelector('[data-probe-name]')).toBeNull();
  });

  test('the close x takes the card out of the area at once and writes it', () => {
    card('core.activity-log').querySelector<HTMLButtonElement>('[data-head-close]')!.click();
    flushSync();
    expect(drawerZone.items.map((item) => item.widget)).toEqual(['core.notes']);
    expect(written.at(-1)!.items.map((item) => item.widget)).toEqual(['core.notes']);
  });

  test('the icon opens the shared menu; the tick takes the row off this copy alone and the same menu puts it back', () => {
    const tick = menuItem('core.activity-log', 'show-header');
    expect(tick.getAttribute('aria-checked')).toBe('true');
    expect(document.querySelector('.acm-menu [data-node="close-widget"]')).not.toBeNull();
    expect(document.querySelector('.acm-menu [data-node="pop-out"]')).not.toBeNull();
    tick.click();
    flushSync();
    expect(drawerZone.items[0]!.options).toEqual({ show_header: false });
    expect(written.at(-1)!.items[0]).toMatchObject({ widget: 'core.activity-log', options: { show_header: false } });
    expect(card('core.activity-log').querySelector('[data-widget-head]')).toBeNull();
    expect(card('core.activity-log').querySelector('[data-probe-bar]')).toBeNull();
    expect(card('core.activity-log').querySelector('[data-corner], .oc-frame-corner, [data-widget-head]')).toBeNull();
    expect(card('core.activity-log').firstElementChild?.classList.contains('dzc-body')).toBe(true);
    expect(card('core.activity-log').querySelector('[data-probe-name]'), 'no name text where the header was').toBeNull();
    const back = menuItem('core.activity-log', 'show-header');
    expect(back.getAttribute('aria-checked')).toBe('false');
    back.click();
    flushSync();
    expect(drawerZone.items[0]!.options).toEqual({ show_header: true });
    expect(card('core.activity-log').querySelector('[data-widget-head]')).not.toBeNull();
  });

  test('a copy stored with its header off draws no row and no bar anywhere, and offers the tick', () => {
    expect(card('core.notes').querySelector('[data-widget-head]')).toBeNull();
    expect(card('core.notes').querySelector('[data-probe-bar]')).toBeNull();
    expect(menuItem('core.notes', 'show-header').getAttribute('aria-checked')).toBe('false');
  });
});

describe('a drawer card with its header off opens the widget menu by right-click and Shift+F10', () => {
  const body = (): HTMLElement => card('core.notes').querySelector<HTMLElement>('.dzc-body')!;

  test('the body starts at the top of the card, with its normal inset, and is focusable', () => {
    expect(card('core.notes').firstElementChild).toBe(body());
    expect(body().hasAttribute('data-headless')).toBe(true);
    expect(body().getAttribute('tabindex')).toBe('0');
    expect(card('core.activity-log').querySelector<HTMLElement>('.dzc-body')!.hasAttribute('tabindex')).toBe(false);
  });

  test('a right-click anywhere on the card opens the menu, a field keeps the browser menu', () => {
    const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 });
    body().dispatchEvent(ev);
    flushSync();
    expect(ev.defaultPrevented).toBe(true);
    expect(document.querySelector('.acm-menu [data-node="show-header"]')).not.toBeNull();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    flushSync();
    const field = document.createElement('input');
    body().appendChild(field);
    const fieldEv = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    field.dispatchEvent(fieldEv);
    flushSync();
    expect(fieldEv.defaultPrevented).toBe(false);
    expect(document.querySelector('.acm-menu')).toBeNull();
  });

  test('Shift+F10 on the body, or on anything focused inside it, opens the same menu; a plain F10 does not', () => {
    const inner = document.createElement('button');
    body().appendChild(inner);
    inner.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', bubbles: true, cancelable: true }));
    flushSync();
    expect(document.querySelector('.acm-menu')).toBeNull();
    const ev = new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true });
    inner.dispatchEvent(ev);
    flushSync();
    expect(ev.defaultPrevented).toBe(true);
    expect(document.querySelector('.acm-menu [data-node="show-header"]')?.getAttribute('aria-checked')).toBe('false');
  });
});

describe('a right-click anywhere on the title row opens the icon menu (item 685, Q6 a); the body keeps the browser menu', () => {
  test('the name opens it; a second right-click while it is open leaves it open; the body does not open it', () => {
    const head = card('core.activity-log').querySelector<HTMLElement>('[data-widget-head]')!;
    const name = head.querySelector<HTMLElement>('.oc-frame-name')!;
    const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    name.dispatchEvent(ev);
    flushSync();
    expect(ev.defaultPrevented).toBe(true);
    expect(document.querySelector('.acm-menu')).not.toBeNull();
    name.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
    flushSync();
    expect(document.querySelectorAll('.acm-menu')).toHaveLength(1);
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    flushSync();
    expect(document.querySelector('.acm-menu')).toBeNull();
    const body = card('core.activity-log').querySelector<HTMLElement>('.dzc-body')!;
    const bodyEv = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    body.dispatchEvent(bodyEv);
    flushSync();
    expect(bodyEv.defaultPrevented).toBe(false);
    expect(document.querySelector('.acm-menu')).toBeNull();
  });

  test('edit layout adds settings... to the same menu; normal mode lists none', () => {
    menuItem('core.activity-log', 'close-widget');
    expect(document.querySelector('.acm-menu [data-node="settings"]')).toBeNull();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    flushSync();
    layoutEditor.active = true;
    flushSync();
    menuItem('core.activity-log', 'settings');
    expect(document.querySelector('.acm-menu [data-node="settings"]')).not.toBeNull();
  });
});
