/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: null, revision: 3, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0 }] };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 9, cursor: 9, groups: [], items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

beforeEach(() => {
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = [
    mk(1),
    mk(2, { github_issue: 'https://github.com/Example-owner/CarnivoreAIDev/issues/1571' }),
    mk(3, { github_issue: 'javascript:alert(1)' }),
  ];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

describe('the github issue link', () => {
  test('shows only for an item with an issue, as #N opening a new tab with rel noopener', async () => {
    const host = await mountBody();
    const open = async (id: number) => {
      host.querySelector<HTMLElement>(`[data-task-manager-toggle="${id}"]`)!.click();
      await settle();
    };
    await open(2);
    const link = host.querySelector<HTMLAnchorElement>('[data-task-manager-github-issue="2"] a')!;
    expect(link.textContent).toBe('#1571');
    expect(link.getAttribute('href')).toBe('https://github.com/Example-owner/CarnivoreAIDev/issues/1571');
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
    await open(1);
    expect(host.querySelector('[data-task-manager-github-issue="1"]')).toBeNull();
    await open(3);
    expect(host.querySelector('[data-task-manager-github-issue="3"]')).toBeNull();
  });
});
