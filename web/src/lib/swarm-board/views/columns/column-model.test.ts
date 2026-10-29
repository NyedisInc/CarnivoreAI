import { describe, expect, it } from 'vitest';
import type { CardColumn, CardView } from '../../board-types';
import { dropBefore, stack } from './column-model';

const card = (id: number, column: CardColumn, extra: Partial<CardView> = {}) =>
  ({ id, column, list_key: 'p1', queued: false, lane_role: null, ...extra }) as CardView;
const lane = (cards: CardView[], counts?: Partial<Record<CardColumn, number>>) => {
  const columns = { todo: [] as CardView[], in_progress: [] as CardView[], review: [] as CardView[], done: [] as CardView[] };
  for (const c of cards) columns[c.column].push(c);
  return { columns, counts: { todo: columns.todo.length, in_progress: columns.in_progress.length, review: columns.review.length, done: columns.done.length, ...counts } };
};

describe('columns-by-project model', () => {
  it('stacks review, in progress, todo, done and leaves out empty states', () => {
    const groups = stack(lane([card(1, 'todo'), card(2, 'done'), card(3, 'review'), card(4, 'in_progress')]), {});
    expect(groups.map((g) => [g.column, g.shown.map((c) => c.id)])).toEqual([['review', [3]], ['in_progress', [4]], ['todo', [1]], ['done', [2]]]);
    expect(stack(lane([card(1, 'todo')]), {}).map((g) => g.column)).toEqual(['todo']);
  });

  it('cuts each state at five with a "+N more" from the server count, and shows all once opened', () => {
    const todos = [1, 2, 3, 4, 5, 6, 7].map((id) => card(id, 'todo'));
    expect(stack(lane(todos), {})[0]).toMatchObject({ column: 'todo', more: 2 });
    expect(stack(lane(todos), {})[0]?.shown).toHaveLength(5);
    expect(stack(lane(todos), { todo: true })[0]).toMatchObject({ more: 0 });
    expect(stack(lane([card(9, 'done')], { done: 40 }), {})[0]).toMatchObject({ column: 'done', more: 39 });
  });

  it('places a drop inside the dragged card state run only', () => {
    const r1 = card(1, 'review');
    const t1 = card(2, 'todo');
    const t2 = card(3, 'todo');
    const drawn = [r1, t1, t2];
    expect(dropBefore(drawn, [t1, t2], t2, 1)).toBe(t1.id);
    expect(dropBefore(drawn, [t1, t2], t2, 0)).toBe(t1.id);
    expect(dropBefore(drawn, [t1, t2], t1, 3)).toBeNull();
    const q = card(4, 'in_progress', { queued: true });
    expect(dropBefore([q, t1, t2], [t1, t2], t2, 0)).toBe(t1.id);
    const t3 = card(5, 'todo');
    expect(dropBefore([t1, t2], [t1, t2, t3], t1, 2)).toBe(t3.id);
  });
});
