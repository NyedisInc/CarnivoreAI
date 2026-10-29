import { expect, test } from 'vitest';
import {
  FOOT_PRIORITY_C, FOOT_SAFETY_PX_C, admittedC, leadingScopeC, pieceCostC, planFootC,
  type FootFeatureC, type FootMeasureC,
} from './foot-plan-c';

function measureAt(): FootMeasureC {
  return {
    core: 24 + 90,
    features: { model: 95, leadBar: 64, leadReset: 60, effort: 38 },
    work: { full: 205, short: 120 },
  };
}

function kept(width: number, m: FootMeasureC = measureAt()): FootFeatureC[] {
  const plan = planFootC(width, m);
  if (!plan) throw new Error('a measured bar must plan');
  return FOOT_PRIORITY_C.filter((k) => plan.admit[k]);
}

test('everything fits: every optional piece admitted, work in full form', () => {
  const m = measureAt();
  const total = m.core + m.work.short + FOOT_SAFETY_PX_C
    + FOOT_PRIORITY_C.reduce((sum, k) => sum + pieceCostC(k, m), 0);
  expect(kept(total)).toEqual([...FOOT_PRIORITY_C]);
  expect(planFootC(total, m)?.work).toBe('full');
});

test('a narrow bar keeps only the core: no optional piece fits', () => {
  const m = measureAt();
  expect(kept(m.core + m.work.short + FOOT_SAFETY_PX_C)).toEqual([]);
});

test('effort only ever admitted beside model', () => {
  const m: FootMeasureC = { ...measureAt(), features: { ...measureAt().features, model: 999999 } };
  expect(kept(2000, m)).not.toContain('effort');
});

test('no measurement: falls back to work-short + nothing else drawn optionally', () => {
  expect(admittedC(null)).toEqual({ workFull: false, model: true, leadBar: false, leadReset: false, effort: false });
});

test('no usable width or measurement: plan is null', () => {
  expect(planFootC(0, measureAt())).toBeNull();
  expect(planFootC(1000, null)).toBeNull();
});

test('the leading scope is whichever percent is nearest its own end', () => {
  expect(leadingScopeC({ context: 44, fiveHour: 64, sevenDay: 38 })).toBe('fiveHour');
  expect(leadingScopeC({ context: 80, fiveHour: 20, sevenDay: 10 })).toBe('context');
  expect(leadingScopeC({ context: 10, fiveHour: 20, sevenDay: 90 })).toBe('sevenDay');
});

test('a tie keeps context, then the 5h window, then the 7d window', () => {
  expect(leadingScopeC({ context: 50, fiveHour: 50, sevenDay: 50 })).toBe('context');
  expect(leadingScopeC({ context: null, fiveHour: 50, sevenDay: 50 })).toBe('fiveHour');
  expect(leadingScopeC({ context: null, fiveHour: null, sevenDay: null })).toBe('context');
});
