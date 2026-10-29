/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], github_issue: '', section: 'open', status: 'open',
});

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [
        { key: '7', name: 'Carnivore', project_id: 7, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        { key: '8', name: 'Other', project_id: 8, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [
        { list: '7', name: 'Carnivore', project_id: 7, revision: 1, items: [mk(1, '7'), mk(2, '7'), mk(3, '7')] },
        { list: '8', name: 'Other', project_id: 8, revision: 1, items: [mk(11, '8'), mk(12, '8'), mk(13, '8')] }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: [mk(1, one[1] as string)] };
      return {};
    },
  };
});
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  sessions: { data: [{ session_row_id: 1, project_id: 7, session: { id: 'ses_1', working_dir: '/x' } }] },
}));
vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Mark2 from './Cell.svelte';
import Mk2Host from './fixtures/Mk2Host.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';

cplugEnablement.enabled = { huddle: true };
const apps: Array<ReturnType<typeof mount>> = [];
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

describe('a pinned project widget owns its selection', () => {
  test('mounting it leaves the shared selection and body alone, and it draws its own project', async () => {
    huddle.selected = '8';
    huddle.body = { list: '8', revision: 1, cursor: 0, groups: [], items: [mk(11, '8')] } as unknown as typeof huddle.body;
    const host = document.createElement('div');
    document.body.appendChild(host);
    const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
    apps.push(mount(Mk2Host, { target: host, props: { cell: Mark2, hostId: 'mk2-body', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope } } }));
    for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    await vi.waitFor(() => expect(huddle.groups).not.toBeNull(), { timeout: 6000 });
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    expect(huddle.selected).toBe('8');
    expect(huddle.body?.list).toBe('8');
    const ids = Array.from(host.querySelectorAll('[data-huddle-item]'), (el) => el.getAttribute('data-huddle-item'));
    expect(ids).toEqual(['1', '2', '3']);
  }, 15_000);
});
