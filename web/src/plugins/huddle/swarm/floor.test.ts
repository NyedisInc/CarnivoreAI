/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';
import type { FloorSession } from '../../sdk';
import SwarmPanel from './SwarmPanel.svelte';
import { buildFloor, hashOf, scopeFloor, sessionAgent, type FloorInput } from './floor';
import { colorOf, seedOf, type PanelAgent } from './panel-state';

setLocale('en');

const ses = (key: string, over: Partial<FloorSession> = {}): FloorSession => ({
  key, name: `cloude_${key}`, label: key, sessionId: `ses_${key}`, sessionUuid: `uuid-${key}`, sessionRowId: null, asleep: false, projectId: null,
  projectName: null, harness: 'claude', listing: { activity_status: 'idle' }, ...over,
});
const agent = (id: number, rank: string, over: Partial<PanelAgent> = {}): PanelAgent =>
  ({ id, display_name: `agent${id}`, rank, state: 'awake', thread_key: `agent:${id}`, session_id: null, ...over });

const SESSIONS: FloorSession[] = [
  ses('api', { label: 'api work', projectId: 1, listing: { activity_status: 'working' } }),
  ses('far', { label: 'far away', sessionId: 'remote:peer-x:ses_far', projectId: 2, listing: { activity_status: 'working' } }),
  ses('body', { label: 'cloudecode (project)', projectId: 1, sessionRowId: 101 }),
  ses('alpha', { label: 'Alpha', projectId: null, sessionRowId: 100 }),
  ses('dead', { label: 'dead pane', projectId: 3, listing: { activity_status: 'dead' } }),
  ses('mabel', { label: 'Mabel record', sessionId: null, asleep: true, sessionRowId: 200, sessionUuid: 'uuid-mabel', listing: { activity_status: 'asleep' } }),
  ses('nap', { label: 'sleeper', sessionId: null, asleep: true, projectId: 3, listing: { activity_status: 'asleep' } }),
];
const AGENTS: PanelAgent[] = [
  agent(1, 'alpha', { display_name: 'Alpha', thread_key: 'all', session_id: 'ses_alpha', session_row_id: 100 }),
  agent(11, 'project', { display_name: 'cloudecode', thread_key: '1', project_id: 1, session_id: 'ses_body', session_row_id: 101 }),
  agent(12, 'feature', { display_name: 'Loki', state: 'asleep', question_waiting: true }),
  agent(13, 'task', { display_name: 'Mabel', state: 'asleep', session_row_id: 200, session_uuid: 'uuid-mabel' }),
];
const INPUT: FloorInput = {
  agents: AGENTS, sessions: SESSIONS,
  companies: [{ id: 1, name: 'Larkspur' }, { id: 2, name: 'Empty Co' }],
  projects: [{ id: 1, name: 'cloudecode', companyId: 1 }, { id: 2, name: 'coffee', companyId: null }, { id: 3, name: 'old', companyId: 1 }],
  rowOf: () => undefined, showInactive: false,
};
const keys = (items: { key: string }[]): string[] => items.map((i) => i.key);

