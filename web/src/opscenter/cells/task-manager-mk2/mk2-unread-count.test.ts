import { beforeEach, describe, expect, test } from 'vitest';
import '../../../lib/session-rail/alert-count-sources.svelte';
import { alertCountSource } from '../../../lib/session-rail/alert-counts';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { taskOf } from '../../../cplugs/huddle/task-manager-design/adapter';
import { entriesOf } from '../../../cplugs/huddle/task-manager-design/entries';
import type { HuddleItem, TaskManagerGroup } from '../../../cplugs/huddle/huddle-model';
import { allTasksOf, headCountOf } from './mk2-head-count';
import { unreadCount } from './mk2-chips';

const mk = (id: number, status: string, unread: boolean, list = '18', extra: Record<string, unknown> = {}) =>
  ({ id, list, text: `item ${id}`, state: status === 'todo' ? 'todo' : status === 'done' ? 'approved' : 'open', status, section: status, kind: 'task', thread: [],
    deleted: false, unread, ...extra }) as unknown as HuddleItem;

const ACTIVE_UNREAD = [1131, 814, 1022, 1160, 878, 1064, 1126, 1091, 1170];
const PARKED_UNREAD = [890, 688, 1024, 528, 543, 544, 545, 546, 547, 560, 1043];
const LIVE_18: HuddleItem[] = [
  ...ACTIVE_UNREAD.map((id, at) => mk(id, ['working', 'waiting', 'waiting', 'review', 'waiting', 'waiting', 'waiting', 'question', 'working'][at]!, true)),
  ...PARKED_UNREAD.map((id) => mk(id, 'todo', true)),
  mk(185, 'todo', false), mk(1168, 'working', false), mk(1096, 'working', false), mk(1151, 'open', false), mk(403, 'scheduled', false),
  mk(9001, 'done', true),
];
const CHAT = [mk(7001, 'open', true, 'agent:5'), mk(7002, 'open', true, 'agent:5'), mk(7003, 'open', true, 'agent:5')];
const GROUPS = [
  { list: '18', name: 'Carnivore', items: LIVE_18 },
  { list: '9', name: 'Amerifund', items: [mk(1028, 'scheduled', true, '9'), mk(1127, 'waiting', true, '9')] },
  { list: 'agent:5', name: null, items: CHAT },
] as unknown as TaskManagerGroup[];
const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 18 };

beforeEach(() => {
  huddle.groups = GROUPS;
  huddle.lists = [
    { key: '18', name: 'Carnivore', project_id: 18, items: 30, open: 5, review: 1, questions: 0, claude_seq: 0, unread: 21 },
    { key: '9', name: 'Amerifund', project_id: 9, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 2 },
    { key: 'agent:5', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 3 },
  ] as never;
});

describe('one unread number for the title and the chip; the rail key counts what needs him instead (round 6 point C)', () => {
  test('list 18 reads nine: the active flagged tasks, not the parked or done ones', () => {
    const items = LIVE_18;
    const tasks = entriesOf([GROUPS[0]!]).map((entry) => taskOf(entry));
    expect(headCountOf(tasks)).toBe(ACTIVE_UNREAD.length);
    expect(unreadCount(items)).toBe(ACTIVE_UNREAD.length);
    expect(alertCountSource('core.task-manager-mk2')?.read(scope)).toBe(2);
  });

  test('every project reads ten: list 18 and Amerifund\'s waiting task, no agent chat thread, no never-opened scheduled task', () => {
    expect(headCountOf(allTasksOf(GROUPS)!)).toBe(ACTIVE_UNREAD.length + 1);
    expect(alertCountSource('core.task-manager-mk2-all')?.read(null)).toBe(2);
  });

  test('before the groups are read the key shows nothing, never a zero', () => {
    huddle.groups = null;
    expect(alertCountSource('core.task-manager-mk2')?.read(scope)).toBeNull();
    expect(alertCountSource('core.task-manager-mk2-all')?.read(null)).toBeNull();
  });
});

describe('a scheduled task counts as unread only while it holds an unread message (Joe (ccsliinc), 2026-10-23)', () => {
  const post = (id: number, author: string) => ({ id, author, kind: 'info', text: `post ${id}`, answered: false });
  const never = mk(2001, 'scheduled', true);
  const news = mk(2002, 'scheduled', true, '18', { thread: [post(1, 'joe'), post(2, 'claude')] });
  const answered = mk(2003, 'scheduled', true, '18', { thread: [post(3, 'claude'), post(4, 'joe')] });
  const tasksOf = (items: HuddleItem[]) => entriesOf([{ list: '18', name: 'Carnivore', items }] as unknown as TaskManagerGroup[]).map((entry) => taskOf(entry));

  test('a claude-made scheduled task nobody opened stays out of the title and the chip', () => {
    expect(headCountOf(tasksOf([never]))).toBe(0);
    expect(unreadCount([never])).toBe(0);
  });

  test('a scheduled task with a new agent post counts in both', () => {
    expect(headCountOf(tasksOf([news]))).toBe(1);
    expect(unreadCount([news])).toBe(1);
  });

  test('a scheduled task whose last post is the owner\'s stays out', () => {
    expect(headCountOf(tasksOf([answered]))).toBe(0);
    expect(unreadCount([answered])).toBe(0);
  });
});
