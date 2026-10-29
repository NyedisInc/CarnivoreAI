
import { COL_MIN, ROW_MIN } from './floors';
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_LAYOUT as LIVE_DEFAULT,
  MAX_VIEWERS,
  addInstance,
  arrangeColumns,
  arrangeGrid,
  arrangeRows,
  instancesOf,
  viewersOf,
  removeCell,
  ROW_MAX,
  fitRows,
  hideCell,
  moveCell,
  moveCellToNewRow,
  normalizeRow,
  resetHeights,
  resetLayout,
  resetRow,
  resizeColumns,
  resizeIntersection,
  resizeRows,
  rowFloor,
  rowOf,
  rowOfCell,
  setRowHeight,
  showCell,
  offSurfaceIds,
} from './model';
import { OLD_DEFAULT_LAYOUT } from './old-default.fixture';
import { canSpanDown, spanDown } from './span-extend';
import { repairSpans, spanUp, visualOrder } from './spans';
import { columnSpace, computeTracks } from './tracks';
import { META, metaFor, phoneOrderOf } from './meta';
import type { CellId, Layout, RowId, RowModel, SlotId } from './types';

const DEFAULT_LAYOUT = OLD_DEFAULT_LAYOUT;
const GUTTER = 12;
const ROW_WIDTH = 1407;
const SURFACE_H = 827;
const FLEX_SPACE = 572;

function crowded(): Layout {
  let layout = OLD_DEFAULT_LAYOUT;
  for (const id of ['themes', 'ledger', 'activity-log'] as CellId[]) layout = moveCell(layout, id, 'r4', 3);
  return layout;
}

function seam(layout: Layout, rowId: RowId, index: number): [number, number, number] {
  const tracks = computeTracks({ rows: layout.rows, width: ROW_WIDTH, height: SURFACE_H, gutter: GUTTER, metas: META });
  const row = tracks.rows.find((one) => one.id === rowId);
  const found = row?.seams.find((one) => one.index === index);
  if (!row || !found) throw new Error(`no seam ${index} in ${rowId}`);
  return [row.free, found.leftMinPx, found.leftMaxPx];
}

function sums(layout: Layout): number[] {
  return layout.rows.filter((row) => row.slots.length).map((row) => row.slots.reduce((t, s) => t + s.fr, 0));
}

function place(layout: Layout, id: CellId): [string, number] {
  const row = rowOfCell(layout, id);
  return [row?.id ?? 'none', row ? row.slots.findIndex((slot) => slot.id === id) : -1];
}

