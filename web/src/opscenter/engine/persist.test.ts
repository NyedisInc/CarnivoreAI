
import { describe, expect, it, vi } from 'vitest';
import { META } from './meta';
import { ROW_MAX, resetLayout, rowFloor } from './model';
import { MAX_VIEWERS } from './model';
import { MAX_BYTES, SCHEMA_VERSION, clear, flushSave, load, save, storageKey, validate } from './persist';
import type { CellId, Layout, SlotId } from './types';

function good(): Record<string, unknown> {
  return JSON.parse(JSON.stringify(resetLayout(META))) as Record<string, unknown>;
}

function goodTerminal(): Record<string, unknown> {
  return JSON.parse(JSON.stringify(resetLayout(META, 'terminal'))) as Record<string, unknown>;
}

function withInstance(blob: Record<string, unknown>, id: string): Record<string, unknown> {
  const all = rows(blob);
  const last = all[all.length - 1];
  if (!last) throw new Error('a blob with no rows to add to');
  (last['slots'] as Record<string, unknown>[]).push({ id, fr: 0.2 });
  return blob;
}

function rows(blob: Record<string, unknown>): Record<string, unknown>[] {
  return blob['rows'] as Record<string, unknown>[];
}

function row(blob: Record<string, unknown>, id: string): Record<string, unknown> {
  const found = rows(blob).find((entry) => entry['id'] === id);
  if (!found) throw new Error(`no row ${id}`);
  return found;
}

describe('validate: structure refuses', () => {
  const refusals: [string, unknown, string][] = [
    ['not an object', 42, 'malformed'],
    ['null', null, 'malformed'],
    ['an array', [], 'malformed'],
    ['no version', { rows: [], hidden: [] }, 'version'],
    ['a future version', { v: 8, rows: [], hidden: [] }, 'version'],
    ['a v7 blob that is not a split tree', { v: 7, rows: [], hidden: [] }, 'tree'],
    ['the first version', { v: 1, rows: [], hidden: [] }, 'version'],
    ['the version before the phone folded set', { v: 2, rows: [], hidden: [], collapsed: [] }, 'version'],
    ['the version before instance cells', { v: 3, rows: [], hidden: [], collapsed: [] }, 'version'],
    ['the version before the notepad', { v: 4, rows: [], hidden: [], collapsed: [] }, 'version'],
    ['the version before the page scrolled', { v: 5, rows: [], hidden: [], collapsed: [] }, 'version'],
    ['no rows', { v: 6, hidden: [] }, 'rows'],
    ['empty rows', { v: 6, rows: [], hidden: [] }, 'rows'],
  ];

  for (const [name, blob, refusal] of refusals) {
    it(`refuses ${name}`, () => {
      const checked = validate(blob, META);
      expect(checked.layout).toBeNull();
      expect(checked.refusal).toBe(refusal);
    });
  }

  it('refuses a row id that is not `r` and a number', () => {
    for (const id of ['r0', 'r01', 'rx', 'r', 'row1', 'hero', 'stats', '']) {
      const blob = good();
      row(blob, 'r3')['id'] = id;
      expect([id, validate(blob, META).refusal]).toEqual([id, 'row-id']);
    }
  });

  it('accepts a numbered cell row well past the three the drawing has', () => {
    const blob = good();
    row(blob, 'r3')['id'] = 'r9';
    expect(validate(blob, META).refusal).toBeNull();
  });

  it('refuses the same row twice', () => {
    const blob = good();
    rows(blob).push(JSON.parse(JSON.stringify(row(blob, 'r3'))));
    expect(validate(blob, META).refusal).toBe('row-id');
  });

  it('refuses a row claiming the wrong kind', () => {
    const blob = good();
    row(blob, 'r3')['kind'] = 'flex';
    expect(validate(blob, META).refusal).toBe('row-kind');
  });

  it('refuses a cell id it does not know', () => {
    const blob = good();
    (row(blob, 'r3')['slots'] as Record<string, unknown>[])[0]!['id'] = 'ghost';
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses the same cell in two rows', () => {
    const blob = good();
    (row(blob, 'r4')['slots'] as Record<string, unknown>[]).push({ id: 'themes', fr: 0.2 });
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses a cell that is in no row and not hidden', () => {
    const blob = good();
    const slots = row(blob, 'r4')['slots'] as Record<string, unknown>[];
    slots.pop();
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses a cell that is both on the surface and hidden', () => {
    const blob = good();
    (blob['hidden'] as string[]).push('themes');
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses hidden that is not a list', () => {
    const blob = good();
    blob['hidden'] = 'themes';
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses an emptied row whose cell went missing with it', () => {
    const blob = good();
    (row(blob, 'r3')['slots'] as unknown[]).length = 0;
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses a layout whose every row was empty', () => {
    const blob = good();
    for (const entry of rows(blob)) (entry['slots'] as unknown[]).length = 0;
    blob['hidden'] = Object.keys(META);
    expect(validate(blob, META).refusal).toBe('rows');
  });
});

