import { describe, expect, test } from 'vitest';
import { RAIL_MAX_SECTIONS, RAIL_MIN_SHARE } from './rail-model';
import { canHalve, cutBounds, dropCut, evenCuts, halveAt, moveCut, repairCuts, sectionStyle, spanOf } from './rail-cuts';
import { canSplitAt, normalizeRail, placeInLayout, railToStored, removeFromRail, singleSection, type RailLayout } from './rail-sections';
import type { ZoneItem } from '../drawer-zone/zone-model';

const w = (widget: string): ZoneItem => ({ widget, look: null });
const widgets = (layout: RailLayout): string[][] => layout.sections.map((section) => section.map((item) => item.widget));
const AFTER = (section: number) => ({ section, index: 0, split: true });
const base = (): RailLayout => singleSection([w('core.a'), w('core.b'), w('core.c'), w('core.d'), w('core.e')]);

describe('cuts', () => {
  test('even cuts and spans: N areas have N-1 cuts, the ends are 0 and 1', () => {
    expect(evenCuts(1)).toEqual([]);
    expect(evenCuts(2)).toEqual([0.5]);
    expect(evenCuts(4)).toEqual([0.25, 0.5, 0.75]);
    expect(spanOf([0.3, 0.6], 0)).toEqual([0, 0.3]);
    expect(spanOf([0.3, 0.6], 1)).toEqual([0.3, 0.6]);
    expect(spanOf([0.3, 0.6], 2)).toEqual([0.6, 1]);
  });

  test('halving an area puts the new cut at the middle of its span, after it', () => {
    expect(halveAt([], 0)).toEqual([0.5]);
    expect(halveAt([0.4], 0)).toEqual([0.2, 0.4]);
    expect(halveAt([0.4], 1)).toEqual([0.4, 0.7]);
    expect(halveAt([0.25, 0.5, 0.75], 1)).toEqual([0.25, 0.375, 0.5, 0.75]);
  });

  test('an area under twice the minimum share cannot be halved', () => {
    expect(canHalve([], 0)).toBe(true);
    expect(canHalve([0.5], 0)).toBe(true);
    expect(canHalve([0.25, 0.5, 0.75], 1)).toBe(false);
    expect(canHalve([0.8], 1)).toBe(false);
    expect(RAIL_MIN_SHARE).toBe(0.15);
    expect(canHalve([0.3], 0)).toBe(true);
    expect(canHalve([0.29], 0)).toBe(false);
  });

  test('closing an area gives its span to a neighbor: the first to the next, the others to the previous', () => {
    expect(dropCut([0.3, 0.6], 0)).toEqual([0.6]);
    expect(dropCut([0.3, 0.6], 1)).toEqual([0.6]);
    expect(dropCut([0.3, 0.6], 2)).toEqual([0.3]);
    expect(dropCut([], 0)).toEqual([]);
  });

  test('a cut moves only between its neighbors, never closer than the minimum share', () => {
    expect(cutBounds([0.3, 0.6], 0)).toEqual({ min: 0.15, max: 0.45 });
    expect(cutBounds([0.3, 0.6], 1)).toEqual({ min: 0.45, max: 0.85 });
    expect(moveCut([0.3, 0.6], 0, 0.9)).toEqual([0.45, 0.6]);
    expect(moveCut([0.3, 0.6], 1, 0.2)).toEqual([0.3, 0.45]);
    expect(moveCut([0.3, 0.6], 1, 0.5)).toEqual([0.3, 0.5]);
  });

  test('a bad stored list of cuts is repaired to even cuts, a good one is kept', () => {
    expect(repairCuts([0.3, 0.6], 3)).toEqual([0.3, 0.6]);
    expect(repairCuts([0.6, 0.3], 3)).toEqual(evenCuts(3));
    expect(repairCuts([0.3], 3)).toEqual(evenCuts(3));
    expect(repairCuts('x', 2)).toEqual([0.5]);
    expect(repairCuts([0.05], 2)).toEqual([0.5]);
    expect(repairCuts(null, 1)).toEqual([]);
  });

  test('every area is placed by its own span, the same placement the hairlines use', () => {
    expect(sectionStyle('y', 0, [0.3, 0.6])).toBe('top: 0; bottom: calc(100% - 30%); left: 0; right: 0');
    expect(sectionStyle('y', 1, [0.3, 0.6])).toBe('top: 30%; bottom: calc(100% - 60%); left: 0; right: 0');
    expect(sectionStyle('x', 2, [0.3, 0.6])).toBe('left: 60%; right: 0; top: 0; bottom: 0');
    expect(sectionStyle('y', 0, [])).toBe('top: 0; bottom: 0; left: 0; right: 0');
  });
});

