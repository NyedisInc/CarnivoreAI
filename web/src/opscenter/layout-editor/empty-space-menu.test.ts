/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { homeLayout } from '../engine/layout.svelte';
import { editorSeams, layoutEditor, finishLayoutEditor } from './editor.svelte';
import { emptyMenu, onContextMenu, onMenuKey, onRailContextMenu, onZoneContextMenu } from './empty-space-menu.svelte';
import EmptySpaceMenu from './EmptySpaceMenu.svelte';

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};
const real = { ...editorSeams };
let host: HTMLElement;
let comp: ReturnType<typeof mount>;

beforeEach(() => {
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  homeLayout.resetAll();
  host = document.createElement('main');
  host.tabIndex = 0;
  host.innerHTML = '<div class="oc-cellslot" data-slot="a"><button id="inw">w</button></div><div id="gap"></div>';
  host.addEventListener('contextmenu', onContextMenu);
  host.addEventListener('keydown', (e) => onMenuKey(e, host));
  document.body.append(host);
  comp = mount(EmptySpaceMenu, { target: document.body });
});

afterEach(async () => {
  if (layoutEditor.active) finishLayoutEditor();
  emptyMenu.at = null;
  await unmount(comp);
  document.body.replaceChildren();
  Object.assign(editorSeams, real);
});

const fire = (el: Element): MouseEvent => {
  const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 50 });
  el.dispatchEvent(ev);
  flushSync();
  return ev;
};
const item = (): HTMLElement | null => document.querySelector('[role="menuitem"]');

test('empty space opens the menu and its item enters edit layout', () => {
  const ev = fire(host.querySelector('#gap')!);
  expect(ev.defaultPrevented).toBe(true);
  expect(item()?.textContent).toContain('edit layout');
  item()!.click();
  flushSync();
  expect(layoutEditor.active).toBe(true);
  expect(item()).toBeNull();
});

test('while editing the item says done editing and finishes the edit', () => {
  fire(host.querySelector('#gap')!);
  item()!.click();
  flushSync();
  fire(host);
  expect(item()?.textContent).toContain('done editing');
  item()!.click();
  flushSync();
  expect(layoutEditor.active).toBe(false);
});

test('a contextmenu on a widget opens nothing', () => {
  const ev = fire(host.querySelector('#inw')!);
  expect(ev.defaultPrevented).toBe(false);
  expect(item()).toBeNull();
});

test('Shift+F10 on the focused surface opens the same menu', () => {
  host.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
  flushSync();
  expect(item()?.textContent).toContain('edit layout');
});

test('no menu when edit layout is unavailable (narrow window)', () => {
  editorSeams.wide = () => false;
  fire(host.querySelector('#gap')!);
  expect(item()).toBeNull();
});

test('a widget bar opens its OWN menu (size, pin bar, edit layout) on its space, handle and edge; a key and an open widget keep their own right click', () => {
  const rail = document.createElement('nav');
  rail.innerHTML = '<div class="rail__handle"><button id="h">h</button></div><div class="rail__keys" id="free"><button class="rail__key" id="k">k</button></div>'
    + '<section data-rail-slideout="stats"><div id="w">widget</div></section>';
  rail.addEventListener('contextmenu', (event) => onRailContextMenu(event, 'side'));
  document.body.append(rail);
  for (const id of ['#k', '#w']) {
    expect(fire(rail.querySelector(id)!).defaultPrevented).toBe(false);
    expect(emptyMenu.at).toBeNull();
  }
  expect(fire(rail.querySelector('#h')!).defaultPrevented).toBe(true);
  expect(emptyMenu.target).toBe('side');
  emptyMenu.at = null;
  flushSync();
  const ev = fire(rail.querySelector('#free')!);
  expect(ev.defaultPrevented).toBe(true);
  const nodes = [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset.node);
  expect(nodes).toEqual(['bar-size-compact', 'bar-size-cozy', 'bar-size-detailed', 'pin-bar', 'edit-layout']);
  expect(document.querySelectorAll('[role="menuitemradio"]')).toHaveLength(3);
  document.querySelector<HTMLElement>('[data-node="edit-layout"]')!.click();
  flushSync();
  expect(layoutEditor.active).toBe(true);
});

test('the left widget area opens closed, glance, full and edit layout on its empty space', () => {
  const zone = document.createElement('div');
  zone.innerHTML = '<div id="free"></div><div data-zone-item="x"><span id="onw">w</span></div>';
  zone.addEventListener('contextmenu', onZoneContextMenu);
  document.body.append(zone);
  expect(fire(zone.querySelector('#onw')!).defaultPrevented).toBe(false);
  expect(fire(zone.querySelector('#free')!).defaultPrevented).toBe(true);
  expect([...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset.node)).toEqual(['area-closed', 'area-glance', 'area-full', 'edit-layout']);
});

test('a second right click elsewhere re-draws the menu there and leaves it open (the keyed re-open and the one-menu handle do not close each other)', () => {
  fire(host.querySelector('#gap')!);
  expect(document.querySelectorAll('.acm-menu')).toHaveLength(1);
  const again = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 200, clientY: 90 });
  host.querySelector('#gap')!.dispatchEvent(again);
  flushSync();
  expect(emptyMenu.at).toEqual({ x: 200, y: 90 });
  expect(document.querySelectorAll('.acm-menu')).toHaveLength(1);
});

