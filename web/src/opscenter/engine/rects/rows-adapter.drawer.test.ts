/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import type { GestureState } from '../../../lib/motion-grid';
import type { CompassView } from '../dock-compass';
import type { LayoutStore } from '../layout.svelte';
import type { Layout, SlotId } from '../types';
import { createRowsAdapter } from './rows-adapter';

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const X = 'crosstalk' as SlotId;
const W = 1200;
const H = 800;

const row = (id: 'r1' | 'r2', ids: SlotId[]): Layout['rows'][number] => ({ id, kind: 'flex', size: 0.5, slots: ids.map((slot) => ({ id: slot, fr: 1 / ids.length })) });
const layoutOf = (...rows: Layout['rows']): Layout => ({ v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] });

test('the compass of the window the widget defaults beside enables every side, and the start rects are the live ones', () => {
  const live = layoutOf(row('r1', [A]), row('r2', [B]));
  const state = { layout: live };
  const store = { page: 'terminal', state, snapshot: () => state.layout, commitLayout: vi.fn() } as unknown as LayoutStore;
  const container = document.createElement('div');
  container.getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: H, width: W, height: H }) as DOMRect;
  document.body.appendChild(container);
  const views: (CompassView | null)[] = [];
  const adapter = createRowsAdapter({ store, box: () => ({ width: W, height: H }), gutter: 9, wide: () => true, zoomed: () => null, container: () => container, onState: () => {}, onCompass: (v) => views.push(v) });
  const liveB = adapter.rects().get(B)!;
  adapter.setPending({ id: X, layout: layoutOf(row('r1', [A]), row('r2', [B, X])) });
  adapter.begin!({ kind: 'external', id: X }, 'external');
  const g: GestureState = {
    source: { kind: 'external', id: X }, pointer: { x: liveB.x + liveB.w / 2, y: liveB.y + liveB.h / 2 }, start: { x: 0, y: 0 }, delta: { x: 0, y: 0 }, grab: { x: 0, y: 0 },
    startRect: null, base: adapter.rects(), bounds: { w: W, h: H }, outside: false,
  };
  adapter.targetKey(g);
  const view = views.at(-1)!;
  expect(view.window).toBe(B);
  const on = (d: string) => view.icons.find((i) => i.dir === d)!.enabled;
  expect([on('up'), on('down'), on('left'), on('right')]).toEqual([true, true, true, true]);
  expect(Math.abs(view.plate.x + view.plate.w / 2 - (liveB.x + liveB.w / 2))).toBeLessThan(2);
});

test('from an unsound start (a row of narrow windows) the compass refuses a cut that leaves the target under the floor and keeps the others (#2935)', () => {
  const T = 'terminal:ses_t' as SlotId;
  const narrow = ['a', 'b', 'c', 'd', 'e', 'f'].map((n) => `terminal:ses_${n}` as SlotId);
  const mk = (ids: SlotId[]): Layout => layoutOf({ ...row('r1', [T]), size: 0.25 }, { ...row('r2', ids), size: 0.75 });
  const state = { layout: mk(narrow) };
  const store = { page: 'terminal', state, snapshot: () => state.layout, commitLayout: vi.fn() } as unknown as LayoutStore;
  const container = document.createElement('div');
  container.getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: H, width: W, height: H }) as DOMRect;
  document.body.appendChild(container);
  const views: (CompassView | null)[] = [];
  const adapter = createRowsAdapter({ store, box: () => ({ width: W, height: H }), gutter: 9, wide: () => true, zoomed: () => null, container: () => container, onState: () => {}, onCompass: (v) => views.push(v) });
  const liveT = adapter.rects().get(T)!;
  expect(liveT.h).toBeLessThan(230);
  adapter.setPending({ id: X, layout: mk([...narrow, X]) });
  adapter.begin!({ kind: 'external', id: X }, 'external');
  const g: GestureState = {
    source: { kind: 'external', id: X }, pointer: { x: liveT.x + liveT.w / 2, y: liveT.y + liveT.h / 2 }, start: { x: 0, y: 0 }, delta: { x: 0, y: 0 }, grab: { x: 0, y: 0 },
    startRect: null, base: adapter.rects(), bounds: { w: W, h: H }, outside: false,
  };
  adapter.targetKey(g);
  const view = views.at(-1)!;
  expect(view.window).toBe(T);
  const on = (d: string) => view.icons.find((i) => i.dir === d)!.enabled;
  expect([on('up'), on('down'), on('left'), on('right')]).toEqual([false, false, true, true]);
});
