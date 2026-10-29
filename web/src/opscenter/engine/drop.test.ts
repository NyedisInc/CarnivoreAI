import { describe, expect, test } from 'vitest';

import { applyDrop, columnDropAt } from './drop';
import type { DropTarget } from './layout.svelte';
import { META } from './meta';
import { stackCell } from './stack';
import { repairSpans, visualOrder } from './spans';
import { computeTracks } from './tracks';
import type { Layout, SlotId } from './types';

const S = 'terminal:@primary' as SlotId;
const R = 'terminal:ses_rename' as SlotId;
const U = 'terminal:ses_ui' as SlotId;
const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;

const W = 1200;
const H = 800;

/** A page of flex rows holding the given cells, evenly shared. */
function page(...rows: SlotId[][]): Layout {
  return {
    v: 6,
    rows: rows.map((ids, at) => ({
      id: `r${at + 1}` as `r${number}`,
      kind: 'flex' as const,
      size: 1 / rows.length,
      slots: ids.map((id) => ({ id, fr: 1 / ids.length })),
    })),
    hidden: ['notes'],
    heroCollapsed: false,
    collapsed: [],
  };
}

function screenshot(): Layout {
  return stackCell(page([S, R, U]), U, R, 'below');
}

function boxes(layout: Layout): Map<SlotId, { x: number; width: number; top: number; height: number }> {
  const tracks = computeTracks({ rows: layout.rows, width: W, height: H, gutter: 12, metas: META });
  const out = new Map<SlotId, { x: number; width: number; top: number; height: number }>();
  for (const row of tracks.rows) {
    for (const cell of row.cells) {
      if (!cell.slotId) continue;
      const height = cell.span >= 2 ? (tracks.spanHeight.get(cell.slotId) ?? row.height) : row.height;
      out.set(cell.slotId, { x: cell.x, width: cell.width, top: row.top, height });
    }
  }
  return out;
}

function visible(box: { x: number; width: number } | undefined): boolean {
  return !!box && box.width > 0 && box.x + box.width <= W;
}

function targets(layout: Layout, dragged: SlotId): DropTarget[] {
  const out: DropTarget[] = [];
  for (const row of layout.rows) {
    for (let index = 0; index <= visualOrder(row).length; index += 1) {
      out.push(columnDropAt(layout, row.id, index, dragged) ?? { kind: 'row', row: row.id, index });
    }
  }
  out.push({ kind: 'new', after: null });
  for (const row of layout.rows) out.push({ kind: 'new', after: row.id });
  for (const row of layout.rows) {
    for (const slot of row.slots) {
      if (slot.id === dragged) continue;
      out.push({ kind: 'stack', of: slot.id, edge: 'above' });
      out.push({ kind: 'stack', of: slot.id, edge: 'below' });
    }
  }
  return out;
}

function placed(layout: Layout): SlotId[] {
  return layout.rows.flatMap((row) => row.slots.map((slot) => slot.id)).sort();
}

function expectIntact(before: Layout, after: Layout, dragged: SlotId, label: string): void {
  expect(placed(after), label).toEqual(placed(before));
  expect(after.hidden, label).toEqual(before.hidden);
  expect(repairSpans(after), label).toBe(after);
  const was = boxes(before);
  const now = boxes(after);
  for (const [id, box] of was) {
    if (!visible(box)) continue;
    expect(visible(now.get(id)), `${label}: ${id} drawn ${JSON.stringify(now.get(id))}`).toBe(true);
  }
  expect(visible(now.get(dragged)), `${label}: the dragged cell`).toBe(true);
}

describe("the owner's screenshot: Rename can become a third full height column", () => {
  const full = (layout: Layout, id: SlotId): boolean => {
    const box = boxes(layout).get(id);
    const tracks = computeTracks({ rows: layout.rows, width: W, height: H, gutter: 12, metas: META });
    return !!box && box.top === 0 && box.height === tracks.contentHeight && visible(box);
  };

  for (const [label, row, index] of [
    ['the gap between Share and Rename', 'r1', 1],
    ['the gap between Share and UI', 'r2', 1],
    ['the left edge beside Share, top row', 'r1', 0],
    ['the left edge beside Share, bottom row', 'r2', 0],
  ] as const) {
    test(`${label} is a full height column and lands three columns`, () => {
      const layout = screenshot();
      const drop = columnDropAt(layout, row, index, R);
      expect(drop?.kind, label).toBe('column');
      expect(drop?.kind === 'column' ? [drop.row, drop.rows] : null).toEqual(['r1', 2]);
      const next = applyDrop(layout, R, drop!);
      expect(next).not.toBe(layout);
      for (const id of [S, R, U]) expect(full(next, id), `${label}: ${id} full height`).toBe(true);
      expectIntact(layout, next, R, label);
    });
  }
});

describe('no drop from the screenshot loses a cell', () => {
  for (const dragged of [S, R, U]) {
    test(`dragging ${dragged}`, () => {
      const layout = screenshot();
      for (const target of targets(layout, dragged)) {
        const next = applyDrop(layout, dragged, target);
        expectIntact(layout, next, dragged, `${dragged} -> ${JSON.stringify(target)}`);
      }
    });
  }
});

/** A small seeded generator, so a failure names the case that made it. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

describe('random layouts, random drags: a move lands or changes nothing', () => {
  test('200 seeds, every target of a random dragged cell', () => {
    const ids = [S, R, U, A, B];
    let landed = 0;
    let tried = 0;
    for (let seed = 1; seed <= 200; seed += 1) {
      const random = seeded(seed);
      let layout = page(ids.slice(0, 2 + Math.floor(random() * 4)));
      const live = placed(layout);
      for (let step = 0; step < 5; step += 1) {
        const dragged = live[Math.floor(random() * live.length)]!;
        const all = targets(layout, dragged);
        const next = applyDrop(layout, dragged, all[Math.floor(random() * all.length)]!);
        expectIntact(layout, next, dragged, `seed ${seed} shaping step ${step}`);
        layout = next;
      }
      const dragged = live[Math.floor(random() * live.length)]!;
      for (const target of targets(layout, dragged)) {
        const next = applyDrop(layout, dragged, target);
        expectIntact(layout, next, dragged, `seed ${seed} ${dragged} -> ${JSON.stringify(target)}`);
        tried += 1;
        if (next !== layout) landed += 1;
      }
    }
    expect(tried).toBeGreaterThan(1000);
    expect(landed / tried).toBeGreaterThan(0.5);
  });
});
