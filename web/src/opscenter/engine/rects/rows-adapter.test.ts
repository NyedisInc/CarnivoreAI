/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';
import type { GestureState, Source } from '../../../lib/motion-grid';
import type { LayoutStore } from '../layout.svelte';
import type { Layout, SlotId } from '../types';
import { mountKeyboard } from '../../../lib/motion-grid/motion-test-kit';
import type { CompassView } from '../dock-compass';
import { createRowsAdapter } from './rows-adapter';

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const W = 1200;
const H = 800;

/** Two flex rows: A | B over C. */
function page(): Layout {
  const row = (id: 'r1' | 'r2', ids: SlotId[]): Layout['rows'][number] => ({
    id,
    kind: 'flex',
    size: 0.5,
    slots: ids.map((slot) => ({ id: slot, fr: 1 / ids.length })),
  });
  return { v: 6, rows: [row('r1', [A, B]), row('r2', [C])], hidden: ['notes'], heroCollapsed: false, collapsed: [] };
}

function fakeStore(layout: Layout) {
  const state = { layout };
  const commits: Layout[] = [];
  const store = {
    page: 'terminal',
    state,
    snapshot: () => state.layout,
    commitLayout: vi.fn((next: Layout) => {
      commits.push(next);
      state.layout = next;
    }),
  } as unknown as LayoutStore;
  return { store, commits, state };
}

function kit(merge?: Parameters<typeof createRowsAdapter>[0]['merge'], now?: () => number) {
  const fake = fakeStore(page());
  const states: { preview: Layout | null; moving: boolean }[] = [];
  const compasses: (CompassView | null)[] = [];
  const container = document.createElement('div');
  document.body.appendChild(container);
  const adapter = createRowsAdapter({
    store: fake.store,
    box: () => ({ width: W, height: H }),
    gutter: 9,
    wide: () => true,
    zoomed: () => null,
    container: () => container,
    merge,
    now,
    onState: (state) => states.push(state),
    onCompass: (view) => compasses.push(view),
  });
  const gesture = (source: Source, over: Partial<GestureState> = {}): GestureState => ({
    source,
    pointer: { x: 0, y: 0 },
    start: { x: 0, y: 0 },
    delta: { x: 0, y: 0 },
    grab: { x: 10, y: 10 },
    startRect: null,
    base: adapter.rects(),
    bounds: { w: W, h: H },
    outside: false,
    ...over,
  });
  return { ...fake, adapter, states, compasses, gesture, container };
}

describe('hit', () => {
  test('the title strip picks a widget up, a divider is a divider, a button or the body grabs nothing', () => {
    const { adapter } = kit();
    document.body.innerHTML = `<div data-abs-slot="${A}"><div class="oc-frame-strip"><span id="t">x</span><button id="b">y</button></div><div id="body"></div></div>
      <div data-abs-divider="col:r1:0"><div id="d"></div></div>`;
    const ev = {} as PointerEvent;
    expect(adapter.hit(document.getElementById('t')!, ev)).toEqual({ kind: 'move', id: A });
    expect(adapter.hit(document.getElementById('b')!, ev)).toBeNull();
    expect(adapter.hit(document.getElementById('body')!, ev)).toBeNull();
    expect(adapter.hit(document.getElementById('d')!, ev)).toEqual({ kind: 'divider', id: 'col:r1:0' });
  });
});