describe('the floor model', () => {
  test('a project that only a paired computer\'s sessions sit under gets no vacant seat here', () => {
    const floor = buildFloor({ ...INPUT, sessions: [ses('far2', { projectId: 9, projectName: 'SoundDesk (2)', remote: true, sessionId: 'remote:peer-x:ses_far2' })], agents: [], showInactive: true });
    expect(keys(floor.projects)).not.toContain('project:9');
  });

  test('a project node narrows AGENTS to its own; a company node narrows PROJECTS and AGENTS to its own; SysOp and a gone node show all', () => {
    const agents: PanelAgent[] = [
      ...AGENTS,
      agent(21, 'company', { display_name: 'Larkspur', company_id: 1 }),
      agent(22, 'project', { display_name: 'coffee', thread_key: '2', project_id: 2, company_id: null }),
      agent(23, 'feature', { display_name: 'Odin', parent_id: 11, project_id: 1 }),
      agent(24, 'task', { display_name: 'Brew', parent_id: 22, project_id: 2 }),
    ];
    const floor = buildFloor({ ...INPUT, agents, showInactive: true });
    expect(keys(floor.projects)).toEqual(['agent:11', 'project:3', 'agent:22']);
    const project = scopeFloor(floor, agents, 11);
    expect(keys(project.agents)).toEqual(['session:api', 'agent:23']);
    expect(keys(project.projects)).toEqual(keys(floor.projects));
    expect(project.alpha).toBe(floor.alpha);
    expect(keys(project.companies)).toEqual(keys(floor.companies));
    expect(keys(scopeFloor(floor, agents, 23).agents)).toEqual(['session:api', 'agent:23']);
    const company = scopeFloor(floor, agents, 21);
    expect(keys(company.projects)).toEqual(['agent:11', 'project:3']);
    expect(keys(company.agents)).toEqual(['session:api', 'session:dead', 'session:nap', 'agent:23']);
    expect(project.agents.find((i) => i.key === 'session:api')?.rollup).toBe(floor.agents.find((i) => i.key === 'session:api')?.rollup);
    expect(scopeFloor(floor, agents, 1)).toBe(floor);
    expect(scopeFloor(floor, agents, null)).toBe(floor);
    expect(scopeFloor(floor, agents, 999)).toBe(floor);
  });

  test('a Swarm body renders once, as its agent, and ordinary sessions follow the drawer order', () => {
    const floor = buildFloor(INPUT);
    expect(floor.alpha?.agent?.display_name).toBe('Alpha');
    const project = floor.projects.find((p) => p.key === 'agent:11');
    expect(project?.session?.key).toBe('body');
    const all = [...(floor.alpha ? [floor.alpha] : []), ...floor.companies, ...floor.projects, ...floor.agents];
    expect(all.filter((i) => i.session?.key === 'body')).toHaveLength(1);
    expect(all.filter((i) => i.session?.key === 'alpha')).toHaveLength(1);
    expect(keys(floor.agents)).toEqual(['session:api', 'session:far', 'agent:13', 'session:nap', 'agent:12']);
  });

  test('an asleep Swarm agent and its own asleep sessions record render exactly once, joined on the sessions row, with inactive shown', () => {
    const shown = buildFloor({ ...INPUT, showInactive: true });
    const all = [...shown.companies, ...shown.projects, ...shown.agents];
    expect(all.filter((i) => i.label === 'Mabel' || i.session?.key === 'mabel')).toHaveLength(1);
    expect(all.find((i) => i.key === 'agent:13')?.session?.key).toBe('mabel');
    const byUuid = buildFloor({ ...INPUT, showInactive: true, agents: AGENTS.map((a) => (a.id === 13 ? { ...a, session_row_id: null } : a)) });
    expect([...byUuid.agents].filter((i) => i.label === 'Mabel' || i.session?.key === 'mabel')).toHaveLength(1);
    const byName = buildFloor({ ...INPUT, showInactive: true, agents: AGENTS.map((a) => (a.id === 13 ? { ...a, session_row_id: null, session_uuid: null, tmux_session: 'cloude_mabel' } : a)) });
    expect(byName.agents.filter((i) => i.label === 'Mabel' || i.session?.key === 'mabel')).toHaveLength(2);
  });

  test('sections, order, vacant seats and the active rule', () => {
    const floor = buildFloor(INPUT);
    expect(keys(floor.companies)).toEqual(['company:1']);
    expect(floor.companies[0]).toMatchObject({ vacant: true, label: 'Larkspur', target: { kind: 'turn_on', scope: 'company', id: 1 } });
    expect(keys(floor.projects)).toEqual(['agent:11', 'project:3', 'project:2']);
    expect(floor.projects[2]).toMatchObject({ vacant: true, agent: null, label: 'coffee', target: { kind: 'turn_on', scope: 'project', id: 2, name: 'coffee' } });
    expect(floor.agents.map((i) => i.label)).toEqual(['api work', 'far away', 'Mabel', 'sleeper', 'Loki']);
    expect(floor.inactive).toBe(2);
    expect(buildFloor({ ...INPUT, agents: AGENTS.map((a) => (a.id === 12 ? { ...a, question_waiting: false } : a)) }).agents.map((i) => i.label)).toEqual(['api work', 'far away', 'Mabel', 'sleeper']);
  });

  test('a company or Alpha home folder is seated by its agent: no vacant seat, no project square, its sessions still draw as agents', () => {
    const home = (extra: PanelAgent[], sessions: FloorSession[] = []) => buildFloor({
      ...INPUT, showInactive: true, agents: [...AGENTS, ...extra], sessions: [...SESSIONS, ...sessions],
      companies: [...INPUT.companies, { id: 3, name: 'Acme' }], projects: [...INPUT.projects, { id: 7, name: 'Acme HQ', companyId: 3 }, { id: 8, name: 'Alpha Home', companyId: null }],
    });
    const hqSession = ses('hq', { label: 'hq shell', projectId: 7, listing: { activity_status: 'working' } });
    const floor = home([agent(30, 'company', { company_id: 3, project_id: 7 })], [hqSession]);
    expect(keys(floor.projects)).not.toContain('project:7');
    expect(floor.projects.every((p) => p.projectId !== 7)).toBe(true);
    const withAlphaHome = buildFloor({ ...INPUT, showInactive: true, agents: AGENTS.map((a) => (a.rank === 'alpha' ? { ...a, project_id: 8 } : a)),
      sessions: [...SESSIONS, ses('ah', { projectId: 8 })], projects: [...INPUT.projects, { id: 8, name: 'Alpha Home', companyId: null }] });
    expect(withAlphaHome.projects.map((p) => p.projectId)).not.toContain(8);
    expect(keys(withAlphaHome.agents)).toContain('session:ah');
    expect(keys(floor.agents)).toContain('session:hq');
    expect(floor.companies.find((c) => c.key === 'agent:30')?.active).toBe(true);
    const off = home([], [hqSession]);
    expect(off.projects.find((p) => p.projectId === 7)).toMatchObject({ vacant: true, key: 'project:7' });
  });

  test('the divider counts are the shown items, and an empty section is empty', () => {
    const floor = buildFloor({ ...INPUT, sessions: [], agents: [AGENTS[0] as PanelAgent], projects: [], companies: [] });
    expect([floor.companies.length, floor.projects.length, floor.agents.length]).toEqual([0, 0, 0]);
    expect(floor.alpha).not.toBeNull();
  });

  test('the toggle reveals exactly the hidden ones, wearing their own state', () => {
    const hidden = buildFloor(INPUT);
    const shown = buildFloor({ ...INPUT, showInactive: true });
    const names = (f: typeof hidden): string[] => [...f.companies, ...f.projects, ...f.agents].map((i) => i.key);
    const extra = names(shown).filter((k) => !names(hidden).includes(k));
    expect(extra.sort()).toEqual(['company:2', 'session:dead']);
    expect(extra).toHaveLength(hidden.inactive);
    expect(shown.agents.find((i) => i.key === 'session:nap')?.agent?.state).toBe('asleep');
    expect(shown.agents.find((i) => i.key === 'session:dead')?.row?.activity_status).toBe('dead');
    expect(shown.projects.find((i) => i.key === 'project:3')?.vacant).toBe(true);
  });

  test('click targets: a session opens, an agent opens its page, a seat asks to turn on', () => {
    const floor = buildFloor(INPUT);
    expect(floor.agents[0]?.target).toMatchObject({ kind: 'session', session: { key: 'api' } });
    expect(floor.projects[0]?.target).toEqual({ kind: 'agent', agentId: 11 });
    expect(floor.agents[4]?.target).toEqual({ kind: 'agent', agentId: 12 });
    expect(floor.projects[1]?.target.kind).toBe('turn_on');
  });

  test('an ordinary session keeps its face across a rename: seed and color come from its uuid', () => {
    const a = sessionAgent(ses('api', { label: 'one' }));
    const b = sessionAgent(ses('api', { label: 'renamed', name: 'cloude_other' }));
    expect([seedOf(a), colorOf(a)]).toEqual([seedOf(b), colorOf(b)]);
    expect(seedOf(a)).toBe(hashOf('uuid-api'));
  });
});