test('a browser click sequence on the item toggles the editor with a second, terminal-surface instance mounted', () => {
  const screen = document.createElement('div');
  screen.id = 'terminal-screen';
  document.body.append(screen);
  const second = mount(EmptySpaceMenu, { target: screen, props: { surface: 'terminal' } });
  try {
    fire(host.querySelector('#gap')!);
    expect(document.querySelectorAll('[role="menuitem"]')).toHaveLength(1);
    const el = item()!;
    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    flushSync();
    expect(item()).not.toBeNull();
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
    flushSync();
    expect(layoutEditor.active).toBe(true);
  } finally {
    void unmount(second);
  }
});

test('a right click inside the terminal screen is drawn by the terminal instance, with a real-size marker', () => {
  const screen = document.createElement('div');
  screen.id = 'terminal-screen';
  screen.innerHTML = '<div id="railgap"></div>';
  document.body.append(screen);
  const second = mount(EmptySpaceMenu, { target: screen, props: { surface: 'terminal' } });
  const sized = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(40, 50, 8, 8));
  try {
    screen.querySelector('#railgap')!.addEventListener('contextmenu', (event) => onRailContextMenu(event as MouseEvent, 'side'));
    fire(screen.querySelector('#railgap')!);
    expect(emptyMenu.surface).toBe('terminal');
    expect(screen.querySelectorAll('[role="menuitem"]')).toHaveLength(2);
    expect(document.querySelectorAll('[role="menuitem"]')).toHaveLength(2);
  } finally {
    sized.mockRestore();
    void unmount(second);
  }
});

test('edit layout and done editing show and accept the same hotkey', () => {
  const keyOf = (): string | undefined => item()?.dataset.menuKey;
  fire(host.querySelector('#gap')!);
  const edit = keyOf();
  expect(edit).toBe('e');
  item()!.click();
  flushSync();
  fire(host.querySelector('#gap')!);
  expect(item()?.textContent).toContain('done editing');
  expect(keyOf()).toBe(edit);
  item()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', bubbles: true, cancelable: true }));
  flushSync();
  expect(layoutEditor.active).toBe(false);
});

test('a right click on a divider that stops its pointerdown (a row gap intersection) still closes and reopens the menu there', () => {
  const square = document.createElement('div');
  square.className = 'oc-intersection';
  square.addEventListener('pointerdown', (e) => e.stopPropagation());
  host.append(square);
  fire(host.querySelector('#gap')!);
  expect(item()).not.toBeNull();
  square.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, button: 2 }));
  flushSync();
  expect(emptyMenu.at).toBeNull();
  const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 470, clientY: 153 });
  square.dispatchEvent(ev);
  flushSync();
  expect(emptyMenu.at).toEqual({ x: 470, y: 153 });
  expect(document.querySelectorAll('[role="menuitem"]')).toHaveLength(1);
  expect(document.querySelectorAll('.oc-empty-menu-anchor')).toHaveLength(1);
});

test('the left drawer zone opens the menu on its empty space, drawn by the showing screen, and a real click sequence toggles edit', () => {
  const screen = document.createElement('div');
  screen.id = 'terminal-screen';
  screen.className = 'screen active';
  const zone = document.createElement('div');
  zone.innerHTML = '<div id="zfree"></div><div data-zone-item="x"><span id="zw">widget</span></div><button id="zb">b</button>';
  zone.addEventListener('contextmenu', onZoneContextMenu);
  document.body.append(screen, zone);
  const second = mount(EmptySpaceMenu, { target: screen, props: { surface: 'terminal' } });
  try {
    for (const id of ['#zw', '#zb']) {
      expect(fire(zone.querySelector(id)!).defaultPrevented).toBe(false);
      expect(emptyMenu.at).toBeNull();
    }
    expect(fire(zone.querySelector('#zfree')!).defaultPrevented).toBe(true);
    expect(emptyMenu.surface).toBe('terminal');
    expect(document.querySelectorAll('[role="menuitem"]')).toHaveLength(1);
    expect(screen.querySelectorAll('[role="menuitem"]')).toHaveLength(1);
    const el = item()!;
    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, button: 0 }));
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
    flushSync();
    expect(item()).not.toBeNull();
    el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, button: 0 }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail: 1, button: 0 }));
    flushSync();
    expect(layoutEditor.active).toBe(true);
  } finally {
    void unmount(second);
  }
});

test('with the terminal screen not showing, the drawer zone belongs to the home surface', () => {
  const screen = document.createElement('div');
  screen.id = 'terminal-screen';
  const zone = document.createElement('div');
  zone.innerHTML = '<div id="zfree"></div>';
  zone.addEventListener('contextmenu', onZoneContextMenu);
  document.body.append(screen, zone);
  fire(zone.querySelector('#zfree')!);
  expect(emptyMenu.surface).toBe('home');
  expect(item()?.textContent).toContain('edit layout');
});
