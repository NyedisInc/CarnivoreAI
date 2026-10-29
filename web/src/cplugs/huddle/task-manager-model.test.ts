import { describe, expect, test } from 'vitest';
import {
  completedCount, messageTime, dropIndex, fullMove, moveId, wholeEntry, surfaceFor, visibleItems,
  type HuddleItem, type TaskManagerListRow,
} from './huddle-model';

function listRow(over: Partial<TaskManagerListRow> = {}): TaskManagerListRow {
  return { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, ...over };
}

function item(id: number, state: HuddleItem['state'] = 'open'): HuddleItem {
  return { id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state, kind: '', revision: 1,
    created_seq: id, seq: id, deleted: false, thread: [] };
}

describe('the pure model', () => {
  test('a move and a drop land where the pointer says', () => {
    expect(moveId([1, 2, 3], 2, 0)).toEqual([3, 1, 2]);
    expect(moveId([1, 2, 3], 0, 9)).toEqual([2, 3, 1]);
    expect(dropIndex([10, 30, 50], 45, 0)).toBe(1);
    expect(dropIndex([10, 30, 50], 5, 2)).toBe(0);
  });

  test('only a claude post past what this device saw surfaces', () => {
    expect(surfaceFor([listRow({ claude_seq: 4 })], 4).surface).toBe(false);
    expect(surfaceFor([listRow({ claude_seq: 4 }), listRow({ key: '12', claude_seq: 9 })], 4)).toEqual({ surface: true, newest: 9, list: '12' });
  });

  test('completed is checked: hidden only while hide completed is on, and counted', () => {
    const items = [item(1), item(2, 'done'), item(3, 'review'), item(4, 'done')];
    expect(visibleItems(items, false).map((i) => i.id)).toEqual([1, 2, 3, 4]);
    expect(visibleItems(items, true).map((i) => i.id)).toEqual([1, 3]);
    expect(completedCount(items)).toBe(2);
  });

  test('a move among visible rows keeps hidden rows where they were', () => {
    expect(fullMove([1, 2, 3, 4], [1, 3, 4], 0, 1)).toEqual([0, 2]);
    expect(moveId([1, 2, 3, 4], 0, 2)).toEqual([2, 3, 1, 4]);
    expect(fullMove([1, 2, 3, 4], [1, 3, 4], 2, 0)).toEqual([3, 0]);
    expect(fullMove([1, 2, 3, 4], [1, 3, 4], 0, 2)).toEqual([0, 3]);
  });

  test('the add box keeps a multi-line paste whole as one entry, trimmed at the ends only (R55)', () => {
    expect(wholeEntry('  a\n\n  b  \r\nc \n')).toBe('a\n\n  b  \nc');
    expect(wholeEntry('  \n ')).toBe('');
  });

  test('a message time is the clock today and month-day plus the clock on another day', () => {
    const at = new Date(2026, 9, 3, 14, 5).getTime() / 1000;
    expect(messageTime(at, at + 60)).toBe('14:05');
    expect(messageTime(at, at + 86_400)).toBe('10-03 14:05');
  });
});