describe('splitting in place', () => {
  test('a key dropped on the split target makes a new area right after the hovered one, holding that key', () => {
    const two = placeInLayout(base(), AFTER(0), 'core.e', undefined, 256, null);
    expect(widgets(two)).toEqual([['core.a', 'core.b', 'core.c', 'core.d'], ['core.e']]);
    expect(two.cuts).toEqual([0.5]);
  });

  test('it splits again the same way, any area of a split bar, up to four', () => {
    let layout = placeInLayout(base(), AFTER(0), 'core.e', undefined, 256, null);
    layout = placeInLayout(layout, AFTER(1), 'core.d', undefined, 256, null);
    expect(widgets(layout)).toEqual([['core.a', 'core.b', 'core.c'], ['core.e'], ['core.d']]);
    expect(layout.cuts).toEqual([0.5, 0.75]);
    layout = placeInLayout(layout, AFTER(0), 'core.c', undefined, 256, null);
    expect(widgets(layout)).toEqual([['core.a', 'core.b'], ['core.c'], ['core.e'], ['core.d']]);
    expect(layout.cuts).toEqual([0.25, 0.5, 0.75]);
  });

  test('the cap refuses a fifth area and the layout is left as it was', () => {
    const four: RailLayout = { sections: [[w('core.a'), w('core.b')], [w('core.c')], [w('core.d')], [w('core.e')]], cuts: [0.4, 0.6, 0.8] };
    expect(four.sections).toHaveLength(RAIL_MAX_SECTIONS);
    const refused = placeInLayout(four, AFTER(0), 'core.b', undefined, 256, null);
    expect(widgets(refused)).toEqual(widgets(four));
    expect(refused.cuts).toEqual(four.cuts);
  });

  test('the cap is judged after an emptied area closes: the sole key of an area moves to a new one', () => {
    const four: RailLayout = { sections: [[w('core.a'), w('core.b'), w('core.c')], [w('core.d')], [w('core.e')], [w('core.f')]], cuts: [0.4, 0.6, 0.8] };
    const moved = placeInLayout(four, AFTER(0), 'core.e', undefined, 256, null);
    expect(widgets(moved)).toEqual([['core.a', 'core.b', 'core.c'], ['core.e'], ['core.d'], ['core.f']]);
    expect(moved.cuts).toEqual([0.2, 0.4, 0.8]);
  });

  test('an area too small to halve refuses the split', () => {
    const narrow: RailLayout = { sections: [[w('core.a'), w('core.b')], [w('core.c')]], cuts: [0.85] };
    const out = placeInLayout(narrow, AFTER(1), 'core.a', undefined, 256, null);
    expect(widgets(out)).toEqual(widgets(narrow));
  });

  test('canSplitAt: room, a key that stays, and an area wide enough', () => {
    const one = base();
    expect(canSplitAt(one, 0, 'core.a')).toBe(true);
    expect(canSplitAt(singleSection([w('core.a')]), 0, 'core.a')).toBe(false);
    expect(canSplitAt(singleSection([w('core.a')]), 0, null)).toBe(true);
    expect(canSplitAt(singleSection([]), 0, null)).toBe(false);
    const four: RailLayout = { sections: [[w('a')], [w('b')], [w('c')], [w('d')]], cuts: [0.25, 0.5, 0.75] };
    expect(canSplitAt(four, 0, 'core.z')).toBe(false);
    expect(canSplitAt({ sections: [[w('a'), w('b')], [w('c')]], cuts: [0.85] }, 1, 'x')).toBe(false);
  });

  test('dragging the last key out of an area closes it and its span goes to a neighbor', () => {
    let layout = placeInLayout(base(), AFTER(0), 'core.e', undefined, 256, null);
    layout = placeInLayout(layout, AFTER(1), 'core.d', undefined, 256, null);
    expect(widgets(layout)).toEqual([['core.a', 'core.b', 'core.c'], ['core.e'], ['core.d']]);
    const closed = removeFromRail(layout, 'core.e');
    expect(widgets(closed)).toEqual([['core.a', 'core.b', 'core.c'], ['core.d']]);
    expect(closed.cuts).toHaveLength(1);
  });
});

