/** @vitest-environment jsdom */
import { beforeEach, expect, test, vi } from 'vitest';
import type { GestureState } from '../../../lib/motion-grid';
import type { LayoutStore } from '../layout.svelte';
import type { Layout, SlotId } from '../types';

const commitTabDrop = vi.hoisted(() => vi.fn(() => true));
vi.mock('../tab-drag', async (orig) => ({ ...(await orig<typeof import('../tab-drag')>()), commitTabDrop }));
import { tabDrag } from '../tab-drag-state.svelte';
import { createRowsAdapter } from './rows-adapter';

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const X = 'terminal:ses_x' as SlotId;
const W = 1200;
const H = 800;

const row = (id: 'r1' | 'r2', ids: SlotId[]): Layout['rows'][number] => ({ id, kind: 'flex', size: 0.5, slots: ids.map((slot) => ({ id: slot, fr: 1 / ids.length })) });
const layoutOf = (...rows: Layout['rows']): Layout => ({ v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] });

function kit() {
  const live = layoutOf(row('r1', [A]), row('r2', [B]));
  const state = { layout: live };
  const store = { page: 'terminal', state, snapshot: () => state.layout, commitLayout: vi.fn() } as unknown as LayoutStore;
  const container = document.createElement('div');
  container.getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: H, width: W, height: H }) as DOMRect;
  container.innerHTML = `<div data-tab-group="${A}"><div class="oc-frame-strip"><button data-tab="${A}"></button></div></div>`;
  const strip = container.querySelector('[data-tab-group]') as HTMLElement;
  strip.getBoundingClientRect = () => ({ left: 0, right: 590, top: 0, bottom: 30, width: 590, height: 30 }) as DOMRect;
  document.body.appendChild(container);
  const adapter = createRowsAdapter({ store, box: () => ({ width: W, height: H }), gutter: 9, wide: () => true, zoomed: () => null, container: () => container, onState: () => {} });
  adapter.setPending({ id: X, layout: layoutOf(row('r1', [A]), row('r2', [B, X])), tab: X, ghost: { label: 'x', w: 220, h: 96 } });
  const g = (x: number, y: number): GestureState => ({
    source: { kind: 'external', id: X }, pointer: { x, y }, start: { x: 0, y: 0 }, delta: { x: 0, y: 0 }, grab: { x: 0, y: 0 },
    startRect: null, base: adapter.rects(), bounds: { w: W, h: H }, outside: false,
  });
  adapter.begin!({ kind: 'external', id: X }, 'external');
  return { adapter, g, live };
}

beforeEach(() => commitTabDrop.mockClear());

test('over a strip the preview moves nothing, marks the strip, and the release commits the strip drop once', () => {
  const { adapter, g, live } = kit();
  const key = adapter.targetKey(g(100, 10));
  expect(key).toBe(`strip:${A}:1`);
  const target = adapter.preview(g(100, 10), key);
  expect(tabDrag.target?.kind).toBe('strip');
  expect(target.rects.get(A)).toEqual(adapter.rects().get(A));
  expect(target.rects.get(B)).toEqual(adapter.rects().get(B));
  expect(target.landing).toBeNull();
  expect(target.mark).toBeUndefined();
  adapter.commit(target, g(100, 10));
  expect(commitTabDrop).toHaveBeenCalledExactlyOnceWith(X, { kind: 'strip', slot: A, index: 1 });
  expect(tabDrag.tab).toBeNull();
  void live;
});

test('over the page the preview is the split the drop would make, committed once', () => {
  const { adapter, g } = kit();
  const at = g(W / 2, H - 4);
  const key = adapter.targetKey(at);
  expect(key).toBe('band:bottom');
  const target = adapter.preview(at, key);
  expect(target.rects.has(X)).toBe(true);
  expect(target.landing).toEqual(target.rects.get(X));
  adapter.commit(target, at);
  expect(commitTabDrop).toHaveBeenCalledTimes(1);
});

test('cancel commits nothing and clears the marks', () => {
  const { adapter, g } = kit();
  adapter.preview(g(100, 10), adapter.targetKey(g(100, 10)));
  adapter.cancel();
  expect(commitTabDrop).not.toHaveBeenCalled();
  expect(tabDrag.target).toBeNull();
});

test('a carried tab is announced by the name its strip draws, not the slot id', () => {
  const { adapter } = kit();
  const btn = document.createElement('button');
  btn.dataset['tab'] = X;
  btn.innerHTML = '<span class="oc-tab-name"> build box </span>';
  document.body.appendChild(btn);
  expect(adapter.label!(X)).toBe('build box');
});
