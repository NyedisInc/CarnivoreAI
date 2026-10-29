import { describe, expect, test } from 'vitest';
import { META } from './meta';
import { resetLayout } from './model';
import { validate } from './persist';
import { REPLACED_CELLS, replaceCells } from './replaced-cells';
import { STAT_TILE_IDS } from './stat-tile-meta';

const TILES = [...STAT_TILE_IDS];

function preSplit(): Record<string, unknown> {
  return {
    v: 6,
    rows: [
      { id: 'r2', kind: 'px', size: 69, slots: [{ id: 'stats', fr: 0.6 }, { id: 'themes', fr: 0.4 }] },
      { id: 'r3', kind: 'px', size: 198, slots: [{ id: 'running-sessions', fr: 1 }] },
    ],
    hidden: ['notes'],
    heroCollapsed: false,
    collapsed: ['stats'],
  };
}

describe('replaced cells', () => {
  test('the declaration file maps the strip to the six tiles', () => {
    expect(REPLACED_CELLS['stats']).toEqual(TILES);
  });

  test('the six tiles take the strip’s place and share its width', () => {
    const { raw, migrated } = replaceCells(preSplit(), 'home');
    expect(migrated).toBe(true);
    const rows = (raw as { rows: Array<{ id: string; slots: Array<{ id: string; fr: number }> }> }).rows;
    expect(rows[0]!.slots.map((slot) => slot.id)).toEqual([...TILES, 'themes']);
    for (const slot of rows[0]!.slots.slice(0, 6)) expect(slot.fr).toBeCloseTo(0.1, 10);
    expect(rows[1]!.slots).toEqual([{ id: 'running-sessions', fr: 1 }]);
    expect((raw as { collapsed: string[] }).collapsed).toEqual(TILES);
  });

  test('a hidden strip gives six hidden tiles', () => {
    const blob = preSplit();
    blob['rows'] = [{ id: 'r3', kind: 'px', size: 198, slots: [{ id: 'running-sessions', fr: 1 }] }];
    blob['hidden'] = ['stats', 'notes'];
    const { raw } = replaceCells(blob, 'home');
    expect((raw as { hidden: string[] }).hidden).toEqual([...TILES, 'notes']);
  });

  test('a tile the layout already holds is not added twice', () => {
    const blob = preSplit();
    blob['hidden'] = ['notes', 'stat-ledger'];
    const { raw } = replaceCells(blob, 'home');
    const placed = (raw as { rows: Array<{ slots: Array<{ id: string }> }> }).rows[0]!.slots.map((slot) => slot.id);
    expect(placed).not.toContain('stat-ledger');
    expect((raw as { hidden: string[] }).hidden).toEqual(['notes', 'stat-ledger']);
  });

  test('a v7 tree gets the tiles side by side where the leaf was', () => {
    const blob = {
      v: 7,
      variants: {
        wide: {
          root: {
            t: 'split',
            id: 's1',
            dir: 'v',
            unit: 'px',
            sizes: [69, 198],
            children: [
              { t: 'leaf', id: 'stats' },
              { t: 'leaf', id: 'running-sessions' },
            ],
          },
        },
      },
      hidden: [],
      collapsed: [],
      heroCollapsed: false,
    };
    const { raw, migrated } = replaceCells(blob, 'home');
    expect(migrated).toBe(true);
    const root = (raw as { variants: { wide: { root: { children: Array<{ t: string; children?: Array<{ id: string }> }> } } } })
      .variants.wide.root;
    expect(root.children[0]!.t).toBe('split');
    expect(root.children[0]!.children!.map((leaf) => leaf.id)).toEqual(TILES);
  });

  test('a layout without the strip comes back as the same object', () => {
    const fresh = resetLayout(META, 'home');
    expect(replaceCells(fresh, 'home').raw).toBe(fresh);
    expect(replaceCells(preSplit(), 'terminal').migrated).toBe(false);
  });

  test('validate reads a pre-split layout instead of refusing it, and says it migrated', () => {
    const today = resetLayout(META, 'home');
    const old = JSON.parse(JSON.stringify(today)) as { rows: Array<{ id: string; slots: Array<{ id: string; fr: number }> }> };
    const strip = old.rows.find((row) => row.slots.some((slot) => slot.id === 'stat-running'))!;
    strip.slots = [{ id: 'stats', fr: 1 }, ...strip.slots.filter((slot) => !TILES.includes(slot.id as never))];
    const checked = validate(old, META, 'home');
    expect(checked.refusal).toBeNull();
    expect(checked.migrated).toBe(true);
    expect(checked.layout!.rows.map((row) => row.slots.map((slot) => slot.id))).toEqual(
      today.rows.map((row) => row.slots.map((slot) => slot.id)),
    );
  });
});

