/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const COMPLETED = 'done';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', status: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, ...extra,
});
const placeholder = (id: number) => ({
  id, list: '12', state: COMPLETED, status: COMPLETED, section: 'done', group: null, position: id, revision: 1, kind: '', number: null,
  text: '', note: '', thread: [], deleted: false, placeholder: true,
});

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
  reads: [] as string[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (path === '/cplugs/huddle' && init?.method === 'PUT') {
        const sent = JSON.parse(init.body ?? '{}') as { settings: Record<string, unknown> };
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...sent.settings } };
        return server.prefs;
      }
      if (path === '/cplugs/huddle') return server.prefs;
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '12', name: 'alpha', project_id: 12, items: 3, open: 1, done_by_claude: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path.startsWith('/cplugs/huddle/aggregate?live_only=1')) {
        server.reads.push(path);
        const hiding = path.includes('hide_completed=1');
        const items = [mk(1), ...[2, 3].map((id) => (hiding ? placeholder(id) : mk(id, { state: COMPLETED, status: COMPLETED, text: `full ${id}` })))];
        return { cursor: 9, groups: [{ list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager, startTaskManager } from './huddle.svelte';
import { refreshPrefs, setHideCompleted } from './task-manager-prefs.svelte';
import { AGGREGATE, completedCount, visibleItems } from './huddle-model';
import { statusSections } from './task-manager-status-sections';
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

const pastCoalesce = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 400));
  await settle();
};

beforeEach(() => {
  server.reads = [];
  server.prefs = { revision: 3, settings: {} };
  huddle.selected = AGGREGATE;
  huddle.groups = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the read follows hide completed', () => {
  test('hide off asks for the plain aggregate, hide on asks for the placeholders', async () => {
    await refreshPrefs();
    await refreshTaskManager();
    expect(server.reads.at(-1)).toBe('/cplugs/huddle/aggregate?live_only=1');
    server.prefs = { revision: 4, settings: { hideCompleted: true } };
    await refreshPrefs();
    await refreshTaskManager();
    expect(server.reads.at(-1)).toBe('/cplugs/huddle/aggregate?live_only=1&hide_completed=1');
  });

  test('turning hide on and off re-reads, and the full items come back when it is off', async () => {
    await refreshPrefs();
    startTaskManager();
    await pastCoalesce();
    server.reads = [];
    expect(await setHideCompleted(true)).toBe(true);
    await pastCoalesce();
    expect(server.reads).toEqual(['/cplugs/huddle/aggregate?live_only=1&hide_completed=1']);
    expect(huddle.groups![0]!.items.filter((i) => i.placeholder)).toHaveLength(2);
    server.reads = [];
    expect(await setHideCompleted(false)).toBe(true);
    await pastCoalesce();
    expect(server.reads).toEqual(['/cplugs/huddle/aggregate?live_only=1']);
    expect(huddle.groups![0]!.items.map((i) => i.text)).toEqual(['item 1', 'full 2', 'full 3']);
  });

  test('another device flipping the setting re-reads this window', async () => {
    await refreshPrefs();
    startTaskManager();
    await pastCoalesce();
    server.reads = [];
    server.prefs = { revision: 9, settings: { hideCompleted: true } };
    await refreshPrefs();
    await pastCoalesce();
    expect(server.reads).toEqual(['/cplugs/huddle/aggregate?live_only=1&hide_completed=1']);
  });
});

describe('a placeholder', () => {
  const items = () => [mk(1), placeholder(2), placeholder(3)] as unknown as Parameters<typeof visibleItems>[0];

  test('is never on screen, hide on or off, and still counts as completed', () => {
    expect(visibleItems(items(), true).map((i) => i.id)).toEqual([1]);
    expect(visibleItems(items(), false).map((i) => i.id)).toEqual([1]);
    expect(statusSections(items(), false).flatMap((s) => s.items.map((i) => i.id))).toEqual([1]);
    expect(completedCount(items())).toBe(2);
  });

  test('the remove-completed key counts the placeholders and no hidden text is drawn', async () => {
    server.prefs = { revision: 4, settings: { hideCompleted: true } };
    await refreshPrefs();
    await refreshTaskManager();
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    expect(host.querySelector('[data-task-manager-remove-completed]')?.textContent?.trim()).toBe('2');
    expect(host.querySelectorAll('[data-huddle-item]')).toHaveLength(1);
  });
});