describe('the default layout', () => {
  it('puts every cell it places in its declared row and index', () => {
    for (const id of Object.keys(META) as CellId[]) {
      if (LIVE_DEFAULT.hidden.includes(id)) continue;
      const meta = META[id];
      expect(place(LIVE_DEFAULT, id)).toEqual([meta.defaultRow, meta.defaultIndex]);
    }
  });

  it('opens with the notepad OFF the surface, and named exactly once', () => {
    expect(LIVE_DEFAULT.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
    expect(rowOfCell(LIVE_DEFAULT, 'notes')).toBeUndefined();
    expect(resetLayout(META, 'terminal').hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
  });

  it('places the file browser even for a layout stored before it existed', () => {
    const old = resetLayout(META, 'terminal');
    const stored = { ...old, hidden: old.hidden.filter((id) => id !== 'files') };
    const shown = showCell(stored, 'files', META);
    expect(rowOfCell(shown, 'files')?.id).toBe('r1');
    expect(shown.hidden).not.toContain('files');
    expect(showCell(shown, 'files', META)).toBe(shown);
  });

  it('puts the notepad in its declared slot the moment it is shown', () => {
    const shown = showCell(resetLayout(META, 'terminal'), 'notes', META);
    expect(shown.hidden).toEqual(['files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
    expect(rowOfCell(shown, 'notes')?.id).toBe('r1');
    expect(rowOf(shown, 'r1')?.slots.map((slot) => slot.id)).toEqual([
      'terminal:@primary',
      'notes',
    ]);
  });

  it('gives every row fractions that sum to one', () => {
    for (const total of sums(LIVE_DEFAULT)) expect(total).toBeCloseTo(1, 10);
  });

  it('reproduces the mockup width of every drawn cell to within the gate tolerance', () => {
    const measured: Record<string, number> = {
      'running-sessions': 742,
      ledger: 653,
      'closed-sessions': 461,
      skills: 461,
      plugins: 461,
    };
    for (const [id, want] of Object.entries(measured)) {
      const row = rowOfCell(LIVE_DEFAULT, id as CellId);
      if (!row) throw new Error(`no row for ${id}`);
      const space = columnSpace(ROW_WIDTH, row.slots.length, GUTTER);
      const slot = row.slots.find((entry) => entry.id === id);
      expect([id, Math.abs((slot?.fr ?? 0) * space - want) <= 3]).toEqual([id, true]);
    }
  });

  it('gives row 5 its three declared shares', () => {
    const row = rowOf(LIVE_DEFAULT, 'r5');
    expect(row?.slots.map((slot) => slot.id)).toEqual(['themes', 'activity-log']);
    expect(row?.slots.map((slot) => Number(slot.fr.toFixed(2)))).toEqual([0.46, 0.54]);
  });

  it('lands each cell on the state the mockup draws', () => {
    const expected: Record<string, [string, string]> = {
      'running-sessions': ['full', 'rows-3'],
      'closed-sessions': ['full', 'rows-5'],
      projects: ['type', 'rows-6'],
      skills: ['description', 'rows-5'],
      plugins: ['description', 'rows-5'],
      themes: ['tiles-3', 'tiles-1row'],
      ledger: ['window', 'rows'],
      'activity-log': ['seconds', 'lines-8'],
    };
    const widths: Record<string, number> = {
      'running-sessions': 772,
      'closed-sessions': 621,
      projects: 463,
      skills: 460,
      plugins: 454,
      themes: 387,
      ledger: 497,
      'activity-log': 497,
    };
    const heights: Record<string, number> = {
      'running-sessions': 196,
      'closed-sessions': 198,
      projects: 212,
      skills: 213,
      plugins: 212,
      themes: 158,
      ledger: 158,
      'activity-log': 159,
    };
    const last = (steps: { name: string; min: number }[], px: number) =>
      steps.reduce((best, step) => (px >= step.min ? step.name : best), steps[0]?.name ?? '');
    for (const [id, [width, height]] of Object.entries(expected)) {
      const meta = META[id as CellId];
      expect([id, last(meta.widthStates, widths[id] ?? 0)]).toEqual([id, width]);
      expect([id, last(meta.heightStates, heights[id] ?? 0)]).toEqual([id, height]);
    }
  });
});

describe('resizeColumns', () => {
  it('conserves the row total and touches only the two neighbours', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const after = resizeColumns(before, 'r4', 0, -120, ...seam(before, 'r4', 0));
    for (const total of sums(after)) expect(total).toBeCloseTo(1, 10);
    const third = (l: Layout) => rowOf(l, 'r4')?.slots[2]?.fr ?? 0;
    expect(third(after)).toBeCloseTo(third(before), 12);
  });

  it('moves the divider by the requested pixels', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const [free] = seam(before, 'r3', 0);
    const after = resizeColumns(before, 'r3', 0, -200, ...seam(before, 'r3', 0));
    const moved = ((rowOf(before, 'r3')?.slots[0]?.fr ?? 0) - (rowOf(after, 'r3')?.slots[0]?.fr ?? 0)) * free;
    expect(Math.abs(moved - 200)).toBeLessThanOrEqual(0.5);
  });

  it('computes from the origin, so two deltas equal one combined delta', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const once = resizeColumns(before, 'r3', 0, -180, ...seam(before, 'r3', 0));
    const twice = resizeColumns(before, 'r3', 0, -180, ...seam(before, 'r3', 0));
    expect(rowOf(twice, 'r3')?.slots[0]?.fr).toBeCloseTo(rowOf(once, 'r3')?.slots[0]?.fr ?? 0, 12);
  });

  it('returns exactly to the origin when dragged back', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const out = resizeColumns(before, 'r3', 0, -240, ...seam(before, 'r3', 0));
    const back = resizeColumns(before, 'r3', 0, 0, ...seam(before, 'r3', 0));
    expect(out).not.toEqual(back);
    expect(back.rows).toEqual(before.rows);
  });

  it('clamps at the neighbour minimum instead of crossing it', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const [free] = seam(before, 'r3', 0);
    const after = resizeColumns(before, 'r3', 0, -5000, ...seam(before, 'r3', 0));
    expect((rowOf(after, 'r3')?.slots[0]?.fr ?? 0) * free).toBeCloseTo(COL_MIN, 6);
  });

  it('ignores a divider index that is not between two cells', () => {
    const before = OLD_DEFAULT_LAYOUT;
    expect(resizeColumns(before, 'r3', 1, -50, 900, 100, 700)).toBe(before);
    expect(resizeColumns(before, 'r3', -1, -50, 900, 100, 700)).toBe(before);
  });

  it('stops a spanner widening past what the row it covers can give up', () => {
    const spanned = spanDown(crowded(), 'running-sessions', ROW_WIDTH, GUTTER, META);
    const [free, low, high] = seam(spanned, 'r3', 0);
    const plain = seam(crowded(), 'r3', 0);
    expect(high).toBeLessThan(plain[2]);
    const after = resizeColumns(spanned, 'r3', 0, 5000, free, low, high);
    expect((rowOf(after, 'r3')?.slots[0]?.fr ?? 0) * free).toBeCloseTo(high, 6);
  });
});

describe('resizeRows', () => {
  it('grows a pixel row without touching any other row', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const after = resizeRows(before, 'r2', 40, 0, META);
    expect(rowOf(after, 'r2')?.size).toBe(109);
    for (const id of ['r1', 'r3', 'r4', 'r5'] as RowId[]) {
      expect([id, rowOf(after, id)?.size]).toEqual([id, rowOf(before, id)?.size]);
    }
  });

  it('clamps a pixel row at its own cells floor and at the engine ceiling, never a widget ceiling', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const strip = rowOf(before, 'r2');
    if (!strip) throw new Error('no stat strip row');
    expect(rowOf(resizeRows(before, 'r2', -5000, 0, META), 'r2')?.size).toBe(Math.min(strip.size, rowFloor(strip, META)));
    expect(rowOf(resizeRows(before, 'r2', 9000, 0, META), 'r2')?.size).toBe(ROW_MAX);
  });

  it('stops every row at the one grid floor', () => {
    const before = showCell(OLD_DEFAULT_LAYOUT, 'notes', META);
    const home = rowOfCell(before, 'notes');
    if (!home) throw new Error('the notepad went nowhere');
    const after = resizeRows(before, home.id, -5000, 0, META);
    expect(rowOf(after, home.id)?.size).toBe(ROW_MIN);
    expect(META.notes.minHeight).toBeGreaterThan(ROW_MIN);
  });

  it('moves a fraction between two flex rows and conserves their total', () => {
    const before = surface(9);
    const after = resizeRows(before, 'r1', 60, FLEX_SPACE, META);
    const pair = (l: Layout) => (rowOf(l, 'r1')?.size ?? 0) + (rowOf(l, 'r2')?.size ?? 0);
    expect(pair(after)).toBeCloseTo(pair(before), 12);
    expect(rowOf(after, 'r3')?.size).toBeCloseTo(rowOf(before, 'r3')?.size ?? 0, 12);
  });

  it('clamps a flex row at its floor', () => {
    const after = resizeRows(surface(9), 'r1', -4000, FLEX_SPACE, META);
    expect((rowOf(after, 'r1')?.size ?? 0) * FLEX_SPACE).toBeCloseTo(ROW_MIN, 6);
  });

  it('grows a flex row by taking from the rows below it when the nearest is at its floor', () => {
    const floor = ROW_MIN / FLEX_SPACE;
    const rows: RowModel[] = [
      { id: 'r7', kind: 'flex', size: 0.32, slots: [{ id: 'terminal:@primary', fr: 0.5, span: 4 }, { id: 'terminal:a', fr: 0.5 }] },
      { id: 'r6', kind: 'flex', size: floor, slots: [{ id: 'terminal:b', fr: 1, span: 3 }], reserved: [{ of: 'terminal:@primary', at: 0 }] },
      { id: 'r5', kind: 'flex', size: 0.4, slots: [], reserved: [{ of: 'terminal:@primary', at: 0 }, { of: 'terminal:b', at: 0 }] },
      { id: 'r4', kind: 'flex', size: 0.3, slots: [], reserved: [{ of: 'terminal:@primary', at: 0 }, { of: 'terminal:b', at: 0 }] },
    ];
    const before: Layout = { v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] };
    const after = resizeRows(before, 'r7', 100, FLEX_SPACE, META);
    const size = (l: Layout, id: RowId) => rowOf(l, id)?.size ?? 0;
    expect(size(after, 'r7') - size(before, 'r7')).toBeCloseTo(100 / FLEX_SPACE, 12);
    expect(size(after, 'r6')).toBeCloseTo(floor, 12);
    expect(size(after, 'r5')).toBeCloseTo(size(before, 'r5') - 100 / FLEX_SPACE, 12);
    const total = (l: Layout) => l.rows.reduce((carry, row) => carry + row.size, 0);
    expect(total(after)).toBeCloseTo(total(before), 12);
    const far = resizeRows(before, 'r7', 9000, FLEX_SPACE, META);
    expect(size(far, 'r4')).toBeCloseTo(floor, 12);
    expect(total(far)).toBeCloseTo(total(before), 12);
  });
});

