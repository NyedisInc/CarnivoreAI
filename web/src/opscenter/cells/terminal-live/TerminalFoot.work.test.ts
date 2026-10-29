/** @vitest-environment jsdom */
/* and the three */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync, tick } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';
import { auth } from '../../api/auth.svelte';
import type { SessionInfo, SessionTokenUsage } from '../../api/types';

let rows: Partial<SessionInfo>[] = [];
let usagePayload: SessionTokenUsage | null = null;
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessions: { get data() { return rows; } },
    sessionUsage: vi.fn(() => ({ data: usagePayload, status: 'ok' })),
    releaseSessionUsage: vi.fn(),
  };
});

vi.mock('../../../lib/timers/timers', async () => {
  const actual = await vi.importActual<typeof import('../../../lib/timers/timers')>('../../../lib/timers/timers');
  return {
    ...actual,
    fetchTimers: vi.fn(async () => ({ state: 'ok', family: 'claude', conversation_uuid: 'u', process: 'alive',
      process_started_at: null, counts: null, next_fire_at: null, timers: [], background: null,
      detail: '', as_of: null })),
  };
});

const terminate = vi.fn();
vi.mock('../../../lib/background-work/background-work', async () => {
  const actual = await vi.importActual<typeof import('../../../lib/background-work/background-work')>(
    '../../../lib/background-work/background-work');
  return {
    ...actual,
    fetchBackgroundWork: vi.fn(async () => ({
      state: 'ok', family: 'claude', detail: '', as_of: null, owners: 'ok',
      processes: [{ agent_id: 'a1', pid: 89199, start: 'Mon Sep 28 08:58:46 2026', task_id: 'bt0wu171w',
        started_at: '2026-09-28T12:58:46Z', children: 2, summary: 'ssh host echo ALIVE | head -12' }],
    })),
    terminateProcess: (...args: unknown[]) => terminate(...args),
  };
});
vi.mock('../../../lib/subagents/subagents', async () => {
  const actual = await vi.importActual<typeof import('../../../lib/subagents/subagents')>(
    '../../../lib/subagents/subagents');
  return {
    ...actual,
    fetchSubagents: vi.fn(async () => ({
      state: 'ok', family: 'claude', conversation_uuid: 'u', detail: '', as_of: null, counts: null,
      subagents: [
        { id: 'a1', agent_type: 'Explore', description: 'map the repo', model: null, background: true,
          spawn_depth: 1, started_at: '2026-09-28T13:00:00Z', last_activity_at: null,
          status: 'running', status_reason: 'no_end_recorded', end_status: null },
        { id: 'a2', agent_type: 'Explore', description: 'finished one', model: null, background: true,
          spawn_depth: 1, started_at: '2026-09-28T12:00:00Z', last_activity_at: null,
          status: 'done', status_reason: 'end_recorded', end_status: 'completed' },
      ],
    })),
  };
});

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  auth.state = 'signed-in';
  installFootBarItems({ agents: true, shells: true });
});

afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  rows = [];
  usagePayload = null;
  terminate.mockReset();
  delete (globalThis as G).PreferenceBridge;
  try { globalThis.localStorage?.clear(); } catch {  }
});

function usage(remainingPct: number): SessionTokenUsage {
  return {
    state: 'ok', family: 'claude', model: 'claude-opus-4', model_display_name: 'Opus 4',
    model_cost_tier: 3, effort: null, input_tokens: 1, output_tokens: 1,
    cache_read_input_tokens: null, cache_creation_input_tokens: null, total_tokens: 2,
    cost_estimate_usd: null, context_used_tokens: 170000, context_window_tokens: 200000,
    context_remaining_pct: remainingPct, as_of: '2026-09-28T00:00:00Z', detail: null, account: null,
  };
}

function setup(row: Partial<SessionInfo>, remainingPct = 15): HTMLElement {
  rows = [{ session: { id: 'ses_1' } as SessionInfo['session'], agent_family: 'claude', ...row }];
  usagePayload = usage(remainingPct);
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width: 900 } }));
  flushSync();
  return target;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

test('the context percent and gauge wear the scale colour of how full it is', () => {
  const target = setup({});
  const pct = target.querySelector('button.oc-tf .oc-tf-pct');
  expect(pct?.textContent).toContain('85');
  expect(pct?.getAttribute('data-scale')).toBe('4');
  const bar = target.querySelector('button.oc-tf .oc-tf-meter .oc-tf-bar');
  expect(bar?.getAttribute('data-scale')).toBe('4');
  expect((bar?.querySelector('.oc-tf-bar-fill') as HTMLElement).style.width).toBe('85%');
});

test('an idle session draws no work segment at all', () => {
  const target = setup({ subagents_running: 0, background_open: 0, timers_live: null });
  expect(target.querySelector('.oc-tfw')).toBeNull();
});

test('the bar draws agents and shells counts from the control center lists, never the summed listing fields; the clock says when it next fires', async () => {
  const future = new Date(Date.now() + 18 * 60 * 1000).toISOString();
  const target = setup({ subagents_running: 1, background_open: 3, timers_live: 2,
    timers_next_fire_at: future });
  await settle();
  const num = (seg: string) => target.querySelector(`.oc-tfw-seg[data-seg="${seg}"] .oc-tfw-num`)?.textContent;
  expect(num('agents')).toBe('1');
  expect(num('shells')).toBe('1');
  expect(target.querySelector('.oc-tfw-seg[data-seg="shells"]')?.textContent).toMatch(/^shells\s*1$/);
  expect(target.querySelector('.oc-tfw-seg[data-seg="agents"]')?.textContent).toMatch(/^agents\s*1$/);
  const clock = target.querySelector('.oc-tfw-seg[data-seg="timers"]');
  expect(clock?.textContent).toContain('timers');
  expect(clock?.textContent).toContain('2');
  expect(clock?.textContent).toContain('next 18m');
});

