import { describe, expect, test } from 'vitest';
import { canSplit, normalizeRail, placeInLayout, railToStored, removeFromRail, resetOptionsInRail, sectionStyle, setOptionInRail, setViewInRail, singleSection, splitAt, stepInRail, type RailLayout } from './rail-sections';
import { zoneItemKey } from '../drawer-zone/zone-model';
import { lastUsedKey, pressKey, readLastUsed, shownKeys, writeLastUsed } from './rail-open';
import { ratioAfterKey, ratioAtPointer } from '../split-divider/split-ratio';

const w = (widget: string) => ({ widget, look: null });
const ids = (layout: RailLayout) => layout.sections.map((section) => section.map((item) => item.widget));
const NONE = { section: 0, index: 0, split: null };

function storage(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  const store = {
    broken: false,
    getItem(key: string) {
      if (store.broken) throw new Error('blocked');
      return data.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      if (store.broken) throw new Error('blocked');
      data.set(key, value);
    },
    data,
  };
  return store;
}

describe('the stored value', () => {
  test('the old flat v1 list reads as ONE section, kept whole, and writes back as v2', () => {
    const layout = normalizeRail({ v: 1, items: [{ widget: 'core.notes' }, { widget: 'core.files', look: 'full' }] }, 256)!;
    expect(ids(layout)).toEqual([['core.notes', 'core.files']]);
    expect(layout.sections[0]![1]!.look).toBe('full');
    expect(railToStored(layout)).toEqual({ v: 2, sections: [{ items: [{ widget: 'core.notes' }, { widget: 'core.files', look: 'full' }] }] });
    expect(normalizeRail({ v: 1, items: [] }, 256)).toEqual({ sections: [[]], ratio: 0.5 });
    expect(normalizeRail(null, 256)).toBeNull();
    expect(normalizeRail({ v: 1, items: 'core.notes' }, 256)).toBeNull();
  });

  test('v2 keeps two sections and the ratio; a repeat across sections, a third section and an empty half are dropped', () => {
    const layout = normalizeRail({ v: 2, ratio: 0.3, sections: [{ items: [{ widget: 'core.a' }] }, { items: [{ widget: 'core.a' }, { widget: 'core.b' }] }, { items: [{ widget: 'core.c' }] }] }, 256)!;
    expect(ids(layout)).toEqual([['core.a'], ['core.b']]);
    expect(layout.ratio).toBe(0.3);
    expect(railToStored(layout)).toEqual({ v: 2, ratio: 0.3, sections: [{ items: [{ widget: 'core.a' }] }, { items: [{ widget: 'core.b' }] }] });
    expect(ids(normalizeRail({ v: 2, ratio: 0.3, sections: [{ items: [] }, { items: [{ widget: 'core.b' }] }] }, 256)!)).toEqual([['core.b']]);
    expect(normalizeRail({ v: 2, ratio: 2, sections: [{ items: [{ widget: 'core.a' }] }, { items: [{ widget: 'core.b' }] }] }, 256)!.ratio).toBe(0.85);
  });
});

describe('splitting and unsplitting', () => {
  const rail = normalizeRail({ v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }] }, 256)!;

  test('a band makes the second section at its end; a moved key leaves its old place', () => {
    expect(ids(placeInLayout(rail, { ...NONE, split: 'end' }, 'core.notes', undefined, 256))).toEqual([['core.changes', 'core.files'], ['core.notes']]);
    expect(ids(placeInLayout(rail, { ...NONE, split: 'start' }, 'core.files', undefined, 256))).toEqual([['core.files'], ['core.changes']]);
    expect(placeInLayout(rail, { ...NONE, split: 'end' }, 'core.notes', undefined, 256).ratio).toBe(0.5);
  });

  test('a band cannot split off the only widget, and a split rail cannot split again', () => {
    const lone = normalizeRail({ v: 1, items: [{ widget: 'core.changes' }] }, 256)!;
    expect(canSplit(lone, 'core.changes')).toBe(false);
    expect(canSplit(lone, null)).toBe(true);
    expect(ids(placeInLayout(lone, { ...NONE, split: 'end' }, 'core.changes', undefined, 256))).toEqual([['core.changes']]);
    const split = placeInLayout(rail, { ...NONE, split: 'end' }, 'core.notes', undefined, 256);
    expect(canSplit(split, null)).toBe(false);
    expect(ids(placeInLayout(split, { ...NONE, split: 'start' }, 'core.task-manager', undefined, 256))).toEqual([['core.task-manager', 'core.changes', 'core.files'], ['core.notes']]);
  });

  test('the last widget leaving a section takes the split away (removed, or moved to the other section)', () => {
    const split = { sections: [[w('core.changes')], [w('core.files'), w('core.notes')]], ratio: 0.3 };
    const removed = removeFromRail(split, 'core.changes');
    expect(ids(removed)).toEqual([['core.files', 'core.notes']]);
    expect(railToStored(removed)).toEqual({ v: 2, sections: [{ items: [{ widget: 'core.files' }, { widget: 'core.notes' }] }] });
    expect(ids(placeInLayout(split, { section: 1, index: 0, split: null }, 'core.changes', undefined, 256))).toEqual([['core.changes', 'core.files', 'core.notes']]);
    expect(ids(placeInLayout(split, { section: 0, index: 1, split: null }, 'core.notes', undefined, 256))).toEqual([['core.changes', 'core.notes'], ['core.files']]);
  });

  test('a step stays inside its section', () => {
    const split = { sections: [[w('core.a'), w('core.b')], [w('core.c')]], ratio: 0.5 };
    expect(ids(stepInRail(split, 'core.b', 1))).toEqual([['core.a', 'core.b'], ['core.c']]);
    expect(ids(stepInRail(split, 'core.b', -1))).toEqual([['core.b', 'core.a'], ['core.c']]);
  });

  test('sections and the hairline are placed by the same ratio', () => {
    expect(sectionStyle('y', 0, 2, 0.3)).toBe('top: 0; bottom: calc(100% - 30%); left: 0; right: 0');
    expect(sectionStyle('y', 1, 2, 0.3)).toBe('top: 30%; bottom: 0; left: 0; right: 0');
    expect(sectionStyle('x', 1, 2, 0.3)).toBe('left: 30%; right: 0; top: 0; bottom: 0');
    expect(sectionStyle('y', 0, 1, 0.3)).toBe('top: 0; bottom: 0; left: 0; right: 0');
    expect(splitAt(0.3)).toBe('30%');
  });
});

