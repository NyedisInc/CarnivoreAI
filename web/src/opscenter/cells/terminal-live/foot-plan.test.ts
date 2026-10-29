// @vitest-environment jsdom
import { expect, test } from 'vitest';
import {
  DEFAULT_FOOT_BAR_COLLAPSED_OPTION,
  DEFAULT_FOOT_BAR_ITEMS,
  FOOT_BAR_COLLAPSED_OPTIONS,
  FOOT_BAR_ITEM_IDS,
  FOOT_PRIORITY,
  FOOT_SAFETY_PX,
  admitted,
  asFootBarItems,
  coreVisible,
  footSpacing,
  maskAdmitByItems,
  pieceCost,
  planFoot,
  readMeasure,
  resolveFootBarCollapsedOption,
  type FootFeature,
  type FootMeasure,
} from './foot-plan';
import { splitFoot } from './foot-toolbar';

function measureAt(width: number): FootMeasure {
  const { leadPx, barPx } = footSpacing(width);
  return {
    core: 24 + 126 + 2 * leadPx,
    features: { model: 95, bars: 3 * (barPx + 4), reset5h: 60, effort: 38, contextDetail: 54, reset7d: 50 },
    work: { full: 205, short: 120 },
    labels: { full: 130, short: 40 },
  };
}

function kept(width: number, m: FootMeasure = measureAt(width)): FootFeature[] {
  const plan = planFoot(width, m);
  if (!plan) throw new Error('a measured bar must plan');
  return FOOT_PRIORITY.filter((k) => plan.admit[k]);
}

test('1440 window: everything fits, the work segments in full', () => {
  expect(kept(1118)).toEqual([...FOOT_PRIORITY]);
  expect(planFoot(1118, measureAt(1118))?.work).toBe('full');
});

test('704 window: the bars hold with the model and effort, then the 5h timer; the 7d timer, full labels and fraction go first (Alex, 2026-10-02)', () => {
  expect(kept(704)).toEqual(['model', 'effort', 'bars', 'reset5h']);
  expect(planFoot(704, measureAt(704))?.work).toBe('short');
});

test('800 window: the effort stays with the model; the bars, resets, full labels and fraction go before it (Alex, 2026-09-29)', () => {
  expect(kept(480)).toEqual(['model', 'effort']);
  expect(planFoot(480, measureAt(480))?.work).toBe('short');
});

test('too narrow for anything optional: the percents and the short work segments stay, and so do the model and effort', () => {
  const plan = planFoot(300, measureAt(300));
  expect(plan && FOOT_PRIORITY.filter((k) => plan.admit[k])).toEqual(['model', 'effort']);
  expect(plan?.work).toBe('short');
});

test('the bars go all together, and tokens are not a piece of the collapsed bar at all', () => {
  expect(FOOT_PRIORITY).not.toContain('tokens');
  for (let width = 300; width <= 1600; width += 10) {
    const plan = planFoot(width, measureAt(width))!;
    expect(typeof plan.admit.bars).toBe('boolean');
  }
});

test('a ~1090px cell keeps all three fixed 112px bars; resets and full labels give way first (Alex, 2026-10-02)', () => {
  const m: FootMeasure = {
    core: 500,
    features: { model: 80, effort: 30, contextDetail: 55, bars: 3 * (112 + 4), reset5h: 60, reset7d: 60 },
    work: { full: 90, short: 50 },
    labels: { full: 130, short: 40 },
  };
  const plan = planFoot(1090, m)!;
  expect(plan.admit.bars).toBe(true);
  expect(plan.admit.reset5h && plan.admit.reset7d && plan.admit.fullLabels).toBe(false);
});

test('a ~990px cell keeps both reset timers: the edge gap is not in the core and takes only what is left (Alex, 2026-10-02)', () => {
  const m: FootMeasure = {
    core: 215,
    features: { model: 130, effort: 50, contextDetail: 55, bars: 3 * (112 + 4), reset5h: 55, reset7d: 60 },
    work: { full: 0, short: 0 },
    labels: { full: 130, short: 40 },
  };
  const plan = planFoot(930, m)!;
  expect(plan.admit.reset5h && plan.admit.reset7d && plan.admit.bars).toBe(true);
  expect(plan.admit.fullLabels).toBe(false);
  expect(plan.edgePx).toBeLessThanOrEqual(4);
  expect(planFoot(1400, m)!.edgePx).toBe(footSpacing(1400).edgePx);
});

