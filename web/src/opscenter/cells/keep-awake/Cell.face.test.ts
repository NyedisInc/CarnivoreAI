/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { GLYPHS } from '../../../../../client/js/icons/glyphs.js';

const calls: { path: string; method: string; body: unknown }[] = [];
let autoSleepReply: unknown = null;
let autoSleepFailure: Error | null = null;
let sessionsReply: unknown[] = [];

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) { super(message); this.status = status; }
  },
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body) : null });
    if (path === '/auto-sleep') {
      if (autoSleepFailure) throw autoSleepFailure;
      return autoSleepReply;
    }
    if (path === '/auto-sleep/keep-awake') return autoSleepReply;
    if (path === '/sessions/list') return sessionsReply;
    if (path === '/projects') return [{ id: 1, name: 'carnivore', path: '/Users/x/dev/carnivore', root: '/Users/x/dev/carnivore', description: null, work_at: null, archived_at: null }];
    return null;
  },
}));

import Cell from './Cell.svelte';
import { keptView, titleCount } from './meta';
import { META } from '../../engine/meta';
import { icons, type SizedIcon } from '../../ui/icons';
import { autoSleep, type AutoSleepState } from '../../../lib/auto-sleep/auto-sleep-store.svelte';
import { sessions, projects } from '../../api';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

function state(over: Partial<AutoSleepState> = {}): AutoSleepState {
  return {
    enabled: true, idle_minutes: 60, min_idle_minutes: 5, max_idle_minutes: 10080,
    unread_blocks_sleep: true, unread_idle_minutes: 180,
    keep_awake: [], keep_awake_session_uuids: [], mac_awake: false, ...over,
  };
}

function live(name: string, label: string, status: string): Record<string, unknown> {
  return {
    session: { id: `ses_${name}`, working_dir: '/Users/x/dev/carnivore', created_at: '2026-09-27T00:00:00Z' },
    tmux_session: name, label, agent_family: 'claude', activity_status: status,
    unread: false, startup_gate: null, status_source: 'registry',
  };
}

beforeEach(() => {
  calls.length = 0;
  autoSleepReply = state();
  autoSleepFailure = null;
  sessionsReply = [];
});

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function render(width = 600): Promise<HTMLElement> {
  await Promise.all([autoSleep.refresh(true), sessions.refresh(true), projects.refresh(true)]);
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(Cell, { target, props: { width, height: 300, meta: META['keep-awake'], instance: 'keep-awake', page: 'home' } as never }));
  await settle();
  return target;
}


describe('the keep awake cell face', () => {
  test('the light and name of a kept row, with every signal the listing carries', async () => {
    autoSleepReply = state({ keep_awake: ['carnivore_a'], keep_awake_session_uuids: ['u1'], mac_awake: true });
    sessionsReply = [{
      ...live('carnivore_a', 'api work', 'working'), unread: true, activity_hint: 'shell', parked_summary: 'waiting on the build',
      host_key: null,
    }];
    const target = await render();
    const face = [...target.querySelectorAll('[data-inner], [data-keep-awake-row]')].map((n) => n.outerHTML).join('\n').replace(/ svelte-[a-z0-9]+/g, '');
    await expect(face + '\n').toMatchFileSnapshot('./__goldens__/keep-awake-face.html');
  });
});
