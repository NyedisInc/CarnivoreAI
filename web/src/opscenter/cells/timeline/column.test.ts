import { describe, expect, it } from 'vitest';
import { ALL_FILTERS_ON } from './model';
import type { SessionTimeline } from './types';
import { timelineWidgetFixtures } from '../../widgets/fixtures/core.timeline';
import { CLUSTER_V_PX, LABEL_PX, layoutColumn, placeLabels, stepColumn } from './column';
import { frameFor } from './plot-model';
import { V_LINE_PX, V_LABEL_PAD_PX } from './scale';

/** The busy fixture, fresh. Output: SessionTimeline. */
const busy = (): SessionTimeline => structuredClone(Object.values(timelineWidgetFixtures.data).find((v) => (v as SessionTimeline).bars) as SessionTimeline);

describe('the column', () => {
  it('is the one layout at every height, and takes no width', () => {
    for (const h of [63, 320, 500, 600, 800, 900]) expect(frameFor(false, h).body, `height ${h}`).toBe('column');
  });

  it('never overlaps two labels, keeps them inside the plot, and keeps every conversation named', () => {
    for (const h of [300, 480, 700]) {
      const col = layoutColumn(busy(), ALL_FILTERS_ON, h, true);
      const tops = col.items.flatMap((c) => (c.labelTop === null ? [] : [c.labelTop])).sort((a, b) => a - b);
      for (let i = 1; i < tops.length; i += 1) expect(tops[i]! - tops[i - 1]!).toBeGreaterThanOrEqual(LABEL_PX - 1e-6);
      expect(Math.min(...tops)).toBeGreaterThanOrEqual(0);
      expect(Math.max(...tops) + LABEL_PX).toBeLessThanOrEqual(h + 1e-6);
      expect(col.items.filter((c) => c.item.kind === 'conversation').every((c) => c.labelTop !== null)).toBe(true);
    }
  });

  it('keeps marks at their time: none lost, clusters only nearer than a cluster apart, time running down', () => {
    const col = layoutColumn(busy(), ALL_FILTERS_ON, 560, true);
    const marks = col.items.filter((c) => c.item.kind === 'mark' || c.item.kind === 'cluster');
    for (let i = 1; i < marks.length; i += 1) expect(marks[i]!.y - marks[i - 1]!.y).toBeGreaterThanOrEqual(CLUSTER_V_PX);
    const count = marks.reduce((n, c) => n + (c.item.kind === 'cluster' ? c.item.marks.length : 1), 0);
    expect(count).toBe(busy().marks.length);
    expect(col.segs.map((s) => s.x0)).toEqual([...col.segs.map((s) => s.x0)].sort((a, b) => a - b));
    expect(col.hooks).toHaveLength(3);
  });

  it('gives the ruler two-line day labels that never collide', () => {
    const ticks = layoutColumn(busy(), ALL_FILTERS_ON, 560, true).ticks;
    const span = (t: (typeof ticks)[number]): [number, number] => {
      const hgt = t.label.split('\n').length * V_LINE_PX;
      return t.anchor === 'start' ? [t.x, t.x + hgt] : t.anchor === 'end' ? [t.x - hgt, t.x] : [t.x - hgt / 2, t.x + hgt / 2];
    };
    for (let i = 1; i < ticks.length; i += 1) expect(span(ticks[i]!)[0]).toBeGreaterThanOrEqual(span(ticks[i - 1]!)[1] + V_LABEL_PAD_PX - 1e-6);
    expect(ticks.some((t) => t.kind === 'day' && t.label.includes('\n'))).toBe(true);
  });

  it('drops the least telling words first when there are more labels than rows, never a conversation name', () => {
    const tops = placeLabels([{ key: 'conv', y: 5, keep: 0 }, { key: 'backup', y: 6, keep: 5 }, { key: 'bookmark', y: 7, keep: 2 }], 32, 16);
    expect([...tops.keys()].sort()).toEqual(['bookmark', 'conv']);
  });

  it('steps through time with up and down', () => {
    const col = layoutColumn(busy(), ALL_FILTERS_ON, 560, true);
    const start = stepColumn(col, null, 'down')!;
    expect(start).toBe('conv:c6');
    expect(stepColumn(col, start, 'up')).toBe(col.items[col.items.findIndex((c) => c.item.key === start) - 1]!.item.key);
    expect(stepColumn(col, start, 'home')).toBe(col.items[0]!.item.key);
  });
});
