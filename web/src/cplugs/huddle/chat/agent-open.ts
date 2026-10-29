import { floorSource, openSessionModal } from '../../sdk';
import { openAgentPage } from '../agents/agent-page.svelte';
import type { AuthorCrumb } from './chat-api';
import { rosterAgent } from './chat-avatar';

export function fullPathOf(path: AuthorCrumb[], agentId: number | null): AuthorCrumb[] {
  if (path.length !== 1) return path;
  const agent = rosterAgent(agentId);
  if (!agent || agent.rank === 'alpha' || agent.rank === 'company') return path;
  const floor = floorSource();
  const project = agent.rank === 'project' ? undefined : floor.projects.find((p) => p.id === agent.project_id);
  const companyId = agent.company_id ?? project?.companyId ?? null;
  const company = companyId === null ? undefined : floor.companies.find((c) => c.id === companyId);
  return [
    ...(company ? [{ kind: 'company' as const, name: company.name, agent_id: null }] : []),
    ...(project ? [{ kind: 'project' as const, name: project.name, agent_id: null }] : []),
    ...path,
  ];
}

export function pathTip(path: AuthorCrumb[]): string {
  return path.length > 1 ? path.map((c) => c.name).join(' / ') : '';
}

export function lineageTip(node: HTMLElement, text: string): { update: (next: string) => void; destroy: () => void } {
  const put = (value: string): void => {
    if (value) node.setAttribute('data-tooltip', value);
    else node.removeAttribute('data-tooltip');
  };
  put(text);
  return { update: put, destroy: () => node.removeAttribute('data-tooltip') };
}

export function openAuthorTerminal(agentId: number | null, sessionUuid: string | null): boolean {
  const viaRoster = rosterAgent(agentId)?.session_id ?? null;
  const viaFloor = sessionUuid ? (floorSource().sessions.find((s) => s.sessionUuid === sessionUuid)?.sessionId ?? null) : null;
  if (openSessionModal(viaRoster ?? viaFloor)) return true;
  return typeof agentId === 'number' && agentId > 0 ? openAgentPage(agentId) : false;
}
