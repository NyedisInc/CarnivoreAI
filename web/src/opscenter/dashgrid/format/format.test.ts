import { describe, expect, it } from 'vitest';
import { hit } from '../../../lib/motion-grid/pack';
import { META } from '../../engine/meta';
import { insertDefaultAnalytics, resetLayout } from '../../engine/model';
import { validate } from '../../engine/persist';
import { repairSpans } from '../../engine/spans';
import type { Layout, RowModel, SlotId } from '../../engine/types';
import { readBoardGrid, validateGrid, writeBoardGrid, type BoardBlob, type GridItem } from './grid-format';
import { rowsSig } from './rows-sig';

const ANALYTICS = [1, 2, 3, 4, 5].map((n) => `analytics:00000000-0000-4000-8000-00000000000${n}` as const);

const blobOf = (layout: Layout): BoardBlob => JSON.parse(JSON.stringify(layout)) as BoardBlob;
const ids = (blob: BoardBlob): SlotId[] => blob.rows.flatMap((r) => r.slots.map((s) => s.id));
const row = (id: number, size: number, slots: [SlotId, number, number?][]): RowModel => ({
  id: `r${id}`,
  kind: 'px',
  size,
  slots: slots.map(([sid, fr, span]) => (span ? { id: sid, fr, span } : { id: sid, fr })),
});
const clean = (items: readonly GridItem[]): boolean => items.every((a, i) => items.every((b, j) => i === j || !hit(a, b)));
const inBounds = (items: readonly GridItem[]): boolean => items.every((i) => i.x >= 0 && i.w >= 1 && i.x + i.w <= 24 && i.h >= 1);

const plain = (): BoardBlob => blobOf(insertDefaultAnalytics(resetLayout(META), ANALYTICS));

describe('convert: one fixture per v6 shape', () => {
  it('plain rows: six stat tiles share 24 columns, rows stack on a 40 px pitch', () => {
    const blob = plain();
    const { grid, source } = readBoardGrid(blob);
    const items = grid.layouts['24'];
    expect(source).toBe('converted');
    expect(items.length).toBe(ids(blob).length);
    expect(clean(items) && inBounds(items)).toBe(true);
    const tiles = items.filter((i) => i.id.startsWith('stat-'));
    expect(tiles.map((i) => i.w)).toEqual([4, 4, 4, 4, 4, 4]);
    expect(new Set(tiles.map((i) => i.y)).size).toBe(1);
    const tall = items.find((i) => i.id === 'running-sessions');
    expect(tall?.h).toBeGreaterThanOrEqual(5);
  });

  it('a spanning cell covers its rows and its neighbour sits beside it', () => {
    const layout = repairSpans({
      v: 6,
      rows: [row(1, 200, [['running-sessions', 0.5, 2], ['ledger', 0.5]]), row(2, 200, [['skills', 1]])],
      hidden: [],
      heroCollapsed: false,
      collapsed: [],
    });
    expect(layout.rows[1]?.reserved?.length).toBe(1);
    const items = readBoardGrid(blobOf(layout)).grid.layouts['24'];
    const span = items.find((i) => i.id === 'running-sessions')!;
    const led = items.find((i) => i.id === 'ledger')!;
    const sk = items.find((i) => i.id === 'skills')!;
    expect(span.h).toBeGreaterThanOrEqual(led.h + sk.h);
    expect(clean(items) && inBounds(items)).toBe(true);
    expect(sk.x).toBeGreaterThanOrEqual(span.x + span.w);
  });

  it('hidden cells never become items, and hidden stays in the blob', () => {
    const blob = plain();
    expect(blob.hidden).toContain('projects');
    expect(readBoardGrid(blob).grid.layouts['24'].some((i) => i.id === 'projects')).toBe(false);
  });

  it('instance cells convert like any other', () => {
    const items = readBoardGrid(plain()).grid.layouts['24'];
    expect(items.filter((i) => i.id.startsWith('analytics:')).length).toBe(5);
  });

  it('more than 24 slots in a row wrap onto new bands without overlap', () => {
    const many = Array.from({ length: 30 }, (_, n) => `analytics:00000000-0000-4000-8000-0000000000${String(n).padStart(2, '0')}` as SlotId);
    const blob = blobOf({ v: 6, rows: [row(1, 100, many.map((m) => [m, 1] as [SlotId, number]))], hidden: [], heroCollapsed: false, collapsed: [] });
    const items = readBoardGrid(blob).grid.layouts['24'];
    expect(items.length).toBe(30);
    expect(clean(items) && inBounds(items)).toBe(true);
    expect(Math.max(...items.map((i) => i.y))).toBeGreaterThan(0);
  });

  it('one row, one cell: full width', () => {
    const blob = blobOf({ v: 6, rows: [row(1, 160, [['ledger', 1]])], hidden: [], heroCollapsed: false, collapsed: [] });
    expect(readBoardGrid(blob).grid.layouts['24']).toEqual([{ id: 'ledger', x: 0, y: 0, w: 24, h: 4 }]);
  });
});

