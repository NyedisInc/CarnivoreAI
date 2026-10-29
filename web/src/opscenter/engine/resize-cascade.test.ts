import { describe, expect, it } from 'vitest';
import { computeTracks, GUTTER } from './tracks';
import { boundaryHandles } from './row-handles';
import { resizeRows } from './model';
import { ROW_MIN } from './floors';
import { repairSpans } from './spans';
import type { Layout } from './types';

const P = 'terminal:@primary';
const F = 'terminal:row:311';
const U = 'terminal:row:32';
const sizes = [0.7439333771587187, 0.04108309990662932, 0.13994991803910584, 0.004915102770330653, 0.009830205540661306, 0.01966041108132261, 0.040627885503231764];
const ids = ['r14', 'r15', 'r20', 'r19', 'r18', 'r17', 'r16'];
const rows: any[] = ids.map((id, i) => ({ id, kind: 'flex', size: sizes[i], slots: [] }));
rows[0].slots = [{ id: P, fr: 0.49, span: 7 }, { id: F, fr: 0.51, span: 2 }];
rows[1].reserved = [{ of: P, at: 0 }, { of: F, at: 0 }];
rows[2].slots = [{ id: U, fr: 1 }];
rows[2].reserved = [{ of: P, at: 0 }];
for (let i = 3; i < 7; i += 1) rows[i].reserved = [{ of: P, at: 0 }];
const saved: Layout = { v: 6, rows, hidden: ['files', 'notes'], heroCollapsed: false, collapsed: [] } as any;
const W = 1190;
const H = 1130;

describe('resize cascade (#2264)', () => {
  const layout = repairSpans(saved);
  const space = H - GUTTER * (layout.rows.length - 1);

  it('trims the dead trailing rows and keeps the total height', () => {
    expect(layout.rows.map((r) => r.id)).toEqual(['r14', 'r15', 'r20']);
    expect(layout.rows[0]!.slots.find((s) => s.id === P)!.span).toBe(3);
    expect(layout.rows.reduce((sum, r) => sum + r.size, 0)).toBeCloseTo(1, 9);
  });

  it('offers a handle above the bottom right cell and drags it up by 200px', () => {
    const tracks = computeTracks({ rows: layout.rows, width: W, height: H, gutter: GUTTER, gutterY: GUTTER } as any);
    expect(boundaryHandles(tracks, 1, W, GUTTER).length).toBeGreaterThan(0);
    const next = resizeRows(layout, 'r15', -200, space);
    const px = (l: Layout) => l.rows.map((r) => r.size * space);
    const before = px(layout);
    const after = px(next);
    expect(after[2]! - before[2]!).toBeCloseTo(200, 3);
    expect(after[1]).toBeCloseTo(before[1]!, 6);
    expect(before[0]! - after[0]!).toBeCloseTo(200, 3);
    expect(after[0]).toBeGreaterThanOrEqual(ROW_MIN - 1e-6);
    expect(after.reduce((a, b) => a + b, 0)).toBeCloseTo(before.reduce((a, b) => a + b, 0), 6);
  });
});