describe('validate: numbers repair', () => {
  it('accepts the default layout unchanged', () => {
    const checked = validate(good(), META);
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(false);
    expect(checked.layout?.rows.length).toBe(4);
  });

  it('gives a row with no usable fractions equal shares', () => {
    const blob = good();
    for (const slot of row(blob, 'r4')['slots'] as Record<string, unknown>[]) slot['fr'] = 0;
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(true);
    const repaired = checked.layout?.rows.find((entry) => entry.id === 'r4');
    for (const slot of repaired?.slots ?? []) expect(slot.fr).toBeCloseTo(1 / 3, 10);
  });

  it('renormalises fractions that do not sum to one', () => {
    const blob = good();
    for (const slot of row(blob, 'r3')['slots'] as Record<string, unknown>[]) slot['fr'] = 4;
    const checked = validate(blob, META);
    const repaired = checked.layout?.rows.find((entry) => entry.id === 'r3');
    const total = (repaired?.slots ?? []).reduce((sum, slot) => sum + slot.fr, 0);
    expect(total).toBeCloseTo(1, 10);
  });

  it('replaces a fraction that is not a number', () => {
    const blob = good();
    (row(blob, 'r3')['slots'] as Record<string, unknown>[])[0]!['fr'] = 'wide';
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(true);
    const repaired = checked.layout?.rows.find((entry) => entry.id === 'r3');
    for (const slot of repaired?.slots ?? []) expect(Number.isFinite(slot.fr)).toBe(true);
  });

  it('clamps a row height above the ceiling', () => {
    const blob = good();
    row(blob, 'r2')['size'] = 9000;
    const checked = validate(blob, META);
    expect(checked.layout?.rows.find((entry) => entry.id === 'r2')?.size).toBe(ROW_MAX);
    expect(checked.repaired).toBe(true);
  });

  it('clamps a row height below its own cells floor', () => {
    const blob = good();
    row(blob, 'r2')['size'] = -4;
    const checked = validate(blob, META);
    const strip = checked.layout?.rows.find((entry) => entry.id === 'r2');
    if (!strip) throw new Error('the stat strip row went missing');
    expect(strip.size).toBe(rowFloor(strip, META));
  });

  it('renormalises the flex heights of a TERMINAL blob that do not sum to one', () => {
    const blob = goodTerminal();
    (blob['rows'] as Record<string, unknown>[])[0]!['size'] = 3;
    (blob['rows'] as Record<string, unknown>[]).push({
      id: 'r2',
      kind: 'flex',
      size: 3,
      slots: [{ id: 'themes', fr: 1 }],
    });
    const checked = validate(blob, META, 'terminal');
    const flex = (checked.layout?.rows ?? []).filter((entry) => entry.kind === 'flex');
    expect(flex).toHaveLength(2);
    expect(flex.reduce((sum, entry) => sum + entry.size, 0)).toBeCloseTo(1, 10);
  });

  it('gives every flex row an equal share when one is unusable', () => {
    const blob = goodTerminal();
    (blob['rows'] as Record<string, unknown>[])[0]!['size'] = Number.NaN;
    (blob['rows'] as Record<string, unknown>[]).push({
      id: 'r2',
      kind: 'flex',
      size: 1,
      slots: [{ id: 'themes', fr: 1 }],
    });
    const checked = validate(blob, META, 'terminal');
    for (const entry of checked.layout?.rows ?? []) expect(entry.size).toBeCloseTo(1 / 2, 10);
  });

  it('drops an emptied row and keeps every cell accounted for', () => {
    const blob = good();
    const moved = row(blob, 'r5')['slots'] as { id: CellId; fr: number }[];
    (row(blob, 'r4')['slots'] as unknown[]).push(...moved.map((slot) => ({ id: slot.id, fr: 0.25 })));
    moved.length = 0;
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.layout?.rows.some((entry) => entry.id === 'r5')).toBe(false);
    expect(checked.layout?.rows.find((entry) => entry.id === 'r4')?.slots.length).toBe(5);
  });

  it('keeps a hidden cell hidden', () => {
    const blob = good();
    const slots = row(blob, 'r5')['slots'] as Record<string, unknown>[];
    const removed = slots.shift();
    (blob['hidden'] as string[]).push(removed!['id'] as string);
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.layout?.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects', 'themes']);
  });

  it('reads heroCollapsed as a strict boolean', () => {
    const blob = good();
    blob['heroCollapsed'] = 'yes';
    expect(validate(blob, META).layout?.heroCollapsed).toBe(false);
    blob['heroCollapsed'] = true;
    expect(validate(blob, META).layout?.heroCollapsed).toBe(true);
  });

  it('ignores a stored drop policy entirely', () => {
    const blob = good();
    row(blob, 'r3')['accepts'] = false;
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(JSON.stringify(checked.layout)).not.toContain('accepts');
  });

  it('keeps the rows in the order they were stored, whatever their numbers', () => {
    const blob = good();
    row(blob, 'r4')['id'] = 'r10';
    expect(validate(blob, META).layout?.rows.map((entry) => entry.id)).toEqual(
      ['r2', 'r3', 'r10', 'r5'],
    );
    const reversed = good();
    reversed['rows'] = rows(reversed).slice().reverse();
    expect((validate(reversed, META).layout as Layout).rows.map((entry) => entry.id)).toEqual(
      ['r5', 'r4', 'r3', 'r2'],
    );
  });

  it('carries a span and its reserved column through unchanged', () => {
    const blob = good();
    (row(blob, 'r3')['slots'] as Record<string, unknown>[])[0]!['span'] = 2;
    row(blob, 'r4')['reserved'] = [{ of: 'running-sessions', at: 0 }];
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(false);
    expect(checked.layout?.rows.find((entry) => entry.id === 'r4')?.reserved).toEqual([
      { of: 'running-sessions', at: 0 },
    ]);
  });

  it('refuses a span that is not a number within the bound', () => {
    for (const span of ['two', 0, -3, 1e9, Number.NaN]) {
      const blob = good();
      (row(blob, 'r3')['slots'] as Record<string, unknown>[])[0]!['span'] = span;
      expect([String(span), validate(blob, META).refusal]).toEqual([String(span), 'spans']);
    }
  });

  it('refuses a reserved column of the wrong shape', () => {
    const blob = good();
    row(blob, 'r4')['reserved'] = [{ of: 7, at: 0 }];
    expect(validate(blob, META).refusal).toBe('spans');
  });

  it('clamps a span that reaches past the last row, and says it repaired', () => {
    const blob = good();
    (row(blob, 'r3')['slots'] as Record<string, unknown>[])[0]!['span'] = 9;
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(true);
    const held = checked.layout?.rows.find((entry) => entry.id === 'r3');
    expect(held?.slots[0]?.span).toBe(3);
  });

  it('drops a reserved column naming a cell that is not spanning', () => {
    const blob = good();
    row(blob, 'r4')['reserved'] = [{ of: 'themes', at: 1 }];
    const checked = validate(blob, META);
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(true);
    expect(checked.layout?.rows.find((entry) => entry.id === 'r4')?.reserved).toBeUndefined();
  });
});

