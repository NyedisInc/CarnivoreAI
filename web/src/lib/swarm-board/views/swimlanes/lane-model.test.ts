import { describe, expect, it } from 'vitest';
import type { BoardLane } from '../../board-data.svelte';
import type { CardView } from '../../board-types';
import { cellCards, isFolded, orderLanes, rollup } from './lane-model';

const counts = (todo: number, in_progress: number, review: number, done: number) => ({ todo, in_progress, review, done });
const lane = (key: string, c: ReturnType<typeof counts>): BoardLane =>
  ({ list_key: key, project_id: null, name: key, rules: null, counts: c, columns: { todo: [], in_progress: [], review: [], done: [] },
     companyId: null, companyName: null, owner: null }) as unknown as BoardLane;
const card = (id: number) => ({ id }) as CardView;

describe('swimlanes lane model', () => {
  it('folds a lane with nothing in progress or in review, unless the owner chose', () => {
    expect(isFolded(lane('a', counts(3, 0, 0, 2)), {})).toBe(true);
    expect(isFolded(lane('b', counts(0, 1, 0, 0)), {})).toBe(false);
    expect(isFolded(lane('c', counts(0, 0, 2, 0)), {})).toBe(false);
    expect(isFolded(lane('a', counts(3, 0, 0, 2)), { a: false })).toBe(false);
    expect(isFolded(lane('b', counts(0, 1, 0, 0)), { b: true })).toBe(true);
    expect(isFolded(lane('a', counts(3, 0, 0, 2)), {}, true)).toBe(false);
    expect(isFolded(lane('a', counts(3, 0, 0, 2)), { a: true }, true)).toBe(true);
  });

  it('drops empty lanes and puts active lanes before quiet ones, keeping server order inside each', () => {
    const order = orderLanes([lane('quiet1', counts(2, 0, 0, 0)), lane('empty', counts(0, 0, 0, 0)),
      lane('busy1', counts(0, 2, 0, 0)), lane('quiet2', counts(0, 0, 0, 1)), lane('busy2', counts(0, 0, 1, 0))]);
    expect(order.map((l) => l.list_key)).toEqual(['busy1', 'busy2', 'quiet1', 'quiet2']);
  });

  it('shows five cards per cell and counts the rest, from the server count', () => {
    const six = [1, 2, 3, 4, 5, 6].map(card);
    expect(cellCards(six, 9, false)).toEqual({ shown: six.slice(0, 5), more: 4 });
    expect(cellCards(six.slice(0, 5), 5, false)).toEqual({ shown: six.slice(0, 5), more: 0 });
    expect(cellCards([card(1)], 1, false)).toEqual({ shown: [card(1)], more: 0 });
    expect(cellCards([card(1), card(2), card(3)], 3, true)).toEqual({ shown: [card(1), card(2), card(3)], more: 0 });
  });

  it('rolls the four counts up in board order', () => {
    expect(rollup(counts(1, 2, 3, 4)).map((s) => [s.column, s.count])).toEqual([['todo', 1], ['in_progress', 2], ['review', 3], ['done', 4]]);
  });
});