test('the bar counts equal the grown control center headers on the same lists', async () => {
  const target = setup({ subagents_running: 1, background_open: 3, timers_live: null });
  await settle();
  const bar = (seg: string) => target.querySelector(`.oc-tfw-seg[data-seg="${seg}"] .oc-tfw-num`)?.textContent;
  target.querySelector<HTMLButtonElement>('button.oc-tf')!.click();
  flushSync();
  await settle();
  const panel = (section: string) =>
    target.querySelector(`.scc-section[data-scc-section="${section}"] .scc-count`)?.textContent;
  expect(panel('agents')).toBe('1');
  expect(panel('processes')).toBe('1');
  expect(bar('agents')).toBe(panel('agents'));
  expect(bar('shells')).toBe(panel('processes'));
});

test('a segment grows the bar into the control center on its own section; a second click folds it', async () => {
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get(this: HTMLElement) { return this.classList.contains('oc-tfw-measure') ? 140 : 0; },
  });
  try {
    const future = new Date(Date.now() + 32 * 60 * 1000).toISOString();
    const target = setup({ subagents_running: 2, background_open: 1, timers_live: 3,
      timers_next_fire_at: future });
    const bar = target.querySelector<HTMLButtonElement>('button.oc-tf')!;
    const grown = () => target.querySelector<HTMLElement>('.oc-tf-grown')!;
    const seg = (name: string) => target.querySelector<HTMLButtonElement>(`.oc-tfw-seg[data-seg="${name}"]`)!;
    const focused = () => target.querySelector('.scc-section[data-focused="true"]')?.getAttribute('data-scc-section');

    await settle();
    seg('shells').click();
    await settle();
    expect(bar.getAttribute('aria-expanded')).toBe('true');
    expect(focused()).toBe('processes');
    seg('agents').click();
    await settle();
    expect(focused()).toBe('agents');

    seg('timers').click();
    await settle();
    expect(bar.getAttribute('aria-expanded')).toBe('true');
    expect(grown().hidden).toBe(false);
    expect(focused()).toBe('timers');
    expect(seg('timers').getAttribute('aria-expanded')).toBe('true');
    expect(grown().style.right).toBe('0px');

    seg('timers').click();
    await settle();
    expect(bar.getAttribute('aria-expanded')).toBe('false');
    expect(grown().hidden).toBe(true);
  } finally {
    if (width) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', width);
  }
});

// THE COLLAPSED BAR'S SHOWN ITEMS (issue #1053, Joe (ccsliinc), 2026-09-28):
type G = { PreferenceBridge?: unknown };

function installFootBarItems(stored: Record<string, boolean>): void {
  (globalThis as G).PreferenceBridge = {
    read: (_field: string, local: () => unknown) => stored,
    write: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
}

test('a hidden usage item never draws in the collapsed bar', () => {
  installFootBarItems({ context: false });
  try {
    const target = setup({}, 15);
    expect(target.querySelector('button.oc-tf .oc-tf-meters .oc-tf-label')).toBeNull();
    expect(target.querySelector('button.oc-tf .oc-tf-meters')?.children.length).toBe(0);
  } finally {
    delete (globalThis as G).PreferenceBridge;
  }
});

test('a hidden model item drops the model AND its effort together', () => {
  installFootBarItems({ model: false });
  try {
    const target = setup({}, 15);
    expect(target.querySelector('.oc-tf-model')).toBeNull();
    expect(target.querySelector('.oc-tf-effort')).toBeNull();
  } finally {
    delete (globalThis as G).PreferenceBridge;
  }
});

test('hidden agents, shells and timers items never draw their segment, and the grown view is unaffected', async () => {
  installFootBarItems({ agents: false, shells: false, timers: false });
  try {
    const target = setup({ subagents_running: 2, background_open: 3, timers_live: 2,
      timers_next_fire_at: new Date(Date.now() + 60000).toISOString() });
    await settle();
    expect(target.querySelector('.oc-tfw-seg[data-seg="timers"]')).toBeNull();
    expect(target.querySelector('.oc-tfw-seg[data-seg="agents"]')).toBeNull();
    expect(target.querySelector('.oc-tfw-seg[data-seg="shells"]')).toBeNull();

    const bar = target.querySelector<HTMLButtonElement>('button.oc-tf')!;
    bar.click();
    flushSync();
    await settle();
    expect(target.querySelector('[data-scc-section="agents"]')).not.toBeNull();
    expect(target.querySelector('[data-scc-section="timers"]')).not.toBeNull();
  } finally {
    delete (globalThis as G).PreferenceBridge;
  }
});

test('an unimplemented collapsedOption/openOption falls back to "a" rather than drawing nothing', async () => {
  rows = [{ session: { id: 'ses_1' } as SessionInfo['session'], agent_family: 'claude',
    subagents_running: 1, background_open: 1, timers_live: 1 }];
  usagePayload = usage(15);
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width: 900, collapsedOption: 'b', openOption: 'c' } }));
  flushSync();
  expect(target.querySelector('button.oc-tf .oc-tf-model')).not.toBeNull();
  target.querySelector<HTMLButtonElement>('button.oc-tf')!.click();
  flushSync();
  await settle();
  expect(target.querySelector('.oc-tfs')).not.toBeNull();
  expect(target.querySelector('.scc')).not.toBeNull();
});
