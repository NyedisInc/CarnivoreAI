/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import Host from './AbsSurface.terminal.fixture.svelte';
import { dropHostById } from '../../../lib/motion-grid';
import * as pendingModule from './pending';
import { createLayoutStore } from '../layout.svelte';
import { viewport } from '../viewport.svelte';
import type { Layout, SlotId } from '../types';

vi.mock('./pending', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./pending')>();
  return { ...actual, pendingFor: vi.fn(actual.pendingFor) };
});

const listing = new SvelteMap<string, unknown>();
const storeState = new SvelteMap<string, number>([['tick', 0]]);
let built = 0;
let disposed = 0;

vi.mock('../../cells/terminal-live/client', () => ({
  startLiveTerminal: () => {
    storeState.get('tick');
    built += 1;
    return { client: { fake: true }, dispose(): void { disposed += 1; } };
  },
}));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      get data() { return listing.get('rows'); },
      get status() { return listing.get('status'); },
      refresh: vi.fn(),
      fetchedAt: 1,
      error: null,
      stop() {},
    },
  };
});

type Entry = { target: Element; contentRect: { width: number; height: number } };
const callbacks: ((entries: Entry[]) => void)[] = [];
const boxes = new Map<Element, { width: number; height: number }>();
class FakeObserver {
  constructor(cb: (entries: Entry[]) => void) { callbacks.push(cb); }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
const mounted: ReturnType<typeof mount>[] = [];
const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;

function page(): Layout {
  const row = (id: 'r1' | 'r2', ids: SlotId[]): Layout['rows'][number] => ({ id, kind: 'flex', size: 0.5, slots: ids.map((slot) => ({ id: slot, fr: 1 / ids.length })) });
  return { v: 6, rows: [row('r1', [A, B]), row('r2', [C])], hidden: [], heroCollapsed: false, collapsed: [] };
}

function fakeRow(id: string) {
  return { session: { id }, tmux_session: `carnivore_${id}`, label: id, pinned_theme: null, activity_status: 'idle', startup_gate: null, unread: false };
}

async function resize(el: Element, width: number, height: number): Promise<void> {
  boxes.set(el, { width, height });
  for (const cb of callbacks) cb([{ target: el, contentRect: { width, height } }]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  flushSync();
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', FakeObserver);
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => setTimeout(() => fn(0), 0));
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const box = boxes.get(this) ?? { width: 0, height: 0 };
    return { ...box, top: 0, left: 0, right: box.width, bottom: box.height, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  };
  viewport.wide = true;
  viewport.phone = false;
  listing.set('status', 'ok');
  listing.set('rows', ['ses_a', 'ses_b', 'ses_c'].map(fakeRow));
});
afterEach(async () => {
  for (const one of mounted.splice(0)) await unmount(one);
  document.body.replaceChildren();
  boxes.clear();
  callbacks.length = 0;
  built = 0;
  disposed = 0;
  vi.unstubAllGlobals();
});

test('a layout commit keeps every terminal pane element and builds no new client', async () => {
  const store = createLayoutStore('terminal');
  store.bindSession('carnivore_ea', 1758000000);
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(Host, { target: host, props: { store } }));
  flushSync();
  await resize(host.querySelector('.oc-surface')!, 1200, 800);
  for (const el of host.querySelectorAll('[data-abs-slot] .oc-frame-body')) await resize(el, 590, 390);
  await new Promise((resolve) => setTimeout(resolve, 50));
  flushSync();
  const panes = () => ['a', 'b', 'c'].map((id) => host.querySelector(`[data-abs-slot="terminal:ses_${id}"] .xterm-host`));
  const before = panes();
  expect(before.every(Boolean)).toBe(true);
  const builtBefore = built;

  expect(store.moveTo(A, { kind: 'row', row: 'r2', index: 0 })).toBe(true);
  flushSync();
  await new Promise((resolve) => setTimeout(resolve, 50));
  flushSync();

  panes().forEach((pane, i) => expect(pane).toBe(before[i]));
  expect(built).toBe(builtBefore);
  expect(disposed).toBe(0);
});

test('an arrow key on a focused title strip control reaches the core and steps the cell', async () => {
  const store = createLayoutStore('terminal');
  store.bindSession('carnivore_ea', 1758000000);
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(Host, { target: host, props: { store } }));
  flushSync();
  await resize(host.querySelector('.oc-surface')!, 1200, 800);
  const before = store.state.layout;
  const control = host.querySelector<HTMLElement>('[data-abs-slot="terminal:ses_a"] .oc-frame-strip button')!;
  control.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 50));
  flushSync();
  expect(store.state.layout).toBe(before);
  control.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 50));
  flushSync();
  expect(store.state.layout).not.toBe(before);
});

