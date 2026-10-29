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

export interface FootMeasureB {
  /* padding */
  core: number;
  features: Partial<Record<FootFeatureB, number>>;
  work: Record<'full' | 'short', number>;
}

export interface FootPlanB {
  admit: Record<FootFeatureB, boolean>;
  work: 'full' | 'short';
}

export function pieceCostB(key: FootFeatureB, m: FootMeasureB): number {
  if (key === 'workFull') return Math.max(0, m.work.full - m.work.short);
  return Math.max(0, m.features[key] ?? 0);
}

export function planFootB(width: number, m: FootMeasureB | null): FootPlanB | null {
  if (!m || !(m.core > 0) || !(width > 0)) return null;
  let left = width - FOOT_SAFETY_PX_B - m.core - m.work.short;
  const admit = Object.fromEntries(FOOT_PRIORITY_B.map((k) => [k, false])) as Record<FootFeatureB, boolean>;
  for (const key of FOOT_PRIORITY_B) {
    const partner = FOOT_REQUIRES_B[key];
    if (partner && !admit[partner]) continue;
    const cost = pieceCostB(key, m);
    if (cost > left) continue;
    admit[key] = true;
    left -= cost;
  }
  return { admit, work: admit.workFull ? 'full' : 'short' };
}

export function admittedB(plan: FootPlanB | null): Record<FootFeatureB, boolean> {
  if (plan) return plan.admit;
  return {
    model: true, workFull: false, fiveHReset: false, ctxFraction: false,
    effort: false, captions: false, sevenDReset: false,
  };
}

/*  hidden  */
export function readMeasureB(copy: HTMLElement | null, work: Record<'full' | 'short', number>): FootMeasureB | null {
  if (!copy) return null;
  const whole = copy.getBoundingClientRect().width;
  if (!(whole > 0)) return null;
  const features: Partial<Record<FootFeatureB, number>> = {};
  let spent = 0;
  for (const el of Array.from(copy.querySelectorAll<HTMLElement>('[data-fw]'))) {
    const key = el.dataset.fw as FootFeatureB;
    const parent = el.parentElement;
    const gap = parent ? parseFloat(getComputedStyle(parent).columnGap) || 0 : 0;
    const cost = el.getBoundingClientRect().width + gap;
    const outer = parent?.closest<HTMLElement>('[data-fw]');
    if (outer && copy.contains(outer)) {
      const outerKey = outer.dataset.fw as FootFeatureB;
      features[outerKey] = (features[outerKey] ?? 0) - cost;
    } else {
      spent += cost;
    }
    features[key] = (features[key] ?? 0) + cost;
  }
  return { core: Math.max(1, whole - spent), features, work };
}