describe('what the slide-out shows', () => {
  const sections = [['core.changes', 'core.notes'], ['core.files', 'core.task-manager']];

  test('closed, a key opens with its widget and the other section first widget, then its last-used one', () => {
    expect(pressKey(sections, [], 'core.files', [null, null])).toEqual({ open: ['core.changes', 'core.files'], last: ['core.changes', 'core.files'] });
    expect(pressKey(sections, [], 'core.task-manager', ['core.notes', null])).toEqual({ open: ['core.notes', 'core.task-manager'], last: ['core.notes', 'core.task-manager'] });
  });

  test('open, a key swaps only its own section; a press on either shown widget closes', () => {
    expect(pressKey(sections, ['core.changes', 'core.files'], 'core.notes', [null, null])!.open).toEqual(['core.notes', 'core.files']);
    expect(pressKey(sections, ['core.changes', 'core.files'], 'core.files', [null, null])!.open).toEqual([]);
    expect(pressKey(sections, ['core.changes', 'core.files'], 'core.changes', [null, null])!.open).toEqual([]);
    expect(pressKey(sections, [], 'core.unknown', [null, null])).toBeNull();
  });

  test('one section behaves as before: open, swap, close', () => {
    const lone = [['core.a', 'core.b']];
    expect(pressKey(lone, [], 'core.a', [])!.open).toEqual(['core.a']);
    expect(pressKey(lone, ['core.a'], 'core.b', [])!.open).toEqual(['core.b']);
    expect(pressKey(lone, ['core.b'], 'core.b', [])!.open).toEqual([]);
  });

  test('what is shown is re-read against the live sections; a stale last-used is skipped', () => {
    expect(shownKeys(sections, ['core.files'], ['core.gone', null])).toEqual(['core.changes', 'core.files']);
    expect(shownKeys([['core.changes']], ['core.files'], [null, null])).toEqual([]);
  });

  test('last-used is per device, per rail, and a refused or garbled store is no memory', () => {
    const store = storage();
    writeLastUsed('side', ['core.notes', null], store);
    expect(store.data.get(lastUsedKey('side'))).toBe('["core.notes",null]');
    expect(readLastUsed('side', store)).toEqual(['core.notes', null]);
    expect(readLastUsed('bottom', store)).toEqual([]);
    expect(readLastUsed('side', storage({ [lastUsedKey('side')]: '{oops' }))).toEqual([]);
    store.broken = true;
    expect(readLastUsed('side', store)).toEqual([]);
    expect(() => writeLastUsed('side', ['core.a'], store)).not.toThrow();
  });
});

describe('the shared divider maths', () => {
  const bounds = { min: 0.15, max: 0.85, step: 0.02 };
  test('a pointer reads as its share of the container, clamped', () => {
    expect(ratioAtPointer('y', 0, 300, { left: 0, top: 100, width: 10, height: 400 }, bounds)).toBe(0.5);
    expect(ratioAtPointer('x', 890, 0, { left: 0, top: 0, width: 900, height: 10 }, bounds)).toBe(0.85);
  });
  test('the arrows along its axis step it, Home resets, other keys are not its', () => {
    expect(ratioAfterKey('y', 'ArrowDown', 0.5, bounds, 0.5)).toBe(0.52);
    expect(ratioAfterKey('y', 'ArrowUp', 0.5, bounds, 0.5)).toBe(0.48);
    expect(ratioAfterKey('x', 'ArrowRight', 0.84, bounds, 0.5)).toBe(0.85);
    expect(ratioAfterKey('x', 'Home', 0.3, bounds, 0.5)).toBe(0.5);
    expect(ratioAfterKey('y', 'ArrowLeft', 0.5, bounds, 0.5)).toBeNull();
  });
});

