
export interface PieceMeasure<K extends string> {
  core: number;
  features: Partial<Record<K, number>>;
  work: Record<'full' | 'short', number>;
}

export interface PiecePlan<K extends string> {
  admit: Record<K, boolean>;
  work: 'full' | 'short';
}

export interface PieceRules<K extends string> {
  priority: readonly K[];
  requires: Partial<Record<K, K>>;
  floor: number;
}

export function pieceCost<K extends string>(key: K, m: PieceMeasure<K>): number {
  if (key === 'workFull') return Math.max(0, m.work.full - m.work.short);
  return Math.max(0, m.features[key] ?? 0);
}

export function planPieces<K extends string>(rules: PieceRules<K>, width: number, m: PieceMeasure<K> | null): PiecePlan<K> | null {
  if (!m || !(m.core > 0) || !(width > 0)) return null;
  let left = width - rules.floor - m.core - m.work.short;
  const admit = Object.fromEntries(rules.priority.map((k) => [k, false])) as Record<K, boolean>;
  for (const key of rules.priority) {
    const partner = rules.requires[key];
    if (partner && !admit[partner]) continue;
    const cost = pieceCost(key, m);
    if (cost > left) continue;
    admit[key] = true;
    left -= cost;
  }
  return { admit, work: 'workFull' in admit && (admit as Record<string, boolean>).workFull ? 'full' : 'short' };
}

export function readPieces<K extends string>(copy: HTMLElement | null, work: Record<'full' | 'short', number>): PieceMeasure<K> | null {
  if (!copy) return null;
  const whole = copy.getBoundingClientRect().width;
  if (!(whole > 0)) return null;
  const features: Partial<Record<K, number>> = {};
  let spent = 0;
  for (const el of Array.from(copy.querySelectorAll<HTMLElement>('[data-fw]'))) {
    const key = el.dataset.fw as K;
    const parent = el.parentElement;
    const gap = parent ? parseFloat(getComputedStyle(parent).columnGap) || 0 : 0;
    const cost = el.getBoundingClientRect().width + gap;
    const outer = parent?.closest<HTMLElement>('[data-fw]');
    if (outer && copy.contains(outer)) {
      const outerKey = outer.dataset.fw as K;
      features[outerKey] = (features[outerKey] ?? 0) - cost;
    } else {
      spent += cost;
    }
    features[key] = (features[key] ?? 0) + cost;
  }
  return { core: Math.max(1, whole - spent), features, work };
}
