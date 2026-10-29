import { describe, expect, test } from 'vitest';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { askFold, oneLineFold, ONE_LINE_CHARS, postFold } from '../../../cplugs/huddle/task-manager-posts';
import { taskOf } from '../../../cplugs/huddle/task-manager-design/adapter';
import { newCount, unread } from '../../../cplugs/huddle/task-manager-design/model';
import { actionableIdOf } from './mk2-task-tabs';

const msg = (id: number, kind: string, extra: Record<string, unknown> = {}) => ({ id, item_id: 1, author: 'claude', kind, text: `message ${id}`, created_at: id, unread: true, answered: false, ...extra });
const mk = (extra: Record<string, unknown> = {}): HuddleItem => ({
  id: 1, list: '7', text: 'task', note: '', position: 1, created_by: 'claude', state: 'open', status: 'working', kind: '', number: 1,
  revision: 1, created_seq: 1, seq: 1, deleted: false, thread: [], unread: true, ...extra,
} as unknown as HuddleItem);
const REVIEW = { state: 'review', status: 'review', review_description: 'look at it', review_where: 'here', review_action: 'tick' };

describe('G: what the action tab holds', () => {
  test('an info that is the only news shows', () => {
    expect(actionableIdOf(mk({ thread: [msg(5, 'info')] }))).toBe(5);
  });
  test('an open question shows, and the info beside it stays in the discussion tab', () => {
    expect(actionableIdOf(mk({ thread: [msg(4, 'question'), msg(6, 'info')] }))).toBe(4);
  });
  test('a review waiting on him shows its block and no info beside it', () => {
    expect(actionableIdOf(mk({ ...REVIEW, thread: [msg(6, 'info')] }))).toBeNull();
  });
  test('nothing waiting is nothing', () => {
    expect(actionableIdOf(mk())).toBeNull();
  });
});

describe('L: a post folds to one line', () => {
  test('a long or multi-line post is its first line, cut at the one-line limit', () => {
    const long = 'x'.repeat(ONE_LINE_CHARS + 20);
    expect(oneLineFold(long)).toMatchObject({ foldable: true, folded: long, limit: ONE_LINE_CHARS, more: true });
    expect(oneLineFold('title\nmore words')).toMatchObject({ foldable: true, folded: 'title' });
    expect(oneLineFold('short')).toMatchObject({ foldable: false, folded: 'short' });
  });
  test('postFold and askFold take the one-line mode and the original three lines stay the default', () => {
    expect(postFold('a\nb', true).folded).toBe('a');
    expect(postFold('a\nb').foldable).toBe(false);
    expect(askFold({ text: 'a\nb\nc', context: '', questions: [], form: undefined } as never, true)).toMatchObject({ foldable: true, text: 'a' });
  });
});

describe('E: a status line is never unread', () => {
  test('a status message counts as read, so the task has no new message from it', () => {
    const item = mk({ unread: false, thread: [msg(9, 'info', { category: 'status', text: 'status changed from open to review by the owner', author: 'system' })] });
    const task = taskOf({ item, project: 'p', list: '7' });
    expect(task.messages[0]).toMatchObject({ system: true, read: true, text: 'moved from open to review' });
    expect(newCount(task)).toBe(0);
    expect(unread(task)).toBe(false);
  });
});
