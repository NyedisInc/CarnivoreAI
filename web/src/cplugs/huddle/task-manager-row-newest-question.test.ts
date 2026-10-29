import { describe, expect, test } from 'vitest';
import { rowQuestionPick } from './task-manager-posts';

const q = (id: number) => ({ id, kind: 'question' as const });

describe('rowQuestionPick', () => {
  test('picks the newest open question and counts the older ones', () => {
    expect(rowQuestionPick([q(3), { id: 4, kind: 'info' as const }, q(9), q(5)])).toEqual({ shown: 5, hidden: 2 });
  });
  test('a lone question hides nothing', () => {
    expect(rowQuestionPick([q(7)])).toEqual({ shown: 7, hidden: 0 });
  });
  test('no question picks nothing', () => {
    expect(rowQuestionPick([{ id: 1, kind: 'info' }])).toEqual({ shown: null, hidden: 0 });
  });
});