describe('a divider gesture', () => {
  test('is instant, follows the pointer pixel for pixel, stops at the floor, writes once and cancel writes nothing', () => {
    const k = kit();
    const source: Source = { kind: 'divider', id: 'col:r1:0' };
    const before = k.adapter.rects().get(A)!.w;
    k.adapter.begin!(source, 'pointer');
    const g = k.gesture(source, { delta: { x: 57, y: 0 } });
    const key = k.adapter.targetKey(g);
    const target = k.adapter.preview(g, key);
    expect(target.instant).toBe(true);
    expect(Math.abs(target.rects.get(A)!.w - before - 57)).toBeLessThanOrEqual(1);
    expect(k.states.at(-1)!.preview).not.toBeNull();
    expect(k.adapter.targetKey(k.gesture(source, { delta: { x: 57, y: 0 } }))).toBe(key);
    const far = k.adapter.preview(k.gesture(source, { delta: { x: -9999, y: 0 } }), 'far');
    expect(far.rects.get(A)!.w).toBeGreaterThanOrEqual(239);
    expect(k.commits).toHaveLength(0);
    k.adapter.commit(target, g);
    expect(k.commits).toHaveLength(1);
    expect(k.states.at(-1)).toEqual({ preview: null, moving: false });

    k.adapter.begin!(source, 'pointer');
    k.adapter.preview(k.gesture(source, { delta: { x: 40, y: 0 } }), 'x');
    k.adapter.cancel();
    expect(k.commits).toHaveLength(1);
  });
});

describe('a window merged into another', () => {
  test('boxes and arms the survivor at the size it lands at, in the space the dragged window leaves', () => {
    let clock = 0;
    const k = kit(() => ({}) as never, () => clock);
    const source: Source = { kind: 'move', id: C };
    k.container.innerHTML = `<div data-tab-group="${A}"><div class="oc-frame-strip"><button data-tab="${A}"></button></div></div>`;
    (k.container.querySelector('[data-tab-group]') as HTMLElement).getBoundingClientRect = () => ({ left: 0, right: 590, top: 0, bottom: 30, width: 590, height: 30 }) as DOMRect;
    k.adapter.begin!(source, 'pointer');
    const start = k.adapter.rects().get(A)!;
    const g = k.gesture(source, { pointer: { x: start.w / 2, y: start.h / 2 } });
    const key = k.adapter.targetKey(g);
    expect(key.startsWith(`mid:${A}`)).toBe(true);
    const idle = k.adapter.preview(g, key);
    expect(idle.landing!.h).toBeGreaterThan(start.h + 100);
    expect(idle.rects.get(A)).toEqual(start);
    clock += 200;
    const armedKey = k.adapter.targetKey(g);
    expect(armedKey).toBe(`${key}|a`);
    const armed = k.adapter.preview(g, armedKey);
    expect(armed.rects.get(A)).toEqual(idle.landing);
    expect(armed.rects.get(C)).toEqual(idle.landing);
    expect(k.commits).toHaveLength(0);
  });
});

