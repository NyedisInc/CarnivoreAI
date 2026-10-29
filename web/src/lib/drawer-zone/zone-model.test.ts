import { describe, expect, test } from 'vitest';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { validateManifest } from '../../opscenter/widgets/validate';
import {
  DEFAULT_ZONE_ITEMS,
  MAX_ZONE_ITEMS,
  addItem,
  lookOf,
  moveItem,
  normalizeZone,
  removeItem,
  resetItemOptions,
  setItemLook,
  setItemOption,
  setItemView,
  stepItem,
  toStored,
  zoneItemKey,
  type ZoneItem,
} from './zone-model';
import * as zm from './zone-model';

const item = (widget: string, look: ZoneItem['look'] = null): ZoneItem => ({ widget, look });
const ids = (list: readonly ZoneItem[]): string[] => list.map((i) => i.widget);

describe('default contents', () => {
  test('the area starts as the providers widget alone', () => {
    expect(ids(DEFAULT_ZONE_ITEMS)).toEqual(['core.ledger']);
  });

  test('absent is not empty: no value reads as null, an emptied area as []', () => {
    expect(normalizeZone(undefined)).toBeNull();
    expect(normalizeZone(null)).toBeNull();
    expect(normalizeZone('x')).toBeNull();
    expect(normalizeZone({ v: 1, items: [] })).toEqual([]);
  });
});

describe('normalizeZone', () => {
  test('drops malformed entries and repeats, keeps unknown ids and valid looks', () => {
    const out = normalizeZone({
      items: [
        { widget: 'core.ledger', look: 'full' },
        { widget: 'core.ledger' },
        { widget: 'acme.clock', look: 'weird' },
        { widget: 7 },
        null,
      ],
    });
    expect(out).toEqual([item('core.ledger', 'full'), item('acme.clock', null)]);
  });

  test('caps the count', () => {
    const many = Array.from({ length: MAX_ZONE_ITEMS + 5 }, (_, i) => ({ widget: `w.${i}` }));
    expect(normalizeZone({ items: many })).toHaveLength(MAX_ZONE_ITEMS);
  });

  test('toStored omits a null look and round-trips through normalizeZone', () => {
    const list = [item('core.ledger', 'full'), item('core.keep-awake')];
    const stored = toStored(list);
    expect(stored).toEqual({ v: 1, items: [{ widget: 'core.ledger', look: 'full' }, { widget: 'core.keep-awake' }] });
    expect(normalizeZone(stored)).toEqual(list);
  });
});

describe('add, move, step, remove', () => {
  const base = [item('a.one'), item('a.two'), item('a.three')];

  test('add lands at the index, clamps it, and refuses a repeat', () => {
    expect(ids(addItem(base, 'a.new', 1))).toEqual(['a.one', 'a.new', 'a.two', 'a.three']);
    expect(ids(addItem(base, 'a.new', 99))).toEqual(['a.one', 'a.two', 'a.three', 'a.new']);
    expect(ids(addItem(base, 'a.new'))).toEqual(['a.one', 'a.two', 'a.three', 'a.new']);
    expect(ids(addItem(base, 'a.two', 0))).toEqual(ids(base));
  });

  test('add refuses when the area is full', () => {
    const full = Array.from({ length: MAX_ZONE_ITEMS }, (_, i) => item(`w.${i}`));
    expect(addItem(full, 'w.extra')).toHaveLength(MAX_ZONE_ITEMS);
  });

  test('move reads the index against the list without the moved widget', () => {
    expect(ids(moveItem(base, 'a.one', 2))).toEqual(['a.two', 'a.three', 'a.one']);
    expect(ids(moveItem(base, 'a.three', 0))).toEqual(['a.three', 'a.one', 'a.two']);
    expect(ids(moveItem(base, 'a.two', 1))).toEqual(ids(base));
    expect(ids(moveItem(base, 'missing', 0))).toEqual(ids(base));
  });

  test('step moves one place and stops at the ends', () => {
    expect(ids(stepItem(base, 'a.two', -1))).toEqual(['a.two', 'a.one', 'a.three']);
    expect(ids(stepItem(base, 'a.two', 1))).toEqual(['a.one', 'a.three', 'a.two']);
    expect(ids(stepItem(base, 'a.one', -1))).toEqual(ids(base));
    expect(ids(stepItem(base, 'a.three', 1))).toEqual(ids(base));
  });

  test('remove takes it out and leaves the rest in order', () => {
    expect(ids(removeItem(base, 'a.two'))).toEqual(['a.one', 'a.three']);
    expect(ids(removeItem(base, 'nope'))).toEqual(ids(base));
  });
});

