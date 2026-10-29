import { describe, expect, it } from 'vitest';
import type { BoardLane } from '../../board-data.svelte';
import type { CardColumn, CardView } from '../../board-types';
import type { CardEventRow } from '../calendar/card-events.svelte';
import { buildGroups, pct, timelineWindow, trackCard } from './timeline-model';

const NOW = new Date(2026, 9, 7, 21, 38).getTime();
const S = (h: number, m = 0) => new Date(2026, 9, 7, h, m).getTime() / 1000;
const card = (id: number, column: CardColumn, extra: Partial<CardView> = {}): CardView =>
  ({ id, column, created_at: S(9), parent: null, holder: null, title: `card ${id}`, ...extra }) as CardView;
const ev = (item_id: number, at: number, from_col: string, to_col: string): CardEventRow =>
  ({ item_id, list_key: '17', at, kind: 'moved', from_col, to_col, by: '' });
const lane = (cards: CardView[]): BoardLane => {
  const columns = { todo: [], in_progress: [], review: [], done: [] } as Record<CardColumn, CardView[]>;
  for (const c of cards) columns[c.column].push(c);
  return { list_key: '17', name: 'carnivore.ai', columns } as unknown as BoardLane;
};

describe('timeline window', () => {
  it('day is twelve hourly ticks ending at the next full hour, now inside the last hour', () => {
    const win = timelineWindow('day', NOW);
    expect(win.ticks).toHaveLength(12);
    expect(new Date(win.start).getHours()).toBe(10);
    expect(new Date(win.end).getHours()).toBe(22);
    expect(pct(NOW / 1000, win)).toBeGreaterThan(95);
    expect(pct(S(3), win)).toBe(0);
  });
  it('three days tick every six hours, a week daily, both ending at the next midnight', () => {
    expect(timelineWindow('three', NOW).ticks).toHaveLength(12);
    const week = timelineWindow('week', NOW);
    expect(week.ticks).toHaveLength(7);
    expect(new Date(week.end).getDate()).toBe(8);
  });
});

describe('a card bar', () => {
  const win = timelineWindow('day', NOW);
  it('draws wait, work, review from to_col, never the event kind', () => {
    const c = card(1, 'review', { created_at: S(16) });
    const t = trackCard(c, [ev(1, S(16, 1), 'todo', 'in_progress'), { ...ev(1, S(16, 13), 'in_progress', 'review'), kind: 'finished' }], win, NOW / 1000);
    expect(t.segments.map((s) => s.kind)).toEqual(['wait', 'work', 'review']);
    expect(t.reviewAt).toBe(S(16, 13));
    expect(t.segments[2]!.to).toBe(NOW / 1000);
  });
  it('a wait that goes straight to review was worked with no recorded start', () => {
    const t = trackCard(card(2, 'review', { created_at: S(15, 59) }), [ev(2, S(16, 24), 'todo', 'review')], win, NOW / 1000);
    expect(t.segments.map((s) => s.kind)).toEqual(['unrecorded', 'review']);
  });
  it('done ends the bar, a send back is counted, a quiet todo from before the window is not active', () => {
    const t = trackCard(card(3, 'done', { created_at: S(11) }),
      [ev(3, S(12), 'todo', 'in_progress'), ev(3, S(13), 'in_progress', 'review'), ev(3, S(14), 'review', 'in_progress'), ev(3, S(15), 'in_progress', 'done')], win, NOW / 1000);
    expect(t.segments.map((s) => s.kind)).toEqual(['wait', 'work', 'review', 'work']);
    expect(t.segments[3]!.to).toBe(S(15));
    expect(t.sentBack).toBe(1);
    expect(trackCard(card(4, 'todo'), [], win, NOW / 1000).active).toBe(false);
  });
  it('a live card from before the window spans it, and a held card in progress wears its worker', () => {
    const t = trackCard(card(5, 'in_progress', { holder: { agent_id: 9 } as CardView['holder'] }), [], win, NOW / 1000);
    expect(t.segments).toEqual([{ kind: 'work', from: win.start / 1000, to: NOW / 1000 }]);
    expect(t.worker).toBe(9);
  });
});

describe('lane rows', () => {
  const win = timelineWindow('day', NOW);
  it('puts parents above their children, carries a worked child node up to the parent and the lane, the rest loose', () => {
    const cards = [
      card(201, 'todo'),
      card(202, 'in_progress', { parent: 201, holder: { agent_id: 7 } as CardView['holder'] }),
      card(203, 'todo', { parent: 201 }),
      card(214, 'in_progress', { holder: { agent_id: 8 } as CardView['holder'] }),
      card(189, 'review'),
      card(150, 'todo'),
      card(216, 'review', { parent: 999 }),
    ];
    const [g] = buildGroups([lane(cards)], [], win, NOW / 1000);
    expect(g!.parents.map((p) => p.parent.card.id)).toEqual([201]);
    expect(g!.parents[0]!.children.map((k) => k.card.id)).toEqual([202, 203]);
    expect(g!.parents[0]!.workers).toEqual([7]);
    expect(g!.loose.map((k) => k.card.id)).toEqual([214, 216, 189]);
    expect(g!.workers.sort()).toEqual([7, 8]);
  });
  it('leaves out a lane where nothing moved', () => {
    expect(buildGroups([lane([card(1, 'todo')])], [], win, NOW / 1000)).toEqual([]);
  });
});
