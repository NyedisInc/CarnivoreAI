import { expect, test } from 'vitest';
import { buildTabMenu, type TabMenuInputs } from './tab-menu';
import type { ProjectResponse, SessionInfo } from '../api/types';
import { blankSession } from '../../lib/blueprints/types';
import type { Blueprint } from '../../lib/blueprints/types';

function blueprint(uuid: string, name: string): Blueprint {
  return {
    blueprint_uuid: uuid,
    name,
    spec: { version: 1, name, shape_template: null, sessions: [blankSession('agent 1')] },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

/** One listing row, every signal on the WRAPPER, where the server puts it. */
function row(id: string, label: string, family: string | null, project: [number, string] | null): SessionInfo {
  return {
    session: { id, working_dir: '/work/' + id },
    label,
    tmux_session: `cloude_${id}`,
    agent_family: family,
    activity_status: 'idle',
    unread: false,
    startup_gate: null,
    status_source: 'registry',
    activity_hint: null,
    project_id: project ? project[0] : null,
    project_name: project ? project[1] : null,
  } as unknown as SessionInfo;
}

function asleepRow(id: string, label: string, project: [number, string] | null): SessionInfo {
  return {
    asleep: true,
    session_uuid: 'u-' + id,
    session: { id: 'asleep:' + id, working_dir: '/work/' + id },
    label,
    tmux_session: `cloude_${id}`,
    agent_family: 'claude',
    activity_status: null,
    unread: null,
    startup_gate: null,
    status_source: null,
    activity_hint: null,
    project_id: project ? project[0] : null,
    project_name: project ? project[1] : null,
  } as unknown as SessionInfo;
}

function project(id: number, name: string, workAt: string | null = null): ProjectResponse {
  return { id, name, path: '/work/' + name, description: null, root: '/work/' + name, work_at: workAt, archived_at: null };
}

const ROWS = [
  row('a', 'alpha', 'claude', [1, 'api']),
  row('b', 'bravo', 'codex', [1, 'api']),
  row('d', 'delta', null, null),
];

function inputs(overrides: Partial<TabMenuInputs> & { openSessionIds: ReadonlySet<string> }): TabMenuInputs {
  return {
    rows: ROWS,
    name: (r) => r.label ?? r.session.id,
    open: () => {},
    wake: () => {},
    newAgent: () => {},
    newAgentInProject: () => {},
    newTerminal: () => {},
    openBlueprints: () => {},
    blueprints: [],
    launchBlueprint: () => {},
    projects: [],
    layoutSessionIds: [],
    ...overrides,
  };
}

function agentSessionIds(root: ReturnType<typeof buildTabMenu>): string[] {
  const agent = root.find((n) => n.id === 'agent')!;
  return (agent.children ?? [])
    .filter((n) => n.id !== 'agent/new')
    .flatMap((project) => (project.children ?? []).map((leaf) => leaf.id));
}

test('nothing open here: every non-shell session is listed', () => {
  const root = buildTabMenu(inputs({ openSessionIds: new Set() }));
  expect(agentSessionIds(root)).toEqual(['agent/p:1/a', 'agent/p:1/b', 'agent/rogue/d']);
});

test('a session already open as a tab here is absent from its project', () => {
  const root = buildTabMenu(inputs({ openSessionIds: new Set(['a']) }));
  const ids = agentSessionIds(root);
  expect(ids).not.toContain('agent/p:1/a');
  expect(ids).toEqual(['agent/p:1/b', 'agent/rogue/d']);
});

test('a project whose only session is already open is absent, not empty', () => {
  const root = buildTabMenu(inputs({ openSessionIds: new Set(['d']) }));
  const agent = root.find((n) => n.id === 'agent')!;
  const projectIds = (agent.children ?? []).map((n) => n.id);
  expect(projectIds).not.toContain('agent/rogue');
  expect(agentSessionIds(root)).toEqual(['agent/p:1/a', 'agent/p:1/b']);
});

test('everything open here: only "new agent" remains under agent', () => {
  const root = buildTabMenu(inputs({ openSessionIds: new Set(['a', 'b', 'd']) }));
  const agent = root.find((n) => n.id === 'agent')!;
  expect((agent.children ?? []).map((n) => n.id)).toEqual(['agent/new']);
});

test('a project with no running or asleep session still lists, with just its own new agent leaf (issue #720)', () => {
  const started: ProjectResponse[] = [];
  const idle = project(9, 'idle-project');
  const root = buildTabMenu(inputs({
    openSessionIds: new Set(),
    rows: [],
    projects: [idle],
    newAgentInProject: (p) => started.push(p),
  }));
  const agent = root.find((n) => n.id === 'agent')!;
  const bucket = (agent.children ?? []).find((n) => n.id === 'agent/p:9')!;
  expect(bucket, 'a project with zero sessions still gets a bucket').toBeDefined();
  expect((bucket.children ?? []).map((n) => n.id)).toEqual(['agent/p:9/new']);
  bucket.children![0]!.run?.();
  expect(started).toEqual([idle]);
});

test('an asleep session is listed under its project, marked asleep, and wakes rather than opens', () => {
  const woken: SessionInfo[] = [];
  const opened: string[] = [];
  const sleeper = asleepRow('z', 'zulu', [5, 'sleepy']);
  const root = buildTabMenu(inputs({
    openSessionIds: new Set(),
    rows: [sleeper],
    projects: [project(5, 'sleepy')],
    open: (id) => opened.push(id),
    wake: (r) => woken.push(r),
  }));
  const agent = root.find((n) => n.id === 'agent')!;
  const bucket = (agent.children ?? []).find((n) => n.id === 'agent/p:5')!;
  const leaf = (bucket.children ?? []).find((n) => n.id === 'agent/p:5/asleep:z')!;
  expect(leaf.badge).toBe('asleep');
  expect(leaf.agent?.status).toBe('asleep');
  leaf.run?.();
  expect(woken).toEqual([sleeper]);
  expect(opened).toEqual([]);
});

test('open projects (a non-asleep agent row, as the drawer shows) first A to Z, a divider, then the rest; emoji and symbols are ignored when sorting', () => {
  const root = buildTabMenu(inputs({
    openSessionIds: new Set(['z1']),
    rows: [
      row('z1', 'zulu agent', 'claude', [30, 'zulu']),
      row('b1', 'bravo agent', 'claude', [40, 'Bravo']),
      row('sh', 'shell', 'shell', [10, 'yankee']),
      asleepRow('c1', 'charlie agent', [50, 'charlie']),
    ],
    projects: [
      project(10, 'yankee'), project(20, 'alpha'), project(30, 'zulu'), project(40, 'Bravo'), project(50, 'charlie'),
      project(60, '\u{1F9E0} Mesh'), project(70, '\u{1F680} Apex'),
    ],
  }));
  const kids = root.find((n) => n.id === 'agent')!.children ?? [];
  expect(kids.map((n) => n.id)).toEqual(['agent/new', 'agent/p:40', 'agent/p:30', 'agent/p:20', 'agent/p:70', 'agent/p:50', 'agent/p:60', 'agent/p:10']);
  expect(kids.map((n) => !!n.sep)).toEqual([false, true, false, true, false, false, false, false]);
});

test('every saved blueprint is a leaf that launches it directly', () => {
  const launched: string[] = [];
  const bps = [blueprint('b1', 'review team'), blueprint('b2', 'solo agent')];
  const root = buildTabMenu(inputs({
    openSessionIds: new Set(),
    blueprints: bps,
    launchBlueprint: (bp) => launched.push(bp.blueprint_uuid),
  }));
  const branch = root.find((n) => n.id === 'blueprint')!;
  const children = branch.children ?? [];
  expect(children.map((n) => n.id)).toEqual(['blueprint/b1', 'blueprint/b2', 'blueprint/manage']);
  expect(children.map((n) => n.label)).toEqual(['review team', 'solo agent', 'View all']);
  children[0]!.run?.();
  expect(launched).toEqual(['b1']);
});

test('the manage leaf is separated from the list and opens the manage page', () => {
  const opened: boolean[] = [];
  const root = buildTabMenu(inputs({
    openSessionIds: new Set(),
    blueprints: [blueprint('b1', 'review team')],
    openBlueprints: () => opened.push(true),
  }));
  const branch = root.find((n) => n.id === 'blueprint')!;
  const manage = (branch.children ?? []).find((n) => n.id === 'blueprint/manage')!;
  expect(manage.sep).toBe(true);
  manage.run?.();
  expect(opened).toEqual([true]);
});

test('with no saved blueprints the list is one blocked line, not an empty branch', () => {
  const root = buildTabMenu(inputs({ openSessionIds: new Set(), blueprints: [] }));
  const branch = root.find((n) => n.id === 'blueprint')!;
  const children = branch.children ?? [];
  expect(children.map((n) => n.id)).toEqual(['blueprint/empty', 'blueprint/manage']);
  expect(children[0]!.blocked).toBeTruthy();
});

test('projects group: in-layout in tab order, other open, then inactive, a divider between each non-empty group (#1527)', () => {
  const proj = (id: number, name: string): ProjectResponse => ({ id, name }) as unknown as ProjectResponse;
  const projects = [proj(1, 'Alpha'), proj(2, 'Bravo'), proj(3, 'Charlie'), proj(4, 'Delta'), proj(5, 'Echo')];
  const rows = [
    row('a', 'a', 'claude', [1, 'Alpha']),
    row('b', 'b', 'claude', [2, 'Bravo']),
    row('c', 'c', 'claude', [3, 'Charlie']),
    row('s', 's', 'shell', [5, 'Echo']),
    asleepRow('d', 'd', [4, 'Delta']),
  ];
  const kids = (layoutSessionIds: string[]) =>
    buildTabMenu(inputs({ rows, projects, layoutSessionIds, openSessionIds: new Set(layoutSessionIds) }))
      .find((n) => n.id === 'agent')!.children!.filter((n) => n.id !== 'agent/new');
  const full = kids(['c', 'b']);
  expect(full.map((n) => n.label)).toEqual(['Charlie', 'Bravo', 'Alpha', 'Delta', 'Echo']);
  expect(full.map((n) => !!n.sep)).toEqual([true, false, true, true, false]);
  const none = kids([]);
  expect(none.map((n) => n.label)).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo']);
  expect(none.map((n) => !!n.sep)).toEqual([true, false, false, true, false]);
  expect(new Set(full.map((n) => n.id)).size).toBe(full.length);
});

test('the widget root lists the picker branches, and is blocked with a sentence where the strip cannot hold widget tabs (slice 8b)', () => {
  const leaf = { id: 'widget/core.notes', label: 'notes', run: () => {} };
  const withWidgets = buildTabMenu(inputs({ openSessionIds: new Set(), widgets: [{ id: 'widget/tools', label: 'tools', children: [leaf] }] }));
  const root = withWidgets.find((node) => node.id === 'widget');
  expect(root?.children?.[0]?.children?.[0]).toBe(leaf);
  const phone = buildTabMenu(inputs({ openSessionIds: new Set(), widgets: null })).find((node) => node.id === 'widget');
  expect(phone?.blocked).toBe('widgets open as tabs on a larger screen');
  expect(phone?.children).toBeUndefined();
});
