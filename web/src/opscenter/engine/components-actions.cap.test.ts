/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { createLayoutStore } from './layout.svelte';
import { addBlocked } from './components-actions';
import { MAX_VIEWERS, insertAnalyticsRow, resetLayout, viewersOf } from './model';
import { META } from './meta';
import type { SlotId } from './types';

const chart = (n: number): SlotId =>
  `analytics:0000000${n}-0000-4000-8000-00000000000${n}` as SlotId;

test('a home holding more charts than the cap, and no viewer, still takes a session', () => {
  const home = createLayoutStore('home');
  const charts = Array.from({ length: MAX_VIEWERS + 1 }, (_, i) => chart(i + 1));
  const layout = insertAnalyticsRow(resetLayout(META, 'home'), charts);
  home.adopt(layout);
  const placed = home.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
  expect(placed).toEqual(expect.arrayContaining(charts));
  expect(viewersOf(home.state.layout)).toEqual([]);

  expect(addBlocked(home, 'terminal', 'ses_drag')).toBe('');
  expect(home.add('terminal', 'ses_drag')).toBeNull();
});

test('the cap still refuses the seventh real viewer', () => {
  const home = createLayoutStore('home');
  for (let i = 0; i < MAX_VIEWERS; i += 1) expect(home.add('terminal', `ses_${i}`)).toBeNull();
  expect(addBlocked(home, 'terminal', 'ses_extra')).toMatch(String(MAX_VIEWERS));
  expect(home.add('terminal', 'ses_extra')).toBe('cap');
});
