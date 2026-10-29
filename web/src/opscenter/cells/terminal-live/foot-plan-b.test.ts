import { expect, test } from 'vitest';
import {
  FOOT_PRIORITY_B, FOOT_SAFETY_PX_B, admittedB, pieceCostB, planFootB,
  type FootFeatureB, type FootMeasureB,
} from './foot-plan-b';

function measureAt(): FootMeasureB {
  return {
    core: 24 + 90,
    features: { model: 95, fiveHReset: 60, ctxFraction: 54, effort: 38, captions: 70, sevenDReset: 50 },
    work: { full: 205, short: 120 },
  };
}

function kept(width: number, m: FootMeasureB = measureAt()): FootFeatureB[] {
  const plan = planFootB(width, m);
  if (!plan) throw new Error('a measured bar must plan');
  return FOOT_PRIORITY_B.filter((k) => plan.admit[k]);
}

test('everything fits: every optional piece admitted, work in full form', () => {
  const m = measureAt();
  const total = m.core + m.work.short + FOOT_SAFETY_PX_B
    + FOOT_PRIORITY_B.reduce((sum, k) => sum + pieceCostB(k, m), 0);
  expect(kept(total)).toEqual([...FOOT_PRIORITY_B]);
  expect(planFootB(total, m)?.work).toBe('full');
});

test('a narrow bar keeps only the core: no optional piece fits', () => {
  const m = measureAt();
  expect(kept(m.core + m.work.short + FOOT_SAFETY_PX_B)).toEqual([]);
});

test('captions never admitted when there is not room for its own cost', () => {
  const m = measureAt();
  const partial = m.core + m.work.short + FOOT_SAFETY_PX_B
    + pieceCostB('model', m) + pieceCostB('workFull', m) + pieceCostB('fiveHReset', m)
    + pieceCostB('ctxFraction', m) + pieceCostB('effort', m) + pieceCostB('captions', m) - 1;
  expect(kept(partial)).not.toContain('captions');
});

test('sevenDReset only ever admitted beside fiveHReset', () => {
  const m: FootMeasureB = { ...measureAt(), features: { ...measureAt().features, fiveHReset: 999999 } };
  expect(kept(2000, m)).not.toContain('sevenDReset');
});

test('effort only ever admitted beside model', () => {
  const m: FootMeasureB = { ...measureAt(), features: { ...measureAt().features, model: 999999 } };
  expect(kept(2000, m)).not.toContain('effort');
});

test('no measurement: falls back to model + core only, nothing else', () => {
  expect(admittedB(null)).toEqual({
    model: true, workFull: false, fiveHReset: false, ctxFraction: false,
    effort: false, captions: false, sevenDReset: false,
  });
});

test('no usable width or measurement: plan is null', () => {
  expect(planFootB(0, measureAt())).toBeNull();
  expect(planFootB(1000, null)).toBeNull();
  expect(planFootB(1000, { core: 0, features: {}, work: { full: 0, short: 0 } })).toBeNull();
});
