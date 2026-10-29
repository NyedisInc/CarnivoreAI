import { beforeEach, describe, expect, test } from 'vitest';
import './alert-count-sources.svelte';
import { alertCountSource } from './alert-counts';
import { huddle } from '../../cplugs/huddle/huddle.svelte';

const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };

beforeEach(() => {
  const mk = (id: number, list: string, extra: Record<string, unknown>) => ({ id, list, text: 'x', state: 'open', status: 'working', thread: [], deleted: false, unread: false, ...extra });
  huddle.groups = [
    { list: '7', name: 'Carnivore', items: [
      mk(1, '7', { unread: true, needs_you: true, needs_action: 'answer', status: 'question' }),
      mk(2, '7', { unread: true, state: 'review', status: 'review' }),
      mk(3, '7', { unread: true, status: 'scheduled' }),
      mk(4, '7', { unread: true, state: 'todo', status: 'todo', needs_you: true }),
    ] },
    { list: '9', name: 'Billing', items: [mk(5, '9', { unread: true, status: 'waiting' }), mk(6, '9', { unread: true, needs_action: 'read', status: 'scheduled' })] },
  ] as never;
});

describe('TM Mark II rail badge', () => {
  test('the single cell publishes the actionable count of the session project list: a question that needs him and a review, not the unread scheduled run and not the parked task', () => {
    expect(alertCountSource('core.task-manager-mk2')?.read(scope)).toBe(2);
  });
  test('the all-projects cell publishes the actionable count of every list, not the unread count (5 of the 6 are unread)', () => {
    expect(alertCountSource('core.task-manager-mk2-all')?.read(null)).toBe(3);
  });
  test('no project is no count, never zero', () => {
    expect(alertCountSource('core.task-manager-mk2')?.read({ ...scope, projectId: null } as never)).toBeNull();
  });
});
