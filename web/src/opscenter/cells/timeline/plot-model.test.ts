import { describe, expect, it } from 'vitest';
import { timelineWidgetFixtures } from '../../widgets/fixtures/core.timeline';
import type { SessionTimeline } from './types';
import { clusterMarks, COLUMN_CONTENT_PLOT_PX, COLUMN_MIN_PLOT_PX, frameFor } from './plot-model';
import { BREAK_PX, buildScale, rulerTicks, spanWords, V_LABEL_PAD_PX, V_LINE_PX } from './scale';

/** The busy fixture, fresh. Output: SessionTimeline. */
const busy = (): SessionTimeline => structuredClone(Object.values(timelineWidgetFixtures.data).find((v) => (v as SessionTimeline).bars) as SessionTimeline);

describe('frameFor', () => {
  it('is the vertical column for every non-phone box, wide or narrow, short or tall, and the list on a phone', () => {
    for (const h of [63, 96, 225, 289, 600, 900, null]) expect(frameFor(false, h).body).toBe('column');
    expect(frameFor(true, 600).body).toBe('list');
  });

  it('gives the rail the height the detail leaves, never less than its floor, and a content-sized host a fixed rail', () => {
    expect(frameFor(false, 900).plotPx).toBeGreaterThan(frameFor(false, 500).plotPx);
    expect(frameFor(false, 63).plotPx).toBe(COLUMN_MIN_PLOT_PX);
    expect(frameFor(false, null).plotPx).toBe(COLUMN_CONTENT_PLOT_PX);
  });
});

describe('the axis', () => {
  it('squeezes long sleeps to fixed breaks and keeps short ones to scale', () => {
    const scale = buildScale(busy(), 800, true)!;
    const breaks = scale.segments.filter((s) => s.kind === 'break');
    expect(breaks.map((b) => spanWords(b.t1 - b.t0))).toEqual(['25m', '13h 15m', '30m']);
    expect(breaks.every((b) => Math.abs(b.x1 - b.x0 - BREAK_PX) < 1e-6)).toBe(true);
    expect(scale.x(Date.parse(busy().now))).toBeCloseTo(800);
  });

  it('never lets two ruler labels touch', () => {
    for (const px of [160, 300, 600, 1100]) {
      const ticks = rulerTicks(buildScale(busy(), px, true)!, px);
      const spans = ticks.map((t): [number, number] => {
        const h = t.label.split('\n').length * V_LINE_PX;
        return t.anchor === 'start' ? [t.x, t.x + h] : t.anchor === 'end' ? [t.x - h, t.x] : [t.x - h / 2, t.x + h / 2];
      });
      for (let i = 1; i < spans.length; i += 1) expect(spans[i]![0]).toBeGreaterThanOrEqual(spans[i - 1]![1] + V_LABEL_PAD_PX - 1e-6);
      expect(ticks.some((t) => t.kind === 'now')).toBe(true);
    }
  });
});

describe('clusterMarks', () => {
  it('merges close marks at their mean and keeps far ones apart', () => {
    const m = (id: string) => ({ id }) as never;
    const items = clusterMarks([{ mark: m('a'), x: 10 }, { mark: m('b'), x: 16 }, { mark: m('c'), x: 60 }], 14);
    expect(items.map((i) => [i.kind, Math.round(i.x)])).toEqual([['cluster', 13], ['mark', 60]]);
  });
});
