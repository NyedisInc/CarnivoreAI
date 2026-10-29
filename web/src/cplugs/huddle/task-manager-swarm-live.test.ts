/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') {
        return { agents: [{ id: 1, display_name: 'Alpha', rank: 'alpha', state: 'awake', thread_key: 'all', session_id: 'ses_a' }] };
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: {} };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [] };
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

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  localStorage.setItem('cloude.huddle.swarmView', 'lists');
});

describe('the huddle body in the swarm view', () => {
  test('draws the live panel with no state written inside a derived', async () => {
    localStorage.setItem('cloude.huddle.swarmView', 'swarm');
    (globalThis as { ListingPush?: unknown }).ListingPush = {
      rows: () => [{ activity_status: 'idle', session: { id: 'ses_a' } }],
      onChange: () => () => {},
    };
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => { errors.push(a); });
    const { swarmView } = await import('./huddle-swarm-view.svelte');
    swarmView.view = 'swarm';
    const host = document.createElement('div');
    document.body.appendChild(host);
    let thrown: unknown = null;
    try {
      app = mount(HuddleBody, { target: host, props: { popout: false } });
      for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
      flushSync();
    } catch (error) {
      thrown = error;
    }
    spy.mockRestore();
    expect(thrown).toBeNull();
    expect(errors).toEqual([]);
    expect(host.querySelector('[data-swarm-agent="1"]')).not.toBeNull();
  });
});
