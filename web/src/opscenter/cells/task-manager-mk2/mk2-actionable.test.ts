import { describe, expect, test } from 'vitest';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { actionableOfGroups, isActionableItem } from './mk2-actionable';
import { unreadOfGroups } from './mk2-unread';

const mk = (id: number, extra: Record<string, unknown> = {}): HuddleItem => ({
  id, list: '18', text: `task ${id}`, note: '', position: id, created_by: 'claude', state: 'open', status: 'working', kind: '', number: id,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: true, ...extra,
} as unknown as HuddleItem);
const msg = (id: number, kind: string, extra: Record<string, unknown> = {}) => ({ id, author: 'claude', kind, text: 'x', created_at: id, unread: true, answered: false, ...extra });

const ITEMS = [
  mk(1, { status: 'question', needs_you: true, needs_action: 'answer' }),
  mk(2, { state: 'review', status: 'review', review_action: 'tick' }),
  mk(3, { status: 'scheduled' }),
  mk(4, { status: 'waiting' }),
  mk(5, { state: 'todo', status: 'todo', needs_you: true }),
  mk(6, { status: 'working', needs_action: 'read' }),
  mk(7, { status: 'working', thread: [msg(70, 'info')] }),
  mk(8, { status: 'working', thread: [msg(80, 'question')] }),
  mk(9, { state: 'done', status: 'done', needs_you: true }),
  mk(10, { status: 'working', unread: false }),
];
const GROUPS = [{ list: '18', name: 'Carnivore', items: ITEMS }] as never;

describe('actionable count', () => {
  test('needs_you, needs_action, a review, an unread info and an open question count; a scheduled run, a waiting task, a parked or closed task and a quiet one do not', () => {
    expect(ITEMS.map((item) => isActionableItem(item))).toEqual([true, true, false, false, false, true, true, true, false, false]);
  });

  test('the number is the actionable tasks, and it is NOT the unread number', () => {
    expect(actionableOfGroups(GROUPS, null)).toBe(5);
    expect(unreadOfGroups(GROUPS, null)).toBe(6);
  });

  test('one project or every project; nothing read yet is null, never zero', () => {
    expect(actionableOfGroups(GROUPS, '18')).toBe(5);
    expect(actionableOfGroups(GROUPS, '99')).toBe(0);
    expect(actionableOfGroups(null, null)).toBeNull();
  });
});
