import { describe, expect, test } from 'vitest';
import { taskOf } from '../../../cplugs/huddle/task-manager-design/adapter';
import { entriesOf } from '../../../cplugs/huddle/task-manager-design/entries';
import type { HuddleItem, TaskManagerGroup, TaskManagerListBody } from '../../../cplugs/huddle/huddle-model';
import { allTasksOf, headCountOf, headCountText, headCountsOf, listTasksOf } from './mk2-head-count';
import { MK2_CHIP_TEST, chipCount } from './mk2-chips';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) =>
  ({ id, list, text: `item ${id}`, state: 'open', status: 'open', kind: 'task', thread: [], deleted: false, ...extra }) as unknown as HuddleItem;

const SEVEN = [
  mk(1, '7', { unread: true }),
  mk(2, '7', { info_unread: 2 }),
  mk(3, '7', { unread: true, status: 'done', state: 'approved', section: 'done' }),
  mk(4, '7'),
  mk(5, '7', { state: 'todo', status: 'todo' }),
];
const NINE = [mk(6, '9', { unread: true })];
const GROUPS = [{ list: '7', name: 'Carnivore', items: SEVEN }, { list: '9', name: 'Billing', items: NINE }] as unknown as TaskManagerGroup[];

describe('the title count is one labeled number over active tasks', () => {
  const body = { list: '7', revision: 1, cursor: 0, items: SEVEN } as TaskManagerListBody;
  const tasksOfAll = () => allTasksOf(GROUPS)!;

  test('closed tasks never count: project 7 has 1 unread active task (the closed unread one is left out)', () => {
    expect(headCountOf(listTasksOf(body, '7')!)).toBe(1);
  });

  test('every project: the number is the active unread tasks of every list', () => {
    expect(headCountOf(tasksOfAll())).toBe(2);
    expect(entriesOf(GROUPS).map((entry) => taskOf(entry)).length).toBe(6);
  });

  test('the words are the one number and its label, and nothing else (no second number)', () => {
    expect(headCountText(2)).toBe('2 unread');
    expect(headCountText(0)).toBe('');
  });

  test('the title, the unread chip and the rail badge are one number', () => {
    const all = [...SEVEN, ...NINE];
    expect(chipCount('unread', SEVEN)).toBe(headCountOf(listTasksOf(body, '7')!));
    expect(chipCount('unread', all)).toBe(headCountOf(tasksOfAll()));
    expect(all.filter(MK2_CHIP_TEST.unread).map((item) => item.id)).toEqual([1, 6]);
  });

  test('the unread chip shows the title strip\'s message number, while its filter still lists tasks', () => {
    const post = (id: number) => ({ id, author: 'claude', kind: 'info', text: `post ${id}`, answered: false });
    const threaded = [mk(11, '7', { unread: true, thread: [post(1), post(2), post(3)] }), mk(12, '7', { unread: true, thread: [post(4)] }), mk(13, '7')];
    const entries = entriesOf([{ list: '7', name: 'Carnivore', items: threaded }] as unknown as TaskManagerGroup[]);
    expect(headCountsOf(entries).unread).toBe(4);
    expect(chipCount('unread', threaded)).toBe(4);
    expect(threaded.filter(MK2_CHIP_TEST.unread).map((item) => item.id)).toEqual([11, 12]);
  });

  test('nothing read yet is null, never zero', () => {
    expect(allTasksOf(null)).toBeNull();
    expect(listTasksOf(null, '7')).toBeNull();
    expect(listTasksOf({ list: '9', revision: 1, cursor: 0, items: NINE } as TaskManagerListBody, '7')).toBeNull();
  });
});