describe('row heights', () => {
  it('sets one row height, clamped to what its cells allow', () => {
    const before = OLD_DEFAULT_LAYOUT;
    expect(rowOf(setRowHeight(before, 'r2', 44, META), 'r2')?.size).toBe(Math.min(rowOf(before, 'r2')!.size, rowFloor(rowOf(before, 'r2')!, META)));
    expect(rowOf(setRowHeight(before, 'r2', 9000, META), 'r2')?.size).toBe(ROW_MAX);
    expect(setRowHeight(before, 'r2', rowOf(before, 'r2')?.size ?? 0, META)).toBe(before);
  });

  it('opens every row at the tallest default its own cells ask for', () => {
    const before = LIVE_DEFAULT;
    expect(before.rows.map((row) => row.size)).toEqual([69, 279, 198, 160]);
    const squashed = setRowHeight(before, 'r4', 300, META);
    expect(resetHeights(squashed, META).rows.map((row) => row.size)).toEqual(before.rows.map((row) => row.size));
  });

  it('scales every row so the surface is exactly as tall as the space given', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const gutters = GUTTER * (before.rows.length - 1);
    const after = fitRows(before, SURFACE_H, GUTTER, META);
    expect(after.rows.reduce((sum, row) => sum + row.size, 0)).toBe(SURFACE_H - gutters);
    const ratio = (l: Layout) => (rowOf(l, 'r3')?.size ?? 0) / (rowOf(l, 'r4')?.size ?? 1);
    expect(ratio(after)).toBeCloseTo(ratio(before), 1);
  });

  it('never fits a row under its own floor, even into a window that small', () => {
    const after = fitRows(OLD_DEFAULT_LAYOUT, 100, GUTTER, META);
    const was = OLD_DEFAULT_LAYOUT;
    for (const row of after.rows) expect([row.id, row.size]).toEqual([row.id, Math.min(rowOf(was, row.id)!.size, rowFloor(row, META))]);
  });

  it('leaves a flex page alone, whose heights are shares and not pixels', () => {
    const terminal = resetLayout(META, 'terminal');
    expect(fitRows(terminal, SURFACE_H, GUTTER, META)).toBe(terminal);
  });
});

describe('resizeIntersection', () => {
  it('moves one column divider and one row boundary, and nothing else', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const after = resizeIntersection(before, 'r3', 0, -80, 60, ...seam(before, 'r3', 0), FLEX_SPACE, META);
    expect(rowOf(after, 'r3')?.slots[0]?.fr).not.toBeCloseTo(rowOf(before, 'r3')?.slots[0]?.fr ?? 0, 6);
    expect(rowOf(after, 'r3')?.size).not.toBeCloseTo(rowOf(before, 'r3')?.size ?? 0, 6);
    expect(rowOf(after, 'r5')?.slots.map((s) => s.fr)).toEqual(rowOf(before, 'r5')?.slots.map((s) => s.fr));
  });

  it('clamps each axis on its own', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const [free] = seam(before, 'r3', 0);
    const after = resizeIntersection(before, 'r3', 0, -9000, 40, ...seam(before, 'r3', 0), FLEX_SPACE, META);
    expect((rowOf(after, 'r3')?.slots[0]?.fr ?? 0) * free).toBeCloseTo(COL_MIN, 6);
    expect(rowOf(after, 'r3')?.size).toBeGreaterThan(rowOf(before, 'r3')?.size ?? 0);
  });
});

