import { pieceCost, planPieces, readPieces, type PieceMeasure, type PiecePlan } from './foot-plan-pieces';

export const FOOT_PRIORITY_C = ['workFull', 'model', 'leadBar', 'leadReset', 'effort'] as const;

export type FootFeatureC = (typeof FOOT_PRIORITY_C)[number];

const FOOT_REQUIRES_C: Partial<Record<FootFeatureC, FootFeatureC>> = {
  effort: 'model',
};

export const FOOT_SAFETY_PX_C = 8;

export type FootMeasureC = PieceMeasure<FootFeatureC>;

export type FootPlanC = PiecePlan<FootFeatureC>;

export type LeadScope = 'context' | 'fiveHour' | 'sevenDay';

export function leadingScopeC(pct: Record<LeadScope, number | null>): LeadScope {
  let best: LeadScope = 'context';
  const order: readonly LeadScope[] = ['context', 'fiveHour', 'sevenDay'];
  for (const scope of order) {
    if ((pct[scope] ?? -1) > (pct[best] ?? -1)) best = scope;
  }
  return best;
}

export function pieceCostC(key: FootFeatureC, m: FootMeasureC): number {
  return pieceCost(key, m);
}

export function planFootC(width: number, m: FootMeasureC | null): FootPlanC | null {
  return planPieces<FootFeatureC>({ priority: FOOT_PRIORITY_C, requires: FOOT_REQUIRES_C, floor: FOOT_SAFETY_PX_C }, width, m);
}

export function admittedC(plan: FootPlanC | null): Record<FootFeatureC, boolean> {
  if (plan) return plan.admit;
  return { workFull: false, model: true, leadBar: false, leadReset: false, effort: false };
}

export function readMeasureC(copy: HTMLElement | null, work: Record<'full' | 'short', number>): FootMeasureC | null {
  return readPieces<FootFeatureC>(copy, work);
}