describe('the retired approvals cell (2026-10-12)', () => {
  const stored = (slots: Array<{ id: string; fr: number }>, hidden: string[]): Record<string, unknown> => ({
    v: 6,
    rows: [{ id: 'r3', kind: 'px', size: 198, slots }],
    hidden,
    heroCollapsed: false,
    collapsed: [],
  });

  test('the declaration file maps it to the questions cell, and the catalog no longer registers it', () => {
    expect(REPLACED_CELLS['approvals']).toEqual(['questions']);
    expect('approvals' in META).toBe(false);
    expect('questions' in META).toBe(true);
  });

  test('a placed approvals cell becomes the questions cell in the same spot and the layout validates', () => {
    const blob = stored([{ id: 'approvals', fr: 0.3 }, { id: 'running-sessions', fr: 0.7 }], []);
    const { raw, migrated } = replaceCells(blob, 'home');
    expect(migrated).toBe(true);
    expect((raw as { rows: Array<{ slots: Array<{ id: string }> }> }).rows[0]!.slots.map((slot) => slot.id)).toEqual(['questions', 'running-sessions']);
  });

  test('a hidden approvals cell becomes a hidden questions cell, and never a second one when questions is already named', () => {
    expect((replaceCells(stored([{ id: 'running-sessions', fr: 1 }], ['approvals']), 'home').raw as { hidden: string[] }).hidden).toEqual(['questions']);
    expect((replaceCells(stored([{ id: 'running-sessions', fr: 1 }], ['approvals', 'questions']), 'home').raw as { hidden: string[] }).hidden).toEqual(['questions']);
  });
});


describe('the renamed Task Manager cells (S8, issue #1711)', () => {
  const stored = (slots: Array<{ id: string; fr: number }>, hidden: string[]): Record<string, unknown> => ({
    v: 6,
    rows: [{ id: 'r3', kind: 'px', size: 198, slots }],
    hidden,
    heroCollapsed: false,
    collapsed: [],
  });
  const RENAMES: Array<[string, string]> = [['huddle', 'task-manager'], ['huddle-all', 'task-manager-all'], ['huddle-list', 'task-list']];

  test('the declaration file maps each old cell to its one successor, and the catalog registers only the new ids', () => {
    for (const [old, fresh] of RENAMES) {
      expect(REPLACED_CELLS[old]).toEqual([fresh]);
      expect(old in META).toBe(false);
      expect(fresh in META).toBe(true);
    }
  });

  test('a placed old cell takes the new id in the same spot with the same width', () => {
    for (const [old, fresh] of RENAMES) {
      const { raw, migrated } = replaceCells(stored([{ id: old, fr: 0.3 }, { id: 'running-sessions', fr: 0.7 }], []), 'home');
      expect(migrated).toBe(true);
      expect((raw as { rows: Array<{ slots: Array<{ id: string; fr: number }> }> }).rows[0]!.slots).toEqual([
        { id: fresh, fr: 0.3 },
        { id: 'running-sessions', fr: 0.7 },
      ]);
    }
  });

  test('a hidden old cell becomes a hidden new cell, never a second one, and a second pass changes nothing', () => {
    const once = replaceCells(stored([{ id: 'running-sessions', fr: 1 }], ['huddle', 'huddle-all', 'huddle-list']), 'home');
    expect((once.raw as { hidden: string[] }).hidden).toEqual(['task-manager', 'task-manager-all', 'task-list']);
    const twice = replaceCells(once.raw, 'home');
    expect(twice.migrated).toBe(false);
    expect(twice.raw).toBe(once.raw);
    const both = replaceCells(stored([{ id: 'running-sessions', fr: 1 }], ['huddle-list', 'task-list']), 'home');
    expect((both.raw as { hidden: string[] }).hidden).toEqual(['task-list']);
  });

  test('an old cell in a v7 tree becomes the new leaf where it stood', () => {
    const blob = {
      v: 7,
      variants: {
        wide: {
          root: {
            t: 'split', id: 's1', dir: 'v', unit: 'px', sizes: [69, 198],
            children: [{ t: 'leaf', id: 'huddle-list' }, { t: 'leaf', id: 'running-sessions' }],
          },
        },
      },
      hidden: [],
    };
    const { raw, migrated } = replaceCells({ ...blob, collapsed: [], heroCollapsed: false } as unknown as Record<string, unknown>, 'home');
    expect(migrated).toBe(true);
    const root = (raw as { variants: { wide: { root: { children: Array<{ t: string; id?: string }> } } } }).variants.wide.root;
    expect(root.children.map((leaf) => leaf.id)).toEqual(['task-list', 'running-sessions']);
  });
});
