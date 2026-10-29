/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  unread: new Set<number>(),
  focus: null as null | { seq: number; list: string; items: number[]; open: number | null },
  calls: [] as { path: string; method: string }[],
}));

const mk = (id: number) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: server.unread.has(id),
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method });
      const seen = /^\/cplugs\/huddle\/items\/(\d+)\/seen$/.exec(path);
      if (seen) {
        server.unread.delete(Number(seen[1]));
        return mk(Number(seen[1]));
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: structuredClone(server.focus) };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: server.unread.size },
          { key: '12', name: 'carnivore', project_id: 12, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 1 },
        ] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: [mk(1), mk(2), mk(3)] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { applyFocus, taskManagerFocus } from './task-manager-focus.svelte';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
import { taskManagerTab } from './task-manager-tab';
import { AGGREGATE, needsYouTotal, unreadTotal } from './huddle-model';
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

async function mountBody(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

function dots(host: HTMLElement): string[] {
  return [...host.querySelectorAll<HTMLElement>('.hdr[data-task-manager-signal="unread"], .hdr[data-task-manager-signal="attention"]')].map((d) => d.dataset.huddleItem ?? '');
}

const seenCalls = (): string[] => server.calls.filter((c) => c.path.endsWith('/seen')).map((c) => c.path);

beforeEach(async () => {
  server.unread = new Set([2, 3]);
  server.focus = null;
  server.calls = [];
  huddle.selected = 'all';
  huddle.openId = null;
  taskManagerFocus.focus = null;
  taskManagerFocus.applied = 0;
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('unread dots', () => {
  test('an unread row folds into its stripe, with no light right of the number; a read row stays plain', async () => {
    const host = await mountBody();
    expect(dots(host)).toEqual(['2', '3']);
    expect(host.querySelector('.hdr-unread, [data-huddle-unread], .status-led')).toBeNull();
    const stripe = host.querySelector<HTMLElement>('[data-huddle-item="3"] .tkm-state')!;
    expect(stripe.dataset.taskManagerSignal).toBe('unread');
    expect(stripe.getAttribute('title')).toContain('new from claude, not seen yet');
    expect(host.querySelector<HTMLElement>('[data-huddle-item="1"] .tkm-state')!.dataset.taskManagerSignal).toBeUndefined();
  });

  test('opening a row reads nothing: the dot stays and the server is told nothing', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(seenCalls()).toEqual([]);
    expect(dots(host)).toEqual(['2', '3']);
  });

  test('a row opened FOR Joe (a focus) stays unread, and pressing inside it reads nothing', async () => {
    const host = await mountBody();
    taskManagerPrefs.density = 'compact';
    await applyFocus({ seq: 9, list: 'all', items: [3], open: 3 });
    await settle();
    expect(huddle.openId).toBe(3);
    expect(dots(host)).toContain('3');
    expect(seenCalls()).toEqual([]);
    host.querySelector<HTMLElement>('[data-task-manager-detail="3"]')!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    await settle();
    expect(seenCalls()).toEqual([]);
    expect(dots(host)).toContain('3');
  });
});

describe('one badge', () => {
  test('the tab badges nothing for unread alone (item 78: the badge is the incomplete count), the picker counts each list', async () => {
    const host = await mountBody();
    expect(taskManagerTab.badge).toBeUndefined();
    taskManagerFocus.focus = { seq: 1, list: 'all', items: [2], open: null };
    expect(taskManagerTab.badge).toBeUndefined();
    const options = [...host.querySelectorAll<HTMLOptionElement>('[data-huddle-pick] option')].map((o) => o.textContent);
    expect(options).toEqual(['all projects (3)', 'shared (2)', 'carnivore (1)']);
    expect(unreadTotal([{ unread: 0 }, {}])).toBeNull();
  });
});

describe('the badge counts needs-you items', () => {
  test('the shown list badges its needs-you count; all projects adds every list; none is null', () => {
    const lists = [{ key: '18', needs_you: 3 }, { key: '17', needs_you: 2 }];
    expect(needsYouTotal(lists, '18')).toBe(3);
    expect(needsYouTotal(lists, AGGREGATE)).toBe(5);
    expect(needsYouTotal([{ key: '18', needs_you: 0 }, { key: '17' }], AGGREGATE)).toBeNull();
  });
});
