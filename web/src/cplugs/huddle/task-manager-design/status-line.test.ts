import { describe, expect, test } from 'vitest';
import { taskOf } from './adapter';
import { statusLineText } from './status-line';
import type { HuddleItem } from '../huddle-model';

const LINE = { id: 21, item_id: 1, author: 'claude', kind: 'info', category: 'status', text: 'status changed from open to review by an agent (done)', created_at: 1002, seq: 21, seen: true };
const REPLY = { id: 22, item_id: 1, author: 'claude', kind: 'reply', text: 'finished', created_at: 1003, seq: 22 };
const item = { id: 1, list: '1', text: 'x', state: 'review', status: 'review', kind: 'task', deleted: false, unread: true, thread: [LINE, REPLY] } as unknown as HuddleItem;

describe('the status line', () => {
  test('keeps the move and leaves out who and why', () => {
    expect(statusLineText(LINE.text)).toBe('moved from open to review');
    expect(statusLineText('status changed from review to open by the owner (replied)')).toBe('moved from review to open');
    expect(statusLineText('something else')).toBe('something else');
  });
  test('is a system message, read, and never one of the new messages', () => {
    const task = taskOf({ item, project: 'p', list: '1' });
    const line = task.messages.find((m) => m.id === '21')!;
    expect(line).toMatchObject({ system: true, read: true, text: 'moved from open to review' });
    expect(task.messages.find((m) => m.id === '22')).toMatchObject({ system: false, read: false });
  });
});