describe('read and write', () => {
  it('is idempotent: read, write, read gives the same grid', () => {
    const blob = plain();
    const first = readBoardGrid(blob);
    const written = writeBoardGrid(blob, first.grid, ids(blob));
    const again = readBoardGrid(written);
    expect(again.source).toBe('grid');
    expect(again.grid.layouts).toEqual(first.grid.layouts);
  });

  it('keeps rows byte identical when the widget set is unchanged', () => {
    const blob = plain();
    const before = JSON.stringify(blob.rows);
    const grid = readBoardGrid(blob).grid;
    const moved = { ...grid, layouts: { '24': grid.layouts['24'].map((i, n) => (n === 0 ? { ...i, y: i.y + 3 } : i)) } };
    const written = writeBoardGrid(blob, moved, ids(blob));
    expect(JSON.stringify(written.rows)).toBe(before);
    expect(written.grid && (written.grid as { rowsSig: string }).rowsSig).toBe(rowsSig(blob.rows));
    expect(JSON.stringify(blob.rows)).toBe(before);
  });

  it('a row edited by the old engine falls back to conversion', () => {
    const blob = plain();
    const written = writeBoardGrid(blob, readBoardGrid(blob).grid, ids(blob));
    const edited = { ...written, rows: written.rows.map((r, n) => (n === 0 ? { ...r, size: r.size + 40 } : r)) };
    expect(readBoardGrid(edited).source).toBe('converted');
  });

  it('an added widget becomes a new bottom row at its own height', () => {
    const blob = plain();
    const grid = readBoardGrid(blob).grid;
    const items = [...grid.layouts['24'], { id: 'notes' as SlotId, x: 0, y: 40, w: 8, h: 6 }];
    const written = writeBoardGrid(blob, { ...grid, layouts: { '24': items } }, [...ids(blob), 'notes']);
    const last = written.rows[written.rows.length - 1]!;
    expect(last.slots).toEqual([{ id: 'notes', fr: 1 }]);
    expect(last.kind).toBe('px');
    expect(last.size).toBeGreaterThan(0);
    expect(written.rows.slice(0, -1)).toEqual(blob.rows);
    expect(readBoardGrid(written).source).toBe('grid');
  });

  it('a removed widget leaves its row, an emptied row is dropped and the blob still validates', () => {
    const blob = blobOf({ v: 6, rows: [row(1, 200, [['running-sessions', 0.5, 2], ['ledger', 0.5]]), row(2, 120, [['skills', 1]])], hidden: [], heroCollapsed: false, collapsed: [] });
    blob.rows = repairSpans(blob as unknown as Layout).rows;
    const grid = readBoardGrid(blob).grid;
    const keep = ['running-sessions', 'ledger'] as SlotId[];
    const written = writeBoardGrid(blob, { ...grid, layouts: { '24': grid.layouts['24'].filter((i) => keep.includes(i.id)) } }, keep);
    expect(ids(written)).toEqual(keep);
    const gone = writeBoardGrid(blob, { ...grid, layouts: { '24': grid.layouts['24'].filter((i) => i.id !== 'running-sessions') } }, ['ledger', 'skills']);
    expect(ids(gone)).toEqual(['ledger', 'skills']);
    expect(gone.rows.every((r) => !r.reserved?.some((x) => x.of === 'running-sessions'))).toBe(true);
  });

  it('a removed instance leaves a blob that master still validates', () => {
    const blob = plain();
    const keep = ids(blob).filter((id) => id !== ANALYTICS[4]);
    const grid = readBoardGrid(blob).grid;
    const written = writeBoardGrid(blob, { ...grid, layouts: { '24': grid.layouts['24'].filter((i) => keep.includes(i.id)) } }, keep);
    expect(ids(written)).toEqual(keep);
    expect(validate(written, META, 'home').layout).not.toBeNull();
  });

  it('refuses a grid whose ids differ from the membership', () => {
    const blob = plain();
    expect(() => writeBoardGrid(blob, readBoardGrid(blob).grid, ['ledger'])).toThrow(RangeError);
  });
});

