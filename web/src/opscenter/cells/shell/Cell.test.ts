/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

import Cell from './Cell.svelte';
import { META } from '../../engine/meta';
import { inputFocus } from '../../lib/input-focus.svelte';
import { DEFAULT_BOTTOM_ITEMS } from '../../../lib/session-rail/rail-model';
import { CORE_MANIFESTS } from '../../widgets/core-manifests';
import { ApiError } from '../../api/auth.svelte';

const listing = new SvelteMap<string, unknown>([['status', 'ok'], ['rows', [] as unknown[]]]);
const scopeHolder = new SvelteMap<string, unknown>([['scope', null]]);

const calls: { path: string; method: string }[] = [];
let answer: (agent: string) => unknown = () => { throw new Error('no answer set'); };

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...actual,
    authFetch: vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, method: init.method ?? 'GET' });
      const agent = decodeURIComponent(path.split('/')[2] ?? '');
      return answer(agent);
    }),
  };
});

const built: { id: string; slot: string }[] = [];
let disposed = 0;
vi.mock('../terminal-live/client', () => ({
  startLiveTerminal: (_host: HTMLElement, slot: string, session: unknown) => {
    built.push({ id: (session as { session_id: string }).session_id, slot });
    return { client: { fake: true }, dispose(): void { disposed += 1; } };
  },
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      get data() { return listing.get('rows'); },
      get status() { return listing.get('status'); },
      refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  built.length = 0;
  calls.length = 0;
  disposed = 0;
  inputFocus.forget('terminal:row:96');
  listing.set('status', 'ok');
  listing.set('rows', []);
  scopeHolder.set('scope', null);
});

function row(id: string, hostKey?: string): unknown {
  return { session: { id }, label: `agent ${id}`, tmux_session: `carnivore_${id}`, ...(hostKey ? { host_key: hostKey } : {}) };
}

function shellFor(agent: string, n: number): unknown {
  return {
    agent_session_id: agent, agent_row_id: n - 100, session_id: `ses_shell_${n}`, session_row_id: n,
    tmux_session: `carnivore_sh-${n - 100}`, working_dir: '/work/a', state: 'created',
    session: { id: `ses_shell_${n}` },
  };
}

function refusal(code: string): ApiError {
  return new ApiError(`${code} sentence`, 409, null, { detail: { code, detail: `${code} sentence` } });
}

function pointAt(agent: string | null): void {
  scopeHolder.set('scope', agent ? { sessionId: agent, rowId: 1, workingDir: '/work/a', projectId: null } : null);
  flushSync();
}

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(Cell, {
    target,
    props: {
      width: 900, height: 300, meta: META.shell, instance: 'session-rail:core.shell',
      get scope() { return scopeHolder.get('scope'); },
    } as never,
  }));
  flushSync();
  return target;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) { await Promise.resolve(); flushSync(); }
}

test('opening the panel is one ensure and one client on the SHELL, under a shell: slot', async () => {
  answer = (agent) => shellFor(agent, 196);
  listing.set('rows', [row('ses_a')]);
  pointAt('ses_a');
  inputFocus.claim('terminal:row:96');
  const el = render();
  await settle();

  expect(calls).toEqual([{ path: '/sessions/ses_a/shell', method: 'POST' }]);
  expect(built).toEqual([{ id: 'ses_shell_196', slot: 'shell:row:196' }]);
  expect(el.querySelector('[data-shell-slot="shell:row:196"]')).not.toBeNull();
  expect(inputFocus.owner).toBe('terminal:row:96');
  el.querySelector('[data-shell-slot]')?.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
  expect(inputFocus.owner).toBe('shell:row:196');
  expect(inputFocus.selected).toBe('terminal:row:96');
});

