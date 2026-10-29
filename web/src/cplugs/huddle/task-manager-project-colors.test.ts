/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open',
});

const server = vi.hoisted(() => ({ colors: new Map<number, string>() }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 3, settings: {} };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'alpha', project_id: 12, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '18', name: 'beta', project_id: 18, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 9, groups: [
          { list: 'all', name: null, project_id: null, revision: 1, groups: [], items: [mk(1, 'all')] },
          { list: '12', name: 'alpha', project_id: 12, revision: 1, groups: [], items: [mk(11, '12')] },
          { list: '18', name: 'beta', project_id: 18, revision: 1, groups: [], items: [mk(21, '18')] },
        ] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

vi.mock('../../lib/project-colors/store.svelte', () => ({
  projectColorOf: (id: number | null) => (id === null ? null : server.colors.get(id) ?? null),
}));

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { AGGREGATE, listProjectId } from './huddle-model';
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

beforeEach(async () => {
  server.colors = new Map([[12, '#4e69ba'], [18, '#7457c2']]);
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('a list key names its project id, the shared list none', () => {
  expect(listProjectId('18')).toBe(18);
  expect(listProjectId('all')).toBeNull();
  expect(listProjectId('aggregate')).toBeNull();
  expect(listProjectId('0')).toBeNull();
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('each project title wears its own hex color, and a project with no color the quiet text token', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout } });
    await settle();
    const paint = (list: string): string => host.querySelector<HTMLElement>(`[data-task-manager-project-fold="${list}"]`)!.closest<HTMLElement>('.hd-group')!.style.getPropertyValue('--_project');
    expect(paint('12')).toBe('#4e69ba');
    expect(paint('18')).toBe('#7457c2');
    server.colors.delete(18);
    unmount(app);
    app = mount(HuddleBody, { target: host, props: { popout } });
    await settle();
    expect(paint('18')).toBe('var(--oc-text-secondary)');
    expect(paint('12')).toBe('#4e69ba');
  });
});