describe('validateGrid', () => {
  const base = (items: unknown) => ({ v: 1, cols: 24, pitch: 40, layouts: { '24': items }, rowsSig: 'x' });
  it('accepts a good grid', () => expect(validateGrid(base([{ id: 'a', x: 0, y: 0, w: 24, h: 1 }]))).toBe(true));
  it.each([
    ['overflow', [{ id: 'a', x: 1, y: 0, w: 24, h: 1 }]],
    ['zero height', [{ id: 'a', x: 0, y: 0, w: 1, h: 0 }]],
    ['too tall', [{ id: 'a', x: 0, y: 0, w: 1, h: 61 }]],
    ['fraction', [{ id: 'a', x: 0.5, y: 0, w: 1, h: 1 }]],
    ['negative x', [{ id: 'a', x: -1, y: 0, w: 1, h: 1 }]],
    ['duplicate ids', [{ id: 'a', x: 0, y: 0, w: 1, h: 1 }, { id: 'a', x: 1, y: 0, w: 1, h: 1 }]],
    ['201 items', Array.from({ length: 201 }, (_, n) => ({ id: `i${n}`, x: 0, y: n, w: 1, h: 1 }))],
  ])('refuses %s', (_name, items) => expect(validateGrid(base(items))).toBe(false));
  it('refuses a wrong version or column count', () => {
    expect(validateGrid({ ...base([]), v: 2 })).toBe(false);
    expect(validateGrid({ ...base([]), cols: 12 })).toBe(false);
  });
});

describe('master compatibility and size', () => {
  it("master's validate accepts a blob that carries a grid (the old engine ignores the key)", () => {
    const blob = plain();
    const written = writeBoardGrid(blob, readBoardGrid(blob).grid, ids(blob));
    const checked = validate(written, META, 'home');
    expect(checked.refusal).toBeNull();
    expect(checked.layout).not.toBeNull();
    expect(checked.layout?.rows.length).toBe(blob.rows.length);
  });

  it('a 40 item grid blob stays far under the 16384 byte layout cap', () => {
    const items: GridItem[] = Array.from({ length: 40 }, (_, n) => ({ id: `analytics:00000000-0000-4000-8000-0000000000${String(n).padStart(2, '0')}` as SlotId, x: (n % 6) * 4, y: Math.floor(n / 6) * 6, w: 4, h: 6 }));
    const blob = blobOf({ v: 6, rows: [row(1, 100, [['ledger', 1]])], hidden: [], heroCollapsed: false, collapsed: [] });
    const grid = { v: 1 as const, cols: 24 as const, pitch: 40 as const, layouts: { '24': items }, rowsSig: rowsSig(blob.rows) };
    expect(JSON.stringify({ ...blob, grid }).length).toBeLessThan(8000);
  });
});

describe('convert: caps', () => {
  it('two tall px rows convert inside the grid height limit and write', () => {
    const blob = blobOf({ v: 6, rows: [row(1, 1600, [['ledger', 1, 2]]), row(2, 1600, [['analytics:00000000-0000-4000-8000-000000000001', 1]])], hidden: [], heroCollapsed: false, collapsed: [] });
    const { grid } = readBoardGrid(blob);
    expect(grid.layouts['24'].every((i) => i.h <= 60)).toBe(true);
    expect(() => writeBoardGrid(blob, grid, ids(blob))).not.toThrow();
  });
});

describe('rowsSig', () => {
  it('ignores key order and changes with content', () => {
    expect(rowsSig([{ a: 1, b: 2 }])).toBe(rowsSig([{ b: 2, a: 1 }]));
    expect(rowsSig([{ a: 1 }])).not.toBe(rowsSig([{ a: 2 }]));
    expect(rowsSig([])).toMatch(/^[0-9a-f]{16}$/);
  });
});
