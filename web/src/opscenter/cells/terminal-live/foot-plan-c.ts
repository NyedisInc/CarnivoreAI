export const FOOT_PRIORITY_C = ['workFull', 'model', 'leadBar', 'leadReset', 'effort'] as const;

export type FootFeatureC = (typeof FOOT_PRIORITY_C)[number];

const FOOT_REQUIRES_C: Partial<Record<FootFeatureC, FootFeatureC>> = {
  effort: 'model',
};

export const FOOT_SAFETY_PX_C = 8;

export interface FootMeasureC {
  /* padding */
  core: number;
  features: Partial<Record<FootFeatureC, number>>;
  work: Record<'full' | 'short', number>;
}

export interface FootPlanC {
  admit: Record<FootFeatureC, boolean>;
  work: 'full' | 'short';
}

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
  if (key === 'workFull') return Math.max(0, m.work.full - m.work.short);
  return Math.max(0, m.features[key] ?? 0);
}

export function planFootC(width: number, m: FootMeasureC | null): FootPlanC | null {
  if (!m || !(m.core > 0) || !(width > 0)) return null;
  let left = width - FOOT_SAFETY_PX_C - m.core - m.work.short;
  const admit = Object.fromEntries(FOOT_PRIORITY_C.map((k) => [k, false])) as Record<FootFeatureC, boolean>;
  for (const key of FOOT_PRIORITY_C) {
    const partner = FOOT_REQUIRES_C[key];
    if (partner && !admit[partner]) continue;
    const cost = pieceCostC(key, m);
    if (cost > left) continue;
    admit[key] = true;
    left -= cost;
  }
  return { admit, work: admit.workFull ? 'full' : 'short' };
}

export function admittedC(plan: FootPlanC | null): Record<FootFeatureC, boolean> {
  if (plan) return plan.admit;
  return { workFull: false, model: true, leadBar: false, leadReset: false, effort: false };
}

/*  hidden  */
export function readMeasureC(copy: HTMLElement | null, work: Record<'full' | 'short', number>): FootMeasureC | null {
  if (!copy) return null;
  const whole = copy.getBoundingClientRect().width;
  if (!(whole > 0)) return null;
  const features: Partial<Record<FootFeatureC, number>> = {};
  let spent = 0;
  for (const el of Array.from(copy.querySelectorAll<HTMLElement>('[data-fw]'))) {
    const key = el.dataset.fw as FootFeatureC;
    const parent = el.parentElement;
    const gap = parent ? parseFloat(getComputedStyle(parent).columnGap) || 0 : 0;
    const cost = el.getBoundingClientRect().width + gap;
    const outer = parent?.closest<HTMLElement>('[data-fw]');
    if (outer && copy.contains(outer)) {
      const outerKey = outer.dataset.fw as FootFeatureC;
      features[outerKey] = (features[outerKey] ?? 0) - cost;
    } else {
      spent += cost;
    }
    features[key] = (features[key] ?? 0) + cost;
  }
  return { core: Math.max(1, whole - spent), features, work };
}
