import { describe, expect, test } from 'vitest';
import { PRIMARY_SLOT } from '../engine/model';
import type { Layout } from '../engine/types';
import { displayedTabs, freeName, fromServerShape, nameProblem, toServerShape, visibleTerminals } from './shape';

/** A grid of one flex row holding these slots. */
function grid(...ids: string[]): Layout {
  return {
    v: 6,
    rows: [{ id: 'r1', kind: 'flex', size: 1, slots: ids.map((id) => ({ id: id as never, fr: 1 / ids.length })) }],
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  };
}

describe('toServerShape', () => {
  test('the pane becomes the anchor row slot, every component gets an explicit group, the grid is kept', () => {
    const layout = grid(PRIMARY_SLOT, 'terminal:row:2', 'notes');
    const out = toServerShape(layout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:3'] } }, 1);
    expect(out.groups).toEqual({
      [PRIMARY_SLOT]: { tabs: ['terminal:row:1', 'terminal:row:3'] },
      'terminal:row:2': { tabs: ['terminal:row:2'] },
    });
    expect(out.layout).toEqual(layout);
    expect(out.layout).not.toBe(layout);
  });
});

describe('fromServerShape', () => {
  test('an anchor already in the pane component comes back as the pane', () => {
    const shape = toServerShape(grid(PRIMARY_SLOT, 'terminal:row:2'), {}, 1);
    const drawn = fromServerShape(shape, 1)!;
    expect(drawn.groups[PRIMARY_SLOT]).toEqual({ tabs: [PRIMARY_SLOT] });
    expect(drawn.layout).toEqual(grid(PRIMARY_SLOT, 'terminal:row:2'));
  });

  test('an anchor in another component moves the pane key there, and the old pane component keeps a free key', () => {
    const shape = {
      layout: grid(PRIMARY_SLOT, 'terminal:row:2'),
      groups: { [PRIMARY_SLOT]: { tabs: ['terminal:row:1'] }, 'terminal:row:2': { tabs: ['terminal:row:2', 'terminal:row:3'] } },
    };
    const drawn = fromServerShape(shape, 3)!;
    const ids = drawn.layout!.rows[0]!.slots.map((slot) => slot.id);
    expect(ids).toEqual(['terminal:row:1', PRIMARY_SLOT]);
    expect(drawn.groups).toEqual({
      'terminal:row:1': { tabs: ['terminal:row:1'] },
      [PRIMARY_SLOT]: { tabs: ['terminal:row:2', PRIMARY_SLOT] },
    });
  });

  test('a shape with no grid becomes one row of its components', () => {
    const drawn = fromServerShape({ layout: null, groups: { 'terminal:row:1': { tabs: ['terminal:row:1', 'terminal:row:2'] } } }, 2)!;
    expect(drawn.layout!.rows[0]!.slots.map((slot) => slot.id)).toEqual([PRIMARY_SLOT]);
    expect(drawn.groups[PRIMARY_SLOT]!.tabs).toEqual(['terminal:row:1', PRIMARY_SLOT]);
  });

  test('an anchor the shape does not display answers null', () => {
    expect(fromServerShape({ layout: grid('terminal:row:1', 'terminal:row:2'), groups: {} }, 9)).toBeNull();
  });

  test('round trip: what is drawn from a shape is written back as the same shape', () => {
    const shape = {
      layout: grid('terminal:row:4', 'terminal:row:2'),
      groups: { 'terminal:row:4': { tabs: ['terminal:row:4', 'terminal:row:1'] }, 'terminal:row:2': { tabs: ['terminal:row:2'] } },
    };
    const drawn = fromServerShape(shape, 1)!;
    const back = toServerShape(drawn.layout!, drawn.groups, 1);
    expect(displayedTabs(back.layout!, back.groups)).toEqual(['terminal:row:4', 'terminal:row:1', 'terminal:row:2']);
    expect(visibleTerminals(back.layout!)).toBe(2);
  });
});

describe('names', () => {
  test('the server rule, checked first', () => {
    expect(nameProblem('   ')).toBe('empty');
    expect(nameProblem('x'.repeat(61))).toBe('too_long');
    expect(nameProblem('a\u0007b')).toBe('invalid');
    expect(nameProblem('  api + web  ')).toBeNull();
  });

  test('a taken suggestion is numbered, ignoring case', () => {
    const numbered = (name: string, n: number) => `${name} ${n}`;
    expect(freeName('api + web', [], numbered)).toBe('api + web');
    expect(freeName('api + web', ['API + WEB', 'api + web 2'], numbered)).toBe('api + web 3');
  });
});