describe('moveCell', () => {
  it('gives the arrival an equal share and keeps the incumbents in proportion', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const ratio = (l: Layout) => {
      const slots = rowOf(l, 'r3')?.slots ?? [];
      return (slots[0]?.fr ?? 0) / (slots[1]?.fr ?? 1);
    };
    const after = moveCell(before, 'plugins', 'r3', 2);
    expect(rowOf(after, 'r3')?.slots).toHaveLength(3);
    expect(rowOf(after, 'r3')?.slots[2]?.fr).toBeCloseTo(1 / 3, 10);
    expect(ratio(after)).toBeCloseTo(ratio(before), 10);
    for (const total of sums(after)) expect(total).toBeCloseTo(1, 10);
  });

  it('renormalises the row the cell left', () => {
    const after = moveCell(OLD_DEFAULT_LAYOUT, 'plugins', 'r3', 2);
    const row = rowOf(after, 'r4');
    expect(row?.slots).toHaveLength(2);
    expect(row?.slots.reduce((t, s) => t + s.fr, 0)).toBeCloseTo(1, 10);
  });

  it('removes a row it emptied', () => {
    let layout = moveCell(OLD_DEFAULT_LAYOUT, 'themes', 'r3', 2);
    layout = moveCell(layout, 'ledger', 'r3', 3);
    layout = moveCell(layout, 'activity-log', 'r3', 4);
    expect(rowOf(layout, 'r5')).toBeUndefined();
    expect(rowOf(layout, 'r3')?.slots).toHaveLength(5);
  });

  it('lands a cell in the row the masthead is in', () => {
    const after = moveCell(OLD_DEFAULT_LAYOUT, 'themes', 'r2', 1);
    expect(rowOf(after, 'r2')?.slots.map((s) => s.id)).toEqual(['stat-running', 'themes', 'stat-sessions', 'stat-projects', 'stat-ledger', 'stat-alive', 'stat-subagents']);
  });

  it('reorders within a row without changing the total', () => {
    const after = moveCell(OLD_DEFAULT_LAYOUT, 'plugins', 'r4', 0);
    expect(rowOf(after, 'r4')?.slots.map((s) => s.id)).toEqual(['plugins', 'projects', 'skills']);
    expect(rowOf(after, 'r4')?.slots.reduce((t, s) => t + s.fr, 0)).toBeCloseTo(1, 10);
  });

  it('reads the drop index as a drawn column, past a reserved one', () => {
    const spanned = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    const after = moveCell(spanned, 'themes', 'r4', 1);
    expect(rowOf(after, 'r4')?.slots.map((s) => s.id)).toEqual(['themes', 'projects', 'skills', 'plugins']);
  });

  it('stops a moved cell spanning, because its span was about where it was', () => {
    const spanned = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    expect(rowOf(spanned, 'r4')?.reserved).toHaveLength(1);
    const after = moveCell(spanned, 'running-sessions', 'r5', 0);
    expect(rowOf(after, 'r4')?.reserved).toBeUndefined();
    expect(rowOf(after, 'r5')?.slots[0]?.span).toBeUndefined();
  });
});

describe('moveCellToNewRow', () => {
  it('splices the row where it was dropped and keeps the array order', () => {
    const after = moveCellToNewRow(OLD_DEFAULT_LAYOUT, 'themes', 'r3', META);
    expect(after.rows.map((row) => row.id)).toEqual(['r2', 'r3', 'r6', 'r4', 'r5']);
    expect(rowOf(after, 'r6')?.slots.map((s) => s.id)).toEqual(['themes']);
    expect(rowOf(after, 'r5')?.slots.map((s) => s.id)).toEqual(['ledger', 'activity-log']);
  });

  it('opens the minted row at the height the cell asks for', () => {
    const after = moveCellToNewRow(OLD_DEFAULT_LAYOUT, 'themes', 'r3', META);
    expect(rowOf(after, 'r6')?.size).toBe(META.themes.defaultHeight);
    expect(rowOf(after, 'r6')?.kind).toBe('px');
  });

  it('puts a cell above every row when nothing is named', () => {
    const after = moveCellToNewRow(OLD_DEFAULT_LAYOUT, 'themes', null, META);
    expect(after.rows[0]?.slots.map((s) => s.id)).toEqual(['themes']);
  });

  it('drops the row the cell was alone in, so a pointless move is no move', () => {
    const one = moveCellToNewRow(OLD_DEFAULT_LAYOUT, 'themes', 'r3', META);
    expect(moveCellToNewRow(one, 'themes', 'r3', META)).toBe(one);
  });

  it('gives a flex page a fresh even split rather than a pixel height', () => {
    const before = surface(6);
    const after = moveCellToNewRow(before, fake(1), 'r1', META);
    expect(after.rows).toHaveLength(3);
    for (const row of after.rows) expect(row.size).toBeCloseTo(1 / 3, 10);
  });
});