test('the 7d reset never without the 5h reset', () => {
  const wideReset: FootMeasure = { ...measureAt(704), features: { ...measureAt(704).features, reset5h: 400 } };
  expect(planFoot(704, wideReset)?.admit.reset5h).toBe(false);
  expect(planFoot(704, wideReset)?.admit.reset7d).toBe(false);
});

test('no big empty gap: what is left over is smaller than every piece that could still come back', () => {
  for (let width = 450; width <= 1600; width += 5) {
    const m = measureAt(width);
    const plan = planFoot(width, m)!;
    const used = m.core + m.work.short
      + FOOT_PRIORITY.reduce((sum, k) => sum + (plan.admit[k] ? pieceCost(k, m) : 0), 0);
    expect(used).toBeLessThanOrEqual(width - FOOT_SAFETY_PX);
    const left = width - FOOT_SAFETY_PX - used;
    for (const k of FOOT_PRIORITY) {
      const partnerMissing = (k === 'effort' && !plan.admit.model) || (k === 'reset7d' && !plan.admit.reset5h);
      if (!plan.admit[k] && !partnerMissing) expect(pieceCost(k, m)).toBeGreaterThan(left);
    }
  }
});

test('the naming ladder: the full words shorten before the fraction goes, after the resets and bars', () => {
  expect(planFoot(1118, measureAt(1118))?.admit.fullLabels).toBe(true);
  expect(planFoot(704, measureAt(704))?.admit.fullLabels).toBe(false);
  expect(planFoot(480, measureAt(480))?.admit.fullLabels).toBe(false);
  expect(planFoot(300, measureAt(300))?.admit.fullLabels).toBe(false);
});

test('fullLabels costs the delta between the two label widths, never the whole full width', () => {
  const m = measureAt(1118);
  expect(pieceCost('fullLabels', m)).toBe(m.labels.full - m.labels.short);
  const equalWidths: FootMeasure = { ...m, labels: { full: 40, short: 40 } };
  expect(pieceCost('fullLabels', equalWidths)).toBe(0);
});

test('a piece with nothing to draw costs nothing, and no work at all is the full form', () => {
  const idle: FootMeasure = { ...measureAt(480), features: { ...measureAt(480).features, effort: undefined }, work: { full: 0, short: 0 } };
  expect(planFoot(480, idle)?.admit.effort).toBe(true);
  expect(planFoot(480, idle)?.work).toBe('full');
});

test('the spacing feathers between its tight and wide values', () => {
  expect(footSpacing(0)).toEqual({ leadPx: 14, barPx: 48, groupPx: 4, edgePx: 8 });
  expect(footSpacing(1440)).toEqual({ leadPx: 32, barPx: 90, groupPx: 28, edgePx: 56 });
  const mid = footSpacing(850);
  expect(mid.barPx).toBeGreaterThan(48);
  expect(mid.barPx).toBeLessThan(90);
});

test('readMeasure takes a nested piece (the effort inside the model group) out of its ancestor', () => {
  const copy = document.createElement('div');
  copy.innerHTML = '<span data-fw="model"><span>Opus</span><span data-fw="effort">high</span></span><span data-fw="bars"></span>';
  const widths = new Map<Element, number>([
    [copy, 400],
    [copy.querySelector('[data-fw="model"]')!, 100],
    [copy.querySelector('[data-fw="effort"]')!, 30],
    [copy.querySelector('[data-fw="bars"]')!, 60],
  ]);
  for (const [el, w] of widths) {
    (el as HTMLElement).getBoundingClientRect = () => ({ width: w }) as DOMRect;
  }
  const m = readMeasure(copy, { full: 10, short: 5 });
  expect(m?.features).toEqual({ model: 70, effort: 30, bars: 60 });
  expect(m?.core).toBe(240);
  expect(m?.labels).toEqual({ full: 0, short: 0 });
});

test('readMeasure carries the labels argument through untouched, the same way it carries work', () => {
  const copy = document.createElement('div');
  copy.getBoundingClientRect = () => ({ width: 400 }) as DOMRect;
  const m = readMeasure(copy, { full: 10, short: 5 }, { full: 130, short: 40 });
  expect(m?.labels).toEqual({ full: 130, short: 40 });
});

