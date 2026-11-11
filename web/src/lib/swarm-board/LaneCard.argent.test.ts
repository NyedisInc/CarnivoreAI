/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { cardCostView, heldRowIds, type ArgentCostSnapshot } from '../argent-cost/cost-view';
import { colorBook } from '../../cplugs/huddle/swarm/agent-colors.svelte';
import type { CardView } from './board-types';

setLocale('en');

const SNAP: ArgentCostSnapshot = {
  enabled: true, state: 'ok',
  sessions: {
    '7': { items: ['wi_a'], cost: { cost_micros: 1_234_500 } },
    '8': { items: ['wi_a'], cost: { cost_micros: 2_000_000 } },
    '9': { items: ['wi_b'], cost: { cost_micros: 99_000_000 } },
    '10': { items: [], cost: { cost_micros: 5_000_000 } },
  },
  items: {
    wi_a: { name: 'login story', held: true, cost: { cost_micros: 3_234_500 }, budget: { state: 'paused', spent_micros: 10_000_000, cap_micros: 10_000_000 } },
    wi_b: { name: 'other', held: false, cost: null, budget: { state: 'ok', spent_micros: 1_000_000, cap_micros: 10_000_000 } },
  },
};

const live = vi.hoisted(() => ({ snap: null as unknown }));
vi.mock('../argent-cost/cost-store.svelte', () => ({ argentCost: () => ({ get data() { return live.snap; } }) }));

import LaneCard from './views/swimlanes/LaneCard.svelte';
import CardDetail from './views/list/CardDetail.svelte';

const AGENTS = [
  { id: 1, display_name: 'Alpha', rank: 'task', state: 'awake', thread_key: 'agent:1', session_row_id: 7 },
  { id: 2, display_name: 'Bravo', rank: 'task', state: 'awake', thread_key: 'agent:2', session_row_id: 8 },
  { id: 3, display_name: 'Cy', rank: 'task', state: 'awake', thread_key: 'agent:3', session_row_id: 9 },
];
const data = { agents: AGENTS, agent: (id: number) => AGENTS.find((a) => a.id === id), colors: colorBook(AGENTS as never, null), now: Date.now() } as never;
const card = (holderId: number | null): CardView => ({
  id: 5, list_key: 'p', project_id: 1, title: 'a card', text: '', column: 'in_progress', state: '', position: 0, queue_index: null, group_id: null,
  holder: holderId === null ? null : { agent_id: holderId, name: null, since: 1, started_at: 1, beat_at: 1 },
  legacy_claim: null, last_holder: null, dealt_to: null, parent: null, lane_role: null, children: { total: 0, done: 0, in_review: 0 },
  origin: { kind: 'x', ref: '' }, paused: null, mark: null, accepted_at: null, report_id: null, pin: { agent_id: null, place: false }, progress: null,
  result: '', handoff: '', how_to_validate: '', validate_link: '', proof: null, validation: null, phone_sent_at: null, summary: '', queued: false,
  archived_at: null, auto_promote: false, owner_note: '', revision: 1, created_at: 1, updated_at: 1,
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

function render(component: unknown, props: Record<string, unknown>, snap: ArgentCostSnapshot | null): HTMLElement {
  live.snap = snap;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(component as never, { target, props }));
  flushSync();
  return target;
}

test('the lane card draws one cost line with the budget and a held chip, from the holder row only', () => {
  const el = render(LaneCard, { card: card(1), data }, SNAP);
  expect(el.querySelectorAll('[data-swarm-card-argent]').length).toBe(1);
  expect(el.querySelector('[data-argent-cost]')?.textContent).toBe('$1.23');
  expect(el.querySelector('[data-argent-budget]')?.getAttribute('data-scale')).toBe('5');
  expect(el.querySelector('[data-swarm-board-chip="argent_held"]')?.textContent).toContain('held');
  const other = render(LaneCard, { card: card(3), data }, SNAP);
  expect(other.querySelector('[data-argent-cost]')?.textContent).toBe('$99.00');
  expect(other.querySelector('[data-swarm-board-chip="argent_held"]')).toBeNull();
});

test('the detail pane names the item and splits the cost by agent', () => {
  const el = render(CardDetail, { card: card(1), companyName: null, laneName: 'p', data }, SNAP);
  const box = el.querySelector('[data-swarm-detail-argent]');
  expect(box?.textContent).toContain('login story');
  expect(box?.querySelector('[data-argent-split="7"]')?.textContent).toBe('Alpha: $1.23');
  expect(box?.querySelector('[data-argent-split="8"]')?.textContent).toBe('Bravo: $2.00');
  expect(box?.querySelector('[data-argent-split="9"]')).toBeNull();
  expect(box?.textContent).not.toContain('99.00');
});

test('negative controls: off, pending, no holder, a session on no item, and an unmeasured cost', () => {
  for (const snap of [{ ...SNAP, enabled: false }, { ...SNAP, state: 'pending' }, null] as (ArgentCostSnapshot | null)[]) {
    expect(render(LaneCard, { card: card(1), data }, snap).querySelector('[data-swarm-card-argent]')).toBeNull();
    expect(heldRowIds(snap).size).toBe(0);
  }
  expect(render(LaneCard, { card: card(null), data }, SNAP).querySelector('[data-swarm-card-argent]')).toBeNull();
  expect(cardCostView(SNAP, 10)).toBeNull();
  expect(cardCostView({ ...SNAP, sessions: { '7': { items: ['wi_b'], cost: null } } }, 7)?.costText).toBe('-');
});

test('the org node glyph set holds exactly the rows on a held item', () => {
  expect([...heldRowIds(SNAP)].sort()).toEqual([7, 8]);
});
