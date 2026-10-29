/* and the three the bottom bar */

export const FOOT_BAR_COLLAPSED_OPTIONS = ['a', 'b', 'c'] as const;
export type FootBarCollapsedOption = (typeof FOOT_BAR_COLLAPSED_OPTIONS)[number];
export const DEFAULT_FOOT_BAR_COLLAPSED_OPTION: FootBarCollapsedOption = 'a';

export function resolveFootBarCollapsedOption(value: unknown): FootBarCollapsedOption {
  return (FOOT_BAR_COLLAPSED_OPTIONS as readonly unknown[]).includes(value)
    ? (value as FootBarCollapsedOption)
    : DEFAULT_FOOT_BAR_COLLAPSED_OPTION;
}

export const FOOT_PRIORITY = [
  'model',
  'effort',
  'bars',
  'reset5h',
  'reset7d',
  'fullLabels',
  'contextDetail',
  'workFull',
] as const;

export type FootFeature = (typeof FOOT_PRIORITY)[number];

const FOOT_FLOOR: readonly FootFeature[] = ['model', 'effort'];

const FOOT_REQUIRES: Partial<Record<FootFeature, FootFeature>> = {
  effort: 'model',
  reset7d: 'reset5h',
};

export type WorkForm = 'full' | 'short';

export interface FootMeasure {
  core: number;
  features: Partial<Record<FootFeature, number>>;
  work: Record<WorkForm, number>;
  labels: Record<'full' | 'short', number>;
}

export interface FootPlan {
  admit: Record<FootFeature, boolean>;
  work: WorkForm;
  edgePx: number;
}

export const FOOT_SAFETY_PX = 8;

const SPACING = { minWidth: 600, maxWidth: 1100, leadTight: 14, leadWide: 32, barTight: 48, barWide: 90, edgeTight: 8, edgeWide: 56 } as const;

const GROUP_GAP = { minWidth: 320, maxWidth: 600, tight: 4, wide: 28 } as const;

export function footSpacing(width: number): { leadPx: number; barPx: number; groupPx: number; edgePx: number } {
  const g = Math.min(1, Math.max(0, (width - GROUP_GAP.minWidth) / (GROUP_GAP.maxWidth - GROUP_GAP.minWidth)));
  const t = Math.min(1, Math.max(0, (width - SPACING.minWidth) / (SPACING.maxWidth - SPACING.minWidth)));
  return {
    leadPx: Math.round(SPACING.leadTight + (SPACING.leadWide - SPACING.leadTight) * t),
    barPx: Math.round(SPACING.barTight + (SPACING.barWide - SPACING.barTight) * t),
    groupPx: Math.round(GROUP_GAP.tight + (GROUP_GAP.wide - GROUP_GAP.tight) * g),
    edgePx: Math.round(SPACING.edgeTight + (SPACING.edgeWide - SPACING.edgeTight) * t),
  };
}

export function pieceCost(key: FootFeature, m: FootMeasure): number {
  if (key === 'workFull') return Math.max(0, m.work.full - m.work.short);
  if (key === 'fullLabels') return Math.max(0, m.labels.full - m.labels.short);
  return Math.max(0, m.features[key] ?? 0);
}

export function planFoot(width: number, m: FootMeasure | null): FootPlan | null {
  if (!m || !(m.core > 0) || !(width > 0)) return null;
  let left = width - FOOT_SAFETY_PX - m.core - m.work.short;
  const admit = Object.fromEntries(FOOT_PRIORITY.map((k) => [k, false])) as Record<FootFeature, boolean>;
  for (const key of FOOT_PRIORITY) {
    const partner = FOOT_REQUIRES[key];
    if (partner && !admit[partner]) continue;
    const cost = pieceCost(key, m);
    if (cost > left && !FOOT_FLOOR.includes(key)) continue;
    admit[key] = true;
    left -= cost;
  }
  const edgePx = Math.max(0, Math.min(footSpacing(width).edgePx, Math.floor(left / 2)));
  return { admit, work: admit.workFull ? 'full' : 'short', edgePx };
}

export function admitted(
  plan: FootPlan | null,
  ladder: { bars: boolean; effort: boolean; reset: boolean },
): Record<FootFeature, boolean> {
  if (plan) return plan.admit;
  return {
    model: true,
    bars: ladder.bars,
    reset5h: ladder.reset,
    workFull: true,
    effort: ladder.effort,
    contextDetail: ladder.bars,
    reset7d: ladder.reset,
    fullLabels: false,
  };
}

export function readMeasure(
  copy: HTMLElement | null,
  work: Record<WorkForm, number>,
  labels: Record<'full' | 'short', number> = { full: 0, short: 0 },
): FootMeasure | null {
  if (!copy) return null;
  const whole = copy.getBoundingClientRect().width;
  if (!(whole > 0)) return null;
  const features: Partial<Record<FootFeature, number>> = {};
  let spent = 0;
  for (const el of Array.from(copy.querySelectorAll<HTMLElement>('[data-fw]'))) {
    const key = el.dataset.fw as FootFeature;
    const parent = el.parentElement;
    const gap = parent ? parseFloat(getComputedStyle(parent).columnGap) || 0 : 0;
    const cost = el.getBoundingClientRect().width + gap;
    const outer = parent?.closest<HTMLElement>('[data-fw]');
    if (outer && copy.contains(outer)) {
      const outerKey = outer.dataset.fw as FootFeature;
      features[outerKey] = (features[outerKey] ?? 0) - cost;
    } else {
      spent += cost;
    }
    features[key] = (features[key] ?? 0) + cost;
  }
  return { core: Math.max(1, whole - spent), features, work, labels };
}

export const FOOT_BAR_ITEM_IDS = [
  'model', 'effort', 'context', 'window_5h', 'window_7d', 'agents', 'shells', 'timers',
] as const;

export type FootBarItemId = (typeof FOOT_BAR_ITEM_IDS)[number];

export const FOOT_BAR_ITEMS_FIELD = 'foot_bar_items';

import { FOOT_BAR_ITEM_DEFAULTS } from '../../../lib/foot-bar-item-defaults';

export type FootBarItems = Record<FootBarItemId, boolean>;

export const DEFAULT_FOOT_BAR_ITEMS: FootBarItems = Object.fromEntries(
  FOOT_BAR_ITEM_IDS.map((id) => [id, FOOT_BAR_ITEM_DEFAULTS[id]]),
) as FootBarItems;

export function asFootBarItems(value: unknown): FootBarItems {
  const out: FootBarItems = { ...DEFAULT_FOOT_BAR_ITEMS };
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const id of FOOT_BAR_ITEM_IDS) {
      if (typeof record[id] === 'boolean') out[id] = record[id] as boolean;
    }
  }
  return out;
}

export function maskAdmitByItems(admit: Record<FootFeature, boolean>, items: FootBarItems): Record<FootFeature, boolean> {
  const model = admit.model && items.model;
  return { ...admit, model, effort: admit.effort && items.effort && model };
}

export interface CoreVisible {
  context: boolean;
  window5h: boolean;
  window7d: boolean;
}

export function coreVisible(items: FootBarItems): CoreVisible {
  return { context: items.context, window5h: items.window_5h, window7d: items.window_7d };
}