describe('looks', () => {
  const ledger = CORE_MANIFESTS['core.ledger']!;

  test('the providers widget declares compact for the drawer and full for home', () => {
    expect(ledger.looks?.defaults).toEqual({ home: 'full', drawer: 'compact' });
    expect(lookOf(ledger, item('core.ledger'))).toBe('compact');
  });

  test('a chosen look wins; a look the widget lacks falls back to the default', () => {
    expect(lookOf(ledger, item('core.ledger', 'full'))).toBe('full');
    expect(lookOf(CORE_MANIFESTS['core.keep-awake'], item('core.keep-awake', 'full'))).toBeNull();
  });

  test('setItemLook changes one instance and refuses a look the widget lacks', () => {
    const list = [item('core.ledger'), item('core.keep-awake')];
    expect(setItemLook(list, 'core.ledger', 'full')[0]?.look).toBe('full');
    expect(setItemLook(list, 'core.keep-awake', 'full')).toEqual(list);
  });
});

describe('manifest declarations', () => {
  test('every core manifest still validates with its looks', () => {
    for (const manifest of Object.values(CORE_MANIFESTS)) {
      const check = validateManifest(JSON.parse(JSON.stringify(manifest)));
      expect(check.ok, manifest.id).toBe(true);
    }
  });

  test('a retired zone list is an unknown field, and a bad look is refused with its own code', () => {
    const base = JSON.parse(JSON.stringify(CORE_MANIFESTS['core.ledger']));
    expect(validateManifest({ ...base, zones: ['drawer'] })).toMatchObject({ ok: false, refusal: 'unknown-field' });
    expect(validateManifest({ ...base, looks: { names: ['huge'], defaults: {} } })).toMatchObject({
      ok: false,
      refusal: 'looks',
    });
    expect(validateManifest({ ...base, looks: { names: ['compact'], defaults: { drawer: 'full' } } })).toMatchObject({
      ok: false,
      refusal: 'looks',
    });
  });
});

describe('family copies in the area', () => {
  test('two copies of a family with different targets are two items, keyed by target; a repeat target is refused', () => {
    let items = zm.addItem([], 'core.terminal', undefined, 'row:7');
    items = zm.addItem(items, 'core.terminal', undefined, 'row:8');
    expect(zm.addItem(items, 'core.terminal', undefined, 'row:7')).toHaveLength(2);
    expect(items.map(zm.zoneItemKey)).toEqual(['core.terminal@row:7', 'core.terminal@row:8']);
    expect(zm.moveItem(items, 'core.terminal@row:8', 0).map((item) => item.target)).toEqual(['row:8', 'row:7']);
    expect(zm.removeItem(items, 'core.terminal@row:7').map((item) => item.target)).toEqual(['row:8']);
  });

  test('a target survives storage and a bad one is dropped', () => {
    const stored = zm.toStored([{ widget: 'core.analytics', look: null, target: 'c-1' }, { widget: 'core.ledger', look: null }]);
    expect(stored.items).toEqual([{ widget: 'core.analytics', target: 'c-1' }, { widget: 'core.ledger' }]);
    expect(zm.normalizeZone(stored)).toEqual([{ widget: 'core.analytics', look: null, target: 'c-1' }, { widget: 'core.ledger', look: null }]);
    expect(zm.normalizeZone({ items: [{ widget: 'core.terminal', target: 'row 7; rm' }] })).toEqual([{ widget: 'core.terminal', look: null }]);
  });
});

