/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';
import SwarmPanel from './SwarmPanel.svelte';
import { ApiError } from '../../sdk';
import { buildFloor } from './floor';
import {
  ACTIVITY_MS, columnsOf, panelDensity, partsOf, priorityCount, sizeOf, squareState, sendOf,
  type PanelAgent, type PanelDensity,
} from './panel-state';

setLocale('en');

const NOW = 1_000_000_000_000;
const SECS = NOW / 1000;
const base = (over: Partial<PanelAgent>): PanelAgent => ({ id: 1, display_name: 'Loki', rank: 'task', state: 'awake', thread_key: 'agent:1', session_id: 'ses_1', ...over });
const live = { activity_status: 'working', startup_gate: 'ready', running_context_used_pct: 42 };

const ROSTER: PanelAgent[] = [
  base({ id: 1, display_name: 'Alpha', rank: 'alpha', thread_key: 'all', session_id: 'ses_a' }),
  base({ id: 2, display_name: 'Larkspur', rank: 'company', thread_key: 'company:1', company_id: 1, session_id: 'ses_c' }),
  base({ id: 3, display_name: 'cloudecode', rank: 'project', thread_key: '12', project_id: 12, session_id: 'ses_p' }),
  base({ id: 4, display_name: 'Loki', rank: 'feature', session_id: 'ses_f', harness: 'claude' }),
  base({ id: 5, display_name: 'Mabel', rank: 'task', state: 'asleep', session_id: null }),
];

describe('the corner tell', () => {
  test('question first, then question_waiting, then notice, then unread, else none', () => {
    const waiting = base({ question_waiting: true });
    expect(sendOf(waiting, { activity_status: 'question' })).toBe('question');
    expect(sendOf(waiting, { activity_status: 'notice' })).toBe('question_waiting');
    expect(sendOf(base({}), { activity_status: 'notice' })).toBe('notice');
    expect(sendOf(base({}), { activity_status: 'finished_unread' })).toBe('unread');
    expect(sendOf(base({}), { activity_status: 'working' })).toBeNull();
    expect(sendOf(base({}), undefined)).toBeNull();
  });

  test('an activity or an alert rung does not hide the tell', () => {
    const busy = base({ alert: 'flash', activity: 'talking', activity_at: SECS });
    expect(squareState(busy, { activity_status: 'question' }, NOW)).toBe('alert_flash');
    expect(sendOf(busy, { activity_status: 'question' })).toBe('question');
  });
});

describe('state precedence', () => {
  test('alert beats everything, then a fresh activity, question_waiting, asleep, startup gate, status, unknown', () => {
    const row = { activity_status: 'working', startup_gate: 'awaiting_startup_prompt' };
    const all = base({ alert: 'priority', activity: 'talking', activity_at: SECS, question_waiting: true, state: 'asleep' });
    expect(squareState(all, row, NOW)).toBe('alert_priority');
    const noAlert = { ...all, alert: null };
    expect(squareState(noAlert, row, NOW)).toBe('talking');
    const stale = { ...noAlert, activity_at: SECS - ACTIVITY_MS / 1000 - 1 };
    expect(squareState(stale, row, NOW)).toBe('question_waiting');
    expect(squareState({ ...stale, question_waiting: false }, row, NOW)).toBe('asleep');
    const awake = { ...stale, question_waiting: false, state: 'awake' };
    expect(squareState(awake, row, NOW)).toBe('startup_gate');
    expect(squareState(awake, { ...row, startup_gate: 'ready' }, NOW)).toBe('working');
    expect(squareState(awake, undefined, NOW)).toBe('unknown');
    expect(squareState(awake, { activity_status: 'nonsense' }, NOW)).toBe('unknown');
  });

  test('absent S6e fields fall back: no alert, no activity, question_waiting false', () => {
    expect(squareState(base({}), live, NOW)).toBe('working');
    expect(squareState(base({ alert: 'loud' }), live, NOW)).toBe('working');
    expect(squareState(base({ activity: 'done' }), live, NOW)).toBe('working');
    expect(squareState(base({ activity: 'asleep', activity_at: SECS }), live, NOW)).toBe('working');
  });

  test('every alert rung wears its own state', () => {
    for (const rung of ['routine', 'priority', 'immediate', 'flash']) expect(squareState(base({ alert: rung }), live, NOW)).toBe(`alert_${rung}`);
  });
});