describe('copies of a widget with views', () => {
  const spot = { section: 0, index: 99, split: null } as const;

  test('a second catalog drop adds a copy and a third another; a singleton moves instead', () => {
    let layout = placeInLayout(singleSection([]), spot, 'core.tasks', undefined, 256);
    layout = placeInLayout(layout, spot, 'core.tasks', undefined, 256);
    layout = placeInLayout(layout, spot, 'core.tasks', undefined, 256);
    expect(layout.sections[0]!.map(zoneItemKey)).toEqual(['core.tasks', 'core.tasks#i2', 'core.tasks#i3']);
    const notes = placeInLayout(placeInLayout(singleSection([]), spot, 'core.notes', undefined, 256), spot, 'core.notes', undefined, 256);
    expect(notes.sections[0]).toHaveLength(1);
  });

  test('each copy has its own view and moving one keeps its copy id', () => {
    let layout = placeInLayout(placeInLayout(singleSection([]), spot, 'core.tasks', undefined, 256), spot, 'core.tasks', undefined, 256);
    layout = setViewInRail(layout, 'core.tasks#i2', 'all');
    const moved = placeInLayout(layout, { section: 0, index: 0, split: null }, 'core.tasks', undefined, 256, 'i2');
    expect(moved.sections[0]!.map((i) => [zoneItemKey(i), i.view])).toEqual([['core.tasks#i2', 'all'], ['core.tasks', undefined]]);
  });

  test('a copy carried from the other rail keeps its view, and takes a new copy id when its key is taken', () => {
    const here = singleSection([{ widget: 'core.tasks', look: null }]);
    const carried = { widget: 'core.tasks', look: null, view: 'all' };
    const next = placeInLayout(here, spot, 'core.tasks', undefined, 256, null, carried);
    expect(next.sections[0]!.map((i) => [zoneItemKey(i), i.view])).toEqual([['core.tasks', undefined], ['core.tasks#i2', 'all']]);
  });

  test('stored copies round trip through the v2 shape', () => {
    const raw = { v: 2, sections: [{ items: [{ widget: 'core.tasks' }, { widget: 'core.tasks', view: 'all', instance: 'i2' }] }] };
    const layout = normalizeRail(raw, 256)!;
    expect(layout.sections[0]).toHaveLength(2);
    expect(railToStored(layout).sections[0]!.items).toEqual(raw.sections[0]!.items);
  });
});

describe('options per copy in a rail', () => {
  const spot = { section: 0, index: 99, split: null } as const;
  const two = () => placeInLayout(placeInLayout(singleSection([]), spot, 'core.questions', undefined, 256), spot, 'core.questions', undefined, 256);

  test('two copies of the widget sit side by side, each with its own options', () => {
    const layout = setOptionInRail(setOptionInRail(two(), 'core.questions#i2', 'kind_huddle', false), 'core.questions', 'kind_approvals', false);
    expect(layout.sections[0]!.map((i) => [zoneItemKey(i), i.options])).toEqual([
      ['core.questions', { kind_approvals: false }],
      ['core.questions#i2', { kind_huddle: false }],
    ]);
    expect(resetOptionsInRail(layout, 'core.questions#i2').sections[0]!.map((i) => i.options)).toEqual([{ kind_approvals: false }, undefined]);
  });

  test('moving a copy keeps its options and its copy id', () => {
    const layout = setOptionInRail(two(), 'core.questions#i2', 'kind_huddle', false);
    const moved = placeInLayout(layout, { section: 0, index: 0, split: null }, 'core.questions', undefined, 256, 'i2');
    expect(moved.sections[0]!.map((i) => [zoneItemKey(i), i.options])).toEqual([['core.questions#i2', { kind_huddle: false }], ['core.questions', undefined]]);
  });

  test('a copy carried from the other rail keeps its options, taking a new copy id when its key is taken', () => {
    const here = singleSection([{ widget: 'core.questions', look: null }]);
    const carried = { widget: 'core.questions', look: null, options: { kind_approvals: false } };
    const next = placeInLayout(here, spot, 'core.questions', undefined, 256, null, carried);
    expect(next.sections[0]!.map((i) => [zoneItemKey(i), i.options])).toEqual([['core.questions', undefined], ['core.questions#i2', { kind_approvals: false }]]);
  });

  test('stored options round trip through the v2 shape', () => {
    const raw = { v: 2, sections: [{ items: [{ widget: 'core.questions', options: { kind_huddle: false } }, { widget: 'core.questions', instance: 'i2' }] }] };
    const layout = normalizeRail(raw, 256)!;
    expect(layout.sections[0]!.map((i) => i.options)).toEqual([{ kind_huddle: false }, undefined]);
    expect(railToStored(layout).sections[0]!.items).toEqual(raw.sections[0]!.items);
  });
});
