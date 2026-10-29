import { describe, expect, test } from 'vitest';
import { applyDrop } from '../engine/drop';
import { META } from '../engine/meta';
import { OLD_DEFAULT_LAYOUT } from '../engine/old-default.fixture';
import { resetLayout, showCell } from '../engine/model';
import { placeOf, visualOrder } from '../engine/spans';
import type { Layout, SlotId } from '../engine/types';
import { aimWithArrival, showAt } from './show-at';

const home = (): Layout => OLD_DEFAULT_LAYOUT;

function drawn(layout: Layout): string[][] {
  return layout.rows.map((row) =>
    visualOrder(row).flatMap((cell) => (cell.kind === 'slot' ? [cell.slot.id as string] : [])),
  );
}

describe('showAt', () => {
  test('a new row above everything', () => {
    const result = showAt(home(), 'notes', { kind: 'new', after: null });
    expect(result.landed).toBe(true);
    expect(drawn(result.layout)[0]).toEqual(['notes']);
    expect(result.layout.hidden).not.toContain('notes');
  });

  test('a new row between two rows', () => {
    const result = showAt(home(), 'keep-awake', { kind: 'new', after: 'r2' });
    expect(result.landed).toBe(true);
    expect(drawn(result.layout)[1]).toEqual(['keep-awake']);
  });

  test('a place in a row, between two cells', () => {
    const result = showAt(home(), 'notes', { kind: 'row', row: 'r3', index: 1 });
    expect(result.landed).toBe(true);
    expect(drawn(result.layout)[1]).toEqual(['running-sessions', 'notes', 'closed-sessions']);
  });

  test('stacked below a cell', () => {
    const result = showAt(home(), 'files', { kind: 'stack', of: 'ledger', edge: 'below' });
    expect(result.landed).toBe(true);
    const at = placeOf(result.layout, 'files');
    expect(at).not.toBeNull();
    expect(result.layout.hidden).not.toContain('files');
  });

  test('every cell stays placed exactly once', () => {
    const before = home();
    const result = showAt(before, 'scheduled-tasks', { kind: 'row', row: 'r4', index: 0 });
    const ids = drawn(result.layout).flat();
    expect(new Set(ids).size).toBe(ids.length);
    for (const row of before.rows) for (const slot of row.slots) expect(ids).toContain(slot.id);
    expect(ids).toContain('scheduled-tasks');
  });

  test('a widget already on the surface is left alone', () => {
    const before = home();
    const result = showAt(before, 'stat-running', { kind: 'new', after: null });
    expect(result.layout).toBe(before);
    expect(result.landed).toBe(false);
  });
});

describe('the index the pointer measured without the arrival', () => {
  test('moves right by one when the arrival was put in the same row to its left', () => {
    const shown = showCell(home(), 'notes');
    const front = applyDrop(shown, 'notes', { kind: 'row', row: 'r3', index: 0 });
    expect(drawn(front)[1]?.[0]).toBe('notes');
    expect(aimWithArrival(front, 'notes' as SlotId, { kind: 'row', row: 'r3', index: 2 })).toEqual({
      kind: 'row',
      row: 'r3',
      index: 3,
    });
  });

  test('stays when the arrival sits at or right of it, or in another row', () => {
    const shown = showCell(home(), 'notes');
    expect(aimWithArrival(shown, 'notes', { kind: 'row', row: 'r3', index: 1 })).toEqual({ kind: 'row', row: 'r3', index: 1 });
    expect(aimWithArrival(shown, 'notes', { kind: 'row', row: 'r4', index: 3 })).toEqual({ kind: 'row', row: 'r4', index: 3 });
    const target = { kind: 'new', after: 'r1' } as const;
    expect(aimWithArrival(shown, 'notes', target)).toBe(target);
  });
});
