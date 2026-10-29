/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { homeLayout, terminalLayout } from './layout.svelte';
import { resetLayout } from './model';
import { META } from './meta';
import { validate } from './persist';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { parseArrangement, upsertEntry, emptyArrangement } from './arrangement-model';
import { isWallboardSearch, readOnlyStore, wallboardLayout } from './wallboard';
import type { Layout } from './types';

const A = 'analytics:11111111-1111-4111-8111-111111111111';
const B = 'analytics:22222222-2222-4222-8222-222222222222';

function withCharts(): Layout {
  const base = resetLayout(META, 'home');
  return { ...base, rows: [...base.rows, { id: 'r90', kind: 'px', size: 300, slots: [{ id: A, fr: 0.5 }, { id: B, fr: 0.5 }] }] };
}

test('the view keeps analytics only and scales rows to fit the window, down to a floor', () => {
  const view = wallboardLayout(withCharts());
  expect(view.rows).toHaveLength(1);
  expect(view.rows[0]!.kind).toBe('px');
  expect(view.rows[0]!.size).toBe(300);
  expect(wallboardLayout(withCharts(), 900).rows[0]!.size).toBe(900);
  expect(wallboardLayout(withCharts(), 100).rows[0]!.size).toBe(180);
  expect(wallboardLayout(withCharts(), 0).rows[0]!.size).toBe(300);
  expect(view.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toEqual([A, B]);
  expect(view.hidden).toEqual([]);
});

test('the wallboard URL param selects the view', () => {
  expect(isWallboardSearch('?view=wallboard')).toBe(true);
  expect(isWallboardSearch('')).toBe(false);
  expect(isWallboardSearch('?view=other')).toBe(false);
});

test('the read-only store follows the source live and never writes it', () => {
  homeLayout.adopt(withCharts());
  const store = readOnlyStore(homeLayout);
  expect(store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toEqual([A, B]);
  const before = JSON.stringify(homeLayout.state.layout);
  store.remove(A);
  store.hide(B);
  store.arrange('columns');
  store.resetAll();
  store.setHeroCollapsed(true);
  expect(JSON.stringify(homeLayout.state.layout)).toBe(before);
  homeLayout.remove(B);
  expect(store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toEqual([A]);
});

test('an analytics widget is allowed on the terminal canvas and round-trips validation and terminal_layouts', () => {
  expect(CORE_MANIFESTS['core.analytics']!.canvases).toContain('terminal');
  const base = resetLayout(META, 'terminal');
  const last = base.rows[base.rows.length - 1]!;
  const layout: Layout = { ...base, rows: [...base.rows.slice(0, -1), { ...last, slots: [...last.slots.map((slot) => ({ ...slot, fr: 0.5 })), { id: A, fr: 0.5 }] }] };
  const checked = validate(JSON.parse(JSON.stringify(layout)), META, 'terminal');
  expect(checked.layout).not.toBeNull();
  expect(checked.layout!.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toContain(A);
  const stored = upsertEntry(emptyArrangement(), 'cloude_x:1', { layout: checked.layout!, groups: {}, active: {} } as never);
  const parsed = parseArrangement(JSON.parse(JSON.stringify(stored)));
  expect(parsed).not.toBeNull();
  expect(JSON.stringify(parsed)).toContain(A);
  expect(terminalLayout.add('analytics', '33333333-3333-4333-8333-333333333333')).toBeNull();
});
