import { expect, test } from 'vitest';
import { setCellSize, sizePresets, sizeRefusal } from './cell-size';
import type { Layout } from './types';

const layout = (kind: 'px' | 'flex', slots: string[]): Layout =>
  ({
    v: 6,
    rows: [{ id: 'r1', kind, size: kind === 'px' ? 128 : 1, slots: slots.map((id) => ({ id, fr: 1 / slots.length })) }],
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  }) as unknown as Layout;

const fits = { min: { w: 2, h: 2 }, sizes: ['full', 'medium', 'large'], anySize: true } as const;

test('presets are the named sizes a widget calls out, smallest first, each carrying its name', () => {
  expect(sizePresets(fits)).toEqual([{ name: 'medium', w: 4, h: 4 }, { name: 'large', w: 6, h: 5 }, { name: 'full', w: 12, h: 5 }]);
  expect(sizePresets({ min: { w: 1, h: 1 }, sizes: ['tall', 'wide', 'small'], anySize: false }).map((size) => size.name)).toEqual(['small', 'wide', 'tall']);
  expect(sizePresets(null)).toEqual([]);
});

test('a width preset takes the share from the neighbours and sets the px row height', () => {
  const next = setCellSize(layout('px', ['projects', 'notes']), 'projects', { w: 4, h: 2 }, 960);
  const slots = next.rows[0]!.slots;
  expect(slots[0]!.fr).toBeCloseTo((4 * 96) / 960);
  expect(slots[0]!.fr + slots[1]!.fr).toBeCloseTo(1);
  expect(next.rows[0]!.size).toBeGreaterThanOrEqual(128);
});

test('alone in a row and on a flex row are refused with a reason, and nothing changes', () => {
  const alone = layout('px', ['projects']);
  expect(sizeRefusal(alone, 'projects')).toBe('alone');
  expect(setCellSize(alone, 'projects', { w: 4, h: 2 }, 960)).toBe(alone);
  const flex = layout('flex', ['projects', 'notes']);
  expect(sizeRefusal(flex, 'projects')).toBe('flex-row');
  expect(sizeRefusal(layout('px', ['projects', 'notes']), 'projects')).toBeNull();
});
