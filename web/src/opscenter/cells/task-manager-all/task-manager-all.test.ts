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

const asked = vi.hoisted(() => [] as string[]);
const page = vi.hoisted(() => ({ session: 'ses_1' }));

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      asked.push(path);
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [row('7', 'Carnivore', 7), row('9', 'Billing', 9)] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: [mk(one[1] === '7' ? 1 : 2, one[1] as string)] };
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 0, groups: [
          { list: '7', name: 'Carnivore', items: [mk(1, '7')] },
          { list: '9', name: 'Billing', items: [mk(2, '9')] },
        ] };
      }
      return {};
    },
  };
});
vi.mock('../../lib/active-terminal', () => ({
  activeTerminalSessionId: () => page.session,
  activeTerminalSlot: () => 'terminal:@primary',
}));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import TaskManagerAll from './Cell.svelte';
import HuddleBody from '../../../cplugs/huddle/HuddleBody.svelte';
import { huddle, selectList } from '../../../cplugs/huddle/huddle.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { swarmView } from '../../../cplugs/huddle/huddle-swarm-view.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;
let second: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  if (second) unmount(second);
  app = null;
  second = null;
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

function snapshot(host: HTMLElement): { items: string[]; heads: string[] } {
  return {
    items: [...host.querySelectorAll('[data-huddle-item]')].map((el) => el.getAttribute('data-huddle-item') ?? ''),
    heads: [...host.querySelectorAll('[data-task-manager-heading]')].map((el) => el.textContent?.trim() ?? ''),
  };
}

describe('the all huddles widget', () => {
  test('shows two lists under their own heads and ignores the selected session', async () => {
    swarmView.view = 'lists';
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerAll, { target: host });
    await settle();

    const before = snapshot(host);
    expect(before.items).toEqual(['1', '2']);
    expect(before.heads).toEqual(['Carnivore', 'Billing']);

    page.session = 'ses_2';
    flushSync();
    await settle();

    expect(snapshot(host)).toEqual(before);
    expect(asked.some((path) => /^\/cplugs\/huddle\/lists\/\d+/.test(path))).toBe(false);
  });

  test('a session huddle widget owns its list: the shared selection changing never moves it, and it never moves the shared selection', async () => {
    swarmView.view = 'lists';
    const sessionHost = document.createElement('div');
    const allHost = document.createElement('div');
    document.body.append(sessionHost, allHost);
    second = mount(HuddleBody, { target: sessionHost, props: { list: '7' } });
    await settle();
    app = mount(TaskManagerAll, { target: allHost });
    await settle();

    const before = snapshot(allHost);
    expect(before.items).toEqual(['1', '2']);
    expect(huddle.selected).not.toBe('7');
    expect(snapshot(sessionHost).items).toEqual(['1']);

    await selectList('9');
    await settle();

    expect(snapshot(allHost)).toEqual(before);
    expect(snapshot(sessionHost).items).toEqual(['1']);

    unmount(app);
    app = null;
    await settle();

    expect(huddle.selected).toBe('9');
    expect(snapshot(sessionHost).items).toEqual(['1']);
  });
});
