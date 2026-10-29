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

/** A `GET /auto-sleep` answer. */
function state(over: Partial<AutoSleepState> = {}): AutoSleepState {
  return {
    enabled: true, idle_minutes: 60, min_idle_minutes: 5, max_idle_minutes: 10080,
    unread_blocks_sleep: true, unread_idle_minutes: 180,
    keep_awake: [], keep_awake_session_uuids: [], mac_awake: false, ...over,
  };
}

/** One `/sessions/list` row, the fields the cell reads. */
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

describe('keptView', () => {
  test('joins each kept name to its live row, counts by stored uuid', () => {
    const view = keptView(
      state({ keep_awake: ['carnivore_a', 'carnivore_gone'], keep_awake_session_uuids: ['u1', 'u2', 'u3'], mac_awake: true }),
      [live('carnivore_a', 'api work', 'working')] as never,
    );
    expect(view.rows.map((row) => [row.name, row.info?.label ?? null])).toEqual([
      ['carnivore_a', 'api work'],
      ['carnivore_gone', null],
    ]);
    expect(view.total).toBe(3);
    expect(view.unnamed).toBe(1);
    expect(view.macAwake).toBe(true);
  });
});

describe('the keep awake cell', () => {
  test('lists each kept session with its name, project, light and a lit cup, and says the mac is held', async () => {
    autoSleepReply = state({ keep_awake: ['carnivore_a'], keep_awake_session_uuids: ['u1'], mac_awake: true });
    sessionsReply = [live('carnivore_a', 'api work', 'working'), live('carnivore_b', 'not kept', 'idle')];
    const target = await render();
    const names = [...target.querySelectorAll('[data-keep-awake-row]')].map((el) => el.textContent);
    expect(names).toEqual(['api work']);
    expect(target.textContent).toContain('carnivore');
    expect(target.querySelector('.status-led, [data-inner]')).not.toBeNull();
    const cup = target.querySelector('button.kaw-icon') as HTMLButtonElement;
    expect(cup.getAttribute('data-keep-awake')).toBe('1');
    expect(cup.getAttribute('aria-pressed')).toBe('true');
    const mac = target.querySelector('[data-mac-awake]') as HTMLElement;
    expect(mac.getAttribute('data-mac-awake')).toBe('held');
    expect(mac.textContent).toContain('this computer is held awake');
    expect(titleCount()).toBe(1);
  });

  test('the cup turns keep awake off for that session through the existing route', async () => {
    autoSleepReply = state({ keep_awake: ['carnivore_a'], keep_awake_session_uuids: ['u1'], mac_awake: true });
    sessionsReply = [live('carnivore_a', 'api work', 'working')];
    const target = await render();
    calls.length = 0;
    (target.querySelector('button.kaw-icon') as HTMLButtonElement).click();
    await settle();
    const put = calls.find((call) => call.method === 'PUT');
    expect(put).toEqual({ path: '/auto-sleep/keep-awake', method: 'PUT', body: { tmux_name: 'carnivore_a', keep_awake: false } });
  });

  test('nobody kept awake is a sentence, and the mac may sleep', async () => {
    const target = await render();
    expect(target.querySelector('[data-keep-awake-notice] .oc-state__title')?.textContent).toBe('no session is kept awake');
    expect(target.querySelector('[data-mac-awake]')?.getAttribute('data-mac-awake')).toBe('free');
    expect(target.querySelector('[data-keep-awake-row]')).toBeNull();
    expect(titleCount()).toBe(0);
  });

  test('kept awake with no assertion held says so, never that the mac is awake', async () => {
    autoSleepReply = state({ keep_awake: ['carnivore_a'], keep_awake_session_uuids: ['u1'], mac_awake: false });
    const target = await render();
    const mac = target.querySelector('[data-mac-awake]') as HTMLElement;
    expect(mac.getAttribute('data-mac-awake')).toBe('missing');
    expect(mac.textContent).not.toContain('is held awake');
  });

  test('a kept name the listing does not carry keeps its row, by tmux name, project not measured', async () => {
    autoSleepReply = state({ keep_awake: ['carnivore_gone'], keep_awake_session_uuids: ['u1', 'u2'], mac_awake: true });
    const target = await render();
    expect(target.querySelector('[data-keep-awake-row]')?.textContent).toBe('carnivore_gone');
    expect(target.textContent).toContain('not measured');
    expect(target.textContent).toContain('1 more kept awake with no live session');
  });

  test('a failed read is its own sentence, not an empty list', async () => {
    autoSleepFailure = new Error('boom');
    const target = await render();
    expect(target.querySelector('[data-keep-awake-notice] .oc-state__title')?.textContent).toBe('boom');
    expect(target.querySelector('[data-mac-awake]')).toBeNull();
  });

  test('the project column appears only once the cell is wide enough', async () => {
    autoSleepReply = state({ keep_awake: ['carnivore_a'], keep_awake_session_uuids: ['u1'], mac_awake: true });
    sessionsReply = [live('carnivore_a', 'api work', 'working')];
    const narrow = await render(240);
    expect(narrow.querySelector('.oc-ka-project')).toBeNull();
    const wide = await render(600);
    expect(wide.querySelector('.oc-ka-project')?.textContent).toBe('carnivore');
  });
});

test('the title mark is the shared coffee glyph, path for path', () => {
  const entry = icons['coffee'] as SizedIcon;
  expect(entry.viewBox).toBe('0 0 16 16');
  const glyph = (GLYPHS as Record<string, Array<Record<string, string>>>).coffee ?? [];
  expect(glyph.length).toBe(5);
  for (const element of glyph) expect(entry.path).toContain(`d="${element.d}"`);
});
