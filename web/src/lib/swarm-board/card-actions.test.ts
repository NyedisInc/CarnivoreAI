import { describe, expect, it } from 'vitest';
import type { CardView } from './board-types';
import { beforeIdAt, dropIsNoop, isWaiting, stageActions } from './card-actions.svelte';

const card = (id: number, column: CardView['column'], extra: Partial<CardView> = {}): CardView =>
  ({ id, column, list_key: '17', queued: false, lane_role: null, archived_at: null, ...extra }) as CardView;

describe('card actions', () => {
  it('lets only a todo card or a queued in progress card move in the queue', () => {
    expect(isWaiting(card(1, 'todo'))).toBe(true);
    expect(isWaiting(card(2, 'in_progress', { queued: true }))).toBe(true);
    expect(isWaiting(card(3, 'in_progress'))).toBe(false);
    expect(isWaiting(card(4, 'review'))).toBe(false);
    expect(isWaiting(card(5, 'todo', { lane_role: 'parent_here' }))).toBe(false);
  });

  it('offers each stage its own keys', () => {
    expect(stageActions(card(1, 'todo'))).toEqual(['top', 'bottom', 'promote', 'reclassify', 'archive', 'collapse', 'delete']);
    expect(stageActions(card(2, 'in_progress', { queued: true }))).toEqual(['top', 'bottom', 'pause', 'reclassify', 'archive', 'collapse', 'delete']);
    expect(stageActions(card(3, 'in_progress'))).toEqual(['pause', 'reclassify', 'archive', 'collapse', 'delete']);
    expect(stageActions(card(4, 'review'))).toEqual(['done', 'reclassify', 'archive', 'collapse', 'delete']);
    expect(stageActions(card(5, 'done'))).toEqual(['reclassify', 'archive', 'collapse', 'delete']);
    expect(stageActions(card(6, 'todo', { archived_at: 1 }))).toEqual(['archive', 'delete']);
    expect(stageActions(card(7, 'todo', { lane_role: 'parent_here' }))).toEqual(['collapse']);
  });

  it('drops above the next waiting card of the same queue, skipping held cards and other queues', () => {
    const held = card(10, 'in_progress');
    const other = card(11, 'in_progress', { queued: true, list_key: '18' });
    const a = card(12, 'in_progress', { queued: true });
    const b = card(13, 'in_progress', { queued: true });
    const col = [held, other, a, b];
    expect(beforeIdAt(col, b.id, 0, '17')).toBe(a.id);
    expect(beforeIdAt(col, a.id, 3, '17')).toBe(b.id);
    expect(beforeIdAt(col, a.id, 4, '17')).toBe(null);
    expect(dropIsNoop(col, a.id, b.id)).toBe(true);
    expect(dropIsNoop(col, b.id, null)).toBe(true);
    expect(dropIsNoop(col, b.id, a.id)).toBe(false);
  });
});
