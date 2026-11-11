/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';
import type { GestureState, Source } from '../../../lib/motion-grid';
import type { LayoutStore } from '../layout.svelte';
import type { Layout, SlotId } from '../types';
import { DWELL_MS, createRowsAdapter } from './rows-adapter';

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const W = 1200;
const H = 800;

/** Two flex rows: A | B over C. */
function page(): Layout {
  const row = (id: 'r1' | 'r2', ids: SlotId[]): Layout['rows'][number] => ({ id, kind: 'flex', size: 0.5, slots: ids.map((slot) => ({ id: slot, fr: 1 / ids.length })) });
  return { v: 6, rows: [row('r1', [A, B]), row('r2', [C])], hidden: ['notes'], heroCollapsed: false, collapsed: [] };
}

function kit() {
  let clock = 0;
  const state = { layout: page() };
  const store = { page: 'terminal', state, snapshot: () => state.layout, commitLayout: vi.fn() } as unknown as LayoutStore;
  const container = document.createElement('div');
  document.body.appendChild(container);
  const adapter = createRowsAdapter({
    store, box: () => ({ width: W, height: H }), gutter: 9, wide: () => true, zoomed: () => null, container: () => container,
    now: () => clock, onState: () => {}, onCompass: () => {},
  });
  const base = adapter.rects();
  const at = (source: Source, x: number, y: number, dt: number): string => {
    clock += dt;
    const g: GestureState = { source, pointer: { x, y }, start: { x: 0, y: 0 }, delta: { x: 0, y: 0 }, grab: { x: 10, y: 10 }, startRect: null, base, bounds: { w: W, h: H }, outside: false };
    return adapter.targetKey(g);
  };
  return { adapter, at, base };
}

describe('gap arming', () => {
  test('a slow sweep through a seam never arms it, resting arms it after the dwell, a compass arm arms moving or not', () => {
    const k = kit();
    const move: Source = { kind: 'move', id: C };
    k.adapter.begin!(move, 'pointer');
    const a = k.base.get(A)!;
    const seamX = a.x + a.w + 4;
    let key = '';
    for (let i = 0; i <= 30; i++) key = k.at(move, seamX, a.y + 40 + i * 3, 25);
    expect(key.startsWith('seam:')).toBe(true);
    expect(key.endsWith('|a')).toBe(false);
    const y = a.y + 40 + 30 * 3;
    expect(k.at(move, seamX, y, DWELL_MS - 40).endsWith('|a')).toBe(false);
    expect(k.at(move, seamX, y, 60).endsWith('|a')).toBe(true);
    k.adapter.cancel();

    const drag: Source = { kind: 'move', id: A };
    k.adapter.begin!(drag, 'pointer');
    const c = k.base.get(C)!;
    const cx = c.x + c.w / 2 - 44;
    const cy = c.y + c.h / 2;
    let ckey = k.at(drag, cx - 8, cy, 0);
    expect(ckey.startsWith(`split:${C}:left`)).toBe(true);
    for (let i = 1; i <= 5; i++) ckey = k.at(drag, cx - 8 + i * 3, cy, 28);
    expect(ckey.endsWith('|a')).toBe(true);
  });
});
