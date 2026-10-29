import { describe, expect, test } from 'vitest';
import type { ProjectResponse, SessionInfo } from '../../opscenter/api/types';
import { buildWall, DEFAULT_TOGGLES, type WallInput } from './warroom-model';
import { gridDims, outlineEdges, PEEK_PAD, PEEK_TEXT_MAX, PEEK_TEXT_MIN, peekCrop, peekPosition, peekRange, peekScale, peekStored, peekTransform, peekWidth, referenceTileWidth, wallCells } from './wall-layout';

const LAND = [1600, 900] as const;
const PORT = [600, 1000] as const;

describe('gridDims', () => {
  test.each([1, 2, 8, 9, 12, 20])('%i tiles: every tile has a cell, no empty row, at both aspects', (n) => {
    for (const [w, h] of [LAND, PORT]) {
      const d = gridDims(n, w, h);
      expect(d.cols * d.rows).toBeGreaterThanOrEqual(n);
      expect(d.cols * (d.rows - 1)).toBeLessThan(n);
    }
  });
  test('the shapes the operator named', () => {
    expect(gridDims(9, ...LAND)).toMatchObject({ cols: 3, rows: 3, scroll: false });
    expect(gridDims(8, ...LAND)).toMatchObject({ cols: 3, rows: 3 });
    expect(gridDims(12, ...LAND)).toMatchObject({ cols: 4, rows: 3 });
    expect(gridDims(12, 900, 1600).cols).toBeLessThan(4);
  });
  test('cells fill the box exactly while they fit, and scroll below the minimum size', () => {
    const fit = gridDims(9, ...LAND);
    expect(fit.cellW * fit.cols).toBeCloseTo(1600);
    expect(fit.cellH * fit.rows).toBeCloseTo(900);
    const tiny = gridDims(20, 400, 300);
    expect(tiny.scroll).toBe(true);
    expect(tiny.cellW).toBeGreaterThanOrEqual(200);
  });
});

describe('outlineEdges', () => {
  test('an L: three over one, the foot has no top, and the pieces meet', () => {
    const e = outlineEdges(['a', 'a', 'a', 'a', 'b', 'b'], 3);
    expect(e[0]).toEqual({ top: true, left: true, right: false, bottom: false });
    expect(e[2]).toEqual({ top: true, left: false, right: true, bottom: true });
    expect(e[3]).toEqual({ top: false, left: true, right: true, bottom: true });
    expect(e[4]).toEqual({ top: true, left: true, right: false, bottom: true });
  });
  test('a lone group is a box; a short last row closes at the end of the group', () => {
    const e = outlineEdges(['a', 'a', 'a', 'a', 'a'], 3);
    expect(e[4]).toEqual({ top: false, left: false, right: true, bottom: true });
    expect(e[2]!.bottom).toBe(true);
  });
});

describe('peekWidth and peekScale: one peek size at every tile count', () => {
  const wall = { width: 1500, height: 900 };
  const R = referenceTileWidth(wall.width);
  test('stored per-mille of R is the width; 0 is none', () => {
    expect(peekWidth(wall.width, 0)).toBe(0);
    expect(peekWidth(wall.width, 1150)).toBeCloseTo(1.15 * R);
    expect(peekWidth(wall.width, 2300)).toBeCloseTo(2.3 * R);
  });
  test("a 3-column tile at the default keeps today's 1.15", () => {
    expect(peekScale({ width: R, height: 300 }, wall, peekWidth(wall.width, 1150))).toBeCloseTo(1.15);
  });
  test("an 8-column tile at the default peeks to the same width as a 3-column one (the owner's #2060 bug)", () => {
    const w = wall.width / 8;
    const s = peekScale({ width: w, height: w / 1.5 }, wall, peekWidth(wall.width, 1150));
    expect(w * s).toBeCloseTo(1.15 * R);
  });
  test('a tile as wide as the peek (2 columns) stays 1, and off is 1 everywhere', () => {
    expect(peekScale({ width: wall.width / 2, height: 450 }, wall, peekWidth(wall.width, 1150))).toBe(1);
    for (const cols of [1, 3, 8]) expect(peekScale({ width: wall.width / cols, height: 100 }, wall, peekWidth(wall.width, 0))).toBe(1);
  });
  test('the cap keeps the scaled tile inside the wall', () => {
    const s = peekScale({ width: 100, height: 400 }, wall, 5000);
    expect(100 * s).toBeLessThanOrEqual(wall.width);
    expect(400 * s).toBeLessThanOrEqual(wall.height);
  });
});

