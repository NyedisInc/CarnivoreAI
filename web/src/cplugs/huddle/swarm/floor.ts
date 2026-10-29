import type { FloorCompany, FloorProject, FloorSession, ListingRow } from '../../sdk';
import { alertOf, sendOf, type PanelAgent } from './panel-state';
import { rollupState } from './rollup';

export type FloorTarget =
  | { kind: 'session'; session: FloorSession }
  | { kind: 'agent'; agentId: number }
  | { kind: 'turn_on'; scope: 'project' | 'company'; id: number; name: string };

export type FloorSection = 'alpha' | 'companies' | 'projects' | 'agents';

export interface FloorItem {
  key: string;
  section: FloorSection;
  rank: 'alpha' | 'company' | 'project' | 'task';
  label: string;
  vacant: boolean;
  agent: PanelAgent | null;
  session: FloorSession | null;
  ordinary: boolean;
  row: ListingRow | undefined;
  active: boolean;
  target: FloorTarget;
  projectId: number | null;
  companyId: number | null;
  rollup: string | null;
}

export interface Floor {
  alpha: FloorItem | null;
  companies: FloorItem[];
  projects: FloorItem[];
  agents: FloorItem[];
  seats: FloorItem[];
  inactive: number;
}

export interface FloorInput {
  agents: readonly PanelAgent[];
  sessions: readonly FloorSession[];
  companies: readonly FloorCompany[];
  projects: readonly FloorProject[];
  rowOf: (sessionId: string | null | undefined) => ListingRow | undefined;
  showInactive: boolean;
}

