/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import FootStats from './FootStats.svelte';
import { statsGroups } from './foot-stats';
import { sessionUsageLabels } from '../../api';
import type { SessionTokenUsage } from '../../api';
import { argentCostView, type ArgentCostSnapshot } from '../../../lib/argent-cost/cost-view';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');

const usage = {
  state: 'ok', model: 'claude-opus-5', input_tokens: 1, output_tokens: 1, cost_estimate_usd: 1,
  context_remaining_pct: 50, context_used_tokens: 1, context_window_tokens: 2, account: null,
} as unknown as SessionTokenUsage;
const model = sessionUsageLabels(usage, null);

const SNAP: ArgentCostSnapshot = {
  enabled: true, state: 'ok',
  sessions: { '7': { items: ['wi_a', 'wi_b'], cost: { cost_micros: 1_234_500 } }, '8': { items: [], cost: { cost_micros: 99_000_000 } }, '9': { items: ['wi_a'], cost: null } },
  items: { wi_a: { budget: { state: 'warn', spent_micros: 8_500_000, cap_micros: 10_000_000 } }, wi_b: { budget: { state: 'ok', spent_micros: 1_000_000, cap_micros: 10_000_000 } } },
};

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

function render(rowId: number | null, snap: ArgentCostSnapshot | null): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(FootStats, { target, props: { model, payload: usage, argent: argentCostView(snap, rowId) } }));
  flushSync();
  return target;
}

test('grown stats draw the cost and the worst budget bar right after the usage cost cell', () => {
  const keys = statsGroups(model, usage, Date.now(), null, argentCostView(SNAP, 7)).flat().map((c) => c.key);
  expect(keys.indexOf('argent')).toBe(keys.indexOf('cost') + 1);
  const el = render(7, SNAP);
  expect(el.querySelector('[data-argent-cost]')?.textContent).toBe('$1.23');
  expect(el.querySelector('[data-argent-budget]')?.getAttribute('data-scale')).toBe('3');
  expect(el.textContent).toContain('85%');
});

test('an unmeasured cost reads a dash and no budget bar is drawn without a measured budget', () => {
  const el = render(9, { ...SNAP, items: { wi_a: { budget: null } } });
  expect(el.querySelector('[data-argent-cost]')?.textContent).toBe('-');
  expect(el.querySelector('[data-argent-budget]')).toBeNull();
});

test('negative controls: off, pending, an untracked row and no row id draw no argent cell, and a row never shows another row cost', () => {
  for (const [id, snap] of [[7, { ...SNAP, enabled: false }], [7, { ...SNAP, state: 'pending' }], [5, SNAP], [null, SNAP], [7, null]] as const) {
    expect(argentCostView(snap as ArgentCostSnapshot | null, id)).toBeNull();
    expect(render(id, snap as ArgentCostSnapshot | null).querySelector('[data-stat="argent"]')).toBeNull();
  }
  expect(render(8, SNAP).querySelector('[data-argent-cost]')?.textContent).toBe('$99.00');
  expect(argentCostView(SNAP, 8)?.pct).toBeNull();
});
