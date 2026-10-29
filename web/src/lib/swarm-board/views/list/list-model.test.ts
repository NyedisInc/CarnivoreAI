import { describe, expect, it } from 'vitest';
import type { BoardLane } from '../../board-data.svelte';
import type { CardColumn, CardView } from '../../board-types';
import { historyLines, listBands, phases, whoOf, type CardEvent } from './list-model';

const card = (id: number, column: CardColumn, extra: Partial<CardView> = {}) =>
  ({ id, column, parent: null, lane_role: null, created_at: 100, holder: null, ...extra }) as CardView;
const lane = (name: string, cards: CardView[]): BoardLane => {
  const columns = { todo: [], in_progress: [], review: [], done: [] } as Record<CardColumn, CardView[]>;
  for (const c of cards) columns[c.column].push(c);
  return { list_key: name, name, project_id: null, columns, companyName: 'acme' } as unknown as BoardLane;
};
const ev = (kind: string, at: number, to_col = '', by = 'server', from_col = ''): CardEvent => ({ kind, at, to_col, from_col, by, detail: '' });

describe('list view bands', () => {
  it('lists review first, then in progress, then todo, leaving done out', () => {
    const bands = listBands([lane('a', [card(1, 'todo'), card(2, 'done'), card(3, 'in_progress'), card(4, 'review')])]);
    expect(bands.map((b) => [b.band, b.rows.map((r) => r.card.id)])).toEqual([['review', [4]], ['in_progress', [3]], ['todo', [1]]]);
  });

  it('keeps a tree whole under its parent, children review first, one level deeper each', () => {
    const bands = listBands([lane('a', [card(10, 'review'), card(11, 'todo', { parent: 10 }), card(12, 'review', { parent: 10 }),
      card(13, 'in_progress', { parent: 12 })])]);
    expect(bands).toHaveLength(1);
    expect(bands[0]!.rows.map((r) => [r.card.id, r.depth])).toEqual([[10, 0], [12, 1], [13, 2], [11, 1]]);
  });

  it('makes a card whose parent is not listed a root of its own column, and lists a card once across lanes', () => {
    const copy = card(20, 'in_progress', { lane_role: 'parent_of_children_here' });
    const bands = listBands([lane('a', [copy, card(21, 'review', { parent: 20 }), card(22, 'todo', { parent: 99 })]),
      lane('b', [card(20, 'in_progress')])]);
    const rows = bands.flatMap((b) => b.rows);
    expect(rows.map((r) => r.card.id)).toEqual([20, 21, 22]);
    expect(rows[0]!.card.lane_role).toBeNull();
    expect(rows[0]!.laneName).toBe('b');
  });
});

describe('list view detail', () => {
  it('reads each reached phase from the last event that landed there, and leaves later ones not yet', () => {
    const events = [ev('created', 100, 'todo'), ev('started', 200, '', 'agent:4'), ev('moved', 300, 'review', 'claude', 'in_progress'),
      ev('sent_back', 400, 'in_progress', 'owner'), ev('finished', 500, 'review', 'agent:4')];
    const strip = phases(card(1, 'review'), events);
    expect(strip.map((p) => [p.phase, p.reached, p.at])).toEqual([['created', true, 100], ['started', true, 400], ['review', true, 500], ['done', false, null]]);
  });

  it('falls back to the holder start, and says nothing it has no record of', () => {
    const strip = phases(card(1, 'in_progress', { holder: { agent_id: 4, name: null, since: 1, started_at: 150, beat_at: null } }), []);
    expect(strip.map((p) => p.at)).toEqual([100, 150, null, null]);
    expect(phases(card(1, 'done'), [])[2]).toEqual({ phase: 'review', column: 'review', reached: true, at: null });
  });

  it('draws history newest first, without heartbeats or a reorder inside a column', () => {
    const lines = historyLines([ev('created', 1, 'todo', 'owner'), ev('moved', 2, 'todo', 'owner', 'todo'), ev('started', 3, '', 'agent:4'),
      ev('handoff', 4, '', 'agent:4'), ev('finished', 5, 'review', 'agent:4'), ev('done', 6, 'done', 'owner', 'review')]);
    expect(lines.map((l) => [l.key.split('.').pop(), l.column, l.at])).toEqual([['done', 'done', 6], ['finished', 'review', 5], ['started', 'in_progress', 3], ['created', 'todo', 1]]);
    expect(lines[0]!.who).toEqual({ kind: 'you' });
    expect(historyLines([ev('moved', 7, 'review', 'claude', 'in_progress')])[0]!.key).toBe('swarm.board.list.event.moved');
  });

  it('names an event writer', () => {
    expect(whoOf('agent:12')).toEqual({ kind: 'agent', id: 12 });
    expect(whoOf('owner')).toEqual({ kind: 'you' });
    expect(whoOf('auto_done')).toEqual({ kind: 'system', name: 'auto done' });
  });
});
