/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ items: [] as Record<string, unknown>[] }));

const mk = (id: number, extra: Record<string, unknown>) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, status: 'open', thread: [],
  unread: false, info_unseen: false, attention_unseen: false, ...extra,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 5, open: 5, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0 }] };
      if (path.endsWith('/sessions')) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { actionOf } from './huddle-review';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

beforeEach(async () => {
  server.items = [
    mk(1, { status: 'question', needs_you: true, needs_action: 'answer' }),
    mk(2, { status: 'review', state: 'review', needs_you: false, needs_action: null }),
    mk(3, { status: 'working', needs_you: true, needs_action: 'read' }),
    mk(4, { status: 'open', needs_you: false, needs_action: null }),
    mk(5, { status: 'review', state: 'review', needs_you: false, needs_action: null }),
  ];
  huddle.selected = 'all';
  huddle.addTarget = 'all';
  huddle.openId = null;
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the action tag on "needs you" rows', () => {
  test('pure: only the five known names are actions', () => {
    expect(['tick', 'push', 'answer', 'read', 'none'].map(actionOf)).toEqual(['tick', 'push', 'answer', 'read', 'none']);
    expect(actionOf('go')).toBeNull();
    expect(actionOf(null)).toBeNull();
  });

  test('each needs-you row shows its action in words, a plain row shows none', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    const word = (id: number) => host.querySelector(`[data-task-manager-toggle="${id}"] [data-task-manager-action]`)?.textContent ?? null;
    expect(word(1)).toBe('answer');
    expect(word(2)).toBeNull();
    expect(word(3)).toBe('read only');
    expect(word(4)).toBeNull();
    expect(word(5)).toBeNull();
    expect(host.querySelector('[data-task-manager-toggle="1"] [data-task-manager-action]')!.getAttribute('data-task-manager-action')).toBe('answer');
  });
});