describe('stored shapes', () => {
  test('one or two areas are written as v2 with the ratio only while split, so an older app reads them', () => {
    expect(railToStored(base())).toEqual({ v: 2, sections: [{ items: base().sections[0]!.map((i) => ({ widget: i.widget })) }] });
    const two = placeInLayout(base(), AFTER(0), 'core.e', undefined, 256, null);
    const stored = railToStored(two);
    expect(stored.v).toBe(2);
    expect(stored).toMatchObject({ ratio: 0.5 });
    expect('cuts' in stored).toBe(false);
  });

  test('three or four areas are written as v3 with their cuts', () => {
    let layout = placeInLayout(base(), AFTER(0), 'core.e', undefined, 256, null);
    layout = placeInLayout(layout, AFTER(1), 'core.d', undefined, 256, null);
    const stored = railToStored(layout);
    expect(stored.v).toBe(3);
    expect(stored).toMatchObject({ cuts: [0.5, 0.75] });
    expect('ratio' in stored).toBe(false);
    expect(stored.sections).toHaveLength(3);
  });

  test('both shapes read back to the same layout, and a v2 value is read as cuts', () => {
    let layout = placeInLayout(base(), AFTER(0), 'core.e', undefined, 256, null);
    expect(normalizeRail(railToStored(layout), 256)).toEqual(layout);
    layout = placeInLayout(layout, AFTER(1), 'core.d', undefined, 256, null);
    expect(layout.sections).toHaveLength(3);
    expect(normalizeRail(railToStored(layout), 256)).toEqual(layout);
    const v2 = normalizeRail({ v: 2, ratio: 0.3, sections: [{ items: [{ widget: 'core.a' }] }, { items: [{ widget: 'core.b' }] }] }, 256)!;
    expect(v2.cuts).toEqual([0.3]);
  });

  test('v3 is read tolerantly: a fifth area is dropped, bad cuts become even ones, an empty area closes with its cut', () => {
    const five = { v: 3, cuts: [0.2, 0.4, 0.6, 0.8], sections: ['a', 'b', 'c', 'd', 'e'].map((x) => ({ items: [{ widget: `core.${x}` }] })) };
    expect(normalizeRail(five, 256)!.sections).toHaveLength(4);
    const bad = { v: 3, cuts: [0.9, 0.1], sections: ['a', 'b', 'c'].map((x) => ({ items: [{ widget: `core.${x}` }] })) };
    expect(normalizeRail(bad, 256)!.cuts).toEqual(evenCuts(3));
    const hole = { v: 3, cuts: [0.3, 0.6], sections: [{ items: [{ widget: 'core.a' }] }, { items: [] }, { items: [{ widget: 'core.c' }] }] };
    const closed = normalizeRail(hole, 256)!;
    expect(widgets(closed)).toEqual([['core.a'], ['core.c']]);
    expect(closed.cuts).toEqual([0.6]);
  });
});