describe('the slider: equal steps in every wall', () => {
  const wall = { width: 1600, height: 900 };
  const three = gridDims(9, wall.width, wall.height);
  const eight = { cols: 8, cellW: wall.width / 8, cellH: wall.width / 8 / 1.5 };
  const range = (d: { cellW: number; cellH: number }) => peekRange(wall, { width: d.cellW, height: d.cellH });
  test('a 3-wide wall: 0 off, 25/50/75 equal steps from the tile to M, 100 is M, default 1150 reads 12', () => {
    expect(three.cols).toBe(3);
    const r = range(three);
    const D = 1.15 * r.ref;
    expect(r.high).toBeCloseTo(Math.min(2 * D, wall.width, (wall.height * three.cellW) / three.cellH));
    expect(peekStored(0, r)).toBe(0);
    for (const p of [25, 50, 75, 100]) {
      const px = peekWidth(wall.width, peekStored(p, r));
      expect(px).toBeCloseTo(r.low + ((r.high - r.low) * p) / 100, 0);
    }
    expect(peekPosition(1150, r)).toBe(12);
  });
  test('an 8-wide wall reads the default near 40, and one stored value is one peek width at both walls', () => {
    expect(eight.cols).toBe(8);
    const r8 = range(eight);
    expect(peekPosition(1150, r8)).toBeGreaterThanOrEqual(38);
    expect(peekPosition(1150, r8)).toBeLessThanOrEqual(42);
    expect(peekWidth(wall.width, 1150)).toBeCloseTo(1.15 * referenceTileWidth(wall.width));
    expect(peekWidth(wall.width, 1150) / r8.low).toBeGreaterThan(1);
  });
  test('position to stored to position round-trips', () => {
    for (const d of [three, eight]) {
      const r = range(d);
      for (let p = 0; p <= 100; p++) expect(Math.abs(peekPosition(peekStored(p, r), r) - p)).toBeLessThanOrEqual(1);
    }
  });
  test('a peek no wider than the tile, or off, reads 0; a wall with no room (tile at least M) has no effect', () => {
    const r = range(three);
    expect(peekPosition(0, r)).toBe(0);
    expect(peekPosition(900, r)).toBe(0);
    const wide = peekRange({ width: 1600, height: 900 }, { width: 1300, height: 731 });
    expect(wide.high).toBeLessThanOrEqual(wide.low);
    expect(peekPosition(1150, wide)).toBe(0);
    expect(peekStored(60, wide)).toBe(0);
  });
});

describe('peekTransform', () => {
  test('the wanted scale, centred, clamped inside the bounds', () => {
    const bounds = { left: 0, top: 0, width: 1600, height: 900 };
    const mid = peekTransform({ left: 600, top: 300, width: 200, height: 150 }, bounds, 1.15);
    expect(mid.scale).toBe(1.15);
    expect(mid.dx).toBeCloseTo(-15);
    const corner = peekTransform({ left: 0, top: 0, width: 200, height: 150 }, bounds, 1.15);
    expect([corner.dx, corner.dy]).toEqual([0, 0]);
    const far = peekTransform({ left: 1400, top: 750, width: 200, height: 150 }, bounds, 1.15);
    expect(1400 + far.dx + 200 * far.scale).toBeLessThanOrEqual(1600);
    expect(750 + far.dy + 150 * far.scale).toBeLessThanOrEqual(900);
  });
});

describe('wall order', () => {
  const projects = [
    { id: 3, name: 'zulu', company_name: null }, { id: 2, name: 'beta', company_name: 'acme' }, { id: 1, name: 'alpha', company_name: 'acme' },
  ] as ProjectResponse[];
  const row = (rowId: number, project: number, over: Partial<SessionInfo> = {}): SessionInfo =>
    ({ session: { id: `ses_${rowId}` }, tmux_session: `t${rowId}`, session_row_id: rowId, label: null, agent_family: 'claude', project_id: project, project_name: null, activity_status: 'idle', ...over }) as SessionInfo;
  const input = (sessions: SessionInfo[], projs = projects): WallInput => ({
    sessions, asleep: [], browsers: [], projects: projs, toggles: { ...DEFAULT_TOGGLES }, colorOf: () => null, unfiledLabel: 'none', browsersLabel: 'b',
  });
  const order = (w: WallInput): string[] => wallCells(buildWall(w)).map((c) => c.tile.key);

  test('sidebar project order, then row id; status, activity, listing order and project list order never move it', () => {
    const base = [row(9, 3), row(5, 1), row(2, 2), row(7, 1), row(4, 2)];
    const want = ['row:5', 'row:7', 'row:2', 'row:4', 'row:9'];
    expect(order(input(base))).toEqual(want);
    const delta = [row(4, 2, { activity_status: 'working' }), row(7, 1, { activity_status: 'question', unread: true }), row(9, 3), row(2, 2, { activity_status: 'working' }), row(5, 1)];
    expect(order(input(delta, [...projects].reverse()))).toEqual(want);
  });
});

