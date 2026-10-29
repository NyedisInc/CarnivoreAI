import { beforeEach, describe, expect, test } from 'vitest';
import './alert-count-sources.svelte';
import { alertCountSource } from './alert-counts';
import { huddle } from '../../cplugs/huddle/huddle.svelte';
import { entriesOf } from '../../cplugs/huddle/task-manager-design/entries';
import { headCountsOf } from '../../opscenter/cells/task-manager-mk2/mk2-head-count';

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
  test('the single cell publishes the strip needs-you number of the session project list, not the unread scheduled run', () => {
    expect(alertCountSource('core.task-manager-mk2')?.read(scope)).toBe(headCountsOf(entriesOf(huddle.groups, '7')).needsYou);
    expect(alertCountSource('core.task-manager-mk2')?.read(scope)).toBe(3);
  });
  test('the all-projects cell publishes the strip needs-you number of every list, not the unread count (5 of the 6 are unread)', () => {
    expect(alertCountSource('core.task-manager-mk2-all')?.read(null)).toBe(headCountsOf(entriesOf(huddle.groups)).needsYou);
  });
  test('no project is no count, never zero', () => {
    expect(alertCountSource('core.task-manager-mk2')?.read({ ...scope, projectId: null } as never)).toBeNull();
  });
});
