import { pieceCost, planPieces, readPieces, type PieceMeasure, type PiecePlan } from './foot-plan-pieces';

export const FOOT_PRIORITY_B = [
  'model',
  'workFull',
  'fiveHReset',
  'ctxFraction',
  'effort',
  'captions',
  'sevenDReset',
] as const;

export type FootFeatureB = (typeof FOOT_PRIORITY_B)[number];

const FOOT_REQUIRES_B: Partial<Record<FootFeatureB, FootFeatureB>> = {
  effort: 'model',
  sevenDReset: 'fiveHReset',
};

export const FOOT_SAFETY_PX_B = 8;

export type FootMeasureB = PieceMeasure<FootFeatureB>;

export type FootPlanB = PiecePlan<FootFeatureB>;

export function pieceCostB(key: FootFeatureB, m: FootMeasureB): number {
  return pieceCost(key, m);
}

export function planFootB(width: number, m: FootMeasureB | null): FootPlanB | null {
  return planPieces<FootFeatureB>({ priority: FOOT_PRIORITY_B, requires: FOOT_REQUIRES_B, floor: FOOT_SAFETY_PX_B }, width, m);
}

export function admittedB(plan: FootPlanB | null): Record<FootFeatureB, boolean> {
  if (plan) return plan.admit;
  return {
    model: true, workFull: false, fiveHReset: false, ctxFraction: false,
    effort: false, captions: false, sevenDReset: false,
  };
}

export function readMeasureB(copy: HTMLElement | null, work: Record<'full' | 'short', number>): FootMeasureB | null {
  return readPieces<FootFeatureB>(copy, work);
}