describe('views', () => {
  test('a placement stored under an old all sessions id reads as the merged widget with that view', () => {
    const items = normalizeZone({ v: 1, items: [{ widget: 'core.tasks-all' }, { widget: 'core.automations-all', look: 'full' }, { widget: 'core.notes' }] })!;
    expect(items).toEqual([
      { widget: 'core.tasks', look: null, view: 'all' },
      { widget: 'core.automations', look: 'full', view: 'all' },
      { widget: 'core.notes', look: null },
    ]);
  });

  test('both old ids of a pair become two copies of the merged widget, nothing lost', () => {
    const items = normalizeZone({ v: 1, items: [{ widget: 'core.task-manager' }, { widget: 'core.task-manager-all' }] })!;
    expect(items).toEqual([
      { widget: 'core.task-manager', look: null },
      { widget: 'core.task-manager', look: null, view: 'all', instance: 'i2' },
    ]);
  });

  test('a stored view round trips and a malformed one is dropped', () => {
    const items = normalizeZone({ v: 1, items: [{ widget: 'core.tasks', view: 'all' }, { widget: 'core.bookmarks', view: 'No Way' }] })!;
    expect(items.map((item) => item.view)).toEqual(['all', undefined]);
    expect(toStored(items).items).toEqual([{ widget: 'core.tasks', view: 'all' }, { widget: 'core.bookmarks' }]);
  });

  test('setItemView stores a non-default view, drops the field for the default and refuses a view the widget lacks', () => {
    const start = [{ widget: 'core.tasks', look: null }, { widget: 'core.notes', look: null }] as const;
    const all = setItemView(start, 'core.tasks', 'all');
    expect(all[0]!.view).toBe('all');
    expect('view' in setItemView(all, 'core.tasks', 'session')[0]!).toBe(false);
    expect(setItemView(start, 'core.tasks', 'bogus')).toEqual(start);
    expect(setItemView(start, 'core.notes', 'all')).toEqual(start);
  });
});

describe('several copies of a widget with views', () => {
  test('a second add is a new copy with its own key, a singleton is still refused', () => {
    const one = addItem([], 'core.tasks');
    const two = addItem(one, 'core.tasks');
    const three = addItem(two, 'core.tasks');
    expect(two.map(zoneItemKey)).toEqual(['core.tasks', 'core.tasks#i2']);
    expect(three.map(zoneItemKey)).toEqual(['core.tasks', 'core.tasks#i2', 'core.tasks#i3']);
    expect(addItem(addItem([], 'core.files'), 'core.files')).toHaveLength(1);
  });

  test('each copy keeps its own view', () => {
    const two = addItem(addItem([], 'core.tasks'), 'core.tasks');
    const next = setItemView(two, 'core.tasks#i2', 'all');
    expect(next[0]!.view).toBeUndefined();
    expect(next[1]!.view).toBe('all');
  });

  test('copies round trip through storage and removing one leaves the other', () => {
    const two = setItemView(addItem(addItem([], 'core.tasks'), 'core.tasks'), 'core.tasks#i2', 'all');
    const stored = toStored(two);
    expect(stored.items).toEqual([{ widget: 'core.tasks' }, { widget: 'core.tasks', view: 'all', instance: 'i2' }]);
    const back = normalizeZone(stored)!;
    expect(back).toEqual(two);
    expect(removeItem(back, 'core.tasks').map(zoneItemKey)).toEqual(['core.tasks#i2']);
  });

  test('a stored placement without an instance keeps its key, and a repeat of a singleton still collapses', () => {
    const items = normalizeZone({ v: 1, items: [{ widget: 'core.tasks', view: 'all' }, { widget: 'core.files' }, { widget: 'core.files' }, { widget: 'core.tasks', instance: 'bad' }] })!;
    expect(items.map(zoneItemKey)).toEqual(['core.tasks', 'core.files', 'core.tasks#i2']);
    expect(items[0]!.view).toBe('all');
  });
});