describe('the panel over the floor', () => {
  let app: object | null = null;
  afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.innerHTML = '';
  });

  async function panel(over: Record<string, unknown> = {}): Promise<HTMLElement> {
    document.body.innerHTML = '<div id="host"></div>';
    const host = document.getElementById('host') as HTMLElement;
    app = mount(SwarmPanel, {
      target: host,
      props: { floor: buildFloor(INPUT), agents: AGENTS, density: 'expanded', now: 1_000_000_000_000, still: true, showInactive: false,
        onToggleInactive: vi.fn(), onOpen: vi.fn(), onTurnOn: vi.fn(), ...over },
    });
    flushSync();
    await tick();
    return host;
  }

  test('threads_ready false adds the permission line and keeps the whole floor; absent adds nothing', async () => {
    const onOpenPlugins = vi.fn();
    let host = await panel({ threadsReady: false, onOpenPlugins });
    expect(host.querySelector('[data-swarm-needs-permission]')).not.toBeNull();
    expect(host.querySelectorAll('[data-swarm-section="agents"] .pkp-it').length).toBe(5);
    (host.querySelector('[data-swarm-open-plugins]') as HTMLElement).click();
    expect(onOpenPlugins).toHaveBeenCalledOnce();
    unmount(app as object);
    host = await panel({});
    expect(host.querySelector('[data-swarm-needs-permission]')).toBeNull();
  });

  test('one click on a vacant seat turns it on, with no question first (#1434)', async () => {
    const onTurnOn = vi.fn();
    const host = await panel({ onTurnOn });
    (host.querySelector('[data-swarm-vacant="project"]') as HTMLElement).click();
    await vi.waitFor(() => expect(onTurnOn).toHaveBeenCalledWith(expect.objectContaining({ kind: 'turn_on', scope: 'project', id: 3 })));
    expect(onTurnOn).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[data-swarm-refusal]')).toBeNull();
    expect(host.textContent).not.toContain('turn on an agent for');
    expect(host.querySelector('button.oc-btn--confirm')).toBeNull();
  });

  test('the quiet link reads show inactive (N) then hide inactive, and toggles', async () => {
    const onToggleInactive = vi.fn();
    let host = await panel({ onToggleInactive });
    const link = host.querySelector('[data-swarm-toggle-inactive]') as HTMLElement;
    expect(link.textContent?.trim()).toBe('show inactive (2)');
    link.click();
    expect(onToggleInactive).toHaveBeenCalledOnce();
    unmount(app as object);
    host = await panel({ floor: buildFloor({ ...INPUT, showInactive: true }), showInactive: true });
    expect(host.querySelector('[data-swarm-toggle-inactive]')?.textContent?.trim()).toBe('hide inactive');
    expect(host.querySelectorAll('[data-swarm-session]').length).toBe(4);
  });
});