describe('the size cap', () => {
  it('is smaller than a blob a user could produce by dragging', () => {
    expect(JSON.stringify(resetLayout(META)).length).toBeLessThan(MAX_BYTES);
  });
});

describe('the phone collapsed set', () => {
  it('is seeded from the records rather than left empty', () => {
    const seeded = resetLayout(META).collapsed;
    const asked = (Object.keys(META) as (keyof typeof META)[]).filter((id) => META[id].phoneCollapsedByDefault === true);
    expect(seeded.length).toBeGreaterThan(0);
    expect(seeded.slice().sort()).toEqual(asked.slice().sort());
  });

  it('survives a round trip through the validator', () => {
    const blob = good();
    blob['collapsed'] = ['themes', 'plugins'];
    expect(validate(blob, META).layout?.collapsed).toEqual(['themes', 'plugins']);
  });

  it('refuses a set that is not an array', () => {
    const blob = good();
    blob['collapsed'] = 'themes';
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses a cell it does not know', () => {
    const blob = good();
    blob['collapsed'] = ['not-a-cell'];
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses the same cell twice', () => {
    const blob = good();
    blob['collapsed'] = ['themes', 'themes'];
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('accepts a cell that is both placed and folded', () => {
    const blob = good();
    blob['collapsed'] = ['running-sessions'];
    expect(validate(blob, META).refusal).toBeNull();
  });

  it('refuses a blob with no collapsed set at all', () => {
    const blob = good();
    delete blob['collapsed'];
    expect(validate(blob, META).refusal).toBe('cells');
  });
});

describe('every cell record carries its phone placement', () => {
  it('gives each cell a unique order', () => {
    const orders = (Object.keys(META) as (keyof typeof META)[]).map((id) => META[id].phoneOrder);
    expect(orders.every((value) => Number.isInteger(value))).toBe(true);
    expect(new Set(orders).size).toBe(orders.length);
  });

  it('caps every list cell and no other', () => {
    expect(META['running-sessions'].phoneCap).toBe(10);
    expect(META['activity-log'].phoneCap).toBe(5);
    expect(META['stat-ledger'].phoneCap).toBeUndefined();
    expect(META.themes.phoneCap).toBeUndefined();
  });
});


interface FakeStore {
  [key: string]: unknown;
}

function installStorage(): Map<string, string> {
  const held = new Map<string, string>();
  const fake = {
    getItem: (key: string) => (held.has(key) ? (held.get(key) as string) : null),
    setItem: (key: string, value: string) => void held.set(key, value),
    removeItem: (key: string) => void held.delete(key),
  };
  (globalThis as unknown as FakeStore)['localStorage'] = fake;
  return held;
}

describe('validate: instance ids', () => {
  it('accepts one on a row, with every singleton still named once', () => {
    const checked = validate(withInstance(good(), 'terminal:sess-7'), META);
    expect(checked.refusal).toBeNull();
    expect(checked.layout?.rows.find((entry) => entry.id === 'r5')?.slots.map((slot) => slot.id)).toContain(
      'terminal:sess-7',
    );
  });

  it('accepts the primary sentinel', () => {
    expect(validate(withInstance(good(), 'terminal:@primary'), META).refusal).toBeNull();
  });

  it('accepts an ADOPTED session id, colon and all', () => {
    for (const id of ['terminal:adopted:cloude_Argent', 'terminal:adopted:cloude_Lantern App']) {
      expect([id, validate(withInstance(good(), id), META).refusal]).toEqual([id, null]);
    }
  });

  it('refuses one that is not spelled the one way', () => {
    const bad = [
      'terminal:',
      'terminal:@other',
      'terminal: x',
      'terminal:x ',
      'terminal:has/slash',
      'terminal:' + 'x'.repeat(65),
      'terminal',
      'viewer:sess-7',
    ];
    for (const id of bad) {
      expect([id, validate(withInstance(good(), id), META).refusal]).toEqual([id, 'cells']);
    }
  });

  it('accepts a browser slot: browser: and sixteen lowercase hex (issue #448)', () => {
    const checked = validate(withInstance(good(), 'browser:0123456789abcdef'), META);
    expect(checked.refusal).toBeNull();
    expect(JSON.stringify(checked.layout)).toContain('browser:0123456789abcdef');
  });

  it('refuses a browser slot spelled any other way', () => {
    const bad = [
      'browser:',
      'browser:@primary',
      'browser:0123456789abcde',
      'browser:0123456789abcdef0',
      'browser:0123456789ABCDEF',
      'browser:0123456789abcdeg',
      'browser:../../etc/passwd',
      'browser:0123456789abcdef ',
      'browsers:0123456789abcdef',
    ];
    for (const id of bad) {
      expect([id, validate(withInstance(good(), id), META).refusal]).toEqual([id, 'cells']);
    }
  });

  it('refuses the same instance twice', () => {
    const blob = withInstance(withInstance(good(), 'terminal:sess-7'), 'terminal:sess-7');
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('refuses an instance that is both on a row and in the hidden list', () => {
    const blob = withInstance(good(), 'terminal:sess-7');
    (blob['hidden'] as string[]).push('terminal:sess-7');
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('does NOT require one: a blob with no instance at all is fine', () => {
    const checked = validate(good(), META);
    expect(checked.refusal).toBeNull();
    expect(JSON.stringify(checked.layout)).not.toContain('terminal:');
  });

  it('still refuses a missing singleton even when an instance makes the count up', () => {
    const blob = good();
    (row(blob, 'r4')['slots'] as Record<string, unknown>[]).pop();
    expect(validate(withInstance(blob, 'terminal:sess-7'), META).refusal).toBe('cells');
  });

  it('accepts exactly the cap of viewers and refuses one more', () => {
    const at = good();
    for (let n = 1; n <= MAX_VIEWERS; n += 1) withInstance(at, `terminal:sess-${n}`);
    expect(validate(at, META).refusal).toBeNull();
    withInstance(at, `terminal:sess-${MAX_VIEWERS + 1}`);
    expect(validate(at, META).refusal).toBe('cells');
  });

  it('counts viewers in the hidden list against the cap too', () => {
    const blob = good();
    for (let n = 1; n <= MAX_VIEWERS; n += 1) withInstance(blob, `terminal:sess-${n}`);
    (blob['hidden'] as string[]).push('terminal:sess-99');
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('accepts the primary plus the full cap of viewers on the terminal page', () => {
    const blob = goodTerminal();
    const slots = (blob['rows'] as Record<string, unknown>[])[0]!['slots'] as Record<string, unknown>[];
    for (let n = 1; n <= MAX_VIEWERS; n += 1) slots.push({ id: `terminal:sess-${n}`, fr: 0.1 });
    const checked = validate(blob, META, 'terminal');
    expect(checked.refusal).toBeNull();
    expect(checked.layout?.rows[0]?.slots).toHaveLength(MAX_VIEWERS + 1);
  });

  it('refuses the seventh viewer on the terminal page even beside the primary', () => {
    const blob = goodTerminal();
    const slots = (blob['rows'] as Record<string, unknown>[])[0]!['slots'] as Record<string, unknown>[];
    for (let n = 1; n <= MAX_VIEWERS + 1; n += 1) slots.push({ id: `terminal:sess-${n}`, fr: 0.1 });
    expect(validate(blob, META, 'terminal').refusal).toBe('cells');
  });

  it('accepts a folded instance, which is a different axis from placement', () => {
    const blob = withInstance(good(), 'terminal:sess-7');
    blob['collapsed'] = ['terminal:sess-7'];
    expect(validate(blob, META).refusal).toBeNull();
  });

  it('refuses a folded id that is neither a cell nor a well formed instance', () => {
    const blob = good();
    blob['collapsed'] = ['terminal:has/slash'];
    expect(validate(blob, META).refusal).toBe('cells');
  });

  it('holds the worst case blob it will accept, which the old cap did not', () => {
    const full = good();
    const longest = 'x'.repeat(64);
    for (let n = 1; n <= MAX_VIEWERS; n += 1) {
      withInstance(full, `terminal:${longest.slice(0, 62)}-${n}`);
    }
    const bytes = JSON.stringify(full).length;
    expect(validate(full, META).refusal).toBeNull();
    expect(bytes).toBeLessThan(MAX_BYTES);
    expect(MAX_BYTES).toBeGreaterThan(8192);
  });

  it('refuses a stored entry longer than the cap without parsing it', () => {
    const held = installStorage();
    held.set(storageKey('home'), 'x'.repeat(MAX_BYTES + 1));
    const opened = load(META, 'home');
    expect(opened.stored).toBe(false);
    expect(opened.notice).not.toBe('');
  });
});

describe('validate: the primary duplicate guard', () => {
  it('refuses a terminal blob naming the session the primary currently shows', () => {
    const blob = withInstance(goodTerminal(), 'terminal:ses_a');
    const checked = validate(blob, META, 'terminal', 'ses_a');
    expect(checked.refusal).toBe('primary-duplicate');
    expect(checked.layout).toBeNull();
  });

  it('accepts the very same blob when the caller does not know the primary session', () => {
    const blob = withInstance(goodTerminal(), 'terminal:ses_a');
    expect(validate(blob, META, 'terminal').refusal).toBeNull();
  });

  it('accepts the very same blob when the primary is showing a different session', () => {
    const blob = withInstance(goodTerminal(), 'terminal:ses_a');
    expect(validate(blob, META, 'terminal', 'ses_b').refusal).toBeNull();
  });

  it('does not apply on the home page, which has no primary sentinel at all', () => {
    const blob = withInstance(good(), 'terminal:ses_a');
    expect(validate(blob, META, 'home', 'ses_a').refusal).toBeNull();
  });

  it('load() forwards the current primary session through to validate()', () => {
    const held = installStorage();
    held.set(storageKey('terminal'), JSON.stringify(withInstance(goodTerminal(), 'terminal:ses_a')));
    const duplicated = load(META, 'terminal', 'ses_a');
    expect(duplicated.stored).toBe(false);
    expect(duplicated.notice).not.toBe('');
    const clean = load(META, 'terminal', 'ses_b');
    expect(clean.stored).toBe(true);
  });
});

describe('validate: the row shape is consulted per page', () => {
  it('accepts the terminal default on the terminal page', () => {
    const checked = validate(goodTerminal(), META, 'terminal');
    expect(checked.refusal).toBeNull();
    expect(checked.layout?.rows).toHaveLength(1);
    expect(checked.layout?.rows[0]?.slots.map((slot) => slot.id)).toEqual(['terminal:@primary']);
  });

  it('refuses a terminal blob naming the old hero band', () => {
    const blob = goodTerminal();
    (blob['rows'] as Record<string, unknown>[]).push({ id: 'hero', kind: 'flex', size: 1, slots: [{ id: 'hero', fr: 1 }] });
    expect(validate(blob, META, 'terminal').refusal).toBe('row-id');
  });

  it('refuses a terminal blob whose rows claim the home kind', () => {
    const blob = goodTerminal();
    (blob['rows'] as Record<string, unknown>[])[0]!['kind'] = 'px';
    expect(validate(blob, META, 'terminal').refusal).toBe('row-kind');
  });

  it('does not require the primary, and a terminal blob without one still reads', () => {
    const blob = goodTerminal();
    (blob['rows'] as Record<string, unknown>[])[0]!['slots'] = [{ id: 'themes', fr: 1 }];
    expect(validate(blob, META, 'terminal').refusal).toBeNull();
  });

  it('does not require the home panels on the terminal page', () => {
    const checked = validate(goodTerminal(), META, 'terminal');
    expect(checked.refusal).toBeNull();
    expect(checked.layout?.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
  });

  it('still refuses a HOME blob whose rows claim the terminal kind', () => {
    const blob = good();
    row(blob, 'r3')['kind'] = 'flex';
    expect(validate(blob, META).refusal).toBe('row-kind');
  });
});

describe('the two pages are two entries', () => {
  it('names a different key for each page', () => {
    expect(storageKey('home')).toBe('cloudecode.opscenter.layout.v1');
    expect(storageKey('terminal')).toBe('cloudecode.opscenter.layout.terminal.v1');
    expect(storageKey('home')).not.toBe(storageKey('terminal'));
  });

  it('reads each page from its own entry and neither from the other', () => {
    const held = installStorage();
    const home = { ...resetLayout(META), heroCollapsed: true };
    const terminal = resetLayout(META, 'terminal');
    save(home, 'home');
    save(terminal, 'terminal');
    flushSave();

    expect(held.size).toBe(2);
    expect(load(META, 'home').layout.heroCollapsed).toBe(true);
    expect(load(META, 'home').stored).toBe(true);
    expect(load(META, 'terminal').layout.rows.map((row) => row.id)).toEqual(['r1']);
    expect(load(META, 'terminal').stored).toBe(true);
  });

  it('forgets one page without touching the other', () => {
    const held = installStorage();
    save(resetLayout(META), 'home');
    save(resetLayout(META, 'terminal'), 'terminal');
    flushSave();
    clear('terminal');
    expect(held.has(storageKey('home'))).toBe(true);
    expect(held.has(storageKey('terminal'))).toBe(false);
    expect(load(META, 'terminal').stored).toBe(false);
  });

  it('opens the terminal page on ONE pane when its entry holds a home layout', () => {
    const held = installStorage();
    held.set(storageKey('terminal'), JSON.stringify(resetLayout(META)));
    const opened = load(META, 'terminal');
    expect(opened.stored).toBe(false);
    expect(opened.layout.rows.map((row) => row.slots.map((slot) => slot.id))).toEqual([['terminal:@primary']]);
  });

  it('opens the home page on the default when its entry holds a v5 blob', () => {
    const held = installStorage();
    const old = { ...(JSON.parse(JSON.stringify(resetLayout(META))) as Record<string, unknown>), v: 5 };
    held.set(storageKey('home'), JSON.stringify(old));
    const opened = load(META, 'home');
    expect(opened.stored).toBe(false);
    expect(opened.notice).not.toBe('');
    expect(opened.layout.rows.map((row) => row.id)).toEqual(['r2', 'r3', 'r4', 'r5']);
  });

  it('declares the version it writes', () => {
    expect(SCHEMA_VERSION).toBe(6);
    expect(resetLayout(META).v).toBe(6);
    expect(resetLayout(META, 'terminal').v).toBe(6);
  });
});


describe('load: a refusal clears what it refused', () => {
  it('says why ONCE, and opens clean on every load after', () => {
    const held = installStorage();
    const key = storageKey('home');
    held.set(key, JSON.stringify({ v: 5, rows: [], hidden: [], collapsed: [] }));

    const first = load(META, 'home');
    expect(first.notice).not.toBe('');
    expect(first.stored).toBe(false);
    expect(first.layout.rows.length).toBeGreaterThan(0);
    expect(held.has(key)).toBe(false);

    const second = load(META, 'home');
    expect(second.notice).toBe('');
    expect(second.stored).toBe(false);
  });

  it('drops a malformed and an oversize entry too, not just an old version', () => {
    for (const [name, text] of [
      ['malformed', '}{not json'],
      ['oversize', `"${'x'.repeat(MAX_BYTES + 1)}"`],
    ] as const) {
      const held = installStorage();
      const key = storageKey('home');
      held.set(key, text);
      const seen = load(META, 'home');
      expect([name, seen.notice === '']).toEqual([name, false]);
      expect([name, held.has(key)]).toEqual([name, false]);
    }
  });

  it('leaves a GOOD entry exactly where it is', () => {
    const held = installStorage();
    const key = storageKey('home');
    const mine = JSON.stringify(good());
    held.set(key, mine);

    const seen = load(META, 'home');
    expect(seen.notice).toBe('');
    expect(seen.stored).toBe(true);
    expect(held.get(key)).toBe(mine);
  });

  it('does not touch the OTHER page when one page is refused', () => {
    const held = installStorage();
    const terminalKey = storageKey('terminal');
    const terminalBlob = JSON.stringify(resetLayout(META, 'terminal'));
    held.set(storageKey('home'), JSON.stringify({ v: 5, rows: [], hidden: [] }));
    held.set(terminalKey, terminalBlob);

    load(META, 'home');
    expect(held.has(storageKey('home'))).toBe(false);
    expect(held.get(terminalKey)).toBe(terminalBlob);
  });
});

describe('flushSave refuses an oversize layout (u161-05)', () => {
  it('keeps the last good entry instead of writing text load() would delete', () => {
    const held = installStorage();
    const good = resetLayout(META);
    save(good, 'home');
    flushSave();
    const key = storageKey('home');
    const before = held.get(key);
    expect(before).toBeDefined();
    const fat = { ...good, hidden: Array.from({ length: 1200 }, (_, at) => `analytics:fat${at}` as SlotId) };
    save(fat, 'home');
    flushSave();
    expect(held.get(key)).toBe(before);
  });

  it('raises one visible toast, once, when the save is refused', () => {
    installStorage();
    const add = vi.fn();
    (globalThis as { ToastManager?: unknown }).ToastManager = { add };
    try {
      const fat = { ...resetLayout(META), hidden: Array.from({ length: 1200 }, (_, at) => `analytics:toast${at}` as SlotId) };
      save(fat, 'terminal', 'ses_toast');
      flushSave();
      save(fat, 'terminal', 'ses_toast');
      flushSave();
      expect(add).toHaveBeenCalledTimes(1);
      expect(add.mock.calls[0]?.[0]).toMatchObject({ local: true, kind: 'LayoutOversize' });
    } finally {
      delete (globalThis as { ToastManager?: unknown }).ToastManager;
    }
  });
});