describe('options per copy', () => {
  test('the questions widget may be placed more than once, a widget without options of its own may not', () => {
    expect(zm.isRepeatable('core.questions')).toBe(true);
    const two = addItem(addItem([], 'core.questions'), 'core.questions');
    expect(two.map(zoneItemKey)).toEqual(['core.questions', 'core.questions#i2']);
    expect(addItem(addItem([], 'core.notes'), 'core.notes')).toHaveLength(1);
  });

  test('each copy keeps its own options; the other copy is untouched', () => {
    const two = addItem(addItem([], 'core.questions'), 'core.questions');
    const next = setItemOption(setItemOption(two, 'core.questions#i2', 'kind_huddle', false), 'core.questions#i2', 'kind_approvals', false);
    expect(next[0]!.options).toBeUndefined();
    expect(next[1]!.options).toEqual({ kind_huddle: false, kind_approvals: false });
    const back = setItemOption(next, 'core.questions', 'kind_huddle', false);
    expect(back[0]!.options).toEqual({ kind_huddle: false });
    expect(back[1]!.options).toEqual({ kind_huddle: false, kind_approvals: false });
  });

  test('clearing the last option stores none, and reset clears one copy only', () => {
    const two = setItemOption(setItemOption(addItem(addItem([], 'core.questions'), 'core.questions'), 'core.questions', 'kind_huddle', false), 'core.questions#i2', 'kind_huddle', false);
    expect(setItemOption(two, 'core.questions', 'kind_huddle', null)[0]).toEqual({ widget: 'core.questions', look: null });
    const reset = resetItemOptions(two, 'core.questions#i2');
    expect(reset[0]!.options).toEqual({ kind_huddle: false });
    expect(reset[1]!.options).toBeUndefined();
  });

  test('a widget whose copies carry no options, an unknown key and a bad option key are left as they were', () => {
    const notes = addItem([], 'core.notes');
    expect(setItemOption(notes, 'core.notes', 's_x', false)).toEqual(notes);
    const qs = addItem([], 'core.questions');
    expect(setItemOption(qs, 'core.questions#i9', 'kind_huddle', false)).toEqual(qs);
    expect(setItemOption(qs, 'core.questions', 'Bad Key', false)).toEqual(qs);
  });

  test('the show header tick is every copy\'s: a widget with no options takes it, round trips it, and a reset keeps it', () => {
    const notes = setItemOption(addItem([], 'core.notes'), 'core.notes', 'show_header', false);
    expect(notes[0]!.options).toEqual({ show_header: false });
    expect(normalizeZone(toStored(notes))).toEqual(notes);
    expect(setItemOption(notes, 'core.notes', 'kind_huddle', false)).toEqual(notes);
    const qs = setItemOption(setItemOption(addItem([], 'core.questions'), 'core.questions', 'kind_huddle', false), 'core.questions', 'show_header', true);
    expect(resetItemOptions(qs, 'core.questions')[0]!.options).toEqual({ show_header: true });
    expect(resetItemOptions(notes.map((item) => ({ ...item, options: { show_header: 'x' } })), 'core.notes')[0]!.options).toBeUndefined();
  });

  test('options round trip through storage per copy, only legal ones are read back', () => {
    const two = setItemOption(addItem(addItem([], 'core.questions'), 'core.questions'), 'core.questions#i2', 'kind_huddle', false);
    const stored = toStored(two);
    expect(stored.items).toEqual([{ widget: 'core.questions' }, { widget: 'core.questions', instance: 'i2', options: { kind_huddle: false } }]);
    expect(normalizeZone(stored)).toEqual(two);
    const dirty = normalizeZone({ v: 1, items: [{ widget: 'core.questions', options: { kind_huddle: false, 'Bad Key': true, s_x: 1.5, s_y: 'x'.repeat(200), s_ok: 'yes' } }] })!;
    expect(dirty[0]!.options).toEqual({ kind_huddle: false, s_ok: 'yes' });
  });
});
