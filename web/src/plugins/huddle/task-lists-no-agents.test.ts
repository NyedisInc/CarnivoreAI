/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const row = (key: string, name: string | null, project_id: number | null) => ({
  key, name, project_id, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0,
});
const mk = (id: number, list: string) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [],
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') {
        return { agents: [{ id: 5, display_name: 'Frigg', rank: 'feature', state: 'awake', thread_key: 'agent:5', session_id: null }] };
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [row('all', null, null), row('7', 'Carnivore', 7), row('agent:5', null, null)] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 0, groups: [
          { list: 'all', name: null, items: [mk(1, 'all')] },
          { list: '7', name: 'Carnivore', items: [mk(2, '7')] },
          { list: 'agent:5', name: null, items: [mk(3, 'agent:5')] },
        ] };
      }
      return {};
    },
  };
});
vi.mock('../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';
import { swarmView } from './huddle-swarm-view.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the lists view without agent listings', () => {
  test('no agent rows, agent lists or agent groups; project and shared lists stay', async () => {
    swarmView.view = 'lists';
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    const picker = [...host.querySelectorAll('[data-huddle-pick] option')].map((o) => o.getAttribute('value'));
    expect(picker).toContain('7');
    expect(picker).toContain('all');
    expect(picker.some((key) => key?.startsWith('agent:'))).toBe(false);
    const addTargets = [...host.querySelectorAll('option')].map((o) => o.getAttribute('value'));
    expect(addTargets.some((key) => key?.startsWith('agent:'))).toBe(false);
    expect(host.querySelector('[data-huddle-agents]')).toBeNull();
    expect(host.querySelector('[data-huddle-item="1"]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="2"]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="3"]')).toBeNull();
  });
});