describe('spanning a cell down a row', () => {
  it('reserves a column of the row below and leaves the rest to its cells', () => {
    const after = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    expect(rowOf(after, 'r3')?.slots[0]?.span).toBe(2);
    expect(rowOf(after, 'r4')?.reserved).toEqual([{ of: 'running-sessions', at: 0 }]);
    expect(rowOf(after, 'r4')?.slots.map((s) => s.id)).toEqual(['projects', 'skills', 'plugins']);
  });

  it('reserves the side the spanner is actually drawn on', () => {
    const after = spanDown(OLD_DEFAULT_LAYOUT, 'closed-sessions', ROW_WIDTH, GUTTER, META);
    expect(rowOf(after, 'r4')?.reserved).toEqual([{ of: 'closed-sessions', at: 3 }]);
  });

  it('refuses when the row below could not give the width up', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const narrow = 300;
    expect(canSpanDown(before, 'running-sessions', narrow, GUTTER, META)).toBe('no-room');
    expect(spanDown(before, 'running-sessions', narrow, GUTTER, META)).toBe(before);
  });

  it('allows it at the width a real surface actually has', () => {
    expect(canSpanDown(OLD_DEFAULT_LAYOUT, 'closed-sessions', 824, GUTTER, META)).toBeNull();
    expect(canSpanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', 824, GUTTER, META)).toBeNull();
  });

  it('refuses from the last row, where there is nothing underneath', () => {
    const before = OLD_DEFAULT_LAYOUT;
    expect(canSpanDown(before, 'themes', ROW_WIDTH, GUTTER, META)).toBe('last-row');
    expect(spanDown(before, 'themes', ROW_WIDTH, GUTTER, META)).toBe(before);
  });

  it('pulls back to an ordinary cell and gives the column back', () => {
    const spanned = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    const back = spanUp(spanned, 'running-sessions');
    expect(rowOf(back, 'r3')?.slots[0]?.span).toBeUndefined();
    expect(rowOf(back, 'r4')?.reserved).toBeUndefined();
    expect(back.rows).toEqual(OLD_DEFAULT_LAYOUT.rows);
  });

  it('extends twice, reaching two rows down', () => {
    let layout = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    layout = spanDown(layout, 'running-sessions', ROW_WIDTH, GUTTER, META);
    expect(rowOf(layout, 'r3')?.slots[0]?.span).toBe(3);
    expect(rowOf(layout, 'r4')?.reserved).toHaveLength(1);
    expect(rowOf(layout, 'r5')?.reserved).toHaveLength(1);
  });

  it('keeps a row emptied of its own cells while a spanner still reaches it', () => {
    let layout = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    for (const id of ['projects', 'skills', 'plugins'] as CellId[]) layout = hideCell(layout, id);
    expect(rowOf(layout, 'r4')?.slots).toEqual([]);
    expect(rowOf(layout, 'r4')?.reserved).toEqual([{ of: 'running-sessions', at: 0 }]);
    expect(rowOf(layout, 'r3')?.slots[0]?.span).toBe(2);
    expect(rowOf(spanUp(layout, 'running-sessions'), 'r4')).toBeUndefined();
  });

  it('clamps a stored span that reaches past the last row', () => {
    const base = OLD_DEFAULT_LAYOUT;
    const reaching: Layout = {
      ...base,
      rows: base.rows.map((row) =>
        row.id === 'r4' ? { ...row, slots: row.slots.map((s, at) => (at === 0 ? { ...s, span: 9 } : s)) } : row,
      ),
    };
    const fixed = repairSpans(reaching);
    expect(rowOf(fixed, 'r4')?.slots[0]?.span).toBe(2);
    expect(rowOf(fixed, 'r5')?.reserved).toHaveLength(1);
  });
});

