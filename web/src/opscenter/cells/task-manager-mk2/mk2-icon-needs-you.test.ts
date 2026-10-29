import { describe, expect, test } from 'vitest';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { entriesOf } from '../../../cplugs/huddle/task-manager-design/entries';
import { headCountsOf, needsYouOfGroups } from './mk2-head-count';

const mk = (id: number, extra: Record<string, unknown> = {}): HuddleItem => ({
  id, list: '18', text: `task ${id}`, note: '', position: id, created_by: 'claude', state: 'open', status: 'working', kind: '', number: id,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: true, ...extra,
} as unknown as HuddleItem);
const msg = (id: number, kind: string) => ({ id, author: 'claude', kind, text: 'x', created_at: id, unread: true, answered: false });

const ITEMS = [
  mk(1, { status: 'question', needs_you: true, needs_action: 'answer' }),
  mk(2, { state: 'review', status: 'review', review_action: 'tick' }),
  mk(3, { status: 'scheduled' }),
  mk(4, { state: 'todo', status: 'todo', needs_you: true }),
  mk(5, { status: 'working', thread: [msg(50, 'info')] }),
  mk(6, { status: 'working', thread: [msg(60, 'info')] }),
  mk(7, { status: 'working', thread: [msg(70, 'info')] }),
  mk(8, { state: 'done', status: 'done', needs_you: true }),
];
const GROUPS = [{ list: '18', name: 'Carnivore', items: ITEMS }, { list: '9', name: 'Billing', items: [mk(9, { list: '9', state: 'review', status: 'review' })] }] as never;

describe('the rail icon count', () => {
  test('is the strip needs-you number, for one project and for every project', () => {
    expect(needsYouOfGroups(GROUPS, '18')).toBe(headCountsOf(entriesOf(GROUPS, '18')).needsYou);
    expect(needsYouOfGroups(GROUPS, null)).toBe(headCountsOf(entriesOf(GROUPS)).needsYou);
  });

  test('working tasks whose only news is an unread info do not count', () => {
    const infoOnly = [{ list: '18', name: 'Carnivore', items: ITEMS.slice(4, 7) }] as never;
    expect(needsYouOfGroups(infoOnly, null)).toBe(0);
  });

  test('an unknown project is zero; nothing read yet is null, never zero', () => {
    expect(needsYouOfGroups(GROUPS, '99')).toBeNull();
    expect(needsYouOfGroups(null, null)).toBeNull();
  });
});