test('no measurement, no plan: the fixed ladder answers instead, never dropping the model', () => {
  expect(planFoot(1440, null)).toBeNull();
  expect(planFoot(1440, { ...measureAt(1440), core: 0 })).toBeNull();
  const ladder = admitted(null, splitFoot(600));
  expect(ladder.model).toBe(true);
  expect(ladder.workFull).toBe(true);
  expect(ladder.reset5h).toBe(false);
});

// THE COLLAPSED BAR'S SHOWN ITEMS (issue #1053, Joe (ccsliinc), 2026-09-28):
test('asFootBarItems: absent, non-boolean or unknown always reads as shown', () => {
  expect(asFootBarItems(undefined)).toEqual(DEFAULT_FOOT_BAR_ITEMS);
  expect(asFootBarItems(null)).toEqual(DEFAULT_FOOT_BAR_ITEMS);
  expect(asFootBarItems({ agents: false })).toEqual({ ...DEFAULT_FOOT_BAR_ITEMS, agents: false });
  expect(asFootBarItems({ agents: 'no', bogus_id: false })).toEqual(DEFAULT_FOOT_BAR_ITEMS);
  expect(FOOT_BAR_ITEM_IDS).toEqual(
    ['model', 'effort', 'context', 'window_5h', 'window_7d', 'agents', 'shells', 'timers']);
});

test('maskAdmitByItems: a hidden model also drops its effort, exactly as FOOT_REQUIRES does on width alone', () => {
  const all = Object.fromEntries(FOOT_PRIORITY.map((k) => [k, true])) as Record<FootFeature, boolean>;
  expect(maskAdmitByItems(all, DEFAULT_FOOT_BAR_ITEMS)).toEqual(all);
  const noModel = maskAdmitByItems(all, { ...DEFAULT_FOOT_BAR_ITEMS, model: false });
  expect(noModel.model).toBe(false);
  expect(noModel.effort).toBe(false);
  expect(noModel.bars).toBe(true);
  const noEffort = maskAdmitByItems(all, { ...DEFAULT_FOOT_BAR_ITEMS, effort: false });
  expect(noEffort.model).toBe(true);
  expect(noEffort.effort).toBe(false);
  const widthDropped = { ...all, model: false };
  expect(maskAdmitByItems(widthDropped, { ...DEFAULT_FOOT_BAR_ITEMS, model: true }).model).toBe(false);
});

test('resolveFootBarCollapsedOption: a/b/c are all implemented, anything else falls back to "a"', () => {
  expect(DEFAULT_FOOT_BAR_COLLAPSED_OPTION).toBe('a');
  expect(FOOT_BAR_COLLAPSED_OPTIONS).toEqual(['a', 'b', 'c']);
  expect(resolveFootBarCollapsedOption('a')).toBe('a');
  expect(resolveFootBarCollapsedOption('b')).toBe('b');
  expect(resolveFootBarCollapsedOption('c')).toBe('c');
  expect(resolveFootBarCollapsedOption(undefined)).toBe('a');
  expect(resolveFootBarCollapsedOption('bogus')).toBe('a');
});

test('coreVisible: each of the three core meters follows its own item', () => {
  expect(coreVisible(DEFAULT_FOOT_BAR_ITEMS)).toEqual({ context: true, window5h: true, window7d: true });
  expect(coreVisible({ ...DEFAULT_FOOT_BAR_ITEMS, context: false })).toEqual(
    { context: false, window5h: true, window7d: true });
  expect(coreVisible({ ...DEFAULT_FOOT_BAR_ITEMS, window_5h: false, window_7d: false })).toEqual(
    { context: true, window5h: false, window7d: false });
});

test('the model and the effort are admitted at every width, down to 320 (Alex, 2026-09-29)', () => {
  for (const w of [320, 360, 400, 500]) {
    const plan = planFoot(w, measureAt(w));
    expect(plan?.admit.model, `model at ${w}`).toBe(true);
    expect(plan?.admit.effort, `effort at ${w}`).toBe(true);
  }
  expect(planFoot(200, measureAt(200))?.admit.effort).toBe(true);
});

test('the group gap shrinks below 600 px and is exactly 28 px from 600 up', () => {
  expect(footSpacing(1440).groupPx).toBe(28);
  expect(footSpacing(600).groupPx).toBe(28);
  expect(footSpacing(320).groupPx).toBe(4);
  expect(footSpacing(460).groupPx).toBeLessThan(28);
});
