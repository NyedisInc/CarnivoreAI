import { describe, expect, it } from 'vitest';
import type { IdleReport } from '../sdk/widget-lab';
import { measureIdle, readingOf } from './idle-read';

const report = (hidden: number, routes: Record<string, number> = {}): IdleReport => ({ shown: { requests: hidden }, hidden: { requests: hidden }, shell: 9, hiddenRoutes: routes, failures: [] });

function windowWith(state: { ready: boolean; error?: string; idle?: () => Promise<IdleReport> }) {
  return { __widgetHarness: { ready: state.ready, error: state.error ?? '', misses: [], idle: state.idle }, document: {} } as never;
}

describe('idle readout', () => {
  it('lists the hidden routes busiest first', () => {
    expect(readingOf(report(14, { 'GET /a': 2, 'GET /b': 12 }))).toEqual({ hidden: 14, shown: 14, routes: ['GET /b x12', 'GET /a x2'] });
  });

  it('reads a clean widget as zero', async () => {
    const got = await measureIdle(windowWith({ ready: true, idle: async () => report(0) }), () => false);
    expect(got?.hidden).toBe(0);
  });

  it('reads a polling widget as its count (the negative control)', async () => {
    const got = await measureIdle(windowWith({ ready: true, idle: async () => report(12, { 'GET /planted-offender': 12 }) }), () => false);
    expect(got).toEqual({ hidden: 12, shown: 12, routes: ['GET /planted-offender x12'] });
  });

  it('reads nothing from a frame with no check or a draw error', async () => {
    expect(await measureIdle(windowWith({ ready: true }), () => false)).toBeNull();
    expect(await measureIdle(windowWith({ ready: true, error: 'x', idle: async () => report(0) }), () => false)).toBeNull();
  });
});
