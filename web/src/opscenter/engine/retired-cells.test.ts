/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { META } from './meta';
import { resetLayout } from './model';
import { STORAGE_KEYS, load, validate } from './persist';
import { dropRetiredCells } from './retired-cells';
import { v7Layout } from './v7/fixtures/v7-layouts';
import type { Layout, RowModel } from './types';

function withHero(layout: Layout = resetLayout(META, 'home')): Layout {
  const band: RowModel = { id: 'r1', kind: 'px', size: 139, slots: [{ id: 'hero' as never, fr: 1 }] };
  return { ...layout, rows: [band, ...layout.rows] };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe('the default', () => {
  it('has no hero anywhere and no cell record for it', () => {
    const ids = resetLayout(META, 'home').rows.flatMap((row) => row.slots.map((slot) => slot.id));
    expect(ids).not.toContain('hero');
    expect(Object.keys(META)).not.toContain('hero');
  });
});

describe('a stored layout that had the hero', () => {
  it('drops the hero and keeps every other row, size, fraction and span exactly', () => {
    const now = resetLayout(META, 'home');
    now.rows[1]!.size += 31;
    const pair = now.rows.find((row) => row.slots.length === 2)!;
    pair.slots = [{ ...pair.slots[0]!, fr: 0.7 }, { ...pair.slots[1]!, fr: 0.3 }];
    const checked = validate(clone(withHero(now)), META, 'home');
    expect(checked.refusal).toBeNull();
    expect(checked.migrated).toBe(true);
    expect(checked.repaired).toBe(false);
    expect(checked.layout?.rows).toEqual(clone(now.rows));
  });

  it('leaves no empty row behind and keeps the other rows ids', () => {
    const rows = validate(clone(withHero()), META, 'home').layout!.rows;
    expect(rows.some((row) => row.slots.length === 0)).toBe(false);
    expect(rows.map((row) => row.id)).toEqual(resetLayout(META, 'home').rows.map((row) => row.id));
  });

  it('gives the whole width to a cell that shared the hero row', () => {
    const shared = withHero();
    shared.rows[0] = { ...shared.rows[0]!, slots: [{ id: 'hero' as never, fr: 0.5 }, { id: 'notes', fr: 0.5 }] };
    shared.hidden = shared.hidden.filter((id) => id !== 'notes');
    const checked = validate(clone(shared), META, 'home');
    expect(checked.layout!.rows[0]!.slots.map((slot) => [slot.id, slot.fr])).toEqual([['notes', 1]]);
  });

  it('takes it out of hidden and collapsed, and survives a span across its row', () => {
    const odd = withHero();
    odd.rows[1] = {
      ...odd.rows[1]!,
      slots: odd.rows[1]!.slots.map((slot, at) => (at === 0 ? { ...slot, span: 2 } : slot)),
    };
    odd.collapsed = ['hero' as never];
    const checked = validate(clone(odd), META, 'home');
    expect(checked.refusal).toBeNull();
    expect(checked.layout!.collapsed).not.toContain('hero');
  });

  it('is read from a v7 tree the same way', () => {
    const doc = v7Layout('homeWithHero');
    expect(JSON.stringify(doc)).toContain('"id":"hero"');
    const checked = validate(doc, META, 'home');
    expect(checked.refusal).toBeNull();
    expect(checked.migrated).toBe(true);
    expect(checked.layout!.rows.flatMap((row) => row.slots.map((slot) => slot.id))).not.toContain('hero');
  });

  it('is idempotent: a migrated blob migrates to itself, and a clean one is returned as is', () => {
    const once = dropRetiredCells(clone(withHero()), 'home');
    expect(once.migrated).toBe(true);
    const twice = dropRetiredCells(once.raw, 'home');
    expect(twice.migrated).toBe(false);
    expect(twice.raw).toBe(once.raw);
    const clean = clone(resetLayout(META, 'home'));
    expect(dropRetiredCells(clean, 'home')).toEqual({ raw: clean, migrated: false });
    expect(validate(clean, META, 'home').migrated).toBeUndefined();
  });

  it('never touches the terminal page', () => {
    expect(dropRetiredCells(clone(withHero()), 'terminal').migrated).toBe(false);
  });

  it('loads from the local cache quietly and says it was migrated', () => {
    localStorage.setItem(STORAGE_KEYS.home, JSON.stringify(withHero()));
    const opened = load(META, 'home');
    expect(opened.stored).toBe(true);
    expect(opened.migrated).toBe(true);
    expect(opened.notice).toBe('');
    expect(opened.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))).not.toContain('hero');
  });

  it('control: the same blob checked without the step is refused for naming an unknown cell', () => {
    const refused = validate(clone(withHero()), META, 'terminal');
    expect(refused.layout).toBeNull();
    const raw = clone(withHero());
    const asStored = { ...raw, rows: raw.rows.map((row) => ({ ...row })) };
    expect(JSON.stringify(asStored)).toContain('hero');
  });
});
