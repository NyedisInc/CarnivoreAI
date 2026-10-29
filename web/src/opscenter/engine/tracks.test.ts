
import { describe, expect, it } from 'vitest';
import { META } from './meta';
import { OLD_DEFAULT_LAYOUT } from './old-default.fixture';
import { moveCell, resetLayout, resizeColumns } from './model';
import { spanDown } from './span-extend';
import { COL_MIN } from './floors';
import { CELL_SQUEEZE_MIN, columnSpace, computeTracks, sharePixels } from './tracks';
import { canSpanDown } from './span-extend';
import type { CellId, Layout, RowId, SlotId } from './types';

const GUTTER = 12;
const WIDTH = 1407;
const HEIGHT = 827;

function home() {
  return computeTracks({ rows: OLD_DEFAULT_LAYOUT.rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
}

function at(tracks: ReturnType<typeof home>, id: RowId) {
  const row = tracks.rows.find((one) => one.id === id);
  if (!row) throw new Error(`no row ${id}`);
  return row;
}

describe('row heights', () => {
  it('gives every row the pixel height the layout stores', () => {
    expect(home().rows.map((row) => row.height)).toEqual([69, 198, 213, 160]);
  });

  it('is as tall as its rows and the bands between them', () => {
    const tracks = home();
    const bands = GUTTER * (tracks.rows.length - 1);
    expect(tracks.contentHeight).toBe(69 + 198 + 213 + 160 + bands);
  });

  it('grows past the box it was measured in rather than squeezing', () => {
    const tracks = computeTracks({ rows: OLD_DEFAULT_LAYOUT.rows, width: WIDTH, height: 400, gutter: GUTTER, metas: META });
    expect(tracks.contentHeight).toBe(home().contentHeight);
    expect(tracks.contentHeight).toBeGreaterThan(400);
  });

  it('writes a track list of whole pixels with a band between each pair', () => {
    expect(home().template).toBe(`69px ${GUTTER}px 198px ${GUTTER}px 213px ${GUTTER}px 160px`);
  });
});

describe('column widths', () => {
  it('divides a row into whole pixels that lose nothing', () => {
    for (const row of home().rows) {
      const cells = row.cells.reduce((sum, cell) => sum + cell.width, 0);
      expect([row.id, cells]).toEqual([row.id, columnSpace(WIDTH, row.cells.length, GUTTER)]);
      for (const cell of row.cells) expect([row.id, Number.isInteger(cell.width)]).toEqual([row.id, true]);
    }
  });

  it('reproduces the widths the drawing measured, to the pixel it rounds to', () => {
    const row = at(home(), 'r3');
    expect(row.cells.map((cell) => cell.width)).toEqual([772, 623]);
    expect(row.cells.map((cell) => cell.x)).toEqual([0, 784]);
  });

  it('lays every cell out left to right with one gutter between', () => {
    for (const row of home().rows) {
      let x = 0;
      for (const cell of row.cells) {
        expect([row.id, cell.x]).toEqual([row.id, x]);
        x += cell.width + GUTTER;
      }
    }
  });
});

describe('a spanning cell', () => {
  const spanned = () =>
    computeTracks({
      rows: spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', WIDTH, GUTTER, META).rows,
      width: WIDTH,
      height: HEIGHT,
      gutter: GUTTER,
      metas: META,
    });

  it('reserves a column of the row below at exactly its own width', () => {
    const tracks = spanned();
    const mine = at(tracks, 'r3').cells[0];
    const below = at(tracks, 'r4').cells;
    expect(below[0]?.slotId).toBeNull();
    expect(below[0]?.width).toBe(mine?.width);
  });

  it('leaves the row below dividing only what is left, one gutter poorer', () => {
    const tracks = spanned();
    const row = at(tracks, 'r4');
    const reserved = row.cells[0]?.width ?? 0;
    expect(row.free).toBe(columnSpace(WIDTH, 4, GUTTER) - reserved);
    const own = row.cells.filter((cell) => cell.slotId !== null).reduce((sum, cell) => sum + cell.width, 0);
    expect(own).toBe(row.free);
  });

  it('is as tall as the rows it covers plus the gutters it crosses', () => {
    const tracks = spanned();
    expect(tracks.spanHeight.get('running-sessions' as SlotId)).toBe(198 + GUTTER + 213);
  });

  it('gives no seam beside a reserved column, so no divider owns that width', () => {
    const row = at(spanned(), 'r4');
    expect(row.cells.map((cell) => cell.slotId === null)).toEqual([true, false, false, false]);
    expect(row.seams.map((seam) => seam.afterVisual)).toEqual([1, 2]);
  });

  it('tightens the seam beside it by what the row it covers can give up', () => {
    let crowded = OLD_DEFAULT_LAYOUT;
    for (const id of ['themes', 'ledger', 'activity-log'] as CellId[]) crowded = moveCell(crowded, id, 'r4', 3);
    const box = { width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META };
    const plain = computeTracks({ rows: crowded.rows, ...box }).rows.find((r) => r.id === 'r3')?.seams[0];
    const withSpan = spanDown(crowded, 'running-sessions', WIDTH, GUTTER, META);
    const tight = computeTracks({ rows: withSpan.rows, ...box }).rows.find((r) => r.id === 'r3')?.seams[0];
    expect(columnSpace(WIDTH, 7, GUTTER) - 6 * COL_MIN).toBeLessThan(tight?.leftPx ?? 0);
    expect(tight?.leftMaxPx).toBe(tight?.leftPx);
    expect(tight?.leftMaxPx).toBeLessThan(plain?.leftMaxPx ?? 0);
    expect(tight?.leftMinPx).toBe(COL_MIN);
  });

  it('lets the seam between two spanning cells travel', () => {
    const layout: Layout = {
      v: 6,
      hidden: [],
      heroCollapsed: false,
      collapsed: [],
      rows: [
        {
          id: 'r1',
          kind: 'px',
          size: 200,
          slots: [
            { id: 'projects', fr: 0.6, span: 3 },
            { id: 'skills', fr: 0.4, span: 2 },
          ],
        },
        {
          id: 'r2',
          kind: 'px',
          size: 100,
          slots: [],
          reserved: [
            { of: 'projects', at: 0 },
            { of: 'skills', at: 1 },
          ],
        },
        {
          id: 'r3',
          kind: 'px',
          size: 200,
          slots: [{ id: 'themes', fr: 1 }],
          reserved: [{ of: 'projects', at: 0 }],
        },
      ],
    };
    const tracks = computeTracks({ rows: layout.rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
    const seam = at(tracks, 'r1').seams[0];
    expect(seam).toBeDefined();
    expect(seam!.leftMinPx).toBeLessThan(seam!.leftPx);
    expect(seam!.leftPx).toBeLessThan(seam!.leftMaxPx);
    const moved = resizeColumns(layout, 'r1', 0, 40, seam!.space, seam!.leftMinPx, seam!.leftMaxPx);
    expect(moved.rows[0]?.slots[0]?.fr).not.toBe(0.6);
  });
});

describe('a flex page', () => {
  it('divides the measured height between its rows and never exceeds it', () => {
    const rows = resetLayout(META, 'terminal').rows;
    const tracks = computeTracks({ rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
    expect(tracks.flexSpace).toBe(HEIGHT);
    expect(tracks.contentHeight).toBe(HEIGHT);
    expect(tracks.rows[0]?.height).toBe(HEIGHT);
  });

  it('shares a budget in whole pixels that add up exactly', () => {
    expect(sharePixels([0.5, 0.5], 101)).toEqual([51, 50]);
    expect(sharePixels([1 / 3, 1 / 3, 1 / 3], 100).reduce((sum, one) => sum + one, 0)).toBe(100);
  });
});

function interior(at: number): Layout {
  return {
    v: 6,
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
    rows: [
      {
        id: 'r1',
        kind: 'px',
        size: 200,
        slots: [
          { id: 'projects', fr: 0.25 },
          { id: 'skills', fr: 0.2, span: 2 },
          { id: 'plugins', fr: 0.55 },
        ],
      },
      {
        id: 'r2',
        kind: 'px',
        size: 200,
        slots: [
          { id: 'themes', fr: 0.4 },
          { id: 'ledger', fr: 0.3 },
          { id: 'activity-log', fr: 0.3 },
        ],
        reserved: [{ of: 'skills', at }],
      },
    ],
  };
}

function tiles(row: ReturnType<typeof at>, gutter: number, width: number): void {
  let edge = 0;
  for (const cell of row.cells) {
    expect(cell.x).toBe(edge);
    edge += cell.width + gutter;
  }
  expect(edge - gutter).toBe(width);
}

describe('a spanning cell and the column reserved for it', () => {
  it('pins the column to the very pixels the panel is drawn at', () => {
    const tracks = computeTracks({ rows: interior(1).rows, width: WIDTH, height: 400, gutter: GUTTER, metas: META });
    const spanner = at(tracks, 'r1').cells.find((cell) => cell.slotId === 'skills');
    const column = at(tracks, 'r2').cells.find((cell) => cell.reserved);
    expect(spanner).toBeDefined();
    expect(column).toBeDefined();
    expect(column!.x).toBe(spanner!.x);
    expect(column!.width).toBe(spanner!.width);
  });

  it('never overlaps a cell, and still tiles the row exactly', () => {
    const tracks = computeTracks({ rows: interior(1).rows, width: WIDTH, height: 400, gutter: GUTTER, metas: META });
    for (const row of tracks.rows) tiles(row, GUTTER, WIDTH);
    const under = at(tracks, 'r2').cells;
    const column = under.find((cell) => cell.reserved)!;
    for (const cell of under) {
      if (cell.slotId === null) continue;
      expect(cell.x + cell.width <= column.x || cell.x >= column.x + column.width).toBe(true);
    }
  });

  it('draws a hole, not a second reserved column, on an empty side', () => {
    const tracks = computeTracks({ rows: interior(0).rows, width: WIDTH, height: 400, gutter: GUTTER, metas: META });
    const under = at(tracks, 'r2');
    const spanner = at(tracks, 'r1').cells.find((cell) => cell.slotId === 'skills')!;
    tiles(under, GUTTER, WIDTH);
    expect(under.cells[0]?.slotId).toBeNull();
    expect(under.cells[0]?.reserved).toBe(false);
    expect(under.cells[1]?.reserved).toBe(true);
    expect(under.cells[1]?.x).toBe(spanner.x);
    expect(under.cells.filter((cell) => cell.reserved).length).toBe(1);
  });

  it('refuses to extend a second cell over a row the first has filled', () => {
    const base = OLD_DEFAULT_LAYOUT;
    const once = spanDown(base, 'running-sessions', WIDTH, GUTTER, META);
    expect(once).not.toBe(base);
    expect(canSpanDown(once, 'closed-sessions', WIDTH, GUTTER, META)).toBe('no-room');
    expect(spanDown(once, 'closed-sessions', WIDTH, GUTTER, META)).toBe(once);
  });

  it('keeps every cell of a spanned row at one tap target or wider', () => {
    const once = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', WIDTH, GUTTER, META);
    const tracks = computeTracks({ rows: once.rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
    for (const row of tracks.rows) {
      tiles(row, GUTTER, WIDTH);
      for (const cell of row.cells) {
        if (cell.slotId !== null) expect(cell.width).toBeGreaterThanOrEqual(CELL_SQUEEZE_MIN);
      }
    }
  });

  it('states a seam conversion that moves the divider with the pointer', () => {
    const tracks = computeTracks({ rows: interior(1).rows, width: WIDTH, height: 400, gutter: GUTTER, metas: META });
    const row = at(tracks, 'r2');
    const seam = row.seams[0];
    expect(seam).toBeDefined();
    expect(seam!.space).not.toBe(row.free);
    const moved = resizeColumns(interior(1), 'r2', seam!.index, 60, seam!.space, seam!.leftMinPx, seam!.leftMaxPx);
    const after = computeTracks({ rows: moved.rows, width: WIDTH, height: 400, gutter: GUTTER, metas: META });
    const grew = at(after, 'r2').cells.find((cell) => cell.slotId === 'ledger')!.width - seam!.leftPx;
    expect(Math.abs(grew - 60)).toBeLessThanOrEqual(1);
  });
});
