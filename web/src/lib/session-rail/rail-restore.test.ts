/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD, RAIL_SPECS, type RailEdge } from './rail-model';
import { openKey } from './rail-open';
import { railOutSizes } from './rail-out-size.svelte';
import { railSlideout } from './slideout.svelte';
import { BOTTOM_FIELD, follow, keyIn, mountRails, remountRails, unmountRails } from './rail-test-harness';

const items = (...widgets: string[]) => ({ items: widgets.map((widget) => ({ widget })) });
const rail = (edge: RailEdge): HTMLElement => document.getElementById(RAIL_SPECS[edge].id)!;
const panel = (): HTMLElement | null => document.querySelector<HTMLElement>('[data-rail-slideout]');
const shownWidgets = (): string[] => [...document.querySelectorAll<HTMLElement>('[data-rail-out-section]')].map((s) => s.dataset['railOutWidget']!);

function refresh(): void {
  unmountRails();
  railSlideout.reload();
  railOutSizes.reload();
  remountRails();
}

beforeEach(() => {
  mountRails();
  localStorage.removeItem('carnivore.session.rail.out.side');
  localStorage.removeItem('carnivore.session.rail.out.bottom');
  railOutSizes.reload();
  follow(RAIL_FIELD, { v: 2, ratio: 0.5, sections: [items('core.changes', 'core.files'), items('core.notes')] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }, { widget: 'core.ledger' }] });
});
afterEach(() => unmountRails());

test('each rail comes back with the same widgets open at the same size, pushed, with no slide', () => {
  for (const [edge, press, expectShown, size, margin] of [
    ['side', ['core.files'], ['core.files', 'core.notes'], 520, 'marginLeft'],
    ['bottom', ['core.ledger'], ['core.ledger'], 400, 'marginTop'],
  ] as const) {
    for (const key of press) keyIn(edge, key).click();
    flushSync();
    railOutSizes.set(edge, size, 2000);
    railOutSizes.remember(edge);
    flushSync();
    expect(shownWidgets()).toEqual(expectShown);

    refresh();
    expect(railSlideout.edge).toBe(edge);
    expect(shownWidgets()).toEqual(expectShown);
    expect(panel()!.dataset['railExtent']).toBe(String(size));
    expect(rail(edge).style[margin]).toBe(`${size}px`);
    expect(railSlideout.restoring).toBe(true);
    expect(JSON.parse(localStorage.getItem(openKey(edge))!)).toEqual(expectShown);

    keyIn(edge, press[0]).click();
    flushSync();
    expect(railSlideout.restoring).toBe(false);
    expect(railSlideout.edge).toBeNull();
    expect(JSON.parse(localStorage.getItem(openKey(edge))!)).toEqual([]);
    refresh();
    expect(panel()).toBeNull();
  }
});

test('a stored widget that is no longer on the rail comes back closed, and bad storage is closed too', () => {
  localStorage.setItem(openKey('side'), JSON.stringify(['core.gone']));
  refresh();
  expect(panel()).toBeNull();
  localStorage.setItem(openKey('side'), '{not json');
  refresh();
  expect(panel()).toBeNull();
  expect(railSlideout.edge).toBeNull();
});