describe('hideCell and showCell', () => {
  it('round trips a cell back to its default slot', () => {
    const before = LIVE_DEFAULT;
    const hidden = hideCell(before, 'skills');
    expect(hidden.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects', 'skills']);
    expect(rowOfCell(hidden, 'skills')).toBeUndefined();
    for (const slot of rowOf(hidden, 'r4')?.slots ?? []) expect(slot.fr).toBeCloseTo(0.5, 3);
    const shown = showCell(hidden, 'skills', META);
    expect(shown.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
    expect(place(shown, 'skills')).toEqual(['r4', 1]);
    expect(rowOf(shown, 'r4')?.slots.map((s) => Number(s.fr.toFixed(3)))).toEqual(
      rowOf(LIVE_DEFAULT, 'r4')?.slots.map((s) => Number(s.fr.toFixed(3))),
    );
  });

  it('removes a row emptied by hiding and still restores the cell', () => {
    let layout = hideCell(OLD_DEFAULT_LAYOUT, 'themes');
    layout = hideCell(layout, 'ledger');
    layout = hideCell(layout, 'activity-log');
    expect(rowOf(layout, 'r5')).toBeUndefined();
    layout = showCell(layout, 'themes', META);
    expect(rowOfCell(layout, 'themes')).toBeDefined();
    expect(layout.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'ledger', 'activity-log']);
  });

  it('ignores hiding twice and showing what is not hidden', () => {
    const once = hideCell(OLD_DEFAULT_LAYOUT, 'skills');
    expect(hideCell(once, 'skills')).toBe(once);
    expect(showCell(once, 'plugins', META)).toBe(once);
  });
});

describe('resetRow and normalizeRow', () => {
  it('puts one row back without disturbing another', () => {
    const before = LIVE_DEFAULT;
    let layout = resizeColumns(before, 'r3', 0, -200, ...seam(before, 'r3', 0));
    layout = resizeColumns(layout, 'r4', 0, -90, ...seam(layout, 'r4', 0));
    const after = resetRow(layout, 'r3', META);
    expect(rowOf(after, 'r3')?.slots.map((s) => s.fr)).toEqual(rowOf(before, 'r3')?.slots.map((s) => s.fr));
    expect(rowOf(after, 'r4')?.slots.map((s) => s.fr)).toEqual(rowOf(layout, 'r4')?.slots.map((s) => s.fr));
  });

  it('drops fractions that are not finite and positive', () => {
    const row = normalizeRow({ id: 'r1', kind: 'flex', size: 1, slots: [
      { id: 'projects', fr: Number.NaN },
      { id: 'skills', fr: -1 },
      { id: 'plugins', fr: 3 },
    ] });
    expect(row.slots).toEqual([{ id: 'plugins', fr: 1 }]);
  });
});

/* and the three */

function fake(n: number): SlotId {
  return `terminal:test-${n}` as SlotId;
}

function surface(n: number): Layout {
  const ids = Array.from({ length: n }, (_, at) => fake(at + 1));
  const groups: SlotId[][] = [];
  for (let at = 0; at < ids.length; at += 3) groups.push(ids.slice(at, at + 3));
  const size = 1 / groups.length;
  return {
    v: 6,
    rows: groups.map((group, at) => ({
      id: `r${at + 1}` as RowId,
      kind: 'flex' as const,
      size,
      slots: group.map((id) => ({ id, fr: 1 / group.length })),
    })),
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  };
}

function ids(layout: Layout): SlotId[] {
  return layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
}

function flexRows(layout: Layout) {
  return layout.rows.filter((row) => row.kind === 'flex');
}

const ARRANGE_CASES: [string, (layout: Layout) => Layout][] = [
  ['arrangeColumns', (layout) => arrangeColumns(layout, META)],
  ['arrangeRows', (layout) => arrangeRows(layout, META)],
  ['arrangeGrid', (layout) => arrangeGrid(layout, META)],
];

for (const [name, arrange] of ARRANGE_CASES) {
  describe(`${name} conserves the surface`, () => {
    for (let n = 1; n <= 7; n += 1) {
      it(`keeps every one of ${n} cells, once, in a row that sums to one`, () => {
        const before = surface(n);
        const after = arrange(before);
        expect(ids(after).slice().sort()).toEqual(ids(before).slice().sort());
        expect(new Set(ids(after)).size).toBe(n);
        for (const row of flexRows(after)) {
          expect([row.id, row.slots.reduce((sum, slot) => sum + slot.fr, 0)]).toEqual([row.id, expect.closeTo(1, 10)]);
        }
        for (const row of flexRows(after)) expect(row.slots.length).toBeGreaterThan(0);
        expect(flexRows(after).reduce((sum, row) => sum + row.size, 0)).toBeCloseTo(1, 10);
      });
    }
  });
}

describe('the three arrangements have the shapes they are named for', () => {
  it('arrangeColumns puts every cell in one row at an equal share', () => {
    for (let n = 1; n <= 7; n += 1) {
      const after = arrangeColumns(surface(n), META);
      expect([n, flexRows(after).length]).toEqual([n, 1]);
      expect([n, flexRows(after)[0]?.slots.length]).toEqual([n, n]);
      for (const slot of flexRows(after)[0]?.slots ?? []) expect(slot.fr).toBeCloseTo(1 / n, 10);
    }
  });

  it('arrangeRows gives every cell a row of its own at full width', () => {
    for (let n = 1; n <= 7; n += 1) {
      const after = arrangeRows(surface(n), META);
      expect([n, flexRows(after).length]).toEqual([n, n]);
      for (const row of flexRows(after)) {
        expect(row.slots).toHaveLength(1);
        expect(row.slots[0]?.fr).toBeCloseTo(1, 10);
        expect(row.size).toBeCloseTo(1 / n, 10);
      }
    }
  });

  it('arrangeGrid fills ceil(sqrt(n)) columns and lets the last row be short', () => {
    const expected: Record<number, number[]> = {
      1: [1],
      2: [2],
      3: [2, 1],
      4: [2, 2],
      5: [3, 2],
      6: [3, 3],
      7: [3, 3, 1],
    };
    for (let n = 1; n <= 7; n += 1) {
      const after = arrangeGrid(surface(n), META);
      expect([n, flexRows(after).map((row) => row.slots.length)]).toEqual([n, expected[n]]);
      const last = flexRows(after)[flexRows(after).length - 1];
      expect([n, (last?.slots ?? []).reduce((sum, slot) => sum + slot.fr, 0)]).toEqual([n, expect.closeTo(1, 10)]);
    }
  });

  it('reads the surface in row order then index', () => {
    const after = arrangeColumns(surface(7), META);
    expect(after.rows[0]?.slots.map((slot) => slot.id)).toEqual([1, 2, 3, 4, 5, 6, 7].map(fake));
  });

  it('sweeps the masthead and the stat strip in with every other cell', () => {
    const after = arrangeRows(DEFAULT_LAYOUT, META);
    expect(after.rows).toHaveLength(14);
    for (const row of after.rows) expect([row.id, row.slots.length]).toEqual([row.id, 1]);
    expect(after.rows[0]?.slots[0]?.id).toBe('stat-running');
  });

  it('gives a rebuilt pixel row the tallest height its cells ask for', () => {
    const after = arrangeColumns(DEFAULT_LAYOUT, META);
    expect(after.rows).toHaveLength(1);
    expect(after.rows[0]?.kind).toBe('px');
    expect(after.rows[0]?.size).toBe(META['running-sessions'].defaultHeight);
  });

  it('clears every span, because an arrange states the whole shape', () => {
    const spanned = spanDown(DEFAULT_LAYOUT, 'running-sessions', ROW_WIDTH, GUTTER, META);
    const after = arrangeGrid(spanned, META);
    for (const row of after.rows) {
      expect([row.id, row.reserved]).toEqual([row.id, undefined]);
      for (const slot of row.slots) expect([slot.id, slot.span]).toEqual([slot.id, undefined]);
    }
  });

  it('is undone by a reset, which is what the popover offers beside it', () => {
    expect(arrangeGrid(DEFAULT_LAYOUT, META)).not.toEqual(DEFAULT_LAYOUT);
    expect(OLD_DEFAULT_LAYOUT).toEqual(DEFAULT_LAYOUT);
  });

  it('leaves an empty surface alone rather than building a row with no cells', () => {
    const empty: Layout = { v: 6, rows: [], hidden: [], heroCollapsed: false, collapsed: [] };
    for (const [, arrange] of ARRANGE_CASES) expect(arrange(empty)).toBe(empty);
  });
});

describe('addInstance', () => {
  it('scales the incumbents by n/(n+1) exactly as a drop does', () => {
    const before = OLD_DEFAULT_LAYOUT;
    const ratio = (layout: Layout) => {
      const slots = rowOf(layout, 'r5')?.slots ?? [];
      return (slots[0]?.fr ?? 0) / (slots[1]?.fr ?? 1);
    };
    const result = addInstance(before, 'terminal', 'test-1', '', META);
    expect(result.refusal).toBeNull();
    const row = rowOf(result.layout, 'r5');
    expect(row?.slots).toHaveLength(4);
    expect(row?.slots[3]?.id).toBe('terminal:test-1');
    expect(row?.slots[3]?.fr).toBeCloseTo(1 / 4, 10);
    expect(ratio(result.layout)).toBeCloseTo(ratio(before), 10);
    for (const total of sums(result.layout)) expect(total).toBeCloseTo(1, 10);
  });

  it('joins the LAST row of the surface', () => {
    const result = addInstance(DEFAULT_LAYOUT, 'terminal', 'test-1', '', META);
    expect(rowOfCell(result.layout, 'terminal:test-1' as CellId)?.id).toBe('r5');
  });

  it('refuses a session already on the surface, with a reason and no change', () => {
    const once = addInstance(OLD_DEFAULT_LAYOUT, 'terminal', 'test-1', '', META);
    const twice = addInstance(once.layout, 'terminal', 'test-1', '', META);
    expect(twice.refusal).toBe('duplicate');
    expect(twice.layout).toBe(once.layout);
  });

  it('refuses the seventh viewer on the home page, with a reason and no change', () => {
    let layout = OLD_DEFAULT_LAYOUT;
    for (let n = 1; n <= MAX_VIEWERS; n += 1) {
      const step = addInstance(layout, 'terminal', `test-${n}`, '', META);
      expect([n, step.refusal]).toEqual([n, null]);
      layout = step.layout;
    }
    const seventh = addInstance(layout, 'terminal', 'test-7', '', META);
    expect(seventh.refusal).toBe('cap');
    expect(seventh.layout).toBe(layout);
    expect(viewersOf(layout)).toHaveLength(MAX_VIEWERS);
  });

  it('lets the terminal page hold the primary AND the full six viewers', () => {
    let layout = resetLayout(META, 'terminal');
    for (let n = 1; n <= MAX_VIEWERS; n += 1) {
      const step = addInstance(layout, 'terminal', `test-${n}`, '', META);
      expect([n, step.refusal]).toEqual([n, null]);
      layout = step.layout;
    }
    expect(viewersOf(layout)).toHaveLength(MAX_VIEWERS);
    expect(instancesOf(layout)).toHaveLength(MAX_VIEWERS + 1);
    expect(rowOfCell(layout, 'terminal:@primary')).toBeDefined();
  });

  it('still refuses the seventh viewer on the terminal page', () => {
    let layout = resetLayout(META, 'terminal');
    for (let n = 1; n <= MAX_VIEWERS; n += 1) layout = addInstance(layout, 'terminal', `test-${n}`, '', META).layout;
    const seventh = addInstance(layout, 'terminal', 'test-7', '', META);
    expect(seventh.refusal).toBe('cap');
    expect(seventh.layout).toBe(layout);
  });

  it('does not count the primary as a viewer', () => {
    const terminal = resetLayout(META, 'terminal');
    expect(instancesOf(terminal)).toEqual(['terminal:@primary']);
    expect(viewersOf(terminal)).toEqual([]);
  });

  it('refuses when the surface has no row at all', () => {
    const empty: Layout = { v: 6, rows: [], hidden: [], heroCollapsed: false, collapsed: [] };
    expect(addInstance(empty, 'terminal', 'test-1', '', META).refusal).toBe('no-row');
  });

  it('counts an instance in the hidden list against the cap and the duplicate check', () => {
    const layout = OLD_DEFAULT_LAYOUT;
    const parked: Layout = { ...layout, hidden: [...layout.hidden, 'terminal:test-1' as CellId] };
    expect(addInstance(parked, 'terminal', 'test-1', '', META).refusal).toBe('duplicate');
  });

  describe('the primary duplicate guard', () => {
    it('refuses adding a session the primary currently shows, even though no slot id matches', () => {
      const layout = resetLayout(META, 'terminal');
      const result = addInstance(layout, 'terminal', 'ses_a', 'ses_a', META);
      expect(result.refusal).toBe('duplicate');
      expect(result.layout).toBe(layout);
    });

    it('still adds a session the primary is showing something else, primary session known', () => {
      const layout = resetLayout(META, 'terminal');
      const result = addInstance(layout, 'terminal', 'ses_b', 'ses_a', META);
      expect(result.refusal).toBeNull();
      expect(rowOfCell(result.layout, 'terminal:ses_b' as CellId)).toBeDefined();
    });

    it('does not refuse everything when the primary session is not known', () => {
      const layout = resetLayout(META, 'terminal');
      const result = addInstance(layout, 'terminal', 'ses_a', '', META);
      expect(result.refusal).toBeNull();
    });
  });
});

describe('removeCell against hideCell', () => {
  it('takes the slot and leaves NO hidden entry, where hiding leaves one', () => {
    const before = addInstance(OLD_DEFAULT_LAYOUT, 'terminal', 'test-1', '', META).layout;
    const removed = removeCell(before, 'terminal:test-1' as CellId);
    expect(rowOfCell(removed, 'terminal:test-1' as CellId)).toBeUndefined();
    expect(removed.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom']);

    const hiddenAway = hideCell(OLD_DEFAULT_LAYOUT, 'themes');
    expect(rowOfCell(hiddenAway, 'themes')).toBeUndefined();
    expect(hiddenAway.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'themes']);
  });

  it('renormalises the row it emptied a slot from', () => {
    const before = addInstance(OLD_DEFAULT_LAYOUT, 'terminal', 'test-1', '', META).layout;
    const after = removeCell(before, 'terminal:test-1' as CellId);
    expect(rowOf(after, 'r5')?.slots.reduce((sum, slot) => sum + slot.fr, 0)).toBeCloseTo(1, 10);
  });

  it('drops a row it emptied entirely', () => {
    const one: Layout = {
      v: 6,
      rows: [
        { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: 'themes', fr: 1 }] },
        { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: 'terminal:test-1' as CellId, fr: 1 }] },
      ],
      hidden: [],
      heroCollapsed: false,
      collapsed: [],
    };
    expect(rowOf(removeCell(one, 'terminal:test-1' as CellId), 'r2')).toBeUndefined();
  });

  it('ignores a slot that is not on the surface', () => {
    const before = OLD_DEFAULT_LAYOUT;
    expect(removeCell(before, 'terminal:nobody' as CellId)).toBe(before);
  });

  it('REFUSES to remove the primary sentinel, leaving the page a pane', () => {
    const before = resetLayout(META, 'terminal');
    expect(removeCell(before, 'terminal:@primary')).toBe(before);
    expect(rowOfCell(before, 'terminal:@primary')).toBeDefined();
  });

  it('REFUSES to hide an instance, because nothing could ever restore it', () => {
    const before = addInstance(OLD_DEFAULT_LAYOUT, 'terminal', 'test-1', '', META).layout;
    expect(hideCell(before, 'terminal:test-1' as CellId)).toBe(before);
  });
});