export function hashOf(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

export function sessionAgent(session: FloorSession): PanelAgent {
  const seed = hashOf(session.sessionUuid ?? session.key);
  return {
    id: seed, display_name: session.label, rank: 'task', state: session.asleep ? 'asleep' : 'awake', thread_key: '',
    harness: session.harness, session_id: session.sessionId, character_seed: seed,
  };
}

export function sessionActive(session: FloorSession): boolean {
  return session.listing.activity_status !== 'dead';
}

export function agentActive(agent: PanelAgent, row: ListingRow | undefined, listed = false): boolean {
  const bodyLive = (agent.state !== 'asleep' || listed) && row?.activity_status !== 'dead';
  return bodyLive || alertOf(agent) !== null || agent.question_waiting === true || sendOf(agent, row) !== null;
}

function projectOfAgent(agent: PanelAgent): number | null {
  if (typeof agent.project_id === 'number') return agent.project_id;
  const n = Number(agent.thread_key);
  return agent.rank === 'project' && Number.isInteger(n) ? n : null;
}

export function buildFloor(input: FloorInput): Floor {
  const { agents, sessions, rowOf } = input;
  const byRowId = new Map<number, PanelAgent>();
  const byUuid = new Map<string, PanelAgent>();
  for (const a of agents) {
    if (typeof a.session_row_id === 'number') byRowId.set(a.session_row_id, a);
    if (a.session_uuid) byUuid.set(a.session_uuid, a);
  }
  const bodyOf = (s: FloorSession): PanelAgent | undefined =>
    (s.sessionRowId !== null ? byRowId.get(s.sessionRowId) : undefined) ?? (s.sessionUuid ? byUuid.get(s.sessionUuid) : undefined);
  const bodyRow = new Map<number, FloorSession>();
  for (const s of sessions) {
    const a = bodyOf(s);
    if (a) bodyRow.set(a.id, s);
  }

  const agentItem = (a: PanelAgent, section: FloorSection, rank: FloorItem['rank']): FloorItem => {
    const row = rowOf(a.session_id) ?? bodyRow.get(a.id)?.listing;
    return {
      key: `agent:${a.id}`, section, rank, label: a.display_name, vacant: false, ordinary: false, agent: a, session: bodyRow.get(a.id) ?? null, row,
      active: agentActive(a, row, bodyRow.has(a.id)), target: { kind: 'agent', agentId: a.id },
      projectId: a.rank === 'project' ? projectOfAgent(a) : (a.project_id ?? null), companyId: a.company_id ?? null, rollup: null,
    };
  };
  const sessionItem = (s: FloorSession): FloorItem => ({
    key: `session:${s.key}`, section: 'agents', rank: 'task', label: s.label, vacant: false, ordinary: true, agent: sessionAgent(s), session: s,
    row: s.listing, active: sessionActive(s), target: { kind: 'session', session: s }, projectId: s.projectId, companyId: null, rollup: null,
  });

  const alpha = agents.find((a) => a.rank === 'alpha');
  const featureAgents = agents.filter((a) => a.rank === 'feature' || a.rank === 'task');

  const agentItems: FloorItem[] = [];
  const placed = new Set<number>();
  for (const s of sessions) {
    const owner = bodyOf(s);
    if (!owner) {
      agentItems.push(sessionItem(s));
    } else if ((owner.rank === 'feature' || owner.rank === 'task') && !placed.has(owner.id)) {
      placed.add(owner.id);
      agentItems.push(agentItem(owner, 'agents', 'task'));
    }
  }
  for (const a of featureAgents) if (!placed.has(a.id)) agentItems.push(agentItem(a, 'agents', 'task'));

  const projectAgents = new Map<number, PanelAgent>();
  for (const a of agents) {
    const id = a.rank === 'project' ? projectOfAgent(a) : null;
    if (id !== null && !projectAgents.has(id)) projectAgents.set(id, a);
  }
  const homes = new Set<number>();
  for (const a of agents) if ((a.rank === 'alpha' || a.rank === 'company') && typeof a.project_id === 'number') homes.add(a.project_id);
  const seen: number[] = [];
  for (const s of sessions) if (s.projectId !== null && !s.remote && !homes.has(s.projectId) && !seen.includes(s.projectId)) seen.push(s.projectId);
  for (const id of projectAgents.keys()) if (!homes.has(id) && !seen.includes(id)) seen.push(id);
  const listed = new Map(input.projects.map((p) => [p.id, p] as const));
  const companyIndex = new Map(input.companies.map((c, i) => [c.id, i] as const));
  const rankOfCompany = (id: number): number => {
    const company = listed.get(id)?.companyId;
    return company != null && companyIndex.has(company) ? (companyIndex.get(company) as number) : Number.MAX_SAFE_INTEGER;
  };
  const ordered = [...seen].sort((a, b) => rankOfCompany(a) - rankOfCompany(b) || seen.indexOf(a) - seen.indexOf(b));
  const featureActive = (a: PanelAgent): boolean => agentActive(a, rowOf(a.session_id) ?? bodyRow.get(a.id)?.listing, bodyRow.has(a.id));
  const projectBusy = (id: number): boolean =>
    sessions.some((s) => s.projectId === id && sessionActive(s)) || featureAgents.some((a) => a.project_id === id && featureActive(a));
  const projectItems: FloorItem[] = ordered.map((id) => {
    const agent = projectAgents.get(id);
    const name = listed.get(id)?.name ?? sessions.find((s) => s.projectId === id)?.projectName ?? `#${id}`;
    const base: FloorItem = agent ? agentItem(agent, 'projects', 'project') : {
      key: `project:${id}`, section: 'projects', rank: 'project', label: name, vacant: true, ordinary: false, agent: null, session: null, row: undefined,
      active: false, target: { kind: 'turn_on', scope: 'project', id, name }, projectId: id, companyId: null, rollup: null,
    };
    const rollup = rollupState(sessions.filter((s) => s.projectId === id).map((s) => s.listing));
    return { ...base, projectId: id, companyId: listed.get(id)?.companyId ?? base.companyId, active: base.active || projectBusy(id), rollup };
  });
  const projectItemOf = new Map(ordered.map((id, i) => [id, projectItems[i] as FloorItem] as const));

  const companyAgents = new Map<number, PanelAgent>();
  for (const a of agents) if (a.rank === 'company' && typeof a.company_id === 'number' && !companyAgents.has(a.company_id)) companyAgents.set(a.company_id, a);
  const companyIds = [...input.companies.map((c) => c.id), ...[...companyAgents.keys()].filter((id) => !companyIndex.has(id))];
  const companyProjectActive = (companyId: number): boolean =>
    ordered.some((id) => listed.get(id)?.companyId === companyId && projectItemOf.get(id)?.active === true);
  const companyItems: FloorItem[] = companyIds.map((id) => {
    const agent = companyAgents.get(id);
    const name = input.companies.find((c) => c.id === id)?.name ?? agent?.display_name ?? `#${id}`;
    const base = agent ? agentItem(agent, 'companies', 'company') : {
      key: `company:${id}`, section: 'companies' as const, rank: 'company' as const, label: name, vacant: true, ordinary: false, agent: null, session: null,
      row: undefined, active: false, target: { kind: 'turn_on' as const, scope: 'company' as const, id, name }, projectId: null, companyId: id, rollup: null,
    };
    const home = agent?.project_id;
    const mine = (s: FloorSession): boolean => s.projectId !== null && (s.projectId === home || listed.get(s.projectId)?.companyId === id);
    const rollup = rollupState(sessions.filter(mine).map((s) => s.listing));
    return { ...base, companyId: id, active: base.active || companyProjectActive(id) || (typeof home === 'number' && projectBusy(home)), rollup };
  });

  const shown = (items: FloorItem[]): FloorItem[] => (input.showInactive ? items : items.filter((i) => i.active));
  const inactive = [...companyItems, ...projectItems, ...agentItems].filter((i) => !i.active).length;
  return {
    alpha: alpha ? { ...agentItem(alpha, 'alpha', 'alpha'), rollup: rollupState(sessions.map((s) => s.listing)) } : null,
    companies: shown(companyItems), projects: shown(projectItems), agents: shown(agentItems), inactive,
    seats: [...companyItems, ...projectItems].filter((i) => i.vacant),
  };
}

export function scopeFloor(floor: Floor, agents: readonly PanelAgent[], selectedId: number | null): Floor {
  const byId = new Map(agents.map((a) => [a.id, a] as const));
  let scope = selectedId === null ? undefined : byId.get(selectedId);
  for (let hop = 0; scope && (scope.rank === 'feature' || scope.rank === 'task') && hop < 16; hop += 1) {
    scope = typeof scope.parent_id === 'number' ? byId.get(scope.parent_id) : undefined;
  }
  if (!scope || (scope.rank !== 'project' && scope.rank !== 'company')) return floor;
  const parents = new Set<number>([scope.id]);
  const projectIds = new Set<number>();
  let projects = floor.projects;
  if (scope.rank === 'project') {
    const id = projectOfAgent(scope);
    if (id !== null) projectIds.add(id);
  } else {
    const companyId = scope.company_id;
    projects = floor.projects.filter((p) => typeof companyId === 'number' && p.companyId === companyId);
    for (const p of projects) {
      if (p.projectId !== null) projectIds.add(p.projectId);
      if (p.agent && !p.vacant) parents.add(p.agent.id);
    }
    if (typeof scope.project_id === 'number') projectIds.add(scope.project_id);
  }
  const mine = (i: FloorItem): boolean =>
    (!i.ordinary && typeof i.agent?.parent_id === 'number' && parents.has(i.agent.parent_id)) || (i.projectId !== null && projectIds.has(i.projectId));
  return { ...floor, projects, agents: floor.agents.filter(mine) };
}

export function lineageFloor(floor: Floor, key: string | null): Floor {
  const all = [...(floor.alpha ? [floor.alpha] : []), ...floor.companies, ...floor.projects, ...floor.agents];
  const picked = key === null ? undefined : all.find((i) => i.key === key);
  if (!picked || picked.section === 'alpha') return floor;
  const byAgent = new Map(all.filter((i) => !i.ordinary && i.agent).map((i) => [(i.agent as PanelAgent).id, i] as const));
  const byProject = new Map(floor.projects.filter((i) => i.projectId !== null).map((i) => [i.projectId as number, i] as const));
  const hqOf = (id: number | null): FloorItem | undefined =>
    id === null ? undefined : floor.companies.find((c) => (c.agent?.project_id ?? null) === id);
  const parentOf = (i: FloorItem): FloorItem | null => {
    if (i.section === 'alpha') return null;
    if (i.section === 'companies') return floor.alpha;
    if (i.section === 'projects') return floor.companies.find((c) => c.companyId !== null && c.companyId === i.companyId) ?? floor.alpha;
    const parentId = i.ordinary ? null : i.agent?.parent_id;
    const viaParent = typeof parentId === 'number' ? byAgent.get(parentId) : undefined;
    if (viaParent && viaParent !== i) return viaParent;
    return (i.projectId !== null ? byProject.get(i.projectId) : undefined) ?? hqOf(i.projectId) ?? floor.alpha;
  };
  const keep = new Set<string>();
  for (let at: FloorItem | null = picked, hop = 0; at && hop < 32; at = parentOf(at), hop += 1) keep.add(at.key);
  for (const i of all) {
    for (let at = parentOf(i), hop = 0; at && hop < 32; at = parentOf(at), hop += 1) {
      if (at === picked) { keep.add(i.key); break; }
    }
  }
  const mine = (items: FloorItem[]): FloorItem[] => items.filter((i) => keep.has(i.key));
  return { ...floor, companies: mine(floor.companies), projects: mine(floor.projects), agents: mine(floor.agents) };
}

export function orderFloor(floor: Floor, order: Readonly<Record<'companies' | 'projects' | 'agents', readonly string[]>>): Floor {
  const sorted = (items: FloorItem[], keys: readonly string[]): FloorItem[] => {
    if (keys.length === 0) return items;
    const rank = new Map(keys.map((k, i) => [k, i] as const));
    const known = items.filter((i) => rank.has(i.key)).sort((a, b) => (rank.get(a.key) as number) - (rank.get(b.key) as number));
    return [...known, ...items.filter((i) => !rank.has(i.key))];
  };
  return { ...floor, companies: sorted(floor.companies, order.companies), projects: sorted(floor.projects, order.projects), agents: sorted(floor.agents, order.agents) };
}