describe('peekCrop', () => {
  const base = { cellW: 7.8, cellH: 16, peek: 1.15 };
  test('a 105x65 pane shows its whole width, keeps the margin and sits on the last row', () => {
    const c = peekCrop({ ...base, cols: 105, rows: 65, usedCols: 105, usedRows: 65, boxW: 550, boxH: 300 });
    const fitW = (550 - 2 * PEEK_PAD) / (105 * base.cellW);
    expect(c.cols).toBeCloseTo(105);
    expect(c.scale).toBeCloseTo(fitW);
    expect(Number.isInteger(c.rows)).toBe(true);
    expect(c.row0).toBe(65 - c.rows);
    expect(c.col0).toBe(0);
    expect(c.x0).toBe(PEEK_PAD);
    expect(c.y0).toBeGreaterThanOrEqual(PEEK_PAD);
  });
  test('a very wide pane stops at the text floor and clips on the right', () => {
    const c = peekCrop({ ...base, cols: 217, rows: 65, usedCols: 217, usedRows: 65, boxW: 550, boxH: 300 });
    expect(c.scale).toBeCloseTo(PEEK_TEXT_MIN / 1.15);
    expect(c.cols).toBeLessThan(217);
  });
  test('narrow content zooms past the full-pane fit, capped at the text maximum', () => {
    const c = peekCrop({ ...base, cols: 105, rows: 65, usedCols: 30, usedRows: 3, boxW: 550, boxH: 300 });
    expect(c.scale).toBeCloseTo(PEEK_TEXT_MAX / 1.15);
    expect(c.row0).toBe(0);
  });
  test('sweep: inside the pane, whole rows, text block inside the margin, never below the text floor', () => {
    const eps = 1e-6;
    for (const [cols, rows] of [[20, 5], [80, 24], [105, 65], [120, 40], [217, 65], [300, 80]] as const) {
      for (const [boxW, boxH] of [[120, 75], [550, 300], [900, 400], [1200, 750]] as const) {
        for (const [uc, ur] of [[0, 0], [cols / 2, 3], [cols, rows]] as const) {
          for (const peek of [1, 1.15]) {
            const c = peekCrop({ ...base, peek, cols, rows, usedCols: uc, usedRows: ur, boxW, boxH });
            const label = JSON.stringify({ cols, rows, boxW, boxH, uc, ur, peek, c });
            for (const n of Object.values(c)) expect(Number.isFinite(n), label).toBe(true);
            expect(c.col0, label).toBeGreaterThanOrEqual(0);
            expect(c.row0, label).toBeGreaterThanOrEqual(0);
            expect(Number.isInteger(c.rows), label).toBe(true);
            expect(Number.isInteger(c.row0), label).toBe(true);
            expect(c.rows, label).toBeGreaterThanOrEqual(1);
            expect(c.col0 + c.cols, label).toBeLessThanOrEqual(cols + eps);
            expect(c.row0 + c.rows, label).toBeLessThanOrEqual(rows + eps);
            const innerW = Math.max(1, boxW - 2 * PEEK_PAD);
            expect(c.x0, label).toBeGreaterThanOrEqual(PEEK_PAD - eps);
            expect(c.y0, label).toBeGreaterThanOrEqual(PEEK_PAD - 1e-3);
            expect(c.y0 + c.rows * base.cellH * c.scale, label).toBeLessThanOrEqual(boxH - PEEK_PAD + 1e-3);
            expect(c.cols * base.cellW * c.scale, label).toBeLessThanOrEqual(innerW + 1e-3);
            expect(c.scale * peek, label).toBeGreaterThanOrEqual(PEEK_TEXT_MIN - 1e-9);
          }
        }
      }
    }
  });
  test('degenerate input is safe', () => {
    const c = peekCrop({ ...base, cols: 0, rows: 0, usedCols: 0, usedRows: 0, boxW: 0, boxH: 0 });
    expect(c).toEqual({ scale: 1, col0: 0, row0: 0, cols: 0, rows: 0, x0: 0, y0: 0 });
  });
});

describe('peekCrop at rest', () => {
  const base = { cellW: 7.8, cellH: 16, peek: 1, rest: true };
  test('a tall narrow pane fills the width inside the margin and keeps the bottom rows', () => {
    const c = peekCrop({ ...base, cols: 105, rows: 65, usedCols: 40, usedRows: 65, boxW: 220, boxH: 130 });
    expect(c.scale).toBeCloseTo((220 - 2 * PEEK_PAD) / (105 * base.cellW));
    expect(c.cols).toBeCloseTo(105);
    expect(c.row0 + c.rows).toBe(65);
    expect(c.y0 + c.rows * base.cellH * c.scale).toBeCloseTo(130 - PEEK_PAD);
  });
  test('a wide pane fits its width and leaves a band above', () => {
    const c = peekCrop({ ...base, cols: 217, rows: 10, usedCols: 217, usedRows: 10, boxW: 550, boxH: 300 });
    expect(c.cols).toBeCloseTo(217);
    expect(c.rows).toBe(10);
    expect(c.y0).toBeGreaterThan(PEEK_PAD);
  });
});