test('a shell that exited draws the ended plate after a user gesture, and start again respawns it', async () => {
  vi.useFakeTimers();
  try {
    let pane: 'live' | 'dead' = 'live';
    answer = (agent) => ({ ...(shellFor(agent, 196) as object), pane });
    listing.set('rows', [row('ses_a')]);
    pointAt('ses_a');
    const el = render();
    await settle();
    expect(el.querySelector('[data-plate="live"]')).not.toBeNull();

    const body = el.querySelector('[data-shell-slot]') as HTMLElement;
    body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await vi.advanceTimersByTimeAsync(800);
    expect(el.querySelector('[data-plate="live"]')).not.toBeNull();
    pane = 'dead';
    body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await vi.advanceTimersByTimeAsync(800);
    await settle();
    expect(el.querySelector('[data-plate="ended"]')?.textContent).toContain('the shell ended');

    pane = 'live';
    const before = calls.filter((c) => c.method === 'POST').length;
    (el.querySelector('button') as HTMLButtonElement).click();
    await settle();
    expect(calls.filter((c) => c.method === 'POST').length).toBe(before + 1);
    expect(el.querySelector('[data-plate="live"]')).not.toBeNull();
    expect(built.length).toBe(2);
  } finally {
    vi.useRealTimers();
  }
});

test('a re-polled identical listing neither re-ensures nor rebuilds, and a row that arrives later still builds', async () => {
  answer = (agent) => shellFor(agent, 196);
  listing.set('status', 'loading');
  pointAt('ses_a');
  render();
  await settle();
  expect(built.length).toBe(1);

  listing.set('status', 'ok');
  listing.set('rows', [row('ses_a')]);
  flushSync();
  listing.set('rows', [row('ses_a')]);
  flushSync();
  await settle();

  expect(calls.length).toBe(1);
  expect(built.length).toBe(1);
  expect(disposed).toBe(0);
});

test('following to another agent disposes the client and starts that agent\'s shell', async () => {
  answer = (agent) => shellFor(agent, agent === 'ses_a' ? 196 : 197);
  listing.set('rows', [row('ses_a'), row('ses_b')]);
  pointAt('ses_a');
  render();
  await settle();
  pointAt('ses_b');
  await settle();

  expect(calls.map((c) => c.path)).toEqual(['/sessions/ses_a/shell', '/sessions/ses_b/shell']);
  expect(built.map((b) => b.slot)).toEqual(['shell:row:196', 'shell:row:197']);
  expect(disposed).toBe(1);
});

test('each refusal word draws its own plate, and an error offers a retry', async () => {
  listing.set('rows', [row('ses_a')]);
  pointAt('ses_a');

  answer = () => { throw refusal('agent_not_running'); };
  let el = render();
  await settle();
  expect(el.querySelector('[data-plate="not_running"]')?.textContent).toContain('agent ses_a is not running');
  expect(el.querySelector('[data-plate="not_running"] button')?.textContent).toContain('try again');

  answer = () => { throw refusal('remote_agent'); };
  el = render();
  await settle();
  expect(el.querySelector('[data-plate="remote"]')?.textContent).toContain('works for agents on this computer');

  answer = () => { throw refusal('folder_missing'); };
  el = render();
  await settle();
  expect(el.querySelector('[data-plate="error"]')?.textContent).toContain('could not open a shell');
  expect(el.querySelector('button')?.textContent).toContain('try again');
  expect(built).toEqual([]);
});

test('an agent on a paired computer draws the plate and makes no request', async () => {
  answer = () => { throw new Error('must not be called'); };
  pointAt('remote:peer-x:ses_9');
  const el = render();
  await settle();
  expect(el.querySelector('[data-plate="remote"]')).not.toBeNull();
  expect(calls).toEqual([]);
});

test('no agent selected says so, and the bottom bar defaults to the terminal widget', async () => {
  const el = render();
  await settle();
  expect(el.querySelector('[data-plate="no_agent"]')?.textContent).toContain('select an agent');
  expect(DEFAULT_BOTTOM_ITEMS).toEqual([{ widget: 'core.shell', look: null }, { widget: 'core.scheduled-tasks', look: null }]);
  expect(CORE_MANIFESTS['core.shell']?.capabilities).toContain('terminal-input');
});