describe('the terminal page default', () => {
  it('is one flex row holding the primary sentinel at full width', () => {
    const layout = resetLayout(META, 'terminal');
    expect(layout.rows).toHaveLength(1);
    expect(layout.rows[0]?.id).toBe('r1');
    expect(layout.rows[0]?.kind).toBe('flex');
    expect(layout.rows[0]?.slots).toEqual([{ id: 'terminal:@primary', fr: 1 }]);
    expect(layout.hidden).toEqual(['notes', 'files', 'scheduled-tasks', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
    expect(layout.collapsed).toEqual([]);
  });

  it('has one row and no masthead or stat strip cell', () => {
    const layout = resetLayout(META, 'terminal');
    expect(layout.rows.map((row) => row.id)).toEqual(['r1']);
    expect(layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toEqual(['terminal:@primary']);
  });

  it('leaves the home default exactly as it was', () => {
    expect(resetLayout(META, 'home')).toEqual(LIVE_DEFAULT);
  });
});

describe('an instance record is minted from its id', () => {
  it('makes the primary bare and every viewer a card', () => {
    expect(metaFor('terminal:@primary', META).chrome).toBe('card');
    expect(metaFor('terminal:test-1' as CellId, META).chrome).toBe('card');
  });

  it('carries the declared floors and the two two-step ladders', () => {
    const meta = metaFor('terminal:test-1' as CellId, META);
    expect(meta.minPx).toBe(COL_MIN);
    expect(meta.minHeight).toBe(ROW_MIN);
    expect(meta.widthStates).toEqual([{ name: 'narrow', min: 0 }, { name: 'wide', min: 560 }]);
    expect(meta.heightStates).toEqual([{ name: 'strip', min: 0 }, { name: 'pane', min: 120 }]);
  });

  it('names a viewer by its session and the primary by its catalog title', () => {
    expect(metaFor('terminal:sess-7' as CellId, META).titleName).toBe('sess-7');
    expect(metaFor('terminal:@primary', META).titleName).toBeUndefined();
  });

  it('sorts every instance after every singleton on a phone', () => {
    const singletons = (Object.keys(META) as CellId[]).map((id) => phoneOrderOf(id, 0, META));
    for (let index = 0; index < 6; index += 1) {
      expect(phoneOrderOf(fake(index + 1) as CellId, index, META)).toBeGreaterThan(Math.max(...singletons));
    }
  });

  it('gives two instances in one row two different phone orders', () => {
    expect(phoneOrderOf(fake(1) as CellId, 0, META)).not.toBe(phoneOrderOf(fake(2) as CellId, 1, META));
  });

  it('leaves a singleton phone order untouched by its index', () => {
    expect(phoneOrderOf('themes', 4, META)).toBe(META.themes.phoneOrder);
  });
});

describe('a reserved column when the row around it changes', () => {
  function drawn(layout: ReturnType<typeof resetLayout>, id: string): string[] {
    const row = layout.rows.find((one) => one.id === id);
    if (!row) throw new Error(`no row ${id}`);
    return visualOrder(row).map((cell) => (cell.kind === 'slot' ? cell.slot.id : 'reserved'));
  }

  const WIDTH = 1407;
  const GUTTER = 12;

  it('keeps the column where it was when a cell is dropped to its left', () => {
    const spanned = spanDown(OLD_DEFAULT_LAYOUT, 'closed-sessions', WIDTH, GUTTER, META);
    expect(drawn(spanned, 'r4')).toEqual(['projects', 'skills', 'plugins', 'reserved']);
    const dropped = moveCell(spanned, 'themes', 'r4', 0);
    expect(drawn(dropped, 'r4')).toEqual(['themes', 'projects', 'skills', 'plugins', 'reserved']);
  });

  it('closes up behind a cell that leaves from its left', () => {
    const spanned = spanDown(OLD_DEFAULT_LAYOUT, 'closed-sessions', WIDTH, GUTTER, META);
    const taken = hideCell(spanned, 'projects');
    expect(drawn(taken, 'r4')).toEqual(['skills', 'plugins', 'reserved']);
  });

  it('stays on the right of a cell dropped to its right', () => {
    const spanned = spanDown(OLD_DEFAULT_LAYOUT, 'running-sessions', WIDTH, GUTTER, META);
    const before = drawn(spanned, 'r4');
    const column = before.indexOf('reserved');
    const dropped = moveCell(spanned, 'themes', 'r4', before.length);
    const after = drawn(dropped, 'r4');
    expect(after.indexOf('reserved')).toBe(column);
    expect(after[after.length - 1]).toBe('themes');
  });
});

describe('offSurfaceIds (issue #893)', () => {
  it('offers a hidden-by-default cell a stored layout predates', () => {
    const old = resetLayout(META, 'home');
    const stored = { ...old, hidden: old.hidden.filter((id) => id !== 'scheduled-tasks') };
    expect(offSurfaceIds(stored)).toEqual(['notes', 'files', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects', 'scheduled-tasks']);
    const shown = showCell(stored, 'scheduled-tasks', META);
    expect(rowOfCell(shown, 'scheduled-tasks')).toBeDefined();
    expect(offSurfaceIds(shown)).toEqual(['notes', 'files', 'keep-awake', 'machine-stats', 'changes', 'task-manager', 'task-manager-all', 'task-manager-mk2', 'task-manager-mk2-all', 'crosstalk', 'tasks', 'tasks-all', 'bookmarks', 'bookmarks-all', 'pipeline', 'automations', 'automations-all', 'shell', 'timeline', 'questions', 'developer', 'task-list', 'session-contents', 'warroom', 'projects']);
  });

  it('never offers a cell that is already placed or listed', () => {
    const layout = resetLayout(META, 'home');
    expect(offSurfaceIds(layout)).toEqual(layout.hidden);
  });
});