describe('sizes and the priority count', () => {
  test('columns and sizes follow the mockup', () => {
    expect([columnsOf('companies', 'condensed'), columnsOf('projects', 'condensed'), columnsOf('projects', 'expanded'), columnsOf('agents', 'condensed'), columnsOf('agents', 'expanded')]).toEqual([3, 5, 4, 8, 6]);
    expect(['alpha', 'company', 'project', 'feature'].map((r) => sizeOf(r, 'expanded'))).toEqual([96, 64, 40, 28]);
    expect(sizeOf('alpha', 'detailed')).toBe(64);
    expect(['company', 'project', 'feature', 'task'].map((r) => sizeOf(r, 'expanded', true))).toEqual([64, 40, 22, 22]);
    expect(sizeOf('task', 'detailed', true)).toBe(28);
  });

  test('the priority count', () => {
    expect(priorityCount([base({ alert: 'routine' }), base({ alert: 'priority' }), base({ alert: 'flash' }), base({})])).toBe(2);
  });
});

describe('densities', () => {
  let app: object | null = null;
  afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.innerHTML = '';
  });

  async function panel(density: PanelDensity): Promise<HTMLElement> {
    document.body.innerHTML = '<div id="host"></div>';
    const host = document.getElementById('host') as HTMLElement;
    app = mount(SwarmPanel, {
      target: host,
      props: {
        floor: buildFloor({
          agents: ROSTER, sessions: [], companies: [{ id: 1, name: 'Larkspur' }], projects: [{ id: 12, name: 'cloudecode', companyId: 1 }], showInactive: true,
          rowOf: (id: string | null | undefined) => (id === 'ses_f' ? { ...live, working_on: 'fixing the drawer', working_on_state: 'ok' } : id ? { activity_status: 'idle' } : undefined),
        }),
        agents: ROSTER, density, now: NOW, still: true, showInactive: true, onToggleInactive: vi.fn(), onOpen: vi.fn(), onTurnOn: vi.fn(),
      },
    });
    flushSync();
    await tick();
    return host;
  }

  test('the huddle setting maps to the panel density', () => {
    expect(['compact', 'normal', 'full'].map((d) => panelDensity(d as 'compact'))).toEqual(['condensed', 'expanded', 'detailed']);
    expect(partsOf('condensed')).toMatchObject({ name: false, provider: false, context: false, workingOn: false });
    expect(partsOf('expanded')).toMatchObject({ name: true, provider: false, context: false, workingOn: false });
    expect(partsOf('detailed')).toMatchObject({ name: true, provider: true, context: true, workingOn: true, list: true });
  });

  test('condensed draws squares only', async () => {
    const host = await panel('condensed');
    expect(host.querySelectorAll('[data-swarm-agent]').length).toBe(5);
    expect(host.querySelector('.pkp-nm')).toBeNull();
    expect(host.querySelector('.oc-gauge')).toBeNull();
  });

  test('expanded adds names, and nothing else', async () => {
    const host = await panel('expanded');
    expect([...host.querySelectorAll('.pkp-nm')].map((n) => n.textContent)).toEqual(['Alpha', 'Larkspur', 'cloudecode', 'Loki', 'Mabel']);
    expect(host.querySelector('.pkp-prov')).toBeNull();
    expect(host.querySelector('.oc-gauge')).toBeNull();
    expect(host.querySelector('[data-swarm-working-on]')).toBeNull();
  });

  test('detailed adds the provider mark, the context bar and the working-on line', async () => {
    const host = await panel('detailed');
    expect(host.querySelectorAll('.pkp-prov').length).toBe(5);
    expect(host.querySelectorAll('.oc-gauge').length).toBe(5);
    expect(host.querySelectorAll('[data-swarm-working-on]').length).toBe(5);
    const loki = host.querySelector('[data-swarm-agent="4"]') as HTMLElement;
    expect(loki.querySelector('[data-swarm-working-on]')?.textContent).toBe('fixing the drawer');
    expect(host.querySelector('[data-swarm-agent="5"] [data-swarm-working-on]')?.textContent).toBe('');
  });

  test('the + slot closes a section, opens a choice, and a pick turns that seat on (#1434)', async () => {
    document.body.innerHTML = '<div id="host"></div>';
    const host = document.getElementById('host') as HTMLElement;
    const onTurnOn = vi.fn();
    app = mount(SwarmPanel, {
      target: host,
      props: {
        floor: buildFloor({ agents: ROSTER, sessions: [], companies: [{ id: 1, name: 'Larkspur' }, { id: 7, name: 'Nyedis' }, { id: 8, name: 'Carnivore' }],
          projects: [{ id: 12, name: 'cloudecode', companyId: 1 }], showInactive: false, rowOf: () => ({ activity_status: 'idle' }) }),
        agents: ROSTER, density: 'expanded', now: NOW, still: true, showInactive: false, onToggleInactive: vi.fn(), onOpen: vi.fn(), onTurnOn,
      },
    });
    flushSync();
    await tick();
    const slot = host.querySelector('[data-swarm-slot="company"]') as HTMLElement;
    expect(slot).not.toBeNull();
    slot.click();
    flushSync();
    expect(host.querySelector('[data-swarm-pick]')).not.toBeNull();
    expect(onTurnOn).not.toHaveBeenCalled();
    (host.querySelector('[data-swarm-pick-seat="company:7"]') as HTMLElement).click();
    flushSync();
    expect(onTurnOn).toHaveBeenCalledWith(expect.objectContaining({ scope: 'company', id: 7 }));
    expect(host.querySelector('[data-swarm-pick]')).toBeNull();
  });

  test('a refused turn-on shows its reason under the section, never silent (#1428), and a click retries', async () => {
    document.body.innerHTML = '<div id="host"></div>';
    const host = document.getElementById('host') as HTMLElement;
    const home = '/Users/me sits inside the git repo at /Users; git init will not run there';
    const onTurnOn = vi.fn()
      .mockRejectedValueOnce(new ApiError(home, 409, null, { detail: { code: 'swarm_refused', message: home } }))
      .mockRejectedValueOnce(new ApiError('Home already has an agent', 409, null, { detail: { code: 'swarm_refused', message: 'Home already has an agent' } }));
    app = mount(SwarmPanel, {
      target: host,
      props: {
        floor: buildFloor({ agents: ROSTER, companies: [{ id: 1, name: 'Larkspur' }],
          sessions: [{ key: 'home', name: 'carnivore_Home', label: 'Home', sessionId: 'ses_home', sessionUuid: 'uuid-home', sessionRowId: null,
            asleep: false, projectId: 54, projectName: 'Home', harness: 'claude', listing: { activity_status: 'idle' } }],
          projects: [{ id: 12, name: 'cloudecode', companyId: 1 }, { id: 54, name: 'Home', companyId: null }], showInactive: false,
          rowOf: () => ({ activity_status: 'idle' }) }),
        agents: ROSTER, density: 'expanded', now: NOW, still: true, showInactive: false, onToggleInactive: vi.fn(), onOpen: vi.fn(), onTurnOn,
      },
    });
    flushSync();
    await tick();
    const click = async (said: string): Promise<void> => {
      (host.querySelector('[data-swarm-slot="project"]') as HTMLElement).click();
      await vi.waitFor(() => expect(host.querySelector('[data-swarm-refusal]')?.textContent).toBe(said));
    };
    await click(`could not turn on an agent for Home: ${home}`);
    expect(onTurnOn).toHaveBeenCalledWith(expect.objectContaining({ scope: 'project', id: 54 }));
    await click('could not turn on an agent for Home: Home already has an agent');
    expect(onTurnOn).toHaveBeenCalledTimes(2);
    expect(host.querySelector('button.oc-btn--confirm')).toBeNull();
  });

  test('each square carries its resolved state, with no alert badge on it', async () => {
    const host = await panel('expanded');
    expect(host.querySelector('[data-swarm-agent="4"]')?.getAttribute('data-swarm-state')).toBe('working');
    expect(host.querySelector('[data-swarm-agent="5"]')?.getAttribute('data-swarm-state')).toBe('asleep');
    expect(host.querySelectorAll('.pk-sq').length).toBe(5);
  });
});
