import { describe, expect, test } from 'vitest';
import type { TaskManagerGroup, HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { LIST_ORDER, densityOf, groupOf, listRows, sectionsOf, statusOption, statusTicked } from './model';

function item(id: number, status: string, at: number, extra: Partial<HuddleItem> = {}): HuddleItem {
  return {
    id, list: '1', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '', revision: 1, created_seq: id, seq: id, deleted: false, status,
    thread: [{ id: 100 + id, item_id: id, author: 'claude', kind: 'reply', text: `post ${id}`, answered: false, created_at: at, seq: id }],
    ...extra,
  } as HuddleItem;
}

const group = (items: HuddleItem[]): TaskManagerGroup => ({ list: '1', name: 'p', project_id: 1, revision: 1, items });

describe('the order', () => {
  test('is questions, reviews, working, waiting, scheduled, open, newest first inside a status', () => {
    const rows = listRows([group([
      item(1, 'open', 10), item(2, 'scheduled', 10), item(3, 'waiting', 10), item(4, 'working', 10), item(5, 'review', 10), item(6, 'question', 10),
      item(7, 'working', 50), item(8, 'open', 90),
    ])]);
    expect(rows.map((row) => row.id)).toEqual([6, 5, 7, 4, 3, 2, 8, 1]);
    expect(LIST_ORDER).toEqual(['question', 'review', 'working', 'waiting', 'scheduled', 'open']);
  });

  test('a scheduled row counts to when it fires, soonest first', () => {
    const at = (fire: number) => ({ start_trigger: { kind: 'at', fire_at: fire, fired_at: null, last_error: null } });
    const rows = listRows([group([item(1, 'scheduled', 5, at(900)), item(2, 'scheduled', 5, at(300))])]);
    expect(rows.map((row) => row.id)).toEqual([2, 1]);
    expect(rows[0]!.atMs).toBe(300_000);
  });

  test('done, back burner, deleted and placeholder items are never listed', () => {
    const rows = listRows([group([item(1, 'done', 1), item(2, 'todo', 1), item(3, 'open', 1, { deleted: true }), item(4, 'open', 1, { placeholder: true }), item(5, 'open', 1)])]);
    expect(rows.map((row) => row.id)).toEqual([5]);
  });

  test('flattens every list, not one', () => {
    const second: TaskManagerGroup = { ...group([item(2, 'question', 1, { list: '2' })]), list: '2' };
    expect(listRows([group([item(1, 'open', 1)]), second]).map((row) => row.list)).toEqual(['2', '1']);
  });
});

describe('the ticks', () => {
  const groups = [group([item(1, 'question', 1), item(2, 'review', 1), item(3, 'working', 1), item(4, 'waiting', 1), item(5, 'scheduled', 1), item(6, 'open', 1)])];

  test('absent is on: a new copy lists everything', () => {
    expect(listRows(groups)).toHaveLength(6);
    expect(listRows(groups, {})).toHaveLength(6);
    expect(statusTicked(undefined, 'open')).toBe(true);
  });

  test('a status ticked off leaves its rows out and nothing else', () => {
    const rows = listRows(groups, { [statusOption('open')]: false, [statusOption('scheduled')]: false });
    expect(rows.map((row) => row.status)).toEqual(['question', 'review', 'working', 'waiting']);
  });

  test('every tick off is an empty list, not an error', () => {
    const off = Object.fromEntries(LIST_ORDER.map((status) => [statusOption(status), false]));
    expect(listRows(groups, off)).toEqual([]);
  });

  test('before the first answer there is nothing', () => {
    expect(listRows(null)).toEqual([]);
  });
});

describe('the density', () => {
  test('is compact unless the copy stored two-line', () => {
    expect(densityOf(undefined)).toBe('compact');
    expect(densityOf({ density: 'full' })).toBe('full');
    expect(densityOf({ density: 'odd' })).toBe('compact');
  });
});

describe('grouping', () => {
  const two = (): TaskManagerGroup[] => [
    group([item(1, 'open', 10), item(2, 'question', 10), item(3, 'open', 20)]),
    { list: '2', name: null, project_id: null, revision: 1, items: [item(4, 'working', 10, { list: '2' }), item(5, 'question', 10, { list: '2' })] },
  ];

  test('groupOf is status unless the copy stored project', () => {
    expect(groupOf(undefined)).toBe('status');
    expect(groupOf({ group: 'project' })).toBe('project');
    expect(groupOf({ group: 'nonsense' })).toBe('status');
  });

  test('by status the headers follow the status order and carry the rows', () => {
    const sections = sectionsOf(listRows(two()), 'status');
    expect(sections.map((s) => [s.key, s.rows.map((r) => r.id)])).toEqual([['question', [2, 5]], ['working', [4]], ['open', [3, 1]]]);
  });

  test('by project the headers carry the project name and each project keeps the status order inside it', () => {
    const sections = sectionsOf(listRows(two()), 'project');
    expect(sections.map((s) => [s.label, s.rows.map((r) => r.id)])).toEqual([['p', [2, 3, 1]], ['project 2', [5, 4]]]);
  });
});