test('a reactive store changing under the client factory does not rebuild a terminal', async () => {
  const store = createLayoutStore('terminal');
  store.bindSession('carnivore_ea', 1758000000);
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(Host, { target: host, props: { store } }));
  flushSync();
  await resize(host.querySelector('.oc-surface')!, 1200, 800);
  for (const el of host.querySelectorAll('[data-abs-slot] .oc-frame-body')) await resize(el, 590, 390);
  await new Promise((resolve) => setTimeout(resolve, 50));
  flushSync();
  const builtBefore = built;
  expect(builtBefore).toBeGreaterThan(0);
  storeState.set('tick', 1);
  flushSync();
  expect(built).toBe(builtBefore);
  expect(disposed).toBe(0);
});

function pointer(type: string, x: number, y: number): PointerEvent {
  const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 });
  return Object.assign(ev, { pointerId: 1, pointerType: 'mouse', isPrimary: true }) as unknown as PointerEvent;
}

async function pageWithHost(): Promise<{ host: HTMLElement; store: ReturnType<typeof createLayoutStore> }> {
  const store = createLayoutStore('terminal');
  store.bindSession('carnivore_ea', 1758000000);
  store.state.layout = page();
  store.state.groups = { [A]: [A, 'terminal:row:9'] };
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(Host, { target: host, props: { store, dropId: 'terminal' } }));
  flushSync();
  await resize(host.querySelector('.oc-surface')!, 1200, 800);
  for (const el of host.querySelectorAll('[data-abs-slot] .oc-frame-body')) await resize(el, 590, 390);
  await new Promise((resolve) => setTimeout(resolve, 50));
  flushSync();
  return { host, store };
}

function escape(): void {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
}

test('the tab ghost is pre-mounted and registered with the core at mount, painted in flip mode', async () => {
  const { host } = await pageWithHost();
  const ghost = host.querySelector<HTMLElement>('.abs-ghost');
  expect(ghost).not.toBeNull();
  expect(ghost!.classList.contains('motion-item')).toBe(true);
  expect(ghost!.style.transformOrigin).toBe('0 0');
  expect(host.querySelector('[data-abs-slot="terminal:ses_a"]')!.getAttribute('style')).toContain('transform-origin');
});

test('a carried tab begins on the ghost without adding a wrapper and without a flush', async () => {
  const { host } = await pageWithHost();
  const slots = () => host.querySelectorAll('[data-abs-slot]').length;
  const before = slots();
  const taken = dropHostById('terminal')!.accept('tab:terminal:row:9', pointer('pointermove', 400, 300));
  expect(taken).toBe(true);
  expect(slots()).toBe(before);
  const ghost = host.querySelector<HTMLElement>('.abs-ghost')!;
  expect(ghost.classList.contains('motion-lifted')).toBe(true);
  expect(ghost.textContent).toBe('terminal:row:9');
  expect(document.body.classList.contains('grid-dragging')).toBe(true);
  escape();
});

test('a press that travels on the only tab of a window lifts the window', async () => {
  const { host } = await pageWithHost();
  const tab = host.querySelector<HTMLElement>('[data-abs-slot="terminal:ses_c"] [data-tab]')!;
  expect(tab.hasAttribute('data-motion-grab')).toBe(true);
  tab.dispatchEvent(pointer('pointerdown', 100, 700));
  window.dispatchEvent(pointer('pointermove', 140, 740));
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(host.querySelector('[data-abs-slot="terminal:ses_c"]')!.classList.contains('motion-lifted')).toBe(true);
  expect(host.querySelector('.abs-ghost')!.classList.contains('motion-lifted')).toBe(false);
  escape();
});

test('an asMove carry lifts the existing wrapper as a move and adds no wrapper', async () => {
  const { host, store } = await pageWithHost();
  const slots = () => host.querySelectorAll('[data-abs-slot]').length;
  const before = slots();
  vi.mocked(pendingModule.pendingFor).mockReturnValueOnce({ id: C, layout: store.state.layout, tab: C, asMove: true } as pendingModule.Pending);
  const taken = dropHostById('terminal')!.accept(`tab:${C}`, pointer('pointermove', 100, 700));
  expect(taken).toBe(true);
  expect(slots()).toBe(before);
  expect(host.querySelector('[data-abs-slot="terminal:ses_c"]')!.classList.contains('motion-lifted')).toBe(true);
  expect(host.querySelector('.abs-ghost')!.classList.contains('motion-lifted')).toBe(false);
  escape();
});