describe('a move gesture', () => {
  test('previews the drop in another row and commits it once; the dragged id keeps one rect', () => {
    const k = kit();
    const source: Source = { kind: 'move', id: A };
    k.adapter.begin!(source, 'pointer');
    const c = k.adapter.rects().get(C)!;
    const g = k.gesture(source, { pointer: { x: c.x + c.w / 2 - 44, y: c.y + c.h / 2 } });
    const key = k.adapter.targetKey(g);
    expect(key.startsWith(`split:${C}:left`)).toBe(true);
    const target = k.adapter.preview(g, key);
    expect(target.instant).toBeFalsy();
    const rects = target.rects;
    expect([...rects.keys()].sort()).toEqual([A, B, C].sort());
    expect(rects.get(A)!.y).toBe(rects.get(C)!.y);
    expect(target.landing).toEqual(rects.get(A));
    expect(k.commits).toHaveLength(0);
    k.adapter.commit(target, g);
    expect(k.commits).toHaveLength(1);
    expect(k.commits[0]!.rows.find((row) => row.id === 'r2')!.slots.map((slot) => slot.id)).toContain(A);
  });

  test('the dock compass is drawn over the window under the pointer, lights the aimed icon, says nothing on an unchanged frame and clears at the end', () => {
    const k = kit();
    const source: Source = { kind: 'move', id: A };
    k.adapter.begin!(source, 'pointer');
    const c = k.adapter.rects().get(C)!;
    const cx = c.x + c.w / 2;
    const cy = c.y + c.h / 2;
    k.adapter.targetKey(k.gesture(source, { pointer: { x: cx + 22, y: cy + 22 } }));
    expect(k.compasses).toHaveLength(1);
    expect(k.compasses[0]!.window).toBe(C);
    expect(k.compasses[0]!.icons.map((i) => i.dir)).toEqual(['centre', 'up', 'down', 'left', 'right']);
    expect(k.compasses[0]!.icons.some((i) => i.hot)).toBe(false);
    expect(k.compasses[0]!.icons.map((i) => i.enabled)).toEqual([false, true, true, true, true]);
    k.adapter.targetKey(k.gesture(source, { pointer: { x: cx + 23, y: cy + 21 } }));
    expect(k.compasses).toHaveLength(1);
    const key = k.adapter.targetKey(k.gesture(source, { pointer: { x: cx + 44, y: cy } }));
    expect(key.startsWith(`split:${C}:right`)).toBe(true);
    expect(k.compasses).toHaveLength(2);
    expect(k.compasses[1]!.icons.filter((i) => i.hot).map((i) => i.dir)).toEqual(['right']);
    k.adapter.cancel();
    expect(k.compasses.at(-1)).toBeNull();
  });

  test('a pointer far outside cancels instead of dropping and writes nothing', () => {
    const k = kit();
    const source: Source = { kind: 'move', id: A };
    k.adapter.begin!(source, 'pointer');
    const out = k.gesture(source, { outside: true });
    const key = k.adapter.targetKey(out);
    expect(key).toBe('out');
    expect(k.adapter.preview(out, key).valid).toBe(false);
    k.adapter.cancel();
    expect(k.commits).toHaveLength(0);
  });
});

describe('the keyboard', () => {
  test('arrows move one step, shift plus arrows resize, and an impossible step is null', () => {
    const k = kit();
    const down = k.adapter.step!(A, { dir: 'down', resize: false })!;
    expect(down).not.toBeNull();
    k.adapter.commit(down, null);
    expect(k.commits).toHaveLength(1);
    const wider = k.adapter.step!(B, { dir: 'left', resize: true });
    expect(wider === null || wider.rects.get(B)!.w > 0).toBe(true);
    expect(k.adapter.step!(C, { dir: 'right', resize: false })).toBeNull();
  });
});

describe('a keyboard session previews, then commits once', () => {
  test('Escape after three divider steps writes nothing; Enter writes once with the three-step layout', () => {
    const k = kit();
    const keys = mountKeyboard(k.adapter, [A, B, C]);
    for (let i = 0; i < 3; i++) keys.key(A, 'ArrowRight', { shiftKey: true });
    keys.key(A, 'Escape');
    expect(k.commits).toHaveLength(0);
    for (let i = 0; i < 3; i++) keys.key(A, 'ArrowRight', { shiftKey: true });
    keys.key(A, 'Enter');
    expect(k.commits).toHaveLength(1);
    const once = k.commits[0]!;
    const fr = (l: Layout): number => l.rows[0]!.slots[0]!.fr;
    expect(fr(once)).toBeGreaterThan(fr(page()));
    const one = kit();
    const single = mountKeyboard(one.adapter, [A, B, C]);
    single.key(A, 'ArrowRight', { shiftKey: true });
    single.key(A, 'Enter');
    expect(fr(once)).toBeGreaterThan(fr(one.commits[0]!));
  });
});

describe('rects', () => {
  test('a zoomed slot takes the whole box', () => {
    const fake = fakeStore(page());
    const adapter = createRowsAdapter({
      store: fake.store, box: () => ({ width: W, height: H }), gutter: 9, wide: () => true, zoomed: () => B, container: () => null, onState: () => {},
    });
    expect(adapter.rects().get(B)).toEqual({ x: 0, y: 0, w: W, h: H });
    expect(adapter.hit(document.body, {} as PointerEvent)).toBeNull();
  });
});
