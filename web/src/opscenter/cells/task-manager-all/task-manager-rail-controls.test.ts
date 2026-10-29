/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [],
});
const stored = vi.hoisted(() => ({ settings: {} as Record<string, unknown> }));

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (path === '/cplugs/huddle') {
        if (init?.method === 'PUT') Object.assign(stored.settings, JSON.parse(init.body ?? '{}').settings);
        return { revision: 1, settings: { ...stored.settings } };
      }
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0 }] };
      if (/^\/cplugs\/huddle\/lists\/7(?:\?.*)?$/.test(path)) return { list: '7', revision: 1, cursor: 0, groups: [], items: [mk(1, '7')] };
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', items: [mk(1, '7')] }] };
      return {};
    },
  };
});
vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import TaskManagerAll from './Cell.svelte';
import HuddleBody from '../../../cplugs/huddle/HuddleBody.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { swarmView } from '../../../cplugs/huddle/huddle-swarm-view.svelte';

cplugEnablement.enabled = { huddle: true };
const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  apps.splice(0).forEach((a) => unmount(a));
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

describe('huddle widget view and density switch', () => {
  test('the session widget and the all huddles widget each carry the switch, and a press re-renders the rows', async () => {
    swarmView.view = 'lists';
    const rail = document.createElement('div');
    const all = document.createElement('div');
    document.body.append(rail, all);
    apps.push(mount(HuddleBody, { target: rail, props: { list: '7' } }));
    apps.push(mount(TaskManagerAll, { target: all }));
    await settle();

    for (const host of [rail, all]) {
      expect(host.querySelector('[data-task-manager-view-key="area"]')).not.toBeNull();
      expect(host.querySelector('[data-huddle-density-key="compact"]')).not.toBeNull();
    }
    expect(rail.querySelector('[data-huddle-item]')?.getAttribute('data-task-manager-density')).toBe('normal');
    expect(rail.querySelector('[data-task-manager-view]')?.getAttribute('data-task-manager-view')).toBe('status');

    (rail.querySelector('[data-huddle-density-key="compact"]') as HTMLElement).click();
    (rail.querySelector('[data-task-manager-view-key="area"]') as HTMLElement).click();
    await settle();

    expect(stored.settings).toMatchObject({ density: 'compact', view: 'area' });
    expect(rail.querySelector('[data-huddle-item]')?.getAttribute('data-task-manager-density')).toBe('compact');
    expect(rail.querySelector('[data-task-manager-view]')?.getAttribute('data-task-manager-view')).toBe('area');
    expect(all.querySelector('[data-huddle-item]')?.getAttribute('data-task-manager-density')).toBe('compact');
    expect(all.querySelector('[data-task-manager-heading]')?.textContent?.trim()).toBe('Carnivore');
  });
});
