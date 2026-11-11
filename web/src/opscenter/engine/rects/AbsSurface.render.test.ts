/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AbsSurfaceHost from './AbsSurface.fixture.svelte';
import { createLayoutStore } from '../layout.svelte';
import { viewport } from '../viewport.svelte';
import { dropHostById } from '../../../lib/motion-grid';
import type { Layout, SlotId } from '../types';

type Entry = { target: Element; contentRect: { width: number; height: number } };
const callbacks: ((entries: Entry[]) => void)[] = [];
const boxes = new Map<Element, { width: number; height: number }>();
const mounted: ReturnType<typeof mount>[] = [];

class FakeObserver {
  constructor(cb: (entries: Entry[]) => void) {
    callbacks.push(cb);
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;

function page(): Layout {
  const row = (id: 'r1' | 'r2', ids: SlotId[]): Layout['rows'][number] => ({
    id,
    kind: 'flex',
    size: 0.5,
    slots: ids.map((slot) => ({ id: slot, fr: 1 / ids.length })),
  });
  return { v: 6, rows: [row('r1', [A, B]), row('r2', [C])], hidden: [], heroCollapsed: false, collapsed: [] };
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
});
afterEach(async () => {
  for (const one of mounted.splice(0)) await unmount(one);
  document.body.replaceChildren();
  boxes.clear();
  callbacks.length = 0;
  vi.unstubAllGlobals();
});

test('a cell moved to another row is the same element, and every cell sits in the wrapper the core positions', async () => {
  const store = createLayoutStore('warroom');
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(AbsSurfaceHost, { target: host, props: { store, dropId: 'warroom' } }));
  flushSync();
  const surface = host.querySelector<HTMLElement>('.oc-surface')!;
  await resize(surface, 1200, 800);
  const wrap = (id: string): HTMLElement => host.querySelector<HTMLElement>(`[data-abs-slot="${id}"]`)!;
  const before = [A, B, C].map(wrap);
  expect(before.every(Boolean)).toBe(true);
  expect(before.every((el) => el.classList.contains('motion-item'))).toBe(true);
  expect(host.querySelectorAll('[data-abs-divider]').length).toBeGreaterThan(0);

  expect(store.moveTo(A, { kind: 'row', row: 'r2', index: 0 })).toBe(true);
  flushSync();
  expect(store.state.layout.rows[1]!.slots.map((slot) => slot.id)).toContain(A);
  expect([A, B, C].map(wrap)).toEqual(before);
});

test('the drawer drop host places a widget through the model reducers (take and add)', async () => {
  const store = createLayoutStore('warroom');
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(AbsSurfaceHost, { target: host, props: { store, dropId: 'warroom' } }));
  flushSync();
  await resize(host.querySelector('.oc-surface')!, 1200, 800);
  const drop = dropHostById('warroom')!;
  expect(drop).not.toBeNull();
  expect(drop.takes!('terminal')).toBe(false);
  expect(drop.takes!('notes')).toBe(true);
  expect(drop.add!('notes')).toBe(true);
  flushSync();
  expect(host.querySelector('[data-abs-slot="notes"]')).not.toBeNull();
});

test('a wrapper resize leaves the inner size alone until the core renders; the final size lands at rest', async () => {
  const store = createLayoutStore('warroom');
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(AbsSurfaceHost, { target: host, props: { store, dropId: 'warroom' } }));
  flushSync();
  const surface = host.querySelector<HTMLElement>('.oc-surface')!;
  await resize(surface, 1200, 800);
  await new Promise((resolve) => setTimeout(resolve, 50));
  const inner = host.querySelector<HTMLElement>(`[data-abs-slot="${C}"] > .abs-body`)!;
  expect(inner).not.toBeNull();
  const wrapper = inner.parentElement!;
  expect(inner.style.width).toBe(`${Math.round(parseFloat(wrapper.style.width))}px`);
  expect(inner.style.height).toBe(`${Math.round(parseFloat(wrapper.style.height))}px`);
  await resize(surface, 900, 600);
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(inner.style.width).toBe(`${Math.round(parseFloat(wrapper.style.width))}px`);
});

test('a spanning-style seam lights every piece with the same row and index, on hover and while pressed', async () => {
  const store = createLayoutStore('warroom');
  store.state.layout = page();
  const host = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(AbsSurfaceHost, { target: host, props: { store, dropId: 'warroom' } }));
  flushSync();
  await resize(host.querySelector('.oc-surface')!, 1200, 800);
  const col = host.querySelector<HTMLElement>('.oc-gutter-col')!;
  const twin = document.createElement('div');
  twin.className = 'oc-gutter-col';
  twin.dataset['row'] = col.dataset['row']!;
  twin.dataset['index'] = col.dataset['index']!;
  host.appendChild(twin);
  col.dispatchEvent(new Event('pointerenter'));
  expect([col, twin].map((el) => el.getAttribute('data-lit'))).toEqual(['hover', 'hover']);
  col.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect([col, twin].map((el) => el.getAttribute('data-lit'))).toEqual(['active', 'active']);
  col.dispatchEvent(new Event('pointerleave'));
  expect(col.getAttribute('data-lit')).toBe('active');
  window.dispatchEvent(new Event('pointerup'));
  expect([col, twin].map((el) => el.getAttribute('data-lit'))).toEqual([null, null]);
});
